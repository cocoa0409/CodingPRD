"""Two deep cascades: one down the safety axis, one down the money axis."""

from test_helpers import (
    ApiErrorId,
    assert_capital_conserved,
    assert_two_decimals,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


class TestFailedImpactTestCascade:
    def test_a_failing_reading_reaches_the_ledger_five_hops_later(
        self, client, roster
    ):
        """One recorded assessment moves an order, a posture, a booking and the ledger.

        "Hop two opens the order: a `result` of `FAIL` opens an order with
        `severity` `MANDATORY`, a `result` of `ADVISORY` opens one with `severity`
        `ADVISORY`, and a `result` of `PASS` opens nothing."

        "A mandatory order pushes the field to `CLOSED_UNSAFE`, from either `OPEN →
        CLOSED_UNSAFE` or `RESTRICTED → CLOSED_UNSAFE`, and that is where hops four
        and five fire."

        "Hop five is the ledger consequence: each cancellation appends a
        `UsageLedgerEntry` with `entry_type` `UNSAFE_CANCELLATION`,
        `wear_units_delta` of 0.00 and `rest_requirement_hours` of 0.00 — an unsafe
        cancellation charges no wear because no play occurred — increments the
        field's `unsafe_cancellation_count` by 1, and forces a recompute of
        `rest_debt_hours`."

        "The age component is 100.00 minus the ratio of `age_years` to
        `expected_life_years` expressed as a percentage, likewise floored at 0.00
        and rounded half up to two decimals, so a surface exactly at its nominal
        life scores 0.00 on age and one past it is floored rather than negative."

        Design: Difficulty/transitive_cascade/failed_impact_test_cascades_through_order_posture_booking_to_ledger
        """
        field = fixtures.register_grass_main_1(client, roster)
        booking = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        confirmed = fixtures.confirm_booking(client, roster, booking["id"])
        assert confirmed["status"] == "CONFIRMED"

        assessment, order = fixtures.fail_field_unsafe(client, roster, field["id"])

        # Hop one: the verdict comes off the readings.
        assert_two_decimals(assessment["gmax_mean_value"], 210.0, "gmax_mean_value")
        assert assessment["result"] == "FAIL"

        # Hop two: the order the client never asked for.
        assert order["severity"] == "MANDATORY"
        assert order["status"] == "OPEN"
        assert order["source_assessment_id"] == assessment["id"]

        # Hop three: the counter and the posture.
        after = fixtures.read_field(client, roster, field["id"])
        assert after["open_mandatory_remediation_count"] == 1
        assert after["play_status"] == "CLOSED_UNSAFE"

        # Hop four: a booking that was confirmed minutes ago is gone.
        cancelled = fixtures.read_booking(client, roster, booking["id"])
        assert cancelled["status"] == "CANCELLED_UNSAFE"

        # Hop five: the ledger records the cancellation without charging wear.
        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert entry["entry_type"] == "UNSAFE_CANCELLATION"
        assert entry["booking_id"] == booking["id"]
        assert_two_decimals(entry["wear_units_delta"], 0.00, "wear_units_delta")
        assert_two_decimals(
            entry["rest_requirement_hours"], 0.00, "rest_requirement_hours"
        )
        assert_two_decimals(
            entry["running_balance_after"], 0.00, "running_balance_after"
        )
        assert after["unsafe_cancellation_count"] == 1

        assert_two_decimals(
            after["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
        )
        assert_two_decimals(after["rest_debt_hours"], 0.00, "Field.rest_debt_hours")
        assert_two_decimals(
            after["latest_gmax_mean_value"], 210.0, "Field.latest_gmax_mean_value"
        )
        # Wear 100.00 x 0.50 + age 30.83 x 0.20 + a safety term clamped to 0.00
        # because 210.0 g is past the mandatory limit altogether.
        assert_two_decimals(
            after["condition_index_agronomic"], 56.17, "Field.condition_index_agronomic"
        )

    def test_the_cancellation_hop_spares_fixtures_already_under_way(
        self, client, roster
    ):
        """Hop four has a window filter, so play in progress is not torn down.

        "Hop four cancels **every** booking on the field whose `status` is
        `SCHEDULED` or `CONFIRMED` and whose `window_start_utc` is at or after the
        current logical instant, taking each `SCHEDULED → CANCELLED_UNSAFE` or
        `CONFIRMED → CANCELLED_UNSAFE`, and it visits them in order of
        `window_start_utc` ascending and then `created_at` ascending."

        "Bookings already in a terminal status are never touched, and neither are
        bookings whose windows have already begun."

        "Hop three increments the matching field counter —
        `open_mandatory_remediation_count` or `open_advisory_remediation_count` —
        and recomputes the posture."

        Design: Difficulty/transitive_cascade/failed_impact_test_cascades_through_order_posture_booking_to_ledger
        """
        field = fixtures.register_grass_main_1(client, roster)
        under_way = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-02T10:00:00Z",
            window_end_utc="2026-08-02T14:00:00Z",
            expected_participant_count=30,
        )
        still_ahead = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        fixtures.confirm_booking(client, roster, under_way["id"])
        fixtures.confirm_booking(client, roster, still_ahead["id"])

        # Two hours into the first window.
        fixtures.set_clock(client, roster, "2026-08-02T12:00:00Z")
        _assessment, order = fixtures.fail_field_unsafe(
            client,
            roster,
            field["id"],
            assessed_at_utc="2026-08-02T12:00:00Z",
        )
        assert order["severity"] == "MANDATORY"

        after = fixtures.read_field(client, roster, field["id"])
        assert after["play_status"] == "CLOSED_UNSAFE"
        assert after["open_mandatory_remediation_count"] == 1
        assert after["open_advisory_remediation_count"] == 0

        spared = fixtures.read_booking(client, roster, under_way["id"])
        assert spared["status"] == "CONFIRMED", (
            "a window that has already begun is not torn down"
        )
        swept = fixtures.read_booking(client, roster, still_ahead["id"])
        assert swept["status"] == "CANCELLED_UNSAFE"

        # Exactly one cancellation, so exactly one ledger entry and one increment.
        assert after["unsafe_cancellation_count"] == 1
        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={
                    "limit": 100,
                    "field_id": field["id"],
                    "entry_type": "UNSAFE_CANCELLATION",
                },
            )
        )
        assert meta["total_count"] == 1
        assert entries[0]["booking_id"] == still_ahead["id"]


