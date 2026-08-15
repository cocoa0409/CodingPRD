"""Compliance posture score: weighted sums across tier boundaries and the
fail-then-verify restoration invariant (PRD §2.9, §3.4, §3.5, §3.9)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_owner_headers, make_reviewer_headers,
    set_clock, create_facility, create_tank, add_component, create_technician,
    create_operator, issue_training, create_record, create_order, schedule_order,
    start_order, record_results, certify_order, get_facility, get_deficiency,
    create_release_event_payload, create_started_order,
    setup_started_cp_order, deficiency_for_order,
    cp_readings, cp_divergence_readings,
    OPEN_RELEASE_WEIGHT, LAPSED_OPERATOR_WEIGHT, MAJOR_WEIGHT,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]


def _setup_posture_site(api):
    """Facility ACTIVE with an IN_SERVICE tank carrying a CATHODIC_PROTECTION
    component, one open SUSPECTED release (-10), and one ACTIVE class-C operator
    whose certificate (completed 2025-06-01) expires 2026-06-01."""
    set_clock("2026-05-01T00:00:00Z")
    facility = create_facility(facility_name="Posture Site", state_code="WA")
    tank = create_tank(facility["id"])
    facility = validate_success(api.activate_facility(facility["id"], OWNER), 200)
    tank = validate_success(api.place_in_service(tank["id"], OWNER), 200)
    comp = add_component(tank["id"], "CATHODIC_PROTECTION", serial_no="CP-9")
    validate_success(api.create_release_event(
        create_release_event_payload(facility["id"], source_description="ATG alarm"),
        OWNER), 201)
    trainer = create_technician([], trainer=True, full_name="Trainer Tess")
    op = create_operator(facility["id"], "C", full_name="Op A")
    issue_training(op["id"], "C", "2025-06-01T00:00:00Z", trainer["id"])
    validate_success(api.activate_operator(op["id"], OWNER), 200)
    return {"facility": facility, "tank": tank, "component": comp, "operator": op}


def _run_posture_close(api, ctx):
    """Record the 2026-05 release-detection record, then close the period after
    the operator's certificate has expired."""
    set_clock("2026-05-20T00:00:00Z")
    create_record(ctx["tank"]["id"], "2026-05",
                  readings_summary={"atg_log": "clean"})
    set_clock("2026-06-11T00:00:00Z")
    return validate_success(api.run_monthly_close(
        ctx["facility"]["id"], {"period_month": "2026-05"}, ADMIN), 200)


def _run_fail_and_verify(api, ctx):
    """CP survey FAIL -> MAJOR deficiency; correct; linked re-test PASS certified.
    Returns (deficiency, facility_mid, facility_final)."""
    t_cp = create_technician(["CP_TESTER"], full_name="CP Tester")
    t_rev = create_technician([], full_name="Reviewer Ray")
    ctx2 = {"facility": ctx["facility"], "tank": ctx["tank"], "tester": t_cp}
    so1 = create_started_order(
        ctx2, "CP_SURVEY", "2026-06-12T10:00:00Z", "2026-06-12T11:00:00Z",
        "2026-06-12T10:30:00Z", component_id=ctx["component"]["id"],
        line_items=[{"description": "cp", "qty": 1, "unit_price_cents": 40000}])
    record_results(so1["id"], t_cp["id"], cp_divergence_readings("INSTANT_OFF"))
    facility_mid = get_facility(ctx["facility"]["id"])

    d1 = deficiency_for_order(so1["id"])
    validate_success(api.order_correction(d1["id"], OWNER), 200)
    validate_success(api.mark_corrected(d1["id"], OWNER), 200)
    so2 = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "CP_SURVEY",
                       component_id=ctx["component"]["id"],
                       linked_deficiency_id=d1["id"],
                       line_items=[{"description": "cp retest", "qty": 1,
                                    "unit_price_cents": 40000}])
    schedule_order(so2["id"], t_cp["id"],
                   "2026-06-13T10:00:00Z", "2026-06-13T11:00:00Z")
    start_order(so2["id"], t_cp["id"], "2026-06-13T10:30:00Z")
    record_results(so2["id"], t_cp["id"], cp_readings(-900, -950, -600))
    certify_order(so2["id"], t_rev["id"])
    facility_final = get_facility(ctx["facility"]["id"])
    return get_deficiency(d1["id"]), facility_mid, facility_final


