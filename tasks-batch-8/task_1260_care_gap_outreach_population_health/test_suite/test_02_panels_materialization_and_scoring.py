"""Panel activation, gap materialization, and priority scoring claims
(PRD §2.7, §3.2, §3.3)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, assert_care_gap, assert_timestamp_instant_equal,
    setup_panel_scenario, advance_clock, make_admin_headers,
)


class TestGapMaterialization:
    def test_care_gap_computed_fields_ignore_input(self, api):
        """PRD §3.2: "From these the system computes the gap's `due_date`: when a
        qualifying event exists, the due date is that event's date plus the measure's
        `lookback_days`; when `last_qualifying_event_at` is null, the due date falls
        back to the member's enrollment date."
        PRD §3.3: "`priority_score` is an integer from 0 to 100 computed from five
        terms, summed and then clamped into that range with any fraction floored away
        after clamping."

        Design: Corner/entities/care_gap_computed_fields_ignore_input
        """
        scenario = setup_panel_scenario(num_members=1)
        assert len(scenario["gaps"]) == 1, f"Expected 1 materialized gap, got {len(scenario['gaps'])}"
        gap = scenario["gaps"][0]
        assert_care_gap(gap)
        # No qualifying event: due_date falls back to the member's enrollment date,
        # which is the registry clock at registration (the default instant).
        assert_timestamp_instant_equal(gap["due_date"], "2026-05-01T00:00:00Z",
                                       label="due_date")

    def test_initial_state_care_gap_is_open(self, api):
        """PRD §3.3: "A gap is born `OPEN` at panel activation."

        Design: Corner/state_machines/initial_state_care_gap_is_open
        """
        scenario = setup_panel_scenario(num_members=1)
        assert len(scenario["gaps"]) == 1
        gap = scenario["gaps"][0]
        assert gap["status"] == "OPEN", f"Expected OPEN gap, got {gap['status']}"
        assert gap.get("closure_source") is None, (
            "closure_source must be null until the gap closes (PRD §3.3)")


class TestPriorityScoring:
    def test_priority_score_correct_result_known_inputs(self, api):
        """PRD §3.3: "The first term is the overdue contribution: the gap's
        `days_overdue` capped at 90 days, so no gap earns more than 90 points from
        age alone. The second term is the clinical weight: the member's risk tier
        contributes a weight of 1 for `LOW`, 2 for `MEDIUM`, or 3 for `HIGH`, the
        measure's domain contributes a weight of 1 for `SCREENING` or 2 for
        `MED_ADHERENCE`, and the product of the two weights is multiplied by 5. The
        third term is the outreach decay: 20 points minus 4 points per recorded
        outreach attempt, floored at zero, so unworked gaps rise to the top and
        heavily worked gaps sink."
        PRD §3.3: "a score of 80 or more is `P1_URGENT`, at least 60 but below 80 is
        `P2_HIGH`, at least 30 but below 60 is `P3_ROUTINE`, and below 30 is `P4_LOW`."

        Freshly materialized gap at the default clock: days_overdue=0, LOW x
        SCREENING, zero attempts -> 0 + 1*1*5 + 20 = 25 -> P4_LOW.

        Design: Corner/calculations/priority_score_correct_result_known_inputs
        """
        scenario = setup_panel_scenario(num_members=1)  # LOW member, SCREENING measure
        gap = scenario["gaps"][0]
        assert gap["priority_score"] == 25, (
            f"Expected priority_score 25, got {gap['priority_score']}")
        assert gap["priority_band"] == "P4_LOW", (
            f"Expected P4_LOW band, got {gap['priority_band']}")

    def test_priority_score_input_set_filtering(self, api):
        """PRD §3.3: "Gaps in `EXCLUDED` or `EXPIRED` status are exempt from
        recomputation and keep their last computed score."
        PRD §3.8: "Whenever the registry clock is at or past a gap's `due_date` plus
        the measure's `reporting_lag_days` and the gap still sits in any of `OPEN`,
        `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, `PENDING_EVIDENCE`, or
        `REOPENED`, the system moves it to the terminal `EXPIRED` status and
        decrements the member's `open_gap_count` by one."

        Design: Corner/calculations/priority_score_input_set_filtering
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        registry_id = scenario["registry"]["id"]
        # Move the clock well past due_date + reporting_lag_days to expire the gap.
        advance_clock(registry_id, "2027-08-01T00:00:00Z")
        gaps = api_client.list_panel_care_gaps(
            scenario["panel"]["id"], make_admin_headers())
        gap_pre = get_success_data(gaps)[0]
        assert gap_pre["status"] == "EXPIRED", (
            f"Expected EXPIRED after clock crossed due_date + lag, got {gap_pre['status']}")
        score_pre = gap_pre["priority_score"]
        # A later clock change must not recompute the expired gap's score.
        advance_clock(registry_id, "2027-09-01T00:00:00Z")
        gap_post = get_success_data(api_client.get_care_gap(gap_pre["id"],
                                                            make_admin_headers()))
        assert gap_post["status"] == "EXPIRED"
        assert gap_post["priority_score"] == score_pre, (
            f"EXPIRED gap must keep its last computed score: {score_pre} -> "
            f"{gap_post['priority_score']}")


class TestPanelRebuildOcc:
    def test_panel_rebuild_occ_stale_version(self, api):
        """PRD §2.7: "Rebuilding a panel requires the request to carry
        `expected_panel_version` holding the caller's last observed `version` of
        that panel. If the panel's current `version` has advanced beyond what the
        caller observed — because another writer triggered a rebuild or any other
        mutation in the meantime — the rebuild is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the caller from rebuilding on top of a panel state it
        never saw."
        PRD §3.2: "Finalizing the rebuild returns the panel to `ACTIVE`."

        Design: Corner/endpoints/panel_rebuild_occ_stale_version
        """
        scenario = setup_panel_scenario(num_members=1)
        panel = scenario["panel"]
        observed_version = panel["version"]
        # First rebuild succeeds and increments the panel version.
        resp = api_client.rebuild_panel(
            panel["id"], {"expected_panel_version": observed_version},
            make_admin_headers())
        validate_success(resp, 200)
        # Return the panel to ACTIVE so only the OCC check can fail next.
        get_success_data(api_client.finalize_rebuild_panel(panel["id"],
                                                           make_admin_headers()))
        # Rebuilding again with the stale observed version is rejected.
        resp = api_client.rebuild_panel(
            panel["id"], {"expected_panel_version": observed_version},
            make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
