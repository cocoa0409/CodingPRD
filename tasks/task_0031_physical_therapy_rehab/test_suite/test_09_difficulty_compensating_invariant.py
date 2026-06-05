"""Difficulty Rule 9 — compensating_invariant.

Two conserved-quantity invariants holding through forward / compensating action pairs:
  (A) grant.units_consumed: schedule then cancel a Visit → invariant holds.
  (B) PlanOfCare.cumulative_billed_cents: discharge cascade cancels only SCHEDULED
      visits; FINALIZED visits' billed_cents survive → invariant holds.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_poc_with_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    record_discharge_assessment,
    discharge_poc,
    make_therapist_headers,
    TEST_USERS,
)


class TestGrantUnitsConsumedUnchangedAfterScheduleThenCancel:
    """Conserved = grant.units_consumed. Forward: schedule a Visit (planned_units
    reserved). Compensating: cancel that Visit (CANCELLED drops from the eligible
    set per PRD §3.4). Invariant: units_consumed before == units_consumed after.
    """

    def test_schedule_increments_units_consumed_and_cancel_restores_it(self, api):
        """PRD §3.4: "the system enumerates the grant's visits whose `status` is one of
        `SCHEDULED`, `COMPLETED`, or `FINALIZED`, orders them by `created_at` ascending
        and then by `id` ascending, and sums each visit's `planned_units` while the visit
        is still `SCHEDULED` or its `billable_units` once the visit has reached `COMPLETED`
        or `FINALIZED`. Visits in `CANCELLED` or `NO_SHOW` status contribute nothing."
        PRD §3.5: "The grant's `units_consumed` is recomputed on cancellation."

        Design: Difficulty/compensating_invariant/grant_units_consumed_unchanged_after_schedule_then_cancel
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=20)
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        # Pre-existing scheduled visit V_pre: planned 30min → 2 units → consumed=2.
        v_pre = schedule_visit(
            gid, th, "2026-06-05T10:00:00Z", "2026-06-05T10:30:00Z",
            planned_minutes=30, cpt_code="CPT_97110_THER_EX",
        )
        g_pre = validate_success(
            api.get_authorization_grant(gid, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert g_pre["units_consumed"] == 2
        # Forward action: schedule a 2nd visit, planned 30min → consumed=4.
        v_new = schedule_visit(
            gid, th, "2026-06-06T10:00:00Z", "2026-06-06T10:30:00Z",
            planned_minutes=30, cpt_code="CPT_97110_THER_EX",
        )
        g_mid = validate_success(
            api.get_authorization_grant(gid, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert g_mid["units_consumed"] == 4
        # Compensating action: cancel v_new (PlatformAdmin override is permitted any time).
        validate_success(
            api.cancel_visit(v_new["id"], TEST_USERS["platform_admin_headers"]), 200,
        )
        g_post = validate_success(
            api.get_authorization_grant(gid, TEST_USERS["billing_clerk_headers"]), 200,
        )
        # Invariant: post == pre.
        assert g_post["units_consumed"] == 2

    def test_cancel_drops_planned_units_per_running_sum_filter(self, api):
        """PRD §3.4: "Visits in `CANCELLED` or `NO_SHOW` status contribute nothing."

        Companion assertion: after cancellation, the conserved quantity returns to its
        pre-trigger value precisely because the running sum excludes CANCELLED rows.

        Design: Difficulty/compensating_invariant/grant_units_consumed_unchanged_after_schedule_then_cancel
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=20)
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        v = schedule_visit(
            gid, th, "2026-06-05T10:00:00Z", "2026-06-05T10:30:00Z",
            planned_minutes=30, cpt_code="CPT_97110_THER_EX",
        )
        g_with = validate_success(
            api.get_authorization_grant(gid, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert g_with["units_consumed"] == 2
        validate_success(api.cancel_visit(v["id"], TEST_USERS["platform_admin_headers"]), 200)
        g_without = validate_success(
            api.get_authorization_grant(gid, TEST_USERS["billing_clerk_headers"]), 200,
        )
        # The CANCELLED visit contributes nothing → consumed is zero.
        assert g_without["units_consumed"] == 0


class TestPocCumulativeBilledUnchangedAfterDischargeCancelsOnlyScheduled:
    """Conserved = PlanOfCare.cumulative_billed_cents. 2 FINALIZED Visits drive
    cum = 11200 + 7000 = 18200¢. Discharge cancels future SCHEDULED visits but
    does NOT touch FINALIZED ones (PRD §3.5 cumulative_billed input filter:
    status==FINALIZED). Invariant: cum AFTER discharge == cum BEFORE discharge.
    """

    def test_cumulative_billed_preserved_across_discharge_cascade(self, api):
        """PRD §3.5: "The plan's `cumulative_billed_cents` is refreshed by summing
        `billed_cents` over every `FINALIZED` visit reachable through any of the plan's
        grants, again ordered by `created_at` then `id` for determinism."
        PRD §3.6: "First hop: every `SCHEDULED` visit reachable through any
        `AuthorizationGrant` of this plan is cancelled (`SCHEDULED → CANCELLED`),
        with each cancelled visit having its `updated_at` refreshed and `version`
        incremented."

        Design: Difficulty/compensating_invariant/poc_cumulative_billed_unchanged_after_discharge_cancels_only_scheduled
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=30,
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        finalize_visit(v1["id"], poc_id)
        v2 = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:45:00Z",
                            planned_minutes=45, cpt_code="CPT_97140_MANUAL")
        complete_visit(v2["id"], th, actual_minutes=45)
        finalize_visit(v2["id"], poc_id)
        # Future SCHEDULED V3 (to be cancelled by discharge cascade).
        v3 = schedule_visit(gid, th, "2026-06-20T09:00:00Z", "2026-06-20T10:00:00Z",
                            planned_minutes=60, cpt_code="CPT_97110_THER_EX")
        poc_pre = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert poc_pre["cumulative_billed_cents"] == 18200
        record_discharge_assessment(poc_id, th, final_functional_score=70,
                                    goals_met_count=8, total_goals_count=10,
                                    assessed_on="2026-06-10")
        discharge_poc(poc_id, th)
        poc_post = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        v3_after = validate_success(
            api.get_visit(v3["id"], TEST_USERS["billing_clerk_headers"]), 200,
        )
        # SCHEDULED V3 cancelled (hop 1); FINALIZED V1, V2 untouched; cum invariant.
        assert v3_after["status"] == "CANCELLED"
        assert poc_post["cumulative_billed_cents"] == 18200

    def test_finalized_visits_remain_finalized_after_discharge(self, api):
        """PRD §3.5: "Once a visit reaches `FINALIZED`, `CANCELLED`, or `NO_SHOW`,
        no further transitions are available."

        Companion assertion: the discharge cascade's first hop is scoped to SCHEDULED
        visits, so the previously FINALIZED visits stay FINALIZED — the conserved
        cumulative quantity is preserved precisely because their billed_cents stay in
        the input set.

        Design: Difficulty/compensating_invariant/poc_cumulative_billed_unchanged_after_discharge_cancels_only_scheduled
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=30,
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        finalize_visit(v1["id"], poc_id)
        record_discharge_assessment(poc_id, th, final_functional_score=70,
                                    goals_met_count=8, total_goals_count=10,
                                    assessed_on="2026-06-10")
        discharge_poc(poc_id, th)
        v1_after = validate_success(
            api.get_visit(v1["id"], TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert v1_after["status"] == "FINALIZED"
