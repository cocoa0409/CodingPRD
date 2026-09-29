"""Two contended resources, two deliberately opposite interval conventions.

An asset's authorized windows are compared with inclusive bounds widened by the
asset class's cooldown, so a network window opening exactly twenty-four hours
after another closes still collides. A tester's occupation intervals are
compared with strict inequalities and no widening at all, so a booking that
begins at the instant another ends is accepted — and the cap that finally
refuses a third booking counts overlaps in aggregate rather than pairwise.
"""

from test_helpers import (
    advance_clock,
    assert_error_id,
    assert_exact_int,
    assert_hour_ledger,
    assert_page,
    assert_score,
    build_scenario,
    created_data,
    engagement_version,
    factories,
    success_data,
)
from test_helpers.api_errors import (
    ERR_ENGAGEMENT_HOURS_EXCEEDED,
    ERR_TARGET_WINDOW_COLLISION,
    ERR_TESTER_CAPACITY_EXCEEDED,
    ERR_WINDOW_OUTSIDE_ENGAGEMENT,
)

# The first network window closes on 10 September, so the 24-hour cooldown
# reaches forward to exactly 11 September at midnight.
FIRST_TARGET_WINDOW_END = "2026-09-10T00:00:00Z"
COLLIDING_WINDOW_START = "2026-09-11T00:00:00Z"
CLEAR_WINDOW_START = "2026-09-11T00:00:01Z"
SECOND_TARGET_WINDOW_END = "2026-09-12T00:00:00Z"

# The segmentation candidate scores 0.45*55 + 0.30*75 + 0.20*65 + 0.05*40.
SEGMENTATION_PRIORITY_SCORE = 62.25


def _network_engagement_with_one_target(client):
    """A network engagement whose first authorized window runs 05 to 10 September."""
    return build_scenario(
        client,
        stage="targets",
        asset=factories.core_network_asset_payload(),
        scope_item={
            "justification": "Internal segmentation review",
            "requested_engagement_hours": 90,
        },
        decision_note="Segmentation review approved",
        engagement={"engagement_type": "NETWORK_TEST", "hours_allocated": 90},
        roe={
            "exclusions": ["10.0.9.0/24"],
            "allowed_techniques": ["LATERAL_MOVEMENT", "DOS"],
            "emergency_stop_procedure": "Drop the test VLAN and page the NOC",
            "escalation_contact": "noc@example.com",
        },
        target={
            "window_end": FIRST_TARGET_WINDOW_END,
            "technique_allowlist": ["LATERAL_MOVEMENT"],
        },
    )


def _propose_a_second_window(client, scenario, window_start):
    """Ask for a second denial-of-service window on the same network segment."""
    return client.create_authorized_target(
        factories.authorized_target_payload(
            scenario["roe_id"],
            scenario["asset_id"],
            window_start=window_start,
            window_end=SECOND_TARGET_WINDOW_END,
            technique_allowlist=["DOS"],
        )
    )