class TestPostureWeightedSumTierBoundary:
    def test_monthly_close_lapse_and_release_weights(self, api):
        """PRD §2.9: "Each release event of the facility in `SUSPECTED`,
        `CONFIRMED`, or `CLEANUP_IN_PROGRESS` status subtracts 10 points. Each
        operator of the facility in `LAPSED` status subtracts 5 points."
        PRD §3.9: "Second, the operator lapse sweep of §3.7 lapses every `ACTIVE`
        operator whose latest class certificate has expired." and "The checkpoint
        returns the counts it produced: `deficiencies_created`, `operators_lapsed`,
        `deficiencies_escalated`, plus the refreshed `posture_score` and
        `compliance_posture`."

        Design: Difficulty/combinatorial_formula/posture_score_weighted_sum_tier_boundary
        """
        ctx = _setup_posture_site(api)
        result = _run_posture_close(api, ctx)
        assert result["deficiencies_created"] == 0, "2026-05 record exists -> no gap"
        assert result["operators_lapsed"] == 1, (
            "class-C cert completed 2025-06-01 expired 2026-06-01 <= clock")
        # 100 - 10 (open release) - 5 (lapsed operator) = 85.
        assert result["posture_score"] == 100 - OPEN_RELEASE_WEIGHT - LAPSED_OPERATOR_WEIGHT == 85
        assert result["compliance_posture"] == "COMPLIANT"

    def test_major_fail_crosses_tier_and_verify_restores(self, api):
        """PRD §2.9: "Each deficiency of the facility in `OPEN`,
        `CORRECTION_ORDERED`, `CORRECTED`, `RE_TEST_SCHEDULED`, or `ESCALATED`
        status subtracts its severity weight — 25 points for `CRITICAL`, 15 for
        `MAJOR`, 5 for `MINOR`" and "The label follows the score: `COMPLIANT` when
        the score is at least 85, `DEFICIENT` when it is at least 60 but below 85,
        and `NON_COMPLIANT` when it falls below 60. Deficiencies that have reached
        `VERIFIED_CLOSED` and releases that are `DISMISSED` or `CLOSED` no longer
        count against the score."
        PRD §3.5: "a `PASS` moves the deficiency to `VERIFIED_CLOSED`, records the
        certifying order as `verified_by_service_order_id`, restores any referenced
        component to `IN_SERVICE`, and recomputes the facility posture now that the
        deficiency has left the open set"

        Design: Difficulty/combinatorial_formula/posture_score_weighted_sum_tier_boundary
        """
        ctx = _setup_posture_site(api)
        result = _run_posture_close(api, ctx)
        assert result["posture_score"] == 85

        deficiency, facility_mid, facility_final = _run_fail_and_verify(api, ctx)
        # 85 - 15 MAJOR = 70 crosses the inclusive 85 COMPLIANT boundary.
        assert facility_mid["posture_score"] == 85 - MAJOR_WEIGHT == 70
        assert facility_mid["compliance_posture"] == "DEFICIENT"
        # Verification removes the deficiency from the open set: back to 85, and
        # exactly 85 satisfies the inclusive COMPLIANT bound.
        assert facility_final["posture_score"] == 85
        assert facility_final["compliance_posture"] == "COMPLIANT"
        assert deficiency["status"] == "VERIFIED_CLOSED"


class TestFailThenVerifyRestoresPosture:
    def _run_cycle(self, api):
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_cp_order()
        facility_id = ctx["facility"]["id"]
        score_before = get_facility(facility_id)["posture_score"]

        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("INSTANT_OFF"))  # FAIL
        score_after_fail = get_facility(facility_id)["posture_score"]

        d1 = deficiency_for_order(ctx["order"]["id"])
        validate_success(api.order_correction(d1["id"], OWNER), 200)
        validate_success(api.mark_corrected(d1["id"], OWNER), 200)
        retest = create_order(facility_id, ctx["tank"]["id"], "CP_SURVEY",
                              component_id=ctx["component"]["id"],
                              linked_deficiency_id=d1["id"],
                              line_items=[{"description": "cp retest", "qty": 1,
                                           "unit_price_cents": 40000}])
        schedule_order(retest["id"], ctx["tester"]["id"],
                       "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
        start_order(retest["id"], ctx["tester"]["id"], "2026-05-04T10:30:00Z")
        record_results(retest["id"], ctx["tester"]["id"],
                       cp_readings(-900, -950, -600))  # PASS
        certify_order(retest["id"], ctx["reviewer"]["id"])
        score_after_verify = get_facility(facility_id)["posture_score"]
        return d1["id"], score_before, score_after_fail, score_after_verify

    def test_fail_deducts_major_weight_exactly_once(self, api):
        """PRD §2.9: "The computation starts at 100 points. Each deficiency of the
        facility in `OPEN`, `CORRECTION_ORDERED`, `CORRECTED`, `RE_TEST_SCHEDULED`,
        or `ESCALATED` status subtracts its severity weight — 25 points for
        `CRITICAL`, 15 for `MAJOR`, 5 for `MINOR`" and "The score is recomputed
        from the facility's live obligations whenever a deficiency is opened,
        verified, escalated, or de-escalated"

        Design: Difficulty/compensating_invariant/fail_then_verify_restores_posture_score
        """
        d1_id, before, after_fail, _ = self._run_cycle(api)
        assert before == 100
        assert after_fail == 100 - MAJOR_WEIGHT == 85, (
            "one MAJOR deficiency deducted exactly once")

    def test_verify_restores_full_score_no_drift(self, api):
        """PRD §3.5: "a `PASS` moves the deficiency to `VERIFIED_CLOSED`, records
        the certifying order as `verified_by_service_order_id`, restores any
        referenced component to `IN_SERVICE`, and recomputes the facility posture
        now that the deficiency has left the open set"
        PRD §2.9: "Deficiencies that have reached `VERIFIED_CLOSED` and releases
        that are `DISMISSED` or `CLOSED` no longer count against the score."

        Design: Difficulty/compensating_invariant/fail_then_verify_restores_posture_score
        """
        d1_id, before, after_fail, after_verify = self._run_cycle(api)
        assert after_verify == before == 100, (
            "verification restores the full weight; no penalty drift")
        assert get_deficiency(d1_id)["status"] == "VERIFIED_CLOSED"