class TestPlanApprovalMoneyCascade:
    def _two_plans_on_one_budget(self, client, full_roster):
        """Price two unrelated plans against one budget and submit only the first."""
        synthetic = fixtures.register_synthetic_stadium_1(client, full_roster)
        grass = fixtures.register_grass_practice_3(client, full_roster)
        budget = fixtures.authorize_budget(client, full_roster)

        first = fixtures.draft_plan(
            client,
            full_roster,
            synthetic["id"],
            budget["id"],
            synthetic["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        sibling = fixtures.draft_plan(
            client,
            full_roster,
            grass["id"],
            budget["id"],
            grass["version"],
            target_surface_type="NATURAL_GRASS",
            area_sq_ft=60000,
            priority_basis="REMAINING_LIFE",
            planned_install_year=2029,
        )
        fixtures.submit_plan(client, full_roster, first["id"])
        return budget, first, sibling

    def test_an_approval_locks_the_budget_and_defers_a_plan_it_never_named(
        self, client, full_roster
    ):
        """The fourth hop lands on an entity the request never mentioned.

        "Hop two increases the budget's `committed_amount_cents` by exactly
        `plan_funding_amount_cents` and recomputes `available_amount_cents`."

        "Hop three tests the lock: when `committed_amount_cents` has reached or
        passed `lock_threshold_amount_cents`, the budget moves `OPEN → LOCKED`."

        "Hop four is the consequence of that lock — **every other** plan on the
        same `capital_budget_id` whose `funding_status` is `DRAFT` moves `DRAFT →
        DEFERRED`, visited in order of `replacement_priority_score` descending and
        then `created_at` ascending — and a deferred plan can no longer be
        submitted until its budget reopens."

        "The plan must be in `DRAFT`, or the submission is refused with
        `ERR_PLAN_NOT_DRAFT`, and its budget must be `OPEN`, or it is refused with
        `ERR_BUDGET_LOCKED`."

        Design: Difficulty/transitive_cascade/plan_approval_cascades_budget_commitment_lock_to_sibling_deferral
        """
        budget, first, sibling = self._two_plans_on_one_budget(client, full_roster)
        assert first["plan_funding_amount_cents"] == 5243000
        # 60000 sq ft of grass at 22 cents, no waste stream, uplifted by 0.10.
        assert sibling["plan_funding_amount_cents"] == 1452000
        assert sibling["funding_status"] == "DRAFT"

        approved = fixtures.decide_plan(
            client,
            full_roster,
            first["id"],
            decision="APPROVE",
            decision_notes="Synthetic surface past nominal life.",
        )
        # Hop one.
        assert approved["funding_status"] == "APPROVED"
        # (100.00 - 65.00) x 0.80 with no mandatory order, plus the 8.00 penalty.
        assert_two_decimals(
            approved["replacement_priority_score"], 36.00, "replacement_priority_score"
        )

        after_budget = fixtures.read_budget(client, full_roster, budget["id"])
        # Hop two.
        assert after_budget["committed_amount_cents"] == 5243000
        assert after_budget["available_amount_cents"] == 582556
        # Hop three: the commitment lands exactly on the threshold.
        assert after_budget["lock_threshold_amount_cents"] == 5243000
        assert after_budget["status"] == "LOCKED"
        assert_capital_conserved(after_budget)

        # Hop four: the sibling was never named in the decision.
        deferred = fixtures.read_plan(client, full_roster, sibling["id"])
        assert deferred["funding_status"] == "DEFERRED"
        assert deferred["plan_funding_amount_cents"] == 1452000

        # A deferred plan is out of `DRAFT`, and the state precondition is checked
        # before the budget's own posture.
        validate_error(
            client.submit_replacement_plan(
                sibling["id"],
                factories.make_plan_submit_payload(full_roster.id_of("director")),
                full_roster.director_headers,
            ),
            ApiErrorId.PLAN_NOT_DRAFT,
            409,
        )
        assert (
            after_budget["available_amount_cents"]
            + after_budget["committed_amount_cents"]
            == 5825556
        )

    def test_a_rescission_unwinds_the_lock_and_the_deferral(self, client, full_roster):
        """The compensating action walks every hop of the cascade backwards.

        "A rescission takes the plan `APPROVED → RESCINDED` and releases exactly
        `plan_funding_amount_cents` back to the budget, decreasing
        `committed_amount_cents` by that precise figure and recomputing
        `available_amount_cents`."

        "If that release drops `committed_amount_cents` back below
        `lock_threshold_amount_cents`, the budget moves `LOCKED → OPEN`, and every
        plan on that budget whose `funding_status` is `DEFERRED` moves `DEFERRED →
        DRAFT` and becomes submittable again."

        "The disposal axis is also withdrawn: a `disposal_status` of `PENDING`
        moves `PENDING → NOT_APPLICABLE` and a `disposal_status` of `MANIFESTED`
        moves `MANIFESTED → NOT_APPLICABLE`, in the latter case retaining the
        recorded manifest values for audit while the obligation itself lapses."

        Design: Difficulty/transitive_cascade/plan_approval_cascades_budget_commitment_lock_to_sibling_deferral
        """
        budget, first, sibling = self._two_plans_on_one_budget(client, full_roster)
        fixtures.decide_plan(client, full_roster, first["id"], decision="APPROVE")
        assert (
            fixtures.read_plan(client, full_roster, sibling["id"])["funding_status"]
            == "DEFERRED"
        )

        rescinded = fixtures.decide_plan(
            client,
            full_roster,
            first["id"],
            decision="RESCIND",
            decision_notes="Capital redirected to the drainage programme.",
        )
        assert rescinded["funding_status"] == "RESCINDED"
        # The synthetic carpet no longer has to go anywhere.
        assert rescinded["disposal_status"] == "NOT_APPLICABLE"

        reopened = fixtures.read_budget(client, full_roster, budget["id"])
        assert reopened["committed_amount_cents"] == 0
        assert reopened["available_amount_cents"] == 5825556
        assert reopened["status"] == "OPEN"
        assert_capital_conserved(reopened)

        # The sibling is back where it started and may be submitted again.
        restored = fixtures.read_plan(client, full_roster, sibling["id"])
        assert restored["funding_status"] == "DRAFT"
        resubmitted = fixtures.submit_plan(client, full_roster, sibling["id"])
        assert resubmitted["funding_status"] == "SUBMITTED"