class TestNetworkWindowsCollideAcrossTheInclusiveCooldown:
    """A full day of quiet on each side of a network test, inclusively compared."""

    def test_a_network_target_carries_a_full_day_of_cooldown(self, client):
        """The buffer comes from the asset's class, not from the window's length.

        PRD: "Each target records `cooldown_hours`, resolved from the asset's class: an `APPLICATION` asset needs no buffer at all, a `CLOUD` asset needs half a day of quiet on each side, and a `NETWORK` asset needs a full day on each side."
        PRD: "On acceptance the target opens at `ACTIVE` state with a null `exclusion_reason`, the parent document's `active_target_count` is incremented, and the document's `version` advances."
        PRD: "Under `RISK_DRIVEN` — the default — exposure is weighted 0.45, tier points 0.30, staleness points 0.20 and regime points 0.05, so attack surface and business criticality dominate."

        Design: Difficulty/resource_temporal_overlap/network_target_windows_collide_across_an_inclusive_cooldown_gap
        """
        scenario = _network_engagement_with_one_target(client)

        target = scenario["target"]
        assert_exact_int(target["cooldown_hours"], 24, "cooldown_hours")
        assert target["state"] == "ACTIVE", (
            f"target state: expected ACTIVE, got {target['state']}"
        )
        assert target["exclusion_reason"] is None
        assert_score(
            scenario["scope_item"]["priority_score"],
            SEGMENTATION_PRIORITY_SCORE,
            "priority_score",
        )

    def test_a_window_exactly_one_cooldown_later_still_collides(self, client):
        """11 September at midnight is the last colliding instant, not the first clear one.

        PRD: "A candidate target collides with an existing target when that existing target is on the same asset, is currently `ACTIVE`, and the two widened windows touch — specifically, when the candidate's `window_start` is at or before the existing target's `window_end` extended forward by the cooldown, **and** the candidate's `window_end` is at or after the existing target's `window_start` pulled back by the cooldown."
        PRD: "Both comparisons are inclusive, so a new window that begins exactly one cooldown period after an existing window ends still collides, while a window beginning one second later does not."
        PRD: "The target's window must lie entirely inside the engagement's own window, and a window that pokes out at either end is refused with `ERR_WINDOW_OUTSIDE_ENGAGEMENT`."

        Design: Difficulty/resource_temporal_overlap/network_target_windows_collide_across_an_inclusive_cooldown_gap
        """
        scenario = _network_engagement_with_one_target(client)

        response = _propose_a_second_window(client, scenario, COLLIDING_WINDOW_START)

        payload = assert_error_id(response, ERR_TARGET_WINDOW_COLLISION)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a colliding window, got {response.status_code}"
        )
        assert payload["error_id"] != ERR_WINDOW_OUTSIDE_ENGAGEMENT, (
            "both candidate windows sit inside the engagement's own window"
        )

    def test_one_second_past_the_widened_bound_is_accepted(self, client):
        """The refusal is a boundary decision, so a second later the same window fits.

        PRD: "Both comparisons are inclusive, so a new window that begins exactly one cooldown period after an existing window ends still collides, while a window beginning one second later does not."

        Design: Difficulty/resource_temporal_overlap/network_target_windows_collide_across_an_inclusive_cooldown_gap
        """
        scenario = _network_engagement_with_one_target(client)
        _propose_a_second_window(client, scenario, COLLIDING_WINDOW_START)

        accepted = created_data(
            _propose_a_second_window(client, scenario, CLEAR_WINDOW_START)
        )

        assert accepted["state"] == "ACTIVE", (
            f"target state: expected ACTIVE, got {accepted['state']}"
        )
        assert_exact_int(accepted["cooldown_hours"], 24, "cooldown_hours")

    def test_the_document_counts_only_the_two_accepted_windows(self, client):
        """The rejected candidate created no row, so the count stops at two.

        PRD: "On acceptance the target opens at `ACTIVE` state with a null `exclusion_reason`, the parent document's `active_target_count` is incremented, and the document's `version` advances."
        PRD: "The server stamps `drafted_by_user_id` from `X-User-ID`, opens the document at `DRAFT` status, and sets `active_target_count` to 0."

        Design: Difficulty/resource_temporal_overlap/network_target_windows_collide_across_an_inclusive_cooldown_gap
        """
        scenario = _network_engagement_with_one_target(client)
        _propose_a_second_window(client, scenario, COLLIDING_WINDOW_START)
        _propose_a_second_window(client, scenario, CLEAR_WINDOW_START)

        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert_exact_int(document["active_target_count"], 2, "active_target_count")
        assert document["status"] == "DRAFT", (
            f"document status: expected DRAFT, got {document['status']}"
        )
        assert_page(
            client.list_authorized_targets(params={"roe_id": scenario["roe_id"]}),
            total_count=2,
            row_count=2,
        )


# The tester's occupation intervals: A2 begins at the exact instant A1 ends.
T_STAFFING = "2026-09-06T08:00:00Z"
FIRST_INTERVAL_START = "2026-09-07T09:00:00Z"
FIRST_INTERVAL_END = "2026-09-10T09:00:00Z"
SECOND_INTERVAL_END = "2026-09-12T09:00:00Z"
THIRD_INTERVAL_START = "2026-09-08T00:00:00Z"
THIRD_INTERVAL_END = "2026-09-11T00:00:00Z"


def _book(client, scenario, interval_start, interval_end):
    """Book a ten-hour MEMBER interval, re-reading the engagement's version first."""
    return client.create_tester_assignment(
        factories.tester_assignment_payload(
            scenario["engagement_id"],
            scenario["tester_id"],
            engagement_version(client, scenario["engagement_id"]),
            [scenario["asset_id"]],
            assignment_role="MEMBER",
            interval_start=interval_start,
            interval_end=interval_end,
            requested_hours=10,
        )
    )


