"""Retention risk scoring variants, bands, and the assessment workflow."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_talent_manager, setup_manager,
    setup_active_role, add_active_successor,
    apply_rating_via_calibration, setup_hipo_cycle, nominate,
    endorse_nomination, enroll_nomination,
    setup_retention_assessment, plan_action,
    assert_retention_assessment, assert_risk_level_matches_score,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_dual_variant_subject(api):
    """Employee E: hire 2024-05-01 (tenure exactly 24 at the startup clock),
    managed by M; three finalized calibrations apply LOW, SOLID, STRONG
    (history latest-first [STRONG, SOLID, LOW], current STRONG); E also holds
    an ACTIVE READY_NOW slate entry."""
    hrbp, hrbp_headers = setup_hrbp()
    tm, tm_headers = setup_talent_manager()
    manager, _ = setup_manager()
    incumbent = setup_employee(job_level=8, performance_rating="STRONG",
                               hire_date="2019-03-01")
    subject = setup_employee(job_level=6, hire_date="2024-05-01",
                             performance_rating="LOW",
                             current_manager_id=manager["id"])
    role = setup_active_role(hrbp_headers, incumbent["id"], role_title="SRE Lead",
                             criticality_tier="TIER_1")
    entry = add_active_successor(role["id"], subject["id"], hrbp_headers,
                                 readiness_rating="READY_NOW", slate_position=1)
    windows = [
        ("CAL-JAN", "2026-01-05T09:00:00Z", "2026-01-05T12:00:00Z", "LOW"),
        ("CAL-FEB", "2026-02-05T09:00:00Z", "2026-02-05T12:00:00Z", "SOLID"),
        ("CAL-MAR", "2026-03-05T09:00:00Z", "2026-03-05T12:00:00Z", "STRONG"),
    ]
    for name, start, end, rating in windows:
        apply_rating_via_calibration(tm_headers, manager["id"], subject["id"],
                                     rating, name, scheduled_start=start,
                                     scheduled_end=end)
    subject = get_success_data(api.get_employee(subject["id"], ADMIN))
    assert subject["performance_rating"] == "STRONG"
    assert len(subject["rating_history"]) == 3
    return hrbp_headers, subject


class TestDualVariantRisk:
    def test_point_in_time_variant_score(self, api):
        """PRD §3.8: "Under the `POINT_IN_TIME` variant, the base is 100 minus
        the employee's current rating points (20 for `LOW`, 50 for `SOLID`, 80
        for `STRONG`, 100 for `EXCEPTIONAL`)."
        PRD §3.8: "Three modifiers then apply to the base in this order: plus
        15 when the employee's tenure per §2.4 is less than 24 months; minus 10
        when the employee's `is_high_potential` is true; and plus 20 when the
        employee holds any successor entry in `ACTIVE` status rated
        `READY_NOW` — being ready to leave for a bigger role is itself a flight
        risk."
        PRD §3.8: "Manually created assessments carry `trigger_source`
        `MANUAL`"

        Design: Difficulty/dual_variant_calc/retention_risk_point_in_time_vs_trend_same_employee
        """
        hrbp_headers, subject = _setup_dual_variant_subject(api)

        assessment = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        assert_retention_assessment(assessment)
        assert assessment["trigger_source"] == "MANUAL"
        # base 100-80=20; tenure 24 -> no delta; not HiPo; +20 READY_NOW.
        assert assessment["risk_score"] == pytest.approx(40.0, abs=0.001)
        assert assessment["risk_level"] == "MEDIUM"

    def test_trend_variant_score(self, api):
        """PRD §3.8: "Under the `TREND` variant, the base uses the trajectory
        instead: take up to the three most recent `rating_history` entries,
        latest first; weight them 0.5, 0.3, and 0.2 respectively; when fewer
        than three entries exist, truncate the weight list to those available
        and renormalize by dividing each weight by the sum of the truncated
        weights; the weighted rating — rounded half-up to 3 decimal places — is
        the sum of each weight times the points of that entry's rating, and the
        base is 100 minus it."
        PRD §3.8: "The two variants produce different scores for identical
        employees whenever the rating trajectory differs from the latest
        rating."

        Design: Difficulty/dual_variant_calc/retention_risk_point_in_time_vs_trend_same_employee
        """
        hrbp_headers, subject = _setup_dual_variant_subject(api)

        trend = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "TREND"}, hrbp_headers,
        ), 201)
        # latest-first [STRONG, SOLID, LOW]: 0.5*80 + 0.3*50 + 0.2*20 = 59.0
        # -> base 41, +20 READY_NOW = 61.0.
        assert trend["risk_score"] == pytest.approx(61.0, abs=0.001)
        assert trend["risk_level"] == "HIGH"

        pit = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        assert pit["risk_score"] != trend["risk_score"], (
            "the trajectory differs from the latest rating, so the variants diverge"
        )


class TestMultifactorClamp:
    def _setup_max_risk_employee(self, api):
        """LOW rating (base 80), tenure 11 (+15), enrolled HiPo (-10),
        ACTIVE READY_NOW successor (+20): raw 105."""
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager(department="SALES")
        incumbent = setup_employee(department="SALES", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        subject = setup_employee(department="SALES", job_level=5,
                                 hire_date="2025-06-01", performance_rating="LOW",
                                 current_manager_id=manager["id"])
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C1")
        nomination = nominate(cycle["id"], manager["id"], subject["id"])
        endorse_nomination(nomination["id"], hrbp_headers)
        enroll_nomination(nomination["id"], tm_headers)
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Sales Director", department="SALES")
        add_active_successor(role["id"], subject["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)
        return hrbp_headers, subject

    def test_multifactor_raw_score_clamped_at_100(self, api):
        """PRD §3.8: "The total is clamped to the 0–100 range and rounded
        half-up to 1 decimal place."
        PRD §3.8: "Three modifiers then apply to the base in this order: plus
        15 when the employee's tenure per §2.4 is less than 24 months; minus 10
        when the employee's `is_high_potential` is true; and plus 20 when the
        employee holds any successor entry in `ACTIVE` status rated
        `READY_NOW` — being ready to leave for a bigger role is itself a flight
        risk."

        Design: Difficulty/combinatorial_formula/retention_risk_multifactor_clamp_at_100
        """
        hrbp_headers, subject = self._setup_max_risk_employee(api)
        subject = get_success_data(api.get_employee(subject["id"], ADMIN))
        assert subject["is_high_potential"] is True

        assessment = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        # raw 80 + 15 - 10 + 20 = 105 -> clamped to the 100 ceiling.
        assert assessment["risk_score"] == pytest.approx(100.0, abs=0.001)

    def test_multifactor_clamped_score_is_critical(self, api):
        """PRD §3.8: "The derived `risk_level` bands the stored score: below 30
        is `LOW`; 30 up to below 60 is `MEDIUM`; 60 up to below 85 is `HIGH`;
        85 and above is `CRITICAL`."

        Design: Difficulty/combinatorial_formula/retention_risk_multifactor_clamp_at_100
        """
        hrbp_headers, subject = self._setup_max_risk_employee(api)
        assessment = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        assert assessment["risk_level"] == "CRITICAL", "100.0 >= 85 engages the top band"
        assert_risk_level_matches_score(assessment)


class TestRiskBandBoundary:
    def test_retention_risk_boundary_60_is_high(self, api):
        """PRD §3.8: "The derived `risk_level` bands the stored score: below 30
        is `LOW`; 30 up to below 60 is `MEDIUM`; 60 up to below 85 is `HIGH`;
        85 and above is `CRITICAL`."
        PRD §2.6: "Band derivations — `bench_posture` and `risk_level` — always
        compare against the stored, already-rounded score values, never against
        unrounded intermediates."

        Design: Corner/calculations/retention_risk_boundary_60_is_high
        """
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        incumbent = setup_employee(job_level=8, performance_rating="STRONG",
                                   hire_date="2019-03-01")
        subject = setup_employee(job_level=5, hire_date="2024-05-01",
                                 performance_rating="SOLID",
                                 current_manager_id=manager["id"])
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C82")
        nomination = nominate(cycle["id"], manager["id"], subject["id"])
        endorse_nomination(nomination["id"], hrbp_headers)
        enroll_nomination(nomination["id"], tm_headers)
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 82",
                                 criticality_tier="TIER_3")
        add_active_successor(role["id"], subject["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)

        assessment = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        # SOLID base 50; tenure 24 -> no delta; -10 HiPo; +20 READY_NOW = 60.0.
        assert assessment["risk_score"] == pytest.approx(60.0, abs=0.001)
        assert assessment["risk_level"] == "HIGH", (
            "the HIGH floor at 60 is inclusive"
        )


class TestTrendRenormalization:
    def test_retention_trend_renormalized_two_entry_history(self, api):
        """PRD §3.8: "when fewer than three entries exist, truncate the weight
        list to those available and renormalize by dividing each weight by the
        sum of the truncated weights; the weighted rating — rounded half-up to
        3 decimal places — is the sum of each weight times the points of that
        entry's rating, and the base is 100 minus it."
        PRD §3.8: "Under the `POINT_IN_TIME` variant, the base is 100 minus the
        employee's current rating points (20 for `LOW`, 50 for `SOLID`, 80 for
        `STRONG`, 100 for `EXCEPTIONAL`)."

        Design: Corner/calculations/retention_trend_renormalized_two_entry_history
        """
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_employee(job_level=5, hire_date="2024-05-01",
                                 performance_rating="LOW",
                                 current_manager_id=manager["id"])
        apply_rating_via_calibration(
            tm_headers, manager["id"], subject["id"], "LOW", "CAL-83-A",
            scheduled_start="2026-01-06T09:00:00Z",
            scheduled_end="2026-01-06T12:00:00Z",
        )
        apply_rating_via_calibration(
            tm_headers, manager["id"], subject["id"], "STRONG", "CAL-83-B",
            scheduled_start="2026-02-06T09:00:00Z",
            scheduled_end="2026-02-06T12:00:00Z",
        )

        trend = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "TREND"}, hrbp_headers,
        ), 201)
        # latest-first [STRONG, LOW]: truncated weights 0.5/0.3 renormalize to
        # 0.625/0.375 -> 0.625*80 + 0.375*20 = 57.5 -> base 42.5.
        assert trend["risk_score"] == pytest.approx(42.5, abs=0.001)
        assert trend["risk_level"] == "MEDIUM"

        pit = validate_success(api.create_retention_assessment(
            subject["id"], {"assessment_method": "POINT_IN_TIME"}, hrbp_headers,
        ), 201)
        assert pit["risk_score"] == pytest.approx(20.0, abs=0.001)
        assert pit["risk_level"] == "LOW"


class TestAssessmentWorkflow:
    def test_escalate_from_open_returns_assessment_invalid_state(self, api):
        """PRD §3.8: "Escalation is reserved for the dangerous cases: from
        `ACTION_PLANNED`, and only while `risk_level` is `HIGH` or `CRITICAL`
        (otherwise `ERR_RISK_NOT_ESCALATABLE`), the assessment moves to
        `ESCALATED`, from which a fresh action plan returns it to
        `ACTION_PLANNED`."
        PRD §2.8: "5. State preconditions of the requested operation — failure
        yields the entity's invalid-state error (HTTP 409)."

        Design: Corner/validations/escalate_from_open_returns_assessment_invalid_state
        """
        hrbp, hrbp_headers = setup_hrbp()
        subject = setup_employee(job_level=5, hire_date="2024-05-01",
                                 performance_rating="LOW")
        assessment = setup_retention_assessment(subject["id"], hrbp_headers)
        assert assessment["status"] == "OPEN"
        assert assessment["risk_score"] == pytest.approx(80.0, abs=0.001)
        assert assessment["risk_level"] == "HIGH"

        resp = api.escalate_retention_assessment(assessment["id"], hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE, 409)
        after = get_success_data(
            api.get_retention_assessment(assessment["id"], hrbp_headers)
        )
        assert after["status"] == "OPEN"

    def test_escalate_low_risk_returns_risk_not_escalatable(self, api):
        """PRD §3.8: "Escalation is reserved for the dangerous cases: from
        `ACTION_PLANNED`, and only while `risk_level` is `HIGH` or `CRITICAL`
        (otherwise `ERR_RISK_NOT_ESCALATABLE`), the assessment moves to
        `ESCALATED`"

        Design: Corner/validations/escalate_low_risk_returns_risk_not_escalatable
        """
        hrbp, hrbp_headers = setup_hrbp()
        subject = setup_employee(job_level=5, hire_date="2024-05-01",
                                 performance_rating="EXCEPTIONAL")
        assessment = setup_retention_assessment(subject["id"], hrbp_headers)
        # EXCEPTIONAL base 0; no modifiers -> clamped to the 0 floor.
        assert assessment["risk_score"] == pytest.approx(0.0, abs=0.001)
        assert assessment["risk_level"] == "LOW"

        planned = plan_action(assessment["id"], hrbp_headers,
                              action_type="STAY_INTERVIEW")
        assert planned["status"] == "ACTION_PLANNED"

        resp = api.escalate_retention_assessment(assessment["id"], hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_RISK_NOT_ESCALATABLE, 409)
        after = get_success_data(
            api.get_retention_assessment(assessment["id"], hrbp_headers)
        )
        assert after["status"] == "ACTION_PLANNED"

    def test_mitigate_while_risk_still_high_returns_error(self, api):
        """PRD §3.8: "With `outcome` `MITIGATED` — allowed only from
        `ACTION_PLANNED` — the risk score is recomputed at close using the
        assessment's own method, and the close succeeds only when the
        recomputed `risk_level` lands `LOW` or `MEDIUM`; a still-elevated risk
        rejects the close with `ERR_RISK_STILL_HIGH`, while a successful close
        refreshes the stored `risk_score` and `risk_level` to the recomputed
        values."

        Design: Corner/validations/mitigate_while_risk_still_high_returns_error
        """
        hrbp, hrbp_headers = setup_hrbp()
        subject = setup_employee(job_level=5, hire_date="2024-05-01",
                                 performance_rating="LOW")
        assessment = setup_retention_assessment(subject["id"], hrbp_headers)
        planned = plan_action(assessment["id"], hrbp_headers,
                              action_type="COMP_REVIEW")
        assert planned["status"] == "ACTION_PLANNED"

        resp = api.close_retention_assessment(
            assessment["id"], {"outcome": "MITIGATED"}, hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RISK_STILL_HIGH, 409)
        after = get_success_data(
            api.get_retention_assessment(assessment["id"], hrbp_headers)
        )
        assert after["status"] == "ACTION_PLANNED"
