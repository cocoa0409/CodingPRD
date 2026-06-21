"""Dual-variant calculations: Back Pay (INITIAL vs ALJ) and SSI supplement
(eligible vs resource-ineligible)."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_in_medical_review,
    setup_application_awarded,
    setup_hearing_in_requested,
    submit_medical_decision,
    schedule_hearing, record_hearing_held, decide_hearing,
    make_claimant_headers,
)


# =========================================================================
# Instance: back_pay_initial_vs_alj_variants_diverge_on_benefit_award
# =========================================================================

class TestBackPayInitialVsAljVariantsDivergeOnBenefitAward:
    """Two tests for the same instance: one pins the INITIAL_APPROVAL
    variant, the other pins the ALJ_APPROVAL variant. Same claimant
    earnings, same EOD, same PFD → identical PIA, but the back-pay
    window closes at different decision_dates."""

    def test_initial_approval_variant_uses_dds_decision_date(self, api):
        """PRD §3.6: "For the `INITIAL_APPROVAL` variant — the path through
        `MEDICAL_REVIEW` to `APPROVED_INITIAL` — the closing date is the
        `created_at` of the `MedicalDeterminationDecision`."
        PRD §3.6: "The `back_pay_cents` value is the monthly benefit
        multiplied by the count of retroactive months."

        Design: Difficulty/dual_variant_calc/back_pay_initial_vs_alj_variants_diverge_on_benefit_award
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant, app = setup_application_in_medical_review(
            claimant_overrides={
                "ssn_last4": "1234",
                "full_name": "Initial Variant",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
            earnings_cents=4_800_000,
            attach_evidence_after=True,
        )
        # decision.created_at lands at 2026-04-15.
        set_clock("2026-04-15T00:00:00Z")
        submit_medical_decision(
            app["id"],
            expected_application_version=app["version"],
            decision_type="RFC_DISABLED",
            established_onset_date="2024-01-15T00:00:00Z",
        )
        # Fetch resulting BenefitAward.
        res = api_client.list_awards(TEST_USERS["benefits_admin_headers"],
                                     params={"application_id": app["id"]})
        awards = get_success_data(res)
        assert len(awards) == 1, "Exactly one BenefitAward created on initial approval"
        award = awards[0]
        # PRD §3.6: PIA = 196092 for this earnings profile (12 yrs * 4.8M cents → AIME 400000).
        assert award["primary_insurance_amount_cents"] == 196_092, \
            f"Expected PIA=196092, got {award['primary_insurance_amount_cents']}"
        assert award["monthly_benefit_cents"] == 196_092
        assert award["back_pay_variant"] == "INITIAL_APPROVAL"
        # entitlement_start = first day of (month_of(EOD)+5) = 2024-06-01
        # retroactive_floor = first day of (PFD - 12 months) = 2025-01-01
        # effective_start = max(2024-06-01, 2025-01-01) = 2025-01-01
        # decision_date = 2026-04-15; months_between = 15
        # back_pay = 196092 * 15 = 2_941_380
        assert award["back_pay_cents"] == 2_941_380, \
            f"Expected back_pay=2941380, got {award['back_pay_cents']}"

    def test_alj_approval_variant_uses_alj_decision_date(self, api):
        """PRD §3.6: "For the `ALJ_APPROVAL` variant — the path through
        `ALJ_PENDING` to `ALJ_APPROVED` — the closing date is the current
        server time at the moment the ALJ records the `APPROVED` outcome."
        PRD §3.6: "The same claimant with the same EOD, PFD, and PIA
        therefore typically receives a substantially larger `back_pay_cents`
        under `ALJ_APPROVAL` than under `INITIAL_APPROVAL`, because the ALJ
        path usually closes the window many months later"

        Design: Difficulty/dual_variant_calc/back_pay_initial_vs_alj_variants_diverge_on_benefit_award
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "2020",
                "full_name": "ALJ Variant",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        set_clock("2026-05-01T00:00:00Z")
        schedule_hearing(hearing["id"], "2027-12-01T00:00:00Z")
        set_clock("2027-12-15T00:00:00Z")
        # PRD §3.5: decision transitions from SCHEDULED to APPROVED/DENIED.
        # record-held is purely administrative and is NOT a precondition for decision.
        decide_hearing(hearing["id"], "APPROVED")
        # The cascade creates a BenefitAward with variant ALJ_APPROVAL.
        res = api_client.list_awards(TEST_USERS["benefits_admin_headers"],
                                     params={"application_id": ctx["application"]["id"]})
        awards = get_success_data(res)
        assert len(awards) == 1, "Exactly one BenefitAward created on ALJ approval"
        award = awards[0]
        assert award["back_pay_variant"] == "ALJ_APPROVAL", \
            f"Expected ALJ_APPROVAL variant, got {award['back_pay_variant']}"
        assert award["primary_insurance_amount_cents"] == 196_092
        # decision_date = NOW = 2027-12-15; effective_start = 2025-01-01;
        # retroactive_months = 35; back_pay = 196092 * 35 = 6_863_220.
        assert award["back_pay_cents"] == 6_863_220, \
            f"Expected back_pay=6863220, got {award['back_pay_cents']}"


# =========================================================================
# Instance: ssi_supplement_eligible_vs_resource_ineligible_variants_on_supplement_entity
# =========================================================================

class TestSsiSupplementEligibleVsResourceIneligibleVariantsOnSupplementEntity:
    """Eligible vs INELIGIBLE_RESOURCES variants of SSISupplement."""

    def test_resource_over_limit_yields_ineligible_status(self, api):
        """PRD §3.7: "If the claimant's `countable_resources_cents` is
        strictly greater than 200000 cents — the federal SSI resource
        limit of $2,000.00, applied with strict boundary precision — the
        supplement is created in `status` of `INELIGIBLE_RESOURCES`, both
        `monthly_supplement_cents` and `state_supplement_cents` are zeroed,
        and no further computation runs."

        Design: Difficulty/dual_variant_calc/ssi_supplement_eligible_vs_resource_ineligible_variants_on_supplement_entity
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "5678",
                "full_name": "Low Income",
                "date_of_birth": "1985-01-01T00:00:00Z",
                "filing_state": "CA",
                "monthly_income_cents": 0,
                "countable_resources_cents": 300_000,  # $3,000 — over limit
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
            earnings_cents=1_200_000,
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        app = ctx["application"]
        # The cascade created an SSISupplement; fetch it.
        res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                               params={"application_id": app["id"]})
        sups = get_success_data(res)
        assert len(sups) == 1, "Exactly one SSISupplement created on concurrent approval"
        sup = sups[0]
        assert sup["status"] == "INELIGIBLE_RESOURCES"
        assert sup["monthly_supplement_cents"] == 0
        assert sup["state_supplement_cents"] == 0

    def test_resource_under_limit_yields_active_status(self, api):
        """PRD §3.7: "When the application's `claim_type` is
        `CONCURRENT_SSDI_SSI`, the system creates an `SSISupplement` resource
        alongside the `BenefitAward`. The supplement's lifecycle begins at
        `ACTIVE`"
        PRD §3.7: "If the resource test passes, the federal supplement is
        computed against the 2024 Federal Benefit Rate for a single
        individual, fixed at 94300 cents ($943.00)."

        Design: Difficulty/dual_variant_calc/ssi_supplement_eligible_vs_resource_ineligible_variants_on_supplement_entity
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "5679",
                "full_name": "Low Income Pass",
                "date_of_birth": "1985-01-01T00:00:00Z",
                "filing_state": "CA",
                "monthly_income_cents": 0,
                "countable_resources_cents": 100_000,  # $1,000 — under limit
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
            earnings_cents=1_200_000,  # low PIA so SSDI doesn't fully offset FBR
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        app = ctx["application"]
        res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                               params={"application_id": app["id"]})
        sups = get_success_data(res)
        assert len(sups) == 1
        sup = sups[0]
        # With PIA=90000 and FBR=94300, the SSDI alone does NOT cover FBR,
        # so a positive federal supplement is paid → status remains ACTIVE.
        assert sup["status"] == "ACTIVE", \
            f"Expected ACTIVE for under-limit resources, got {sup['status']}"
