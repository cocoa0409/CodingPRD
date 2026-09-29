"""Which complaint answers when a single request breaks two rules at once.

Both scenarios here are deliberately doubly invalid. A finding is filed against
an asset whose target was excluded mid-programme, which is both an explicit
exclusion *and* the absence of an active authorization; a second assignment is
booked for a tester who is already fully occupied *and* for more hours than the
engagement can still afford. In each case exactly one error_id is correct, and
the suite proves the loser stays silent as well as that the winner speaks.
"""

from test_helpers import (
    assert_error_id,
    assert_exact_int,
    assert_hour_ledger,
    assert_page,
    assert_risk_ledger,
    assert_version_unchanged,
    build_scenario,
    engagement_version,
    factories,
    program_manager_headers,
    success_data,
)
from test_helpers.api_errors import (
    ERR_ENGAGEMENT_HOURS_EXCEEDED,
    ERR_NO_OPEN_TESTING_WINDOW,
    ERR_TARGET_EXCLUDED,
    ERR_TARGET_NOT_AUTHORIZED,
    ERR_TESTER_CAPACITY_EXCEEDED,
)

# The exclusion is made while the document's window still covers the clock. An
# authorized target's window must lie inside its engagement's window, so once the
# clock runs past the engagement's window_end no authorized window covers the
# instant at all and the first authorization-of-testing check answers
# ERR_NO_OPEN_TESTING_WINDOW before the exclusion is ever consulted. The exclusion
# therefore outranks the scope complaint that survives here: the missing active
# authorization.
EXCLUSION_REASON = "Client removed the payments host from scope mid-engagement"


def _excluded_target_inside_the_open_window(client):
    """Run fieldwork, then exclude the only target while its window is still open."""
    scenario = build_scenario(
        client,
        roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["SQLI", "XSS"]},
        target={"technique_allowlist": ["SQLI"]},
    )
    excluded = success_data(
        client.exclude_authorized_target(scenario["target_id"], EXCLUSION_REASON)
    )
    return scenario, excluded


def _file_the_sql_injection_report(client, scenario):
    """Attempt to report a finding against the now-excluded payments asset."""
    payload = factories.finding_payload(
        scenario["engagement_id"],
        scenario["asset_id"],
        engagement_version(
            client, scenario["engagement_id"], headers=scenario["tester_headers"]
        ),
        title="SQL injection in the settlement report filter",
        reproduction_steps="1. GET /reports?filter=1' OR '1'='1 2. Observe full table dump",
        business_impact_narrative="Full settlement ledger is readable",
        technical_base_score=8.0,
        exposure_class="PARTNER",
        root_cause_theme="INPUT_VALIDATION",
    )
    return client.create_finding(payload, scenario["tester_headers"])


class TestExclusionOutranksTheExpiredWindow:
    """An excluded target is the most specific complaint the programme can make."""

    def test_excluding_the_target_does_not_freeze_the_signed_document(self, client):
        """Exclusion is a target-level act, so the document stays signed and usable.

        PRD: "Exclusion moves the target `ACTIVE` → `EXCLUDED`, stamps the supplied text into `exclusion_reason`, decrements the document's `active_target_count`, and advances the document's `version`."

        Design: Difficulty/priority_pair_validation_conflict/excluded_target_outranks_expired_testing_window
        """
        scenario, excluded = _excluded_target_inside_the_open_window(client)

        assert excluded["state"] == "EXCLUDED", (
            f"target state: expected EXCLUDED, got {excluded['state']}"
        )
        assert excluded["exclusion_reason"] == EXCLUSION_REASON

        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert document["status"] == "SIGNED", (
            "excluding a target must not freeze the document; "
            f"status is {document['status']}"
        )
        assert_exact_int(document["active_target_count"], 0, "active_target_count")

    def test_the_report_names_the_exclusion_and_not_the_calendar(self, client):
        """Two complaints are true at once and the safety band answers first.

        PRD: "Second, if the finding's asset has a target on this engagement's document in `EXCLUDED` state, the report is refused with `ERR_TARGET_EXCLUDED` — an explicit exclusion is reported ahead of every other scope, temporal or fiscal complaint, because it is the most specific statement the programme can make."
        PRD: "First, at least one authorized target of the engagement's document must cover the current instant, meaning the instant falls between that target's `window_start` and `window_end` with both bounds inclusive; **the target's state is deliberately not consulted here**, so even an excluded target proves that an authorized window covered this moment"
        PRD: "Third, the asset must have a target on that document in `ACTIVE` state, or the report is refused with `ERR_TARGET_NOT_AUTHORIZED`."

        Design: Difficulty/priority_pair_validation_conflict/excluded_target_outranks_expired_testing_window
        """
        scenario, _excluded = _excluded_target_inside_the_open_window(client)

        response = _file_the_sql_injection_report(client, scenario)

        payload = assert_error_id(response, ERR_TARGET_EXCLUDED)
        assert response.status_code == 422, (
            f"expected HTTP 422 for an excluded target, got {response.status_code}"
        )
        assert payload["error_id"] != ERR_NO_OPEN_TESTING_WINDOW, (
            "the excluded target still proves an authorized window covered this moment"
        )
        assert payload["error_id"] != ERR_TARGET_NOT_AUTHORIZED, (
            "an excluded target reports the exclusion, not a missing authorization"
        )

    def test_the_refused_report_left_no_finding_and_no_risk_points(self, client):
        """A rejected report writes nothing at all, not even a risk-point entry.

        PRD: "Its points are added to the plan's `total_risk_points` and to its `open_risk_points`."

        Design: Difficulty/priority_pair_validation_conflict/excluded_target_outranks_expired_testing_window
        """
        scenario, _excluded = _excluded_target_inside_the_open_window(client)

        _file_the_sql_injection_report(client, scenario)

        assert_page(
            client.list_findings(params={"engagement_id": scenario["engagement_id"]}),
            total_count=0,
            row_count=0,
        )
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(plan, total=0, open_points=0)


