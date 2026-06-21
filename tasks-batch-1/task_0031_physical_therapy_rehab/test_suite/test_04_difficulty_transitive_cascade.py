"""Difficulty Rule 4 — transitive_cascade.

Two cascades originating from different write endpoints:
  (A) POC discharge — depth-3: Visit CANCELLED → grant.units_consumed → grant CANCELLED.
  (B) Visit finalize — depth-2: cumulative_billed_cents → capped_status (→ EXCEEDED).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_poc_with_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    record_discharge_assessment,
    discharge_poc,
    make_therapist_headers,
    TEST_USERS,
)


class TestPocDischargeDepth3VisitCancelGrantRecomputeGrantCancel:
    """POC.discharge → (hop1) SCHEDULED Visit CANCELLED →
       (hop2) grant.units_consumed recomputed → (hop3) ACTIVE Grant CANCELLED.
    """

    def test_discharge_cancels_scheduled_visit_first_hop(self, api):
        """PRD §3.6: "First hop: every `SCHEDULED` visit reachable through any
        `AuthorizationGrant` of this plan is cancelled (`SCHEDULED → CANCELLED`),
        with each cancelled visit having its `updated_at` refreshed and `version`
        incremented."

        Design: Difficulty/transitive_cascade/poc_discharge_depth3_visit_cancel_grant_recompute_grant_cancel
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=20)
        v = schedule_visit(
            ctx["grant"]["id"], ctx["therapist"]["id"],
            scheduled_start_utc="2026-06-10T10:00:00Z",
            scheduled_end_utc="2026-06-10T11:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        record_discharge_assessment(
            ctx["poc"]["id"], ctx["therapist"]["id"],
            final_functional_score=70, goals_met_count=8, total_goals_count=10,
            assessed_on="2026-06-05",
        )
        discharged = discharge_poc(ctx["poc"]["id"], ctx["therapist"]["id"])
        assert discharged["status"] == "DISCHARGED"
        # Re-read the visit to confirm cascade.
        v_after = validate_success(
            api.get_visit(v["id"], TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert v_after["status"] == "CANCELLED"

    def test_discharge_recomputes_units_consumed_and_cancels_open_grant(self, api):
        """PRD §3.6: "Second hop: each affected grant has its `units_consumed`
        recomputed by the running-sum procedure (the cancelled visits drop out of the
        eligible set). Third hop: any `AuthorizationGrant` whose effective window is
        still open transitions `ACTIVE → CANCELLED`, with its `updated_at` and `version`
        updated."

        Design: Difficulty/transitive_cascade/poc_discharge_depth3_visit_cancel_grant_recompute_grant_cancel
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=20)
        schedule_visit(
            ctx["grant"]["id"], ctx["therapist"]["id"],
            scheduled_start_utc="2026-06-10T10:00:00Z",
            scheduled_end_utc="2026-06-10T11:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        record_discharge_assessment(
            ctx["poc"]["id"], ctx["therapist"]["id"],
            final_functional_score=70, goals_met_count=8, total_goals_count=10,
            assessed_on="2026-06-05",
        )
        discharge_poc(ctx["poc"]["id"], ctx["therapist"]["id"])
        grant_after = validate_success(
            api.get_authorization_grant(ctx["grant"]["id"], TEST_USERS["billing_clerk_headers"]),
            200,
        )
        # Hop 2: cancelled visits drop out → units_consumed back to 0.
        assert grant_after["units_consumed"] == 0
        # Hop 3: grant CANCELLED.
        assert grant_after["status"] == "CANCELLED"


class TestVisitFinalizeDepth2CumulativeThenPostureToExceeded:
    """A third finalize on a MEDICARE POC pushes cumulative_billed_cents past the
    20000¢ cap → capped_status flips UNDER_CAP/AT_CAP_WARNING → EXCEEDED.
    """

    def test_third_finalize_refreshes_cumulative_billed_cents_to_exceed(self, api):
        """PRD §3.5: "The plan's `cumulative_billed_cents` is refreshed by summing
        `billed_cents` over every `FINALIZED` visit reachable through any of the plan's
        grants, again ordered by `created_at` then `id` for determinism."
        PRD §2.7: "a `MEDICARE` plan is capped at twenty thousand cents (two hundred dollars)"

        Design: Difficulty/transitive_cascade/visit_finalize_depth2_cumulative_then_posture_to_exceeded
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=60,
        )
        gid = ctx["grant"]["id"]
        th = ctx["therapist"]["id"]
        poc_id = ctx["poc"]["id"]
        # V1: 90min/CPT_97110 → 6 units → 3200 + round(1600)*5 = 11200
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        finalize_visit(v1["id"], poc_id)
        # V2: 45min/CPT_97140 → 3 units → 3500 + 1750*2 = 7000
        v2 = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:45:00Z",
                            planned_minutes=45, cpt_code="CPT_97140_MANUAL")
        complete_visit(v2["id"], th, actual_minutes=45)
        finalize_visit(v2["id"], poc_id)
        # V3: ready-to-finalize. 90min/CPT_97110 → billed=11200 → cum=18200+11200=29400.
        v3 = schedule_visit(gid, th, "2026-06-04T09:00:00Z", "2026-06-04T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v3["id"], th, actual_minutes=90)
        v3_final = finalize_visit(v3["id"], poc_id)
        assert v3_final["billed_cents"] == 11200
        poc_after = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert poc_after["cumulative_billed_cents"] == 29400

    def test_finalize_cascade_flips_capped_status_to_exceeded(self, api):
        """PRD §3.5: "Finally, the plan's `capped_status` is re-evaluated against the
        refreshed `cumulative_billed_cents` per the three-bucket rule in §2.7."
        PRD §2.7: "`EXCEEDED` when `cumulative_billed_cents` is strictly greater than
        `capped_dollar_limit_cents`."

        Design: Difficulty/transitive_cascade/visit_finalize_depth2_cumulative_then_posture_to_exceeded
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=60,
        )
        gid = ctx["grant"]["id"]
        th = ctx["therapist"]["id"]
        poc_id = ctx["poc"]["id"]
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        finalize_visit(v1["id"], poc_id)
        v2 = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:45:00Z",
                            planned_minutes=45, cpt_code="CPT_97140_MANUAL")
        complete_visit(v2["id"], th, actual_minutes=45)
        finalize_visit(v2["id"], poc_id)
        # Before V3 finalize: cum = 11200 + 7000 = 18200; 18200 >= 0.90 * 20000=18000 → AT_CAP_WARNING.
        poc_before = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert poc_before["cumulative_billed_cents"] == 18200
        assert poc_before["capped_status"] == "AT_CAP_WARNING"
        v3 = schedule_visit(gid, th, "2026-06-04T09:00:00Z", "2026-06-04T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v3["id"], th, actual_minutes=90)
        finalize_visit(v3["id"], poc_id)
        poc_after = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert poc_after["cumulative_billed_cents"] == 29400
        assert poc_after["capped_status"] == "EXCEEDED"
