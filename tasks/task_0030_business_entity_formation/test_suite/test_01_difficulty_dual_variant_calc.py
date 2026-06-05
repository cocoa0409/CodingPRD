"""Difficulty Rule 1 — dual_variant_calc.

Two domains where the same calculation has two variants whose outputs can
diverge: AnnualReport.franchise_tax (provisional at CREATE, assessed at FILE)
and BusinessEntity.compliance_posture (realtime). The PRD describes a snapshot
posture variant conceptually in §3.6 but does NOT expose an endpoint to read
it (§4 lists none) — therefore only the realtime side of the posture instance
is testable. The realtime side has two distinct observable assertions, so the
instance still receives the required ≥2 tests.
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    file_annual_report,
    make_compliance_officer_headers,
)


class TestFranchiseTaxProvisionalVsAssessed:
    """PRD §3.8: provisional-estimate runs at report CREATE; assessed-final
    runs at FILE and re-reads revenue_band. Identical inputs at CREATE
    produce identical provisional values; differing revenue_band yields
    different assessed values.
    """

    def test_de_llc_small_yields_33000_assessed_at_file(self, api):
        """PRD §3.8: "The raw amount is the base in cents multiplied by the tier
        multiplier, then divided by 100 with integer floor"
        PRD §3.8: "The final `franchise_tax_amount_cents` is the larger of the raw
        amount and the state's minimum floor."
        PRD §3.8: "The assessed-final variant runs at filing time and re-reads
        `revenue_band` as currently declared on the parent"

        Design: Difficulty/dual_variant_calc/dvc_franchise_tax_provisional_vs_assessed_on_annual_report
        """
        set_clock("2025-03-01T00:00:00Z")
        be_a, _ = setup_active_llc(
            legal_name="ACME ALPHA LLC", formation_state_code="DE", revenue_band="SMALL"
        )
        ar_a = create_draft_annual_report(be_a, 2024)
        # Provisional stamped at create from SMALL band: base=30000, mult=110,
        # raw=(30000*110)//100=33000; floor=17500; result=33000.
        assert ar_a["franchise_tax_amount_cents"] == 33000, (
            f"provisional should be 33000 for DE LLC SMALL, "
            f"got {ar_a['franchise_tax_amount_cents']}"
        )
        # File the report — assessed-final re-reads revenue_band (still SMALL).
        filed_a = file_annual_report(be_a, ar_a["id"])
        assert filed_a["franchise_tax_amount_cents"] == 33000
        assert filed_a["late_fee_cents"] == 0

    def test_de_llc_medium_yields_37500_assessed_at_file(self, api):
        """PRD §3.8: "The second input is a revenue-tier multiplier, expressed as a
        hundredths-scaled integer: `ZERO` and `MICRO` are 1.00x (multiplier 100),
        `SMALL` is 1.10x (multiplier 110), `MEDIUM` is 1.25x (multiplier 125), and
        `LARGE` is 1.50x (multiplier 150)."

        Design: Difficulty/dual_variant_calc/dvc_franchise_tax_provisional_vs_assessed_on_annual_report
        """
        set_clock("2025-03-01T00:00:00Z")
        be_b, _ = setup_active_llc(
            legal_name="ACME BETA LLC", formation_state_code="DE", revenue_band="MEDIUM"
        )
        ar_b = create_draft_annual_report(be_b, 2024)
        # base=30000, mult=125, raw=(30000*125)//100=37500; floor=17500; result=37500.
        assert ar_b["franchise_tax_amount_cents"] == 37500
        filed_b = file_annual_report(be_b, ar_b["id"])
        assert filed_b["franchise_tax_amount_cents"] == 37500
        assert filed_b["late_fee_cents"] == 0

    def test_provisional_and_assessed_diverge_with_different_revenue_band(self, api):
        """PRD §3.8: "The assessed-final variant runs at filing time and re-reads
        `revenue_band` as currently declared on the parent, possibly producing a
        different number than the provisional estimate if the band has been changed
        in between."

        Design: Difficulty/dual_variant_calc/dvc_franchise_tax_provisional_vs_assessed_on_annual_report
        """
        set_clock("2025-03-01T00:00:00Z")
        be_a, _ = setup_active_llc(
            legal_name="ALPHA SMALL CO LLC", formation_state_code="DE", revenue_band="SMALL"
        )
        be_b, _ = setup_active_llc(
            legal_name="BRAVO MED CO LLC", formation_state_code="DE", revenue_band="MEDIUM"
        )
        ar_a = create_draft_annual_report(be_a, 2024)
        ar_b = create_draft_annual_report(be_b, 2024)
        filed_a = file_annual_report(be_a, ar_a["id"])
        filed_b = file_annual_report(be_b, ar_b["id"])
        # The two assessed values diverge for identical (state, type, year) but
        # different revenue_band.
        assert filed_a["franchise_tax_amount_cents"] != filed_b["franchise_tax_amount_cents"]
        assert filed_a["franchise_tax_amount_cents"] == 33000
        assert filed_b["franchise_tax_amount_cents"] == 37500


class TestCompliancePostureRealtimeCascade:
    """PRD §3.6 realtime variant: posture is recomputed on every write that
    mutates a BusinessEntity or any of its children. The snapshot variant in
    PRD §3.6 is described conceptually but PRD §4 exposes no endpoint to read
    it, so we test only the realtime side via two distinct observable
    assertions.
    """

    def test_realtime_posture_flips_to_restricted_when_report_goes_delinquent(self, api):
        """PRD §3.6: "if any `AnnualReport` for the parent is in `DELINQUENT` status,
        the posture is `RESTRICTED`"

        Design: Difficulty/dual_variant_calc/dvc_compliance_posture_realtime_vs_snapshot_on_business_entity
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="DELTA REALTIME LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        # Advance past the April-15-2025 deadline → AR DRAFT → DELINQUENT
        # cascade → BusinessEntity ACTIVE → DELINQUENT, posture → RESTRICTED.
        set_clock("2025-05-01T00:00:00Z")
        be_now = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert be_now["compliance_posture"] == "RESTRICTED"
        ar_list_resp = api.list_annual_reports(
            be["id"], make_compliance_officer_headers()
        )
        ar_list = validate_success(ar_list_resp, 200)
        # ar_list is a list of AnnualReport rows under this entity.
        assert any(r["status"] == "DELINQUENT" for r in ar_list)

    def test_realtime_status_cascades_to_delinquent_on_report_delinquency(self, api):
        """PRD §3.6: "When a `DRAFT` annual report flips automatically to `DELINQUENT`
        (the deadline-driven transition described in §3.7), the parent is
        recomputed: `compliance_posture` moves to `RESTRICTED` and, if the parent was
        `ACTIVE`, its `status` also flips to `DELINQUENT` (the second hop of the
        cascade)."

        Design: Difficulty/dual_variant_calc/dvc_compliance_posture_realtime_vs_snapshot_on_business_entity
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="DELTA STATUS LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        assert be["status"] == "ACTIVE"
        create_draft_annual_report(be, 2024)
        set_clock("2025-05-01T00:00:00Z")
        be_after = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert be_after["status"] == "DELINQUENT"
        assert be_after["compliance_posture"] == "RESTRICTED"
