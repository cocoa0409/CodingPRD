"""Filing-fee calculation: variant divergence and tier boundaries (PRD 3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    compute_filing_fee_cents,
    get_case,
    make_landlord_headers,
    prepare_package,
    setup_case_filed,
    setup_case_notice_expired,
    setup_two_cases_notice_expired,
    validate_success,
)
from test_helpers import api_client


class TestFilingFeeStandardVsElectronic:
    """Depth instance: the STANDARD/ELECTRONIC variant alone diverges the fee."""

    def test_identical_inputs_diverge_by_variant_1750(self, api):
        """PRD 3.3: "The variant then adjusts the total: a paper filing adds
        a 750-cent counter-service surcharge, while an electronic filing
        subtracts a 1000-cent e-filing discount".

        Design: Difficulty/dual_variant_calc/filing_fee_standard_vs_electronic
        """
        ctx_a, ctx_b = setup_two_cases_notice_expired("CA")
        ll = make_landlord_headers(ctx_a["landlord"]["id"])

        resp_a = api.create_filing_package(
            ctx_a["case"]["id"],
            {"claimed_amount_cents": 200000,
             "defendant_names": ["Dee One", "Dee Two"],
             "jury_demanded": False, "efiled": False},
            ll,
        )
        pkg_a = validate_success(resp_a, 201)
        resp_b = api.create_filing_package(
            ctx_b["case"]["id"],
            {"claimed_amount_cents": 200000,
             "defendant_names": ["Dee One", "Dee Two"],
             "jury_demanded": False, "efiled": True},
            ll,
        )
        pkg_b = validate_success(resp_b, 201)

        # CA tier: 200000 <= 250000 -> base 24000; 2 defendants * 2500 = 5000.
        assert pkg_a["filing_fee_cents"] == 29750, (
            "CA base 24000 + 2*2500 defendants + STANDARD 750")
        assert pkg_b["filing_fee_cents"] == 28000, (
            "CA base 24000 + 2*2500 defendants - ELECTRONIC 1000")
        assert pkg_a["filing_fee_cents"] - pkg_b["filing_fee_cents"] == 1750

    def test_variant_fee_frozen_at_creation(self, api):
        """PRD 3.3: "The court fee is computed once at creation and frozen on
        the package as filing_fee_cents, immutable thereafter."

        Design: Difficulty/dual_variant_calc/filing_fee_standard_vs_electronic
        """
        ctx = setup_case_notice_expired("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        expected = compute_filing_fee_cents("CA", 100000, ["Dee A"], False, True)
        resp = api.create_filing_package(
            ctx["case"]["id"],
            {"claimed_amount_cents": 100000, "defendant_names": ["Dee A"],
             "jury_demanded": False, "efiled": True},
            ll,
        )
        pkg = validate_success(resp, 201)
        # PRD 3.3: CA base 24000 (100000 <= 250000) + 1 defendant x 2500
        # - 1000 ELECTRONIC discount = 25500.
        assert pkg["filing_fee_cents"] == expected == 25500

        # A later read returns the identical frozen figure.
        reread = validate_success(api.get_filing_package(pkg["id"], ll), 200)
        assert reread["filing_fee_cents"] == 25500


class TestFilingFeeTierBoundaryAndSurcharges:
    """Depth instance: tier ceilings use <=; surcharges and jury fee compose."""

    def test_claim_at_tier_ceiling_prices_at_that_tier(self, api):
        """PRD 3.3: "a claim exactly at a tier ceiling prices at that tier: in
        CA, a claim of 250000 cents or less prices at a 24000-cent base".

        Design: Difficulty/combinatorial_formula/filing_fee_tier_boundary_and_surcharges
        """
        ctx_a, ctx_b = setup_two_cases_notice_expired("CA")
        ll = make_landlord_headers(ctx_a["landlord"]["id"])

        resp_a = api.create_filing_package(
            ctx_a["case"]["id"],
            {"claimed_amount_cents": 250000, "defendant_names": ["Dee One"],
             "jury_demanded": True, "efiled": False},
            ll,
        )
        fee_a = validate_success(resp_a, 201)["filing_fee_cents"]
        resp_b = api.create_filing_package(
            ctx_b["case"]["id"],
            {"claimed_amount_cents": 250001, "defendant_names": ["Dee One"],
             "jury_demanded": True, "efiled": False},
            ll,
        )
        fee_b = validate_success(resp_b, 201)["filing_fee_cents"]

        assert fee_a == 42250, "24000 + 2500 defendant + 15000 jury + 750 STANDARD"
        assert fee_b == 50250, "one cent over the ceiling jumps to the 32000 tier"

    def test_jury_and_defendant_surcharge_compose(self, api):
        """PRD 3.3: "A surcharge of 2500 cents is added for each named
        defendant, and a flat 15000 cents is added when a jury is demanded."

        Design: Difficulty/combinatorial_formula/filing_fee_tier_boundary_and_surcharges
        """
        ctx = setup_case_notice_expired("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])

        # No jury, one defendant: 24000 + 2500 + 750 = 27250.
        pkg1 = validate_success(api.create_filing_package(
            ctx["case"]["id"],
            {"claimed_amount_cents": 100000, "defendant_names": ["Dee A"],
             "jury_demanded": False, "efiled": False}, ll), 201)
        assert pkg1["filing_fee_cents"] == 27250

        # The package may be superseded by filing again on the same case only
        # after rejection; instead verify composition on a second case.
        ctx2 = setup_case_notice_expired("CA")
        ll2 = make_landlord_headers(ctx2["landlord"]["id"])
        pkg2 = validate_success(api.create_filing_package(
            ctx2["case"]["id"],
            {"claimed_amount_cents": 100000,
             "defendant_names": ["D1", "D2", "D3"],
             "jury_demanded": True, "efiled": False}, ll2), 201)
        # 24000 + 3*2500 + 15000 + 750 = 47250.
        assert pkg2["filing_fee_cents"] == 47250
