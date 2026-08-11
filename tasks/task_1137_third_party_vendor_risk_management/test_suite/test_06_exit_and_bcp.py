"""Engagement exit gating (blocking incidents, exit-readiness floor) and
business-continuity testing (RTO boundary, TIER_1 failure cascade)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_bcp_test_payload,
    create_fourth_party_payload,
    file_incident,
    get_engagement,
    get_vendor,
    setup_active_engagement,
    setup_active_vendor,
    triage_incident,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import VRM, RO, ADMIN


class TestInitiateExitBlockingIncidents:
    def test_initiate_exit_blocked_by_open_sev2(self, api):
        """PRD §3.9: "The engagement must be `ACTIVE` (otherwise
        `ERR_ENGAGEMENT_NOT_ACTIVE`, HTTP 409) and must have no `OPEN` or
        `REOPENED` incident with severity `SEV_1` or `SEV_2` (otherwise
        `ERR_BLOCKING_INCIDENTS_OPEN`, HTTP 422)."
        PRD §3.16: "which run before segregation-of-duties checks
        (`ERR_SOD_*`), which run before blocking-incident gates, which run
        before contract-clause completeness, which run before fourth-party
        acknowledgement gates, which run before due-diligence outcome gates,
        which run before temporal-ordering rules, which run before fiscal and
        tier-specific business constraints (exit readiness, waive tier,
        fourth-party PII tier)"

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_finalize_exit
        """
        ctx = setup_active_engagement(vendor_name="Prio2 Vendor")
        file_incident(ctx["engagement"]["id"], severity="SEV_2", detected_at="2026-05-02T00:00:00Z")
        res = api.initiate_exit(ctx["engagement"]["id"], VRM)
        validate_error(res, ApiErrorId.ERR_BLOCKING_INCIDENTS_OPEN.value)

    def test_initiate_exit_blocked_by_open_sev1(self, api):
        """PRD §3.9: "The engagement must be `ACTIVE` (otherwise
        `ERR_ENGAGEMENT_NOT_ACTIVE`, HTTP 409) and must have no `OPEN` or
        `REOPENED` incident with severity `SEV_1` or `SEV_2` (otherwise
        `ERR_BLOCKING_INCIDENTS_OPEN`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_finalize_exit
        """
        ctx = setup_active_engagement(vendor_name="Prio2b Vendor")
        file_incident(ctx["engagement"]["id"], severity="SEV_1", detected_at="2026-05-02T00:00:00Z")
        res = api.initiate_exit(ctx["engagement"]["id"], VRM)
        validate_error(res, ApiErrorId.ERR_BLOCKING_INCIDENTS_OPEN.value)


class TestExitReadinessBoundary:
    def test_exit_readiness_75_finalize_rejected(self, api):
        """PRD §3.9: "The exit readiness score starts at 100 and applies
        deductions: 50 points if any incident on the engagement is in a
        non-terminal state (that is, any of `OPEN`, `TRIAGED`,
        `REMEDIATION_PLANNED`, `REMEDIATION_IN_PROGRESS`,
        `AWAITING_VERIFICATION`, or `REOPENED`); 20 points if any remediation
        plan on the engagement's incidents is in `DRAFT`, `SUBMITTED`,
        `APPROVED`, `IN_EXECUTION`, or `VERIFICATION_SUBMITTED`; 30 points if
        the contract lacks `has_exit_plan_section` while the vendor is
        `TIER_1_CRITICAL`; 15 points if any fourth party on the engagement is
        still in `PENDING`; and 10 points if any monitoring cycle on the vendor
        is `OVERDUE`."
        PRD §3.9: "A `RiskOfficer` finalizes exit once the engagement is
        `EXITING` (otherwise `ERR_ENGAGEMENT_NOT_EXITING`, HTTP 409), the score
        is at least 80.00 (otherwise `ERR_EXIT_READINESS_TOO_LOW`, HTTP 422),
        and no `OPEN` or `REOPENED` incidents remain (otherwise
        `ERR_OPEN_INCIDENTS_REMAIN`, HTTP 422)."

        Design: Difficulty/boundary_precision_check/exit_readiness_at_exactly_80
        """
        ctx = setup_active_vendor(vendor_name="Boundary Vendor")
        e_id = ctx["engagement"]["id"]
        # Leave one fourth party PENDING (-15).
        validate_success(
            api.create_fourth_party(
                e_id,
                create_fourth_party_payload(name="Sub Co", service_provided="sub-processing"),
                VRM,
            ),
            201,
        )
        # Push the TIER_3 cycle (due 2027-05-01) into OVERDUE (-10).
        validate_success(api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, ADMIN), 200)

        exiting = validate_success(api.initiate_exit(e_id, VRM), 200)
        # 100 - 15 (PENDING fourth party) - 10 (OVERDUE cycle) = 75
        assert exiting["exit_readiness_score"] == pytest.approx(75.00, abs=1e-9)
        assert exiting["lifecycle_status"] == "EXITING"

        res = api.finalize_exit(e_id, RO)
        validate_error(res, ApiErrorId.ERR_EXIT_READINESS_TOO_LOW.value)

    def test_exit_readiness_100_finalize_succeeds(self, api):
        """PRD §3.9: "The exit readiness score starts at 100 and applies
        deductions: 50 points if any incident on the engagement is in a
        non-terminal state (that is, any of `OPEN`, `TRIAGED`,
        `REMEDIATION_PLANNED`, `REMEDIATION_IN_PROGRESS`,
        `AWAITING_VERIFICATION`, or `REOPENED`); 20 points if any remediation
        plan on the engagement's incidents is in `DRAFT`, `SUBMITTED`,
        `APPROVED`, `IN_EXECUTION`, or `VERIFICATION_SUBMITTED`; 30 points if
        the contract lacks `has_exit_plan_section` while the vendor is
        `TIER_1_CRITICAL`; 15 points if any fourth party on the engagement is
        still in `PENDING`; and 10 points if any monitoring cycle on the vendor
        is `OVERDUE`."
        PRD §3.9: "Finalization transitions the engagement `EXITING → EXITED`
        and resets `risk_attention_state` to `NORMAL`."

        Design: Difficulty/boundary_precision_check/exit_readiness_at_exactly_80
        """
        ctx = setup_active_engagement(vendor_name="Boundary Vendor Clean")
        e_id = ctx["engagement"]["id"]
        exiting = validate_success(api.initiate_exit(e_id, VRM), 200)
        assert exiting["exit_readiness_score"] == pytest.approx(100.00, abs=1e-9)

        exited = validate_success(api.finalize_exit(e_id, RO), 200)
        assert exited["lifecycle_status"] == "EXITED"
        assert exited["risk_attention_state"] == "NORMAL"


class TestBcpRtoBoundary:
    def _make_bcp_in_progress(self, api, engagement_id, scheduled_for):
        bcp = validate_success(
            api.create_bcp_test(
                engagement_id,
                create_bcp_test_payload(
                    scheduled_for=scheduled_for, rto_target_minutes=60, rpo_target_minutes=30
                ),
                RO,
            ),
            201,
        )
        validate_success(api.begin_bcp_test(bcp["id"], RO), 200)
        return bcp

    def test_actual_rto_equal_to_target_passes(self, api):
        """PRD §3.12: "The `outcome` field is `PASS` when the actual RTO is at
        most `rto_target_minutes` and the actual RPO is at most
        `rpo_target_minutes`; otherwise `outcome` is `FAIL`. A `PASS` lands the
        test in `PASSED`."

        Design: Difficulty/boundary_precision_check/bcp_actual_rto_at_target_boundary
        """
        ctx = setup_active_vendor(vendor_name="RTO Vendor", category="CLOUD_INFRA")
        bcp = self._make_bcp_in_progress(api, ctx["engagement"]["id"], "2026-05-10T00:00:00Z")
        result = validate_success(
            api.submit_bcp_result(
                bcp["id"], {"actual_rto_minutes": 60, "actual_rpo_minutes": 30}, RO
            ),
            200,
        )
        assert result["status"] == "PASSED"
        assert result["outcome"] == "PASS"

    def test_actual_rto_one_above_target_fails(self, api):
        """PRD §3.12: "The `outcome` field is `PASS` when the actual RTO is at
        most `rto_target_minutes` and the actual RPO is at most
        `rpo_target_minutes`; otherwise `outcome` is `FAIL`. A `PASS` lands the
        test in `PASSED`. A `FAIL` lands it in `FAILED`, triggers a
        `tier_posture` recompute on the vendor, and, when the engagement's
        vendor is `TIER_1_CRITICAL`, additionally auto-creates an `Incident` of
        type `OUTAGE` with severity `SEV_2` on the same engagement."

        Design: Difficulty/boundary_precision_check/bcp_actual_rto_at_target_boundary
        """
        ctx = setup_active_vendor(vendor_name="RTO Vendor 2", category="CLOUD_INFRA")
        bcp = self._make_bcp_in_progress(api, ctx["engagement"]["id"], "2026-05-11T00:00:00Z")
        result = validate_success(
            api.submit_bcp_result(
                bcp["id"], {"actual_rto_minutes": 61, "actual_rpo_minutes": 30}, RO
            ),
            200,
        )
        assert result["status"] == "FAILED"
        assert result["outcome"] == "FAIL"


class TestBcpFailureCascade:
    def _setup_tier1_bcp_in_progress(self, api, vendor_name):
        ctx = setup_active_vendor(
            vendor_name=vendor_name,
            category="CLOUD_INFRA",
            sensitivity="REGULATED",
            vendor_tier="TIER_1_CRITICAL",
            contract_overrides={
                "has_right_to_audit_clause": True,
                "has_exit_plan_section": True,
                "sla_uptime_pct": 99.99,
            },
        )
        bcp = validate_success(
            api.create_bcp_test(
                ctx["engagement"]["id"],
                create_bcp_test_payload(rto_target_minutes=60, rpo_target_minutes=30),
                RO,
            ),
            201,
        )
        validate_success(api.begin_bcp_test(bcp["id"], RO), 200)
        return ctx, bcp

    def test_failed_bcp_on_tier1_auto_raises_sev2_incident_and_recomputes(self, api):
        """PRD §3.12: "A `FAIL` lands it in `FAILED`, triggers a
        `tier_posture` recompute on the vendor, and, when the engagement's
        vendor is `TIER_1_CRITICAL`, additionally auto-creates an `Incident` of
        type `OUTAGE` with severity `SEV_2` on the same engagement."
        PRD §3.10: "Each non-terminal incident on any of the vendor's
        engagements contributes a severity-weighted amount: `SEV_1` contributes
        40, `SEV_2` contributes 20, `SEV_3` contributes 8, and `SEV_4`
        contributes 3. Each `OVERDUE` monitoring cycle on the vendor
        contributes 10. Each `FAILED` business-continuity test on any of the
        vendor's engagements contributes 15."
        PRD §3.10: "The base sum is multiplied by a tier factor — 1.5 for
        `TIER_1_CRITICAL`, 1.2 for `TIER_2_HIGH`, 1.0 for `TIER_3_STANDARD`,
        and 0.8 for `TIER_4_LOW` — and the product is rounded half-up to two
        decimal places and clamped to the range 0 to 100."

        Design: Difficulty/transitive_cascade/bcp_failure_cascade_to_vendor_posture
        """
        ctx, bcp = self._setup_tier1_bcp_in_progress(api, "Cascade Vendor")
        result = validate_success(
            api.submit_bcp_result(
                bcp["id"], {"actual_rto_minutes": 120, "actual_rpo_minutes": 30}, RO
            ),
            200,
        )
        assert result["status"] == "FAILED"
        assert result["outcome"] == "FAIL"

        incidents, _meta = validate_paginated(
            api.list_incidents(ctx["engagement"]["id"], RO)
        )
        auto = [i for i in incidents if i["incident_type"] == "OUTAGE" and i["severity"] == "SEV_2"]
        assert len(auto) == 1, "TIER_1 BCP failure must auto-create one SEV_2 OUTAGE incident"
        assert auto[0]["status"] == "OPEN"

        vendor = get_vendor(ctx["vendor"]["id"])
        # (20 SEV_2 + 15 FAILED BCP) * 1.5 tier multiplier = 52.50 -> ESCALATED
        assert vendor["composite_risk_score"] == pytest.approx(52.50, abs=1e-9)
        assert vendor["tier_posture"] == "ESCALATED"

    def test_auto_raised_incident_flips_engagement_only_on_triage(self, api):
        """PRD §3.8: "New incidents land in `OPEN` with `reported_by_user_id`
        stamped from `X-User-ID` and `reopen_count` initialized to 0."
        PRD §3.8: "The triage side effects also include setting the
        engagement's `risk_attention_state` to `UNDER_REVIEW` if it was
        `NORMAL`, and recomputing the vendor's `tier_posture`."

        Design: Difficulty/transitive_cascade/bcp_failure_cascade_to_vendor_posture
        """
        ctx, bcp = self._setup_tier1_bcp_in_progress(api, "Cascade Vendor 2")
        validate_success(
            api.submit_bcp_result(
                bcp["id"], {"actual_rto_minutes": 120, "actual_rpo_minutes": 30}, RO
            ),
            200,
        )
        # The auto-created incident is OPEN (never triaged); the engagement's
        # risk_attention_state flips only at triage, so it is still NORMAL.
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["risk_attention_state"] == "NORMAL"

        incidents, _meta = validate_paginated(
            api.list_incidents(ctx["engagement"]["id"], RO)
        )
        auto = [i for i in incidents if i["incident_type"] == "OUTAGE" and i["severity"] == "SEV_2"]
        assert len(auto) == 1
        triage_incident(auto[0]["id"])
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["risk_attention_state"] == "UNDER_REVIEW"
