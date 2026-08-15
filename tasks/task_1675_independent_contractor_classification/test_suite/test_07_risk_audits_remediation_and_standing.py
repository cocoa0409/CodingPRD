"""Risk audits: provisional vs final scoring, standing transitions, remediation counts."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_audit,
    close_remediation_action,
    create_audit,
    create_contractor,
    create_engagement,
    create_jurisdiction,
    create_remediation_action,
    finalize_audit,
    get_audit,
    get_contractor,
    make_answers,
    run_determination,
    setup_engagement_at_state,
    submit_questionnaire,
    validate_error,
    validate_success,
    verify_contractor,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]
_MANAGER = TEST_USERS["engagement_manager_headers"]


def _classified_engagement(jurisdiction_overrides=None, answers=None,
                           engagement_overrides=None):
    """Contractor + CLASSIFIED engagement (COMMON_LAW all-favorable by default)."""
    return setup_engagement_at_state(
        "CLASSIFIED",
        jurisdiction_overrides=jurisdiction_overrides,
        engagement_overrides=engagement_overrides,
        answers=answers,
    )


class TestProvisionalVsFinalVariants:
    def _setup_audit_for_finalization(self):
        """FIELDWORK audit on a CLASSIFIED COMMON_LAW engagement, CONTRACTOR outcome,
        scope creep 0, supervision NONE, start 2026-02-01 (6 full months at the
        default clock): provisional = 0.5*0 + 0 + 0 + 2*6 = 12.0."""
        setup = _classified_engagement()
        audit = create_audit(
            setup["contractor"]["id"], engagement_id=setup["engagement"]["id"]
        )
        return setup, audit

    def test_audit_provisional_score_from_declared_data(self, api):
        """PRD §3.7: "Creation computes a forward-looking `provisional_risk_score`,
        rounded half up to one decimal place, from declared data: one-half of the
        engagement's `scope_creep_index`, plus forty points when the engagement's
        current determination outcome is `EMPLOYEE_RISK`, plus ten points for each
        `ACTIVE` exception grant on the engagement, plus two points per full calendar
        month between the engagement's `start_date` and the clock's date, capped at
        twelve months."
        PRD §3.7: "A new audit begins in `OPEN` with an `open_action_count` of 0 and a
        null `final_risk_score`." and "below 25 is `LOW`".

        Design: Difficulty/dual_variant_calc/dvc_risk_score_provisional_vs_final_same_audit
        """
        _, audit = self._setup_audit_for_finalization()
        assert_audit(audit)
        assert audit["status"] == "OPEN"
        assert audit["provisional_risk_score"] == pytest.approx(12.0, abs=1e-9)
        assert audit["risk_level"] == "LOW"
        assert audit["final_risk_score"] is None
        assert audit["open_action_count"] == 0

    def test_audit_finalize_replays_fieldwork_events(self, api):
        """PRD §3.7: "events are replayed in the order supplied, each event type
        contributing points per occurrence for at most its first three occurrences:
        `SUPERVISION_OBSERVED` fifteen points, `EQUIPMENT_PROVIDED` ten points,
        `INTEGRATED_WORKFLOW` fifteen points, and `PAYMENT_REGULARITY` five points. The
        `final_risk_score` is three-tenths of the provisional score plus the sum of the
        capped event points, rounded half up to one decimal place."
        PRD §3.7: "a `HIGH` level moves a `GOOD_STANDING` contractor to `WATCH`".
        0.3 * 12.0 + 3*15 + 1*10 = 58.6 => HIGH (50 up to but not including 75).

        Design: Difficulty/dual_variant_calc/dvc_risk_score_provisional_vs_final_same_audit
        """
        setup, audit = self._setup_audit_for_finalization()
        finalized = finalize_audit(
            audit["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "EQUIPMENT_PROVIDED"},
            ],
            "Close supervision observed on site",
        )
        assert finalized["final_risk_score"] == pytest.approx(58.6, abs=1e-9)
        assert finalized["risk_level"] == "HIGH"
        assert get_contractor(setup["contractor"]["id"])["standing_status"] == "WATCH"


class TestContractorParallelDimensions:
    def _setup_critical_audit(self):
        """Contractor at VERIFICATION_FAILED; FIELDWORK audit finalized CRITICAL
        (0.3*12.0 + 3*15 SUPERVISION_OBSERVED + 3*15 INTEGRATED_WORKFLOW = 93.6)."""
        jurisdiction = create_jurisdiction()
        contractor = create_contractor(legal_name="Parallel Dims LLC")
        verify_contractor(contractor["id"], outcome="FAILED")
        engagement = create_engagement(contractor["id"], jurisdiction["id"],
                                       title="Parallel dims target", agreed_rate_cents=9000)
        submit_questionnaire(engagement["id"])
        run_determination(engagement["id"])
        audit = create_audit(contractor["id"], engagement_id=engagement["id"])
        finalized = finalize_audit(
            audit["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "INTEGRATED_WORKFLOW"},
                {"event_type": "INTEGRATED_WORKFLOW"},
                {"event_type": "INTEGRATED_WORKFLOW"},
            ],
            "Deep integration and supervision",
        )
        return contractor, audit, finalized

    def test_critical_finalize_suspends_standing_keeps_verification(self, api):
        """PRD §3.2: "A contractor carries **two parallel status dimensions that evolve
        independently**."
        PRD §3.7: "a `CRITICAL` level moves a `GOOD_STANDING` or `WATCH` contractor to
        `SUSPENDED_STANDING`" (75 or more is `CRITICAL`; final score 93.6).

        Design: Difficulty/non_linear_state_machine/nsm_contractor_parallel_dimensions
        """
        contractor, audit, finalized = self._setup_critical_audit()
        assert finalized["risk_level"] == "CRITICAL"
        assert finalized["final_risk_score"] == pytest.approx(93.6, abs=1e-9)
        fresh = get_contractor(contractor["id"])
        assert fresh["verification_status"] == "VERIFICATION_FAILED"
        assert fresh["standing_status"] == "SUSPENDED_STANDING"

    def test_reverification_independent_of_standing(self, api):
        """PRD §3.2: "a contractor in `VERIFICATION_FAILED` can be re-verified to
        `VERIFIED` by a later `VERIFIED` decision" — and the standing dimension is not
        moved by a verification decision ("two parallel status dimensions that evolve
        independently").

        Design: Difficulty/non_linear_state_machine/nsm_contractor_parallel_dimensions
        """
        contractor, _, _ = self._setup_critical_audit()
        verified = verify_contractor(contractor["id"], outcome="VERIFIED")
        assert verified["verification_status"] == "VERIFIED"
        assert verified["standing_status"] == "SUSPENDED_STANDING"


class TestPortfolioAudit:
    def test_portfolio_audit_empty_engagement_set_scores_zero(self, api, compliance_officer_headers):
        """PRD §3.7: "For a portfolio audit the same terms aggregate across the
        contractor's engagements in `ACTIVE` or `SUSPENDED` status: the scope-creep
        term uses the maximum index among those engagements (zero when none exist), the
        determination term contributes forty when any of them has a current outcome of
        `EMPLOYEE_RISK`, the exception term sums `ACTIVE` grants across all of them,
        and the month term measures from the earliest `start_date`." — over an empty
        set every term is zero, and "below 25 is `LOW`".

        Design: Corner/calculations/calc_portfolio_audit_empty_engagement_set
        """
        contractor = create_contractor(legal_name="Empty Portfolio LLC")
        res = api.create_audit(
            {"contractor_id": contractor["id"], "audit_type": "SCREENING"},
            compliance_officer_headers,
        )
        audit = validate_success(res, 201)
        assert_audit(audit)
        assert audit["provisional_risk_score"] == pytest.approx(0.0, abs=1e-9)
        assert audit["risk_level"] == "LOW"
        assert audit["status"] == "OPEN"


class TestRemediationAndClosure:
    def test_remediation_action_on_open_audit_rejected(self, api, compliance_officer_headers):
        """PRD §3.7: a remediation action may be created "only while the owning audit
        is in `FINDINGS_FINALIZED` or `REMEDIATION`; creation against an audit in any
        other status is rejected with `ERR_AUDIT_NOT_OPEN` (HTTP 409)."

        Design: Corner/errors/err_remediation_action_on_open_audit_rejected
        """
        contractor = create_contractor(legal_name="Premature Action LLC")
        audit = create_audit(contractor["id"])
        res = api.create_remediation_action(
            audit["id"],
            {"description": "Too early", "severity": "LOW", "due_date": "2026-09-01"},
            compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_AUDIT_NOT_OPEN.value)
        assert get_audit(audit["id"])["open_action_count"] == 0

    def test_audit_close_blocked_by_open_actions(self, api, compliance_officer_headers):
        """PRD §3.7: "From `REMEDIATION`, closure requires zero open actions. Any close
        attempted with open actions outstanding is rejected with
        `ERR_AUDIT_ACTIONS_OPEN` (HTTP 409)."
        PRD §3.7: "When the finalized level is `HIGH` or `CRITICAL`, the audit
        continues automatically from `FINDINGS_FINALIZED` into `REMEDIATION` within the
        same request".

        Design: Corner/errors/err_audit_close_with_open_actions_rejected
        """
        setup = _classified_engagement()
        audit = create_audit(
            setup["contractor"]["id"], engagement_id=setup["engagement"]["id"]
        )
        # 0.3*12.0 + 3*15 + 1*10 = 58.6 => HIGH => automatic REMEDIATION.
        finalized = finalize_audit(
            audit["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "EQUIPMENT_PROVIDED"},
            ],
            "Supervision observed",
        )
        assert finalized["status"] == "REMEDIATION"
        action = create_remediation_action(
            audit["id"], description="Reduce supervision", severity="HIGH",
            due_date="2026-09-30",
        )

        res = api.close_audit(audit["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_AUDIT_ACTIONS_OPEN.value)

        close_remediation_action(action["id"], outcome="CLOSED")
        closed = validate_success(api.close_audit(audit["id"], compliance_officer_headers), 200)
        assert closed["status"] == "CLOSED"

    def test_open_action_count_create_close_conserved(self, api):
        """PRD §3.7: "Each action begins `OPEN`, its `audit_id` bound from the path,
        and each creation increments the parent audit's `open_action_count` by one."
        and "Either outcome decrements the parent audit's `open_action_count` by one
        and increments the action's `version`".

        Design: Difficulty/compensating_invariant/ci_audit_open_action_count_create_close_pair
        """
        setup = _classified_engagement()
        audit = create_audit(
            setup["contractor"]["id"], engagement_id=setup["engagement"]["id"]
        )
        finalize_audit(audit["id"], [], "One documentation gap")
        assert get_audit(audit["id"])["open_action_count"] == 0

        action = create_remediation_action(
            audit["id"], description="Obtain signed W-9", severity="LOW",
            due_date="2026-09-01",
        )
        assert get_audit(audit["id"])["open_action_count"] == 1

        close_remediation_action(action["id"], outcome="CLOSED")
        assert get_audit(audit["id"])["open_action_count"] == 0

    def test_audit_closes_from_findings_finalized_when_low(self, api, compliance_officer_headers):
        """PRD §3.7: "From `FINDINGS_FINALIZED`, closure requires a `risk_level` of
        `LOW` or `MODERATE` (a finalized `HIGH` or `CRITICAL` audit lives in
        `REMEDIATION` and cannot close from this state) and zero open actions."
        Final score 0.3 * 12.0 = 3.6 => LOW.

        Design: Difficulty/compensating_invariant/ci_audit_open_action_count_create_close_pair
        """
        setup = _classified_engagement()
        audit = create_audit(
            setup["contractor"]["id"], engagement_id=setup["engagement"]["id"]
        )
        finalized = finalize_audit(audit["id"], [], "One documentation gap")
        assert finalized["final_risk_score"] == pytest.approx(3.6, abs=1e-9)
        assert finalized["risk_level"] == "LOW"
        assert finalized["status"] == "FINDINGS_FINALIZED"

        closed = validate_success(api.close_audit(audit["id"], compliance_officer_headers), 200)
        assert closed["status"] == "CLOSED"


class TestRiskLevelThreshold:
    def test_risk_level_high_at_exactly_50(self, api):
        """PRD §3.7: "The audit's `risk_level` is computed over the final score once
        present and over the provisional score before that: below 25 is `LOW`; 25 up to
        but not including 50 is `MODERATE`; 50 up to but not including 75 is `HIGH`;
        75 or more is `CRITICAL`."
        PRD §3.7: "a `HIGH` level moves a `GOOD_STANDING` contractor to `WATCH`".
        Provisional = 40 (EMPLOYEE_RISK) + 2*5 months = 50.0; final with 35 event
        points = 0.3*50.0 + 35 = 50.0 => HIGH; with 30 points = 45.0 => MODERATE.

        Design: Corner/cross_cutting_layers/layer_risk_level_threshold_at_exactly_50
        """
        setup = _classified_engagement(
            jurisdiction_overrides={
                "code": "US-CA", "test_type": "ABC_TEST", "state_filing_threshold_cents": 0,
            },
            answers=make_answers(CONTROL_METHOD="YES"),
            engagement_overrides={"start_date": "2026-03-01", "agreed_rate_cents": 9000},
        )
        contractor = setup["contractor"]
        engagement = setup["engagement"]
        assert setup["determination"]["outcome"] == "EMPLOYEE_RISK"

        audit_hi = create_audit(contractor["id"], engagement_id=engagement["id"])
        audit_mod = create_audit(contractor["id"], engagement_id=engagement["id"])
        assert audit_hi["provisional_risk_score"] == pytest.approx(50.0, abs=1e-9)

        finalized_hi = finalize_audit(
            audit_hi["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "PAYMENT_REGULARITY"},
            ],
            "Boundary high",
        )
        assert finalized_hi["final_risk_score"] == pytest.approx(50.0, abs=1e-9)
        assert finalized_hi["risk_level"] == "HIGH"
        assert get_contractor(contractor["id"])["standing_status"] == "WATCH"

        finalized_mod = finalize_audit(
            audit_mod["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
            ],
            "Just below",
        )
        assert finalized_mod["final_risk_score"] == pytest.approx(45.0, abs=1e-9)
        assert finalized_mod["risk_level"] == "MODERATE"
        # MODERATE carries no standing transition; the contractor stays WATCH.
        assert get_contractor(contractor["id"])["standing_status"] == "WATCH"


class TestStandingGate:
    def test_engagement_create_blocked_for_suspended_standing(self, api, engagement_manager_headers):
        """PRD §3.2: "Opening a new engagement for a contractor, activating an approved
        engagement, and reinstating a suspended engagement each require the
        contractor's `standing_status` to be `GOOD_STANDING` or `WATCH`; a contractor
        in `SUSPENDED_STANDING` or `CONVERTED_TO_EMPLOYEE` causes these operations to
        be rejected with `ERR_CONTRACTOR_STANDING_SUSPENDED` (HTTP 422)."

        Design: Corner/errors/err_engagement_create_on_suspended_standing_contractor
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor(legal_name="Standing Gate LLC")
        engagement = create_engagement(contractor["id"], jurisdiction["id"], title="Original")
        submit_questionnaire(engagement["id"])
        run_determination(engagement["id"])
        audit = create_audit(contractor["id"], engagement_id=engagement["id"])
        # 0.3*12.0 + 45 + 45 = 93.6 => CRITICAL => SUSPENDED_STANDING.
        finalize_audit(
            audit["id"],
            [
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "SUPERVISION_OBSERVED"},
                {"event_type": "INTEGRATED_WORKFLOW"},
                {"event_type": "INTEGRATED_WORKFLOW"},
                {"event_type": "INTEGRATED_WORKFLOW"},
            ],
            "Critical integration",
        )
        assert get_contractor(contractor["id"])["standing_status"] == "SUSPENDED_STANDING"

        res = api.create_engagement(
            {
                "contractor_id": contractor["id"],
                "jurisdiction_id": jurisdiction["id"],
                "title": "Blocked new engagement",
                "scope_description": "x",
                "agreed_rate_cents": 10000,
                "rate_unit": "HOURLY",
                "start_date": "2026-09-01",
                "end_date": "2027-06-30",
            },
            engagement_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_CONTRACTOR_STANDING_SUSPENDED.value)
