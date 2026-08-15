"""Licensee audits: dual claim valuation, the appeal cycle with claim
recomputation, closed-inclusive period overlap, and sample-base validation."""
from test_helpers import (
    ApiErrorId,
    create_licensee,
    create_licensee_audit,
    issue_findings_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, FINANCE

H1_2025 = ("2025-01-01T00:00:00Z", "2025-06-30T23:59:59Z")
H2_2025 = ("2025-07-01T00:00:00Z", "2025-12-31T23:59:59Z")
Y_2025 = ("2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")


class TestClaimValuationVariants:
    def test_audit_claim_actual_shortfall_returns_proven_amount(self, api):
        """PRD §3.9: "Under `ACTUAL_SHORTFALL`, the `claim_amount_cents` is exactly the `actual_shortfall_cents`. Under `EXTRAPOLATED`, the claim scales the proven shortfall up to the full period: the `actual_shortfall_cents` multiplied by the `reported_base_cents` and divided by the `sampled_base_cents`, rounded down to a whole cent."

        Design: Difficulty/dual_variant_calc/audit_claim_actual_vs_extrapolated_valuation
        """
        licensee = create_licensee()
        audit = create_licensee_audit(licensee["id"], "ACTUAL_SHORTFALL",
                                      period=H1_2025)
        validate_success(api.begin_fieldwork(audit["id"], AUDITOR))

        issued = validate_success(api.issue_findings(
            audit["id"], issue_findings_payload(40000), AUDITOR))
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["claim_amount_cents"] == 40000, (
            "ACTUAL_SHORTFALL returns the proven shortfall unchanged")

    def test_audit_claim_extrapolated_scales_to_full_period(self, api):
        """PRD §3.9: "Under `ACTUAL_SHORTFALL`, the `claim_amount_cents` is exactly the `actual_shortfall_cents`. Under `EXTRAPOLATED`, the claim scales the proven shortfall up to the full period: the `actual_shortfall_cents` multiplied by the `reported_base_cents` and divided by the `sampled_base_cents`, rounded down to a whole cent."

        Design: Difficulty/dual_variant_calc/audit_claim_actual_vs_extrapolated_valuation
        """
        licensee = create_licensee()
        audit = create_licensee_audit(licensee["id"], "EXTRAPOLATED",
                                      period=H2_2025)
        validate_success(api.begin_fieldwork(audit["id"], AUDITOR))

        issued = validate_success(api.issue_findings(
            audit["id"],
            issue_findings_payload(40000, sampled_base_cents=250000,
                                   reported_base_cents=1000000),
            AUDITOR))
        assert issued["status"] == "FINDINGS_ISSUED"
        # floor(40000 * 1000000 / 250000) = 160000 — the same proven
        # shortfall yields a different claim under the other variant.
        assert issued["claim_amount_cents"] == 160000
        assert issued["claim_amount_cents"] != 40000


class TestAppealCycle:
    def _fieldwork_audit(self, api):
        licensee = create_licensee()
        audit = create_licensee_audit(licensee["id"], "EXTRAPOLATED",
                                      period=Y_2025)
        validate_success(api.begin_fieldwork(audit["id"], AUDITOR))
        return audit

    def test_appeal_loops_findings_back_to_under_appeal(self, api):
        """PRD §3.9: "An appeal, recorded by the `Auditor` with a `reason`, moves the audit from `FINDINGS_ISSUED` to `UNDER_APPEAL`, opening the loop back to amended findings."

        Design: Difficulty/non_linear_state_machine/licensee_audit_appeal_cycle
        """
        audit = self._fieldwork_audit(api)
        issued = validate_success(api.issue_findings(
            audit["id"],
            issue_findings_payload(40000, sampled_base_cents=250000,
                                   reported_base_cents=1000000),
            AUDITOR))
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["claim_amount_cents"] == 160000

        appealed = validate_success(
            api.appeal_audit(audit["id"], "licensee disputes sample", AUDITOR))
        assert appealed["status"] == "UNDER_APPEAL", (
            "the appeal loops the cycle back")

    def test_amended_findings_recompute_claim(self, api):
        """PRD §3.9: "Findings may be issued from `FIELDWORK` or from `UNDER_APPEAL` — in the latter case they represent amended findings, and `claim_amount_cents` is recomputed from the new inputs by the same rule."

        Design: Difficulty/non_linear_state_machine/licensee_audit_appeal_cycle
        """
        audit = self._fieldwork_audit(api)
        validate_success(api.issue_findings(
            audit["id"],
            issue_findings_payload(40000, sampled_base_cents=250000,
                                   reported_base_cents=1000000),
            AUDITOR))
        validate_success(
            api.appeal_audit(audit["id"], "licensee disputes sample", AUDITOR))

        amended = validate_success(api.issue_findings(
            audit["id"],
            issue_findings_payload(30000, sampled_base_cents=250000,
                                   reported_base_cents=1000000),
            AUDITOR))
        assert amended["status"] == "FINDINGS_ISSUED"
        # floor(30000 * 1000000 / 250000) = 120000 — recomputed, not retained.
        assert amended["claim_amount_cents"] == 120000


class TestSettleGate:
    def test_audit_settle_from_under_appeal_rejected(self, api):
        """PRD §3.9: "Resolution comes from a `FinanceManager`, who settles a `FINDINGS_ISSUED` audit by supplying the agreed `settlement_cents` (zero or more), moving it to terminal `SETTLED`."
        PRD §3.9: "Every other trigger-state combination is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/audit_settle_from_under_appeal_rejected
        """
        licensee = create_licensee()
        audit = create_licensee_audit(licensee["id"], "ACTUAL_SHORTFALL",
                                      period=Y_2025)
        validate_success(api.begin_fieldwork(audit["id"], AUDITOR))
        validate_success(api.issue_findings(
            audit["id"], issue_findings_payload(40000), AUDITOR))
        appealed = validate_success(
            api.appeal_audit(audit["id"], "disputed", AUDITOR))
        assert appealed["status"] == "UNDER_APPEAL"

        resp = api.settle_audit(audit["id"], 30000, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAuditPeriodOverlap:
    def test_audit_period_shared_boundary_conflicts(self, api):
        """PRD §3.9: "One licensee may not have two overlapping audits: the period check is closed-inclusive — a shared boundary date counts as overlap — and runs against that licensee's audits in any status; a conflict is rejected with `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/licensee_audit_period_inclusive_overlap
        """
        licensee = create_licensee()
        create_licensee_audit(licensee["id"], "ACTUAL_SHORTFALL",
                              period=Y_2025)

        # 2025-12-31 is inside the existing audit's closed period.
        payload = {
            "licensee_id": licensee["id"],
            "period_start": "2025-12-31T23:59:59Z",
            "period_end": "2026-06-30T23:59:59Z",
            "valuation_method": "ACTUAL_SHORTFALL",
        }
        resp = api.create_licensee_audit(payload, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP)

    def test_audit_period_non_overlapping_created(self, api):
        """PRD §3.9: "One licensee may not have two overlapping audits: the period check is closed-inclusive — a shared boundary date counts as overlap — and runs against that licensee's audits in any status; a conflict is rejected with `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/licensee_audit_period_inclusive_overlap
        """
        licensee = create_licensee()
        create_licensee_audit(licensee["id"], "ACTUAL_SHORTFALL",
                              period=Y_2025)

        created = create_licensee_audit(
            licensee["id"], "EXTRAPOLATED",
            period=("2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z"))
        assert created["status"] == "OPEN", (
            "a 2026 audit shares no date with the 2025 audit")


class TestSampleBaseValidation:
    def test_audit_extrapolated_sample_base_rejected(self, api):
        """PRD §3.9: "The extrapolated variant is only well-formed when `sampled_base_cents` is present and at least 1 and `reported_base_cents` is present and at least `sampled_base_cents`; otherwise issuing findings is rejected with `ERR_AUDIT_SAMPLE_BASE_INVALID`."

        Design: Corner/validations/audit_extrapolated_sample_base_rejected
        """
        licensee = create_licensee()
        audit = create_licensee_audit(licensee["id"], "EXTRAPOLATED",
                                      period=Y_2025)
        validate_success(api.begin_fieldwork(audit["id"], AUDITOR))

        resp = api.issue_findings(
            audit["id"],
            issue_findings_payload(40000, sampled_base_cents=0,
                                   reported_base_cents=1000000),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_SAMPLE_BASE_INVALID)