# The second booking overlaps the first (07 Sep 09:00 - 14 Sep 09:00) and asks
# for 40 hours when only 10 remain, so both gates two and four are broken.
SECOND_INTERVAL_START = "2026-09-08T00:00:00Z"
SECOND_INTERVAL_END = "2026-09-09T00:00:00Z"


def _tester_fully_booked_with_ten_hours_left(client):
    """One provisioned 70-hour assignment for a tester whose cap is one engagement."""
    return build_scenario(
        client,
        stage="provisioned",
        roe={"allowed_techniques": ["SQLI", "XSS"]},
        target={"technique_allowlist": ["SQLI"]},
        tester={"max_concurrent_engagements": 1},
        assignment={"requested_hours": 70},
    )


def _book_a_second_overlapping_assignment(client, scenario, expected_version):
    """Attempt a 40-hour MEMBER booking inside the first assignment's interval."""
    payload = factories.tester_assignment_payload(
        scenario["engagement_id"],
        scenario["tester_id"],
        expected_version,
        [scenario["asset_id"]],
        assignment_role="MEMBER",
        interval_start=SECOND_INTERVAL_START,
        interval_end=SECOND_INTERVAL_END,
        requested_hours=40,
    )
    return client.create_tester_assignment(payload)


class TestCapacityOutranksTheHourBudget:
    """The aggregate concurrency cap answers before the engagement's chequebook."""

    def test_the_first_booking_leaves_only_ten_of_eighty_hours_available(self, client):
        """Seventy reserved hours out of eighty leave ten, so 40 is unaffordable.

        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."
        PRD: "Stated as standing definitions rather than as increments: an engagement's `hours_reserved` is the sum of `requested_hours` over its assignments whose `access_state` is `REQUESTED` or `PROVISIONED`; its `hours_consumed` is the sum of `settled_hours` over its assignments whose `access_state` is `REVOKED`; and its `hours_available` is `hours_allocated` minus `hours_reserved` minus `hours_consumed`."

        Design: Difficulty/priority_pair_validation_conflict/tester_capacity_outranks_engagement_hour_budget
        """
        scenario = _tester_fully_booked_with_ten_hours_left(client)

        assert_hour_ledger(
            scenario["engagement"], allocated=80, reserved=70, consumed=0, available=10
        )

    def test_the_second_booking_names_the_capacity_cap_and_not_the_budget(self, client):
        """Overbooked and overdrawn at once: gate two speaks and gate four does not.

        PRD: "Four gates guard a booking, and they are evaluated in a fixed order so that the most structural complaint always wins."
        PRD: "If the number of overlapping live assignments has already reached the tester's `max_concurrent_engagements`, the booking is refused with `ERR_TESTER_CAPACITY_EXCEEDED`."
        PRD: "The hour ledger is checked after every capacity and qualification rule precisely so that a booking which is both unqualified and unaffordable reports the qualification problem."

        Design: Difficulty/priority_pair_validation_conflict/tester_capacity_outranks_engagement_hour_budget
        """
        scenario = _tester_fully_booked_with_ten_hours_left(client)

        response = _book_a_second_overlapping_assignment(
            client, scenario, scenario["engagement"]["version"]
        )

        payload = assert_error_id(response, ERR_TESTER_CAPACITY_EXCEEDED)
        assert response.status_code == 409, (
            f"expected HTTP 409 for an overbooked tester, got {response.status_code}"
        )
        assert payload["error_id"] != ERR_ENGAGEMENT_HOURS_EXCEEDED, (
            "the fiscal complaint must stay hidden behind the concurrency cap"
        )

    def test_the_refused_booking_reserved_nothing_and_left_the_version_alone(self, client):
        """No second row, no extra reservation and no version bump from a rejected write.

        PRD: "An accepted booking opens at `REQUESTED` access state, with `provisioned_at` and `revoked_at` null and `settled_hours` at 0."
        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."

        Design: Difficulty/priority_pair_validation_conflict/tester_capacity_outranks_engagement_hour_budget
        """
        scenario = _tester_fully_booked_with_ten_hours_left(client)
        version_before = scenario["engagement"]["version"]

        _book_a_second_overlapping_assignment(client, scenario, version_before)

        assert_page(
            client.list_tester_assignments(params={"tester_id": scenario["tester_id"]}),
            total_count=1,
            row_count=1,
        )
        engagement = success_data(
            client.get_engagement(scenario["engagement_id"], headers=program_manager_headers())
        )
        assert_hour_ledger(engagement, allocated=80, reserved=70, consumed=0, available=10)
        assert_version_unchanged(
            version_before,
            engagement_version(client, scenario["engagement_id"]),
            "engagement version",
        )
