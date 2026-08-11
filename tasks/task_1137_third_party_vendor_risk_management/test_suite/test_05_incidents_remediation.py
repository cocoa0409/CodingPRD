"""Incidents and remediation: parallel engagement dimensions, composite risk
score accumulation and restoration, remediation deadline computation, the
close/reopen cycle, and segregation-of-duties gates on plans and verify."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_dd_package,
    create_engagement,
    create_remediation_plan_payload,
    create_vendor,
    file_incident,
    get_engagement,
    get_incident,
    get_vendor,
    iso_after_days,
    make_business_owner_headers,
    make_risk_officer_headers,
    parse_iso_instant,
    remediate_incident_to_closed,
    reset_clock,
    setup_active_engagement,
    setup_active_vendor,
    setup_closed_incident,
    submit_dd_package,
    triage_incident,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import RO, RO_APPROVER

CLOCK = "2026-05-01T00:00:00Z"


class TestParallelEngagementDimensions:
    def test_triage_flips_risk_attention_without_touching_lifecycle(self, api):
        """PRD §3.8: "The triage side effects also include setting the
        engagement's `risk_attention_state` to `UNDER_REVIEW` if it was
        `NORMAL`, and recomputing the vendor's `tier_posture`."
        PRD §2.9: "`VendorEngagement.lifecycle_status` ∈ {`DRAFT`,
        `DD_IN_PROGRESS`, `DD_APPROVED`, `CONTRACTING`, `ACTIVE`, `EXITING`,
        `EXITED`, `TERMINATED_FOR_CAUSE`}."

        Design: Difficulty/non_linear_state_machine/engagement_parallel_dimensions
        """
        ctx = setup_active_engagement(vendor_name="Parallel Vendor")
        e_id = ctx["engagement"]["id"]
        assert ctx["engagement"]["lifecycle_status"] == "ACTIVE"
        assert ctx["engagement"]["risk_attention_state"] == "NORMAL"

        incident = file_incident(e_id, severity="SEV_4")
        triage_incident(incident["id"])

        engagement = get_engagement(e_id)
        assert engagement["lifecycle_status"] == "ACTIVE"
        assert engagement["risk_attention_state"] == "UNDER_REVIEW"

    def test_closing_last_incident_restores_risk_attention_to_normal(self, api):
        """PRD §3.8: "On success the plan transitions
        `VERIFICATION_SUBMITTED → VERIFIED`, the incident transitions
        `AWAITING_VERIFICATION → CLOSED`, the server stamps `closed_at`, the
        engagement's `risk_attention_state` returns to `NORMAL` if no other
        `OPEN` or `REOPENED` incidents remain on that engagement, and the
        vendor's `tier_posture` is recomputed."

        Design: Difficulty/non_linear_state_machine/engagement_parallel_dimensions
        """
        ctx = setup_active_engagement(vendor_name="Parallel Vendor 2")
        e_id = ctx["engagement"]["id"]
        incident = file_incident(e_id, severity="SEV_4")
        triage_incident(incident["id"])
        remediate_incident_to_closed(incident["id"])

        engagement = get_engagement(e_id)
        assert engagement["lifecycle_status"] == "ACTIVE"
        assert engagement["risk_attention_state"] == "NORMAL"
        closed = get_incident(incident["id"])
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None


class TestCompositeRiskScoreSemantics:
    def test_closed_incident_contributes_zero(self, api):
        """PRD §3.10: "Closed incidents contribute zero; reopening an incident
        immediately re-contributes its severity weight."
        PRD §3.10: "Each non-terminal incident on any of the vendor's
        engagements contributes a severity-weighted amount: `SEV_1` contributes
        40, `SEV_2` contributes 20, `SEV_3` contributes 8, and `SEV_4`
        contributes 3."

        Design: Difficulty/dual_variant_calc/composite_risk_score_non_terminal_only_vs_including_closed
        """
        ctx = setup_active_vendor(vendor_name="Beta Payments Ltd")
        v_id = ctx["vendor"]["id"]
        assert get_vendor(v_id)["composite_risk_score"] == pytest.approx(0, abs=1e-9)

        incident = file_incident(ctx["engagement"]["id"], severity="SEV_3", detected_at="2026-05-02T00:00:00Z")
        score_open = get_vendor(v_id)["composite_risk_score"]
        assert score_open == pytest.approx(8.00, abs=1e-9)  # 8 * 1.0 (TIER_3)

        triage_incident(incident["id"])
        remediate_incident_to_closed(incident["id"], committed="2026-05-20T00:00:00Z")
        score_closed = get_vendor(v_id)["composite_risk_score"]
        assert score_closed == pytest.approx(0, abs=1e-9), (
            "a CLOSED incident must contribute zero under non-terminal-only semantics"
        )

    def test_close_restores_score_and_posture(self, api):
        """PRD §3.10: "Closed incidents contribute zero; reopening an incident
        immediately re-contributes its severity weight."
        PRD §3.10: "Each recompute then derives `tier_posture` by thresholding:
        a score of at least 70 lands the vendor in `BREACH`; at least 40 but
        less than 70 lands in `ESCALATED`; at least 15 but less than 40 lands
        in `WATCH`; anything below 15 lands in `CLEAN`."

        Design: Difficulty/dual_variant_calc/composite_risk_score_non_terminal_only_vs_including_closed
        """
        ctx = setup_active_vendor(vendor_name="Beta Payments Ltd 2")
        v_id = ctx["vendor"]["id"]
        incident = file_incident(ctx["engagement"]["id"], severity="SEV_2", detected_at="2026-05-02T00:00:00Z")
        vendor_open = get_vendor(v_id)
        assert vendor_open["composite_risk_score"] == pytest.approx(20.00, abs=1e-9)
        assert vendor_open["tier_posture"] == "WATCH"

        triage_incident(incident["id"])
        remediate_incident_to_closed(incident["id"], committed="2026-05-20T00:00:00Z")
        vendor_closed = get_vendor(v_id)
        assert vendor_closed["composite_risk_score"] == pytest.approx(0, abs=1e-9)
        assert vendor_closed["tier_posture"] == "CLEAN"

    def test_sev1_on_tier1_scores_60_and_escalates(self, api):
        """PRD §3.10: "Each non-terminal incident on any of the vendor's
        engagements contributes a severity-weighted amount: `SEV_1` contributes
        40, `SEV_2` contributes 20, `SEV_3` contributes 8, and `SEV_4`
        contributes 3."
        PRD §3.10: "The base sum is multiplied by a tier factor — 1.5 for
        `TIER_1_CRITICAL`, 1.2 for `TIER_2_HIGH`, 1.0 for `TIER_3_STANDARD`,
        and 0.8 for `TIER_4_LOW` — and the product is rounded half-up to two
        decimal places and clamped to the range 0 to 100."
        PRD §3.10: "Each recompute then derives `tier_posture` by thresholding:
        a score of at least 70 lands the vendor in `BREACH`; at least 40 but
        less than 70 lands in `ESCALATED`; at least 15 but less than 40 lands
        in `WATCH`; anything below 15 lands in `CLEAN`."

        Design: Corner/calculations/composite_risk_score_constants_applied
        """
        ctx = setup_active_vendor(
            vendor_name="ConstV",
            category="CLOUD_INFRA",
            sensitivity="REGULATED",
            vendor_tier="TIER_1_CRITICAL",
            contract_overrides={
                "has_right_to_audit_clause": True,
                "has_exit_plan_section": True,
                "sla_uptime_pct": 99.99,
            },
        )
        file_incident(
            ctx["engagement"]["id"], severity="SEV_1",
            incident_type="DATA_BREACH", detected_at="2026-05-02T00:00:00Z",
        )
        vendor = get_vendor(ctx["vendor"]["id"])
        assert vendor["composite_risk_score"] == pytest.approx(60.00, abs=1e-9)  # 40 * 1.5
        assert vendor["tier_posture"] == "ESCALATED"


class TestRemediationDeadline:
    def test_contract_cure_window_narrows_severity_window(self, api):
        """PRD §3.8: "At triage the server computes `remediation_due_at` by
        adding an effective window to the triage instant. The base window
        depends on severity: 7 days for `SEV_1`, 30 days for `SEV_2`, 90 days
        for `SEV_3`, and 180 days for `SEV_4`. If the engagement has an
        `EXECUTED` contract, the contract's `breach_cure_window_days` narrows
        the window when shorter — the effective window is the smaller of the
        severity window and the contractual cure window."

        Design: Difficulty/combinatorial_formula/remediation_deadline_severity_vs_contract_window
        """
        ctx = setup_active_engagement(
            vendor_name="Cure-Window Vendor",
            contract_overrides={"breach_cure_window_days": 10},
        )
        incident = file_incident(
            ctx["engagement"]["id"], severity="SEV_2",
            incident_type="SLA_BREACH", detected_at="2026-05-02T00:00:00Z",
        )
        triaged = triage_incident(incident["id"])
        # min(severity 30d, contract cure 10d) -> triage instant + 10 days
        assert parse_iso_instant(triaged["remediation_due_at"]) == iso_after_days(CLOCK, 10)

    def test_severity_window_applies_without_executed_contract(self, api):
        """PRD §3.8: "The base window depends on severity: 7 days for `SEV_1`,
        30 days for `SEV_2`, 90 days for `SEV_3`, and 180 days for `SEV_4`. If
        the engagement has an `EXECUTED` contract, the contract's
        `breach_cure_window_days` narrows the window when shorter — the
        effective window is the smaller of the severity window and the
        contractual cure window."

        Design: Difficulty/combinatorial_formula/remediation_deadline_severity_vs_contract_window
        """
        reset_clock()
        vendor = create_vendor(name="NoContract Vendor")
        engagement = create_engagement(vendor["id"], code="NC-E1", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="nc")
        submit_dd_package(package["id"])  # engagement DD_IN_PROGRESS, no contract
        incident = file_incident(engagement["id"], severity="SEV_1")
        triaged = triage_incident(incident["id"])
        # No EXECUTED contract -> pure severity window of 7 days.
        assert parse_iso_instant(triaged["remediation_due_at"]) == iso_after_days(CLOCK, 7)


class TestCompositeScoreCompensatingInvariant:
    def test_open_close_reopen_restores_and_recontributes(self, api):
        """PRD §3.10: "Closed incidents contribute zero; reopening an incident
        immediately re-contributes its severity weight."
        PRD §3.8: "Reopening increments `reopen_count` by 1, clears `closed_at`
        to null, sets the engagement's `risk_attention_state` to
        `UNDER_REVIEW`, and recomputes the vendor's `tier_posture`."

        Design: Difficulty/compensating_invariant/incident_open_close_reopen_close_restores_composite_risk_score
        """
        ctx = setup_active_vendor(vendor_name="Invariant Vendor")
        v_id = ctx["vendor"]["id"]
        assert get_vendor(v_id)["composite_risk_score"] == pytest.approx(0, abs=1e-9)

        incident = file_incident(ctx["engagement"]["id"], severity="SEV_3", detected_at="2026-05-02T00:00:00Z")
        triage_incident(incident["id"])
        remediate_incident_to_closed(incident["id"], committed="2026-05-20T00:00:00Z")
        score_after_close = get_vendor(v_id)["composite_risk_score"]
        assert score_after_close == pytest.approx(0, abs=1e-9), (
            "after close the score returns to its pre-incident baseline"
        )

        incident_after = get_incident(incident["id"])
        verifier = make_business_owner_headers(incident_after["reported_by_user_id"])
        validate_success(api.reopen_incident(incident["id"], verifier), 200)
        score_after_reopen = get_vendor(v_id)["composite_risk_score"]
        assert score_after_reopen == pytest.approx(8.00, abs=1e-9), (
            "reopening re-contributes the SEV_3 weight of 8 at tier multiplier 1.0"
        )

    def test_close_after_sev1_restores_baseline_and_clean_posture(self, api):
        """PRD §3.10: "Closed incidents contribute zero; reopening an incident
        immediately re-contributes its severity weight."
        PRD §3.10: "Each recompute then derives `tier_posture` by thresholding:
        a score of at least 70 lands the vendor in `BREACH`; at least 40 but
        less than 70 lands in `ESCALATED`; at least 15 but less than 40 lands
        in `WATCH`; anything below 15 lands in `CLEAN`."

        Design: Difficulty/compensating_invariant/incident_open_close_reopen_close_restores_composite_risk_score
        """
        ctx = setup_active_vendor(vendor_name="Invariant Vendor 2")
        v_id = ctx["vendor"]["id"]
        incident = file_incident(ctx["engagement"]["id"], severity="SEV_1", detected_at="2026-05-02T00:00:00Z")
        vendor_open = get_vendor(v_id)
        assert vendor_open["composite_risk_score"] == pytest.approx(40.00, abs=1e-9)
        assert vendor_open["tier_posture"] == "ESCALATED"

        triage_incident(incident["id"])
        remediate_incident_to_closed(incident["id"], committed="2026-05-05T00:00:00Z")
        vendor_closed = get_vendor(v_id)
        assert vendor_closed["composite_risk_score"] == pytest.approx(0, abs=1e-9)
        assert vendor_closed["tier_posture"] == "CLEAN"


class TestCloseReopenCycle:
    def test_reopen_increments_count_and_clears_closed_at(self, api):
        """PRD §3.8: "Reopening increments `reopen_count` by 1, clears
        `closed_at` to null, sets the engagement's `risk_attention_state` to
        `UNDER_REVIEW`, and recomputes the vendor's `tier_posture`."
        PRD §3.8: "A `BusinessUnitOwner` may reopen a closed incident, but only
        the same user who filed it (otherwise `ERR_SOD_REOPEN_NOT_REPORTER`,
        HTTP 403), only when the incident is `CLOSED` (otherwise
        `ERR_INCIDENT_NOT_CLOSED`, HTTP 409), and only while `reopen_count` is
        less than 2 (otherwise `ERR_REOPEN_LIMIT_REACHED`, HTTP 422)."

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_cycle_capped
        """
        ctx = setup_closed_incident(severity="SEV_4", vendor_name="Reopen Vendor")
        incident = ctx["incident"]
        assert incident["status"] == "CLOSED"
        assert incident["reopen_count"] == 0

        verifier = make_business_owner_headers(incident["reported_by_user_id"])
        reopened = validate_success(api.reopen_incident(incident["id"], verifier), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["closed_at"] is None

    def test_reopen_sets_engagement_under_review_and_recontributes_score(self, api):
        """PRD §3.8: "Reopening increments `reopen_count` by 1, clears
        `closed_at` to null, sets the engagement's `risk_attention_state` to
        `UNDER_REVIEW`, and recomputes the vendor's `tier_posture`."
        PRD §3.10: "Closed incidents contribute zero; reopening an incident
        immediately re-contributes its severity weight."

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_cycle_capped
        """
        ctx = setup_closed_incident(severity="SEV_4", vendor_name="Reopen Vendor 2")
        incident = ctx["incident"]
        e_id = ctx["engagement"]["id"]
        v_id = ctx["vendor"]["id"]
        assert get_engagement(e_id)["risk_attention_state"] == "NORMAL"

        verifier = make_business_owner_headers(incident["reported_by_user_id"])
        validate_success(api.reopen_incident(incident["id"], verifier), 200)

        assert get_engagement(e_id)["risk_attention_state"] == "UNDER_REVIEW"
        # SEV_4 weight 3 at TIER_3 multiplier 1.0.
        assert get_vendor(v_id)["composite_risk_score"] == pytest.approx(3.00, abs=1e-9)


class TestRemediationSoD:
    def test_plan_approve_by_plan_owner_rejected(self, api):
        """PRD §3.8: "Approval is performed by a `RiskOfficer` other than the
        plan owner and other than the incident reporter — violating either
        constraint yields `ERR_SOD_PLAN_SELF_APPROVE` (HTTP 403)."

        Design: Corner/state_machines/plan_approve_by_plan_owner_rejected_sod
        """
        ctx = setup_active_engagement(vendor_name="SoD2")
        reporter = make_business_owner_headers("u_bu_reporter_sod2")
        incident = file_incident(
            ctx["engagement"]["id"], severity="SEV_3", reporter_headers=reporter
        )
        triage_incident(incident["id"])
        owner = make_risk_officer_headers("u_risk_owner_sod2")
        plan = validate_success(
            api.create_remediation_plan(
                incident["id"],
                create_remediation_plan_payload(committed_completion_date="2026-05-20T00:00:00Z"),
                owner,
            ),
            201,
        )
        validate_success(api.submit_remediation_plan(plan["id"], owner), 200)

        res = api.approve_remediation_plan(plan["id"], owner)
        validate_error(res, ApiErrorId.ERR_SOD_PLAN_SELF_APPROVE.value)

    def test_verify_by_non_reporter_rejected(self, api):
        """PRD §3.8: "Verification is performed by a `BusinessUnitOwner` and
        only by the same user who filed the incident — any other user yields
        `ERR_SOD_VERIFY_NOT_REPORTER` (HTTP 403)."

        Design: Corner/state_machines/incident_verify_by_non_reporter_rejected
        """
        ctx = setup_active_engagement(vendor_name="SoD3")
        reporter = make_business_owner_headers("u_bu_reporter_sod3")
        incident = file_incident(
            ctx["engagement"]["id"], severity="SEV_3", reporter_headers=reporter
        )
        triage_incident(incident["id"])
        plan = validate_success(
            api.create_remediation_plan(
                incident["id"],
                create_remediation_plan_payload(committed_completion_date="2026-05-20T00:00:00Z"),
                RO,
            ),
            201,
        )
        validate_success(api.submit_remediation_plan(plan["id"], RO), 200)
        validate_success(api.approve_remediation_plan(plan["id"], RO_APPROVER), 200)
        validate_success(
            api.submit_verification(plan["id"], {"verification_evidence_uri": "s3://evidence/x"}, RO),
            200,
        )

        res = api.verify_remediation_plan(plan["id"], make_business_owner_headers("u_bu_other_sod3"))
        validate_error(res, ApiErrorId.ERR_SOD_VERIFY_NOT_REPORTER.value)
