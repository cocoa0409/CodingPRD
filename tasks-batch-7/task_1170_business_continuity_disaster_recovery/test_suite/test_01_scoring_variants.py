"""Dual-variant scoring: BIA criticality and vendor continuity (PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_active_process,
    create_active_vendor,
    create_approved_bia,
    create_assessment,
    create_bia,
    create_contact,
    decide_bia,
    make_risk_committee_headers,
    make_vendor_manager_headers,
    submit_bia,
    validate_success,
)

ANALYST_HEADERS = TEST_USERS["bia_analyst_headers"]


class TestBiaCriticalityDualVariant:
    def test_bia_provisional_score_computed_on_create(self, api):
        """PRD §3.2: "While the analysis is `DRAFT`, `SUBMITTED`, or `REJECTED`, the variant is `PROVISIONAL` and the score recomputes on creation and on every update."
        PRD §3.2: "the financial leg is `impact_financial_per_hour` divided by ten thousand — deliberately uncapped — and contributes with weight 45; the regulatory leg maps `NONE` to 0, `LOW` to 1, and `HIGH` to 2 and contributes with weight 25; the peak leg contributes 1 when `peak_period_flag` is set and 0 otherwise, weighted 20; and the operational leg maps like the regulatory leg, weighted 10."

        1200/10000*45 + 1*25 + 1*20 + 0*10 = 50.40, PROVISIONAL while DRAFT.

        Design: Difficulty/dual_variant_calc/bia_provisional_vs_final_tier1_uplift
        """
        committee = create_contact("Rita Committee", "Risk Committee")
        process = create_active_process(committee["id"], name="Payments",
                                        criticality_tier="TIER_1")
        bia = create_bia(
            process["id"], cycle_label="FY2026-H1", rto_target_hours=4,
            rpo_target_hours=1, mtpd_hours=24, peak_period_flag=True,
            peak_start_month=11, peak_end_month=12,
            impact_financial_per_hour=1200, impact_regulatory="LOW",
            impact_reputational="NONE", impact_operational="NONE",
        )
        assert bia["criticality_score"] == pytest.approx(50.40, abs=0.001), (
            f"PROVISIONAL score must be 50.40, got {bia['criticality_score']}"
        )
        assert bia["score_variant"] == "PROVISIONAL"
        assert bia["status"] == "DRAFT"

    def test_bia_final_score_frozen_at_approval(self, api):
        """PRD §3.2: "The `FINAL` variant is computed exactly once, at the moment the analysis becomes `APPROVED`: the same raw total is taken, and if the owning process's `criticality_tier` is `TIER_1` the raw total is first grown by a fifteen percent uplift before rounding; other tiers keep the provisional formula."
        PRD §3.2: "The result is rounded half-up to 2 decimal places and then frozen — identical inputs afterwards yield the frozen value, never a recomputed one, and a rejected-then-resubmitted analysis keeps recomputing under `PROVISIONAL` until it is finally approved."

        50.40 * 1.15 = 57.96 frozen at approval; a later read returns the frozen value.

        Design: Difficulty/dual_variant_calc/bia_provisional_vs_final_tier1_uplift
        """
        committee = create_contact("Rita Committee", "Risk Committee")
        process = create_active_process(committee["id"], name="Payments",
                                        criticality_tier="TIER_1")
        bia = create_bia(
            process["id"], cycle_label="FY2026-H1", rto_target_hours=4,
            rpo_target_hours=1, mtpd_hours=24, peak_period_flag=True,
            peak_start_month=11, peak_end_month=12,
            impact_financial_per_hour=1200, impact_regulatory="LOW",
            impact_reputational="NONE", impact_operational="NONE",
        )
        submit_bia(bia["id"])
        decided = decide_bia(bia["id"], "APPROVE", committee["id"])
        assert decided["status"] == "APPROVED"
        assert decided["score_variant"] == "FINAL"
        assert decided["criticality_score"] == pytest.approx(57.96, abs=0.001), (
            f"FINAL score must apply the TIER_1 uplift: 50.40*1.15 = 57.96, "
            f"got {decided['criticality_score']}"
        )
        assert decided["decided_by_contact_id"] == committee["id"]

        reread = validate_success(
            api_client.get_bia(bia["id"], make_risk_committee_headers(committee["id"])))
        assert reread["criticality_score"] == pytest.approx(57.96, abs=0.001), (
            "GET after approval must return the frozen 57.96, not a recomputed value"
        )
        assert reread["score_variant"] == "FINAL"


class TestVendorContinuityDualVariant:
    def _setup_event_driven_assessment(self):
        owner = create_contact("Victor Owner", "Vendor Owner")
        manager = create_contact("Manny Manager", "Vendor Manager")
        process = create_active_process(owner["id"], name="Ledger",
                                        criticality_tier="TIER_2")
        create_approved_bia(process["id"], manager["id"],
                            rto_target_hours=8, rpo_target_hours=2,
                            impact_financial_per_hour=500, impact_operational="LOW")
        vendor = create_active_vendor(owner["id"], manager["id"],
                                      name="Acme DR Services",
                                      service_category="Colocation",
                                      criticality_rating="CRITICAL")
        assessment = create_assessment(
            vendor["id"], process["id"], manager["id"],
            assessment_type="EVENT_DRIVEN", assessed_rto_hours=12,
            assessed_rpo_hours=4, rto_required_hours=6, rpo_required_hours=1,
            evidence_doc_ref="doc-1",
        )
        return owner, manager, process, vendor, assessment

    def test_assessment_provisional_score_uses_approved_bia_targets(self, api):
        """PRD §3.4: "The required targets are resolved from the process's latest `APPROVED` analysis — latest meaning the approval-ordered read, tie-broken by the analysis's `updated_at` most recent first and then `created_at` most recent first — and only when the process has no `APPROVED` analysis at all do the fallback inputs `rto_required_hours` and `rpo_required_hours` apply."
        PRD §3.4: "The recovery-time component starts at 100 and loses ten points for every hour by which `assessed_rto_hours` exceeds the required recovery time (shortfalls never add points), clamped between 0 and 100."

        Required 8/2 from the APPROVED BIA (not the 6/1 fallback): 100-(12-8)*10=60,
        100-(4-2)*5=90, floor(0.6*60+0.4*90)=72; 12 > 8 so meets_required_rto is false.

        Design: Difficulty/dual_variant_calc/assessment_provisional_vs_final_event_driven_discount
        """
        _, _, _, _, assessment = self._setup_event_driven_assessment()
        assert assessment["continuity_score"] == 72, (
            f"PROVISIONAL continuity score must be 72, got {assessment['continuity_score']}"
        )
        assert assessment["score_variant"] == "PROVISIONAL"
        assert assessment["meets_required_rto"] is False, (
            "assessed_rto_hours 12 exceeds the APPROVED analysis's 8-hour target"
        )

    def test_assessment_finalize_applies_event_driven_discount_and_opens_gap(self, api):
        """PRD §3.4: "At finalization the `FINAL` variant is computed exactly once: an `EVENT_DRIVEN` assessment takes a fifteen-point discount off the provisional value, floored at zero, and `INITIAL` and `ANNUAL` assessments keep the provisional value; the score then freezes permanently."
        PRD §3.4: "When the finalized assessment's `meets_required_rto` is false, the server opens a remediation gap on the assessment's process: `gap_type` `CAPABILITY` with `capability_id` and `finding_id` both empty, severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days out."

        72 - 15 = 57 frozen as FINAL; exactly one HIGH CAPABILITY gap opens.

        Design: Difficulty/dual_variant_calc/assessment_provisional_vs_final_event_driven_discount
        """
        _, manager, process, _, assessment = self._setup_event_driven_assessment()
        finalized = validate_success(
            api_client.finalize_assessment(
                assessment["id"], make_vendor_manager_headers(manager["id"])))
        assert finalized["status"] == "FINALIZED"
        assert finalized["score_variant"] == "FINAL"
        assert finalized["continuity_score"] == 57, (
            f"FINAL score must be 72-15 = 57, got {finalized['continuity_score']}"
        )
        assert finalized["finalized_by_contact_id"] == manager["id"]

        gaps = validate_success(
            api_client.list_gaps(make_vendor_manager_headers(manager["id"]),
                                 params={"process_id": process["id"]}))
        assert len(gaps) == 1, f"expected exactly one auto-created gap, got {len(gaps)}"
        assert gaps[0]["severity"] == "HIGH"
        assert gaps[0]["gap_type"] == "CAPABILITY"
        assert gaps[0]["status"] == "OPEN"


class TestBiaProvisionalRecompute:
    def test_bia_provisional_score_recomputes_on_update(self, api):
        """PRD §3.2: "While the analysis is `DRAFT`, `SUBMITTED`, or `REJECTED`, the variant is `PROVISIONAL` and the score recomputes on creation and on every update."
        PRD §3.2: "While in `DRAFT` or `REJECTED`, the analyst may still update the analysis's mutable fields — `cycle_label`, `rto_target_hours`, `rpo_target_hours`, `mtpd_hours`, `peak_period_flag`, `peak_start_month`, `peak_end_month`, `impact_financial_per_hour`, `impact_regulatory`, `impact_reputational`, and `impact_operational` — each update recomputing the provisional score and incrementing `version`; updates in any other state are refused with `ERR_INVALID_STATE`."

        1200 -> 50.40 on create; raising impact to 2400 recomputes to 55.80 (TIER_2: no uplift).

        Design: Corner/calculations/bia_provisional_recomputed_on_update
        """
        analyst = create_contact("Analyst Amy", "BIA Analyst")
        process = create_active_process(analyst["id"], name="RecompProc")
        bia = create_bia(
            process["id"], cycle_label="FY2026-H1", rto_target_hours=8,
            rpo_target_hours=2, mtpd_hours=24, peak_period_flag=True,
            peak_start_month=11, peak_end_month=12,
            impact_financial_per_hour=1200, impact_regulatory="LOW",
            impact_reputational="NONE", impact_operational="NONE",
        )
        assert bia["criticality_score"] == pytest.approx(50.40, abs=0.001)

        updated = validate_success(
            api_client.update_bia(bia["id"], {"impact_financial_per_hour": 2400},
                                  ANALYST_HEADERS))
        assert updated["criticality_score"] == pytest.approx(55.80, abs=0.001), (
            f"PROVISIONAL recompute must yield 55.80, got {updated['criticality_score']}"
        )
        assert updated["version"] == bia["version"] + 1
        assert updated["score_variant"] == "PROVISIONAL"