def _tester_holding_one_interval(client):
    """A cleared tester with a cap of two and one ten-hour interval already booked."""
    scenario = build_scenario(client, stage="tester_cleared")
    advance_clock(client, T_STAFFING)
    created_data(_book(client, scenario, FIRST_INTERVAL_START, FIRST_INTERVAL_END))
    return scenario


class TestTesterIntervalsAreHalfOpenAndCappedInAggregate:
    """Strict comparisons at the seam, and a cap counted across all overlaps."""

    def test_an_interval_beginning_when_another_ends_does_not_overlap_it(self, client):
        """Both comparisons are strict, so adjacency is free of charge.

        PRD: "The server counts the tester's existing assignments whose `access_state` is either `REQUESTED` or `PROVISIONED` — across every engagement and every plan, not just this one — and treats an existing assignment as overlapping the request when its `interval_start` falls strictly before the requested `interval_end` **and** its `interval_end` falls strictly after the requested `interval_start`."
        PRD: "Because both comparisons are strict, intervals are half-open: a booking that begins at the exact instant another one ends does **not** overlap it."
        PRD: "Note that this is the opposite boundary convention from the authorized-target cooldown check in §3.4, where both comparisons are inclusive."

        Design: Difficulty/resource_temporal_overlap/tester_intervals_are_half_open_and_capped_in_aggregate
        """
        scenario = _tester_holding_one_interval(client)

        adjacent = created_data(
            _book(client, scenario, FIRST_INTERVAL_END, SECOND_INTERVAL_END)
        )

        assert adjacent["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {adjacent['access_state']}"
        )
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=20, consumed=0, available=60)

    def test_a_third_interval_overlapping_both_reaches_the_aggregate_cap(self, client):
        """Two live overlaps meet a cap of two, and the money is nowhere near the limit.

        PRD: "If the number of overlapping live assignments has already reached the tester's `max_concurrent_engagements`, the booking is refused with `ERR_TESTER_CAPACITY_EXCEEDED`."
        PRD: "Fourth and last comes the money: `requested_hours` must be no greater than the engagement's current `hours_available`, with equality passing, and an over-draw is refused with `ERR_ENGAGEMENT_HOURS_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/tester_intervals_are_half_open_and_capped_in_aggregate
        """
        scenario = _tester_holding_one_interval(client)
        created_data(_book(client, scenario, FIRST_INTERVAL_END, SECOND_INTERVAL_END))
        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert_exact_int(
            tester["max_concurrent_engagements"], 2, "max_concurrent_engagements"
        )

        response = _book(client, scenario, THIRD_INTERVAL_START, THIRD_INTERVAL_END)

        payload = assert_error_id(response, ERR_TESTER_CAPACITY_EXCEEDED)
        assert response.status_code == 409, (
            f"expected HTTP 409 for an overbooked tester, got {response.status_code}"
        )
        assert payload["error_id"] != ERR_ENGAGEMENT_HOURS_EXCEEDED, (
            "ten requested hours against sixty available cannot be a fiscal refusal"
        )

    def test_the_refused_interval_left_two_rows_and_twenty_reserved_hours(self, client):
        """A rejected booking reserves nothing and adds no row.

        PRD: "Stated as standing definitions rather than as increments: an engagement's `hours_reserved` is the sum of `requested_hours` over its assignments whose `access_state` is `REQUESTED` or `PROVISIONED`; its `hours_consumed` is the sum of `settled_hours` over its assignments whose `access_state` is `REVOKED`; and its `hours_available` is `hours_allocated` minus `hours_reserved` minus `hours_consumed`."
        PRD: "Revoked assignments release their interval and are not counted."

        Design: Difficulty/resource_temporal_overlap/tester_intervals_are_half_open_and_capped_in_aggregate
        """
        scenario = _tester_holding_one_interval(client)
        created_data(_book(client, scenario, FIRST_INTERVAL_END, SECOND_INTERVAL_END))

        _book(client, scenario, THIRD_INTERVAL_START, THIRD_INTERVAL_END)

        assert_page(
            client.list_tester_assignments(params={"tester_id": scenario["tester_id"]}),
            total_count=2,
            row_count=2,
        )
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=20, consumed=0, available=60)
