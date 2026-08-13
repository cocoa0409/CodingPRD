"""Subrecipient risk, verification, and rate-agreement windows (PRD §3.2, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_fa_rate_agreement_payload,
    create_proposal_payload,
    get_proposal,
    get_success_data,
    make_context,
    make_opportunity,
    make_org,
    make_pi,
    make_proposal,
    make_rate_agreement,
    make_routed_proposal,
    make_sub_commitment,
    reset_clock,
    validate_error,
    validate_success,
    verify_sub_commitment,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
SUBMGR = TEST_USERS["sub_manager_headers"]


class TestRiskVariantDual:
    def _setup(self, api):
        """Org NOT_REQUIRED + 4 findings (standard 40, MEDIUM); commitment of
        30000000 cents with docs complete and monitoring acknowledged."""
        reset_clock()
        ctx = make_context()
        org = make_org(
            legal_name="Org D", uei="UEI-DDD4", single_audit_status="NOT_REQUIRED",
            audit_finding_count=4, is_foreign=False, first_time_subrecipient=False,
        )
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="P",
                             fa_base_type="MTDC")
        comm = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=30_000_000,
            enhanced_monitoring_acknowledged=True,
        )
        return org, comm

    def test_org_registry_reads_standard_variant(self, api):
        """PRD §3.7: "Registration computes the standard-variant `risk_score` and
        `risk_tier` on the spot." and "The enhanced score lives only on the
        verification snapshot, so one and the same organization can read `MEDIUM`
        on its registry entry yet verify as `HIGH` for a large commitment."

        Design: Difficulty/dual_variant_calc/subrecipient_risk_standard_vs_enhanced
        """
        org, _comm = self._setup(api)
        # standard variant: 20 base + min(5*4, 25)=20 findings = 40
        assert org["risk_score"] == 40
        assert org["risk_tier"] == "MEDIUM"

    def test_verify_applies_enhanced_variant(self, api):
        """PRD §3.7: "when the commitment's `subaward_amount_cents` is at least
        $250,000 (25000000 cents — an amount exactly equal selects the enhanced
        variant), the score is computed as the standard score plus a 15-point
        surcharge, then tiered by the same thresholds" and "sets
        `monitoring_level` to `ENHANCED` when the verified tier is `HIGH`,
        otherwise `STANDARD`."

        Design: Difficulty/dual_variant_calc/subrecipient_risk_standard_vs_enhanced
        """
        org, comm = self._setup(api)
        verified = verify_sub_commitment(comm["id"])
        # enhanced variant: 40 + 15 = 55 -> HIGH -> ENHANCED monitoring
        assert verified["verified_risk_snapshot_score"] == 55
        assert verified["monitoring_level"] == "ENHANCED"
        assert verified["verified_risk_snapshot_score"] != org["risk_score"]


class TestEnhancedThresholdBoundary:
    def _setup(self, api):
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Thresh", uei="UEI-THR1",
                       single_audit_status="NOT_REQUIRED", audit_finding_count=4)
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Thresh",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        return org, prop

    def test_exactly_at_threshold_enhanced(self, api):
        """PRD §3.7: "when the commitment's `subaward_amount_cents` is at least
        $250,000 (25000000 cents — an amount exactly equal selects the enhanced
        variant), the score is computed as the standard score plus a 15-point
        surcharge, then tiered by the same thresholds."

        Design: Corner/cross_cutting_layers/enhanced_scoring_threshold_boundary
        """
        org, prop = self._setup(api)
        assert org["risk_tier"] == "MEDIUM"
        comm = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=25_000_000,
            enhanced_monitoring_acknowledged=True,
        )
        verified = verify_sub_commitment(comm["id"])
        assert verified["verified_risk_snapshot_score"] == 55
        assert verified["monitoring_level"] == "ENHANCED"

    def test_one_cent_below_threshold_standard(self, api):
        """PRD §3.7: "when the commitment's `subaward_amount_cents` is at least
        $250,000 (25000000 cents — an amount exactly equal selects the enhanced
        variant)" and "sets `monitoring_level` to `ENHANCED` when the verified
        tier is `HIGH`, otherwise `STANDARD`."

        Design: Corner/cross_cutting_layers/enhanced_scoring_threshold_boundary
        """
        org, prop = self._setup(api)
        comm = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=24_999_999,
            enhanced_monitoring_acknowledged=False,
        )
        verified = verify_sub_commitment(comm["id"])
        # standard variant: 40 -> MEDIUM -> STANDARD monitoring, no ack required
        assert verified["verified_risk_snapshot_score"] == 40
        assert verified["monitoring_level"] == "STANDARD"


class TestVerifyGates:
    def _setup(self, api):
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Docs", uei="UEI-DOC1")
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Docs",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        return org, prop

    def test_docs_incomplete_rejected(self, api):
        """PRD §3.7: "both `statement_of_work_received` and `budget_received`
        must be true, else `ERR_SUBREC_DOCS_INCOMPLETE` (HTTP 422)".

        Design: Corner/errors/sub_docs_incomplete_rejected
        """
        org, prop = self._setup(api)
        c1 = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=500_000,
            statement_of_work_received=False, budget_received=True,
        )
        resp = api.verify_subrecipient_commitment(c1["id"], SUBMGR)
        validate_error(resp, ApiErrorId.ERR_SUBREC_DOCS_INCOMPLETE.value)

    def test_docs_complete_verifies(self, api):
        """PRD §3.7: "Verification, performed by the `SubrecipientManager`, is
        allowed from `DRAFT` or `STALE`" and "both `statement_of_work_received`
        and `budget_received` must be true".

        Design: Corner/errors/sub_docs_incomplete_rejected
        """
        org, prop = self._setup(api)
        c2 = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=500_000,
            statement_of_work_received=True, budget_received=True,
        )
        verified = verify_sub_commitment(c2["id"])
        assert verified["status"] == "VERIFIED"


class TestHighRiskAck:
    def _setup(self, api):
        """Org DELINQUENT + 9 findings + foreign -> 95 HIGH; one proposal with
        two commitments (C1 without ack, C2 with ack)."""
        reset_clock()
        ctx = make_context()
        org = make_org(
            legal_name="Risky", uei="UEI-RSK1", single_audit_status="DELINQUENT",
            audit_finding_count=9, is_foreign=True,
        )
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Sub",
                             fa_base_type="MTDC")
        c1 = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=10_000_000,
            enhanced_monitoring_acknowledged=False,
        )
        c2 = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=10_000_000,
            enhanced_monitoring_acknowledged=True,
        )
        return org, c1, c2

    def test_high_tier_without_ack_rejected(self, api):
        """PRD §3.7: "when the organization's risk tier is `HIGH`,
        `enhanced_monitoring_acknowledged` must be true, else
        `ERR_SUBREC_HIGH_RISK_NOT_ACKED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/verify_requires_org_risk_ack
        """
        org, c1, _c2 = self._setup(api)
        assert org["risk_tier"] == "HIGH"
        resp = api.verify_subrecipient_commitment(c1["id"], SUBMGR)
        validate_error(resp, ApiErrorId.ERR_SUBREC_HIGH_RISK_NOT_ACKED.value)

    def test_high_tier_with_ack_verifies_enhanced(self, api):
        """PRD §3.7: "Successful verification pins
        `verified_risk_snapshot_score` to the risk score computed under the
        variant the amount selects, and sets `monitoring_level` to `ENHANCED`
        when the verified tier is `HIGH`, otherwise `STANDARD`."

        Design: Difficulty/cross_entity_state_dependency/verify_requires_org_risk_ack
        """
        _org, _c1, c2 = self._setup(api)
        verified = verify_sub_commitment(c2["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["monitoring_level"] == "ENHANCED"
        assert verified["verified_risk_snapshot_score"] == 95


class TestStaleReverifyCycle:
    def _setup(self, api):
        """ROUTED proposal carrying a VERIFIED commitment on a LOW-risk org."""
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="LowSub", uei="UEI-LOW1")
        env = make_routed_proposal(ctx=ctx)
        prop_id = env["proposal"]["id"]
        comm = make_sub_commitment(prop_id, org["id"], subaward_amount_cents=500_000)
        verify_sub_commitment(comm["id"])
        return env, comm

    def test_return_for_revision_stales_commitment(self, api):
        """PRD §3.5: "every `VERIFIED` subrecipient commitment goes `STALE`".
        PRD §3.7: "When the parent proposal is returned for revision, every
        `VERIFIED` commitment goes `STALE` automatically".

        Design: Corner/state_machines/sub_commitment_stale_reverify_cycle
        """
        env, comm = self._setup(api)
        api.return_for_revision(
            env["proposal"]["id"], {"reason": "fix budget"}, DIRECTOR
        )
        subs = get_success_data(
            api.list_subrecipient_commitments(env["proposal"]["id"], DIRECTOR)
        )
        assert subs[0]["status"] == "STALE"

    def test_reverify_closes_cycle(self, api):
        """PRD §3.7: "Verification, performed by the `SubrecipientManager`, is
        allowed from `DRAFT` or `STALE`" and "Successful verification pins
        `verified_risk_snapshot_score` to the risk score computed under the
        variant the amount selects, and sets `monitoring_level` to `ENHANCED`
        when the verified tier is `HIGH`, otherwise `STANDARD`."

        Design: Corner/state_machines/sub_commitment_stale_reverify_cycle
        """
        env, comm = self._setup(api)
        api.return_for_revision(
            env["proposal"]["id"], {"reason": "fix budget"}, DIRECTOR
        )
        verified = verify_sub_commitment(comm["id"])
        assert verified["status"] == "VERIFIED"
        # standard variant (500000 < 25000000): CURRENT + 0 findings = 10 LOW
        assert verified["verified_risk_snapshot_score"] == 10
        assert verified["monitoring_level"] == "STANDARD"


class TestRateWindowOverlap:
    def test_adjacent_final_windows_allowed(self, api):
        """PRD §3.2: "The overlap rule guards only FINAL-versus-FINAL pairs: a
        `FINAL` agreement whose half-open window overlaps another `FINAL`
        agreement of the same `rate_type` is rejected with
        `ERR_FA_RATE_WINDOW_OVERLAP` (HTTP 409), while mere adjacency — one
        window's `effective_end_on` equal to the other's `effective_start_on` —
        is allowed".

        Design: Difficulty/resource_temporal_overlap/final_rate_window_overlap_adjacency
        """
        a = make_rate_agreement(
            rate_pct=52.00, effective_start_on="2025-01-01",
            effective_end_on="2026-01-01", initial_status="FINAL",
        )
        assert a["status"] == "FINAL"
        # starts exactly at A's end -> adjacency, not overlap
        b = make_rate_agreement(
            rate_pct=53.00, effective_start_on="2026-01-01",
            effective_end_on="2027-01-01", initial_status="FINAL",
        )
        assert b["status"] == "FINAL"

    def test_straddling_final_window_rejected_provisional_unaffected(self, api):
        """PRD §3.2: "a `FINAL` agreement whose half-open window overlaps another
        `FINAL` agreement of the same `rate_type` is rejected with
        `ERR_FA_RATE_WINDOW_OVERLAP` (HTTP 409) ... and `PROVISIONAL` agreements
        never trigger the check." and "Finalization moves a `PROVISIONAL`
        agreement to `FINAL`".

        Design: Difficulty/resource_temporal_overlap/final_rate_window_overlap_adjacency
        """
        make_rate_agreement(
            rate_pct=52.00, effective_start_on="2025-01-01",
            effective_end_on="2026-01-01", initial_status="FINAL",
        )
        # [2025-06-01, 2026-06-01) straddles the existing FINAL window
        resp = api.create_fa_rate_agreement(
            create_fa_rate_agreement_payload(
                rate_pct=54.00, effective_start_on="2025-06-01",
                effective_end_on="2026-06-01", initial_status="FINAL",
            ),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_FA_RATE_WINDOW_OVERLAP.value)
        # A PROVISIONAL agreement of a different rate_type finalizes freely:
        # the overlap rule is per rate_type.
        prov = make_rate_agreement(
            rate_type="OFF_CAMPUS_RESEARCH", rate_pct=26.00,
            effective_start_on="2025-06-01", effective_end_on="2026-06-01",
        )
        finalized = validate_success(
            api.finalize_fa_rate_agreement(prov["id"], DIRECTOR), 200
        )
        assert finalized["status"] == "FINAL"

    def test_finalize_final_agreement_rejected(self, api):
        """PRD §3.2: "Finalization moves a `PROVISIONAL` agreement to `FINAL` —
        finalizing anything else is rejected with
        `ERR_RATE_AGREEMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/errors/finalize_final_agreement_rejected
        """
        rate = make_rate_agreement(
            rate_type="INSTRUCTION", rate_pct=40.00, initial_status="FINAL"
        )
        resp = api.finalize_fa_rate_agreement(rate["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RATE_AGREEMENT_INVALID_STATE.value)
