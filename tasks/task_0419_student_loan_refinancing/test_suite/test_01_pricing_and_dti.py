"""Pricing (estimated/locked APR) and debt-to-income calculations.

Difficulty queue A: dual_variant_calc and combinatorial_formula (APR / DTI parts).
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    make_borrower_headers,
    make_cosigner_headers,
    setup_prequalified_application,
    setup_locked_application,
    get_application,
    get_offer,
    list_offers,
    consent_cosigner,
)


class TestDualVariantDti:
    def test_dti_borrower_only_then_with_cosigner_recompute(self, api):
        """PRD 3.2: "The estimated monthly payment is the requested principal
        multiplied by a flat amortization factor keyed on the requested term,
        rounded half up to whole cents."
        PRD 3.2: "The combined income at prequalification is just the borrower's
        annual_income_cents."
        PRD 3.3: "Consent recomputes the parent application's dti_ratio using the
        with-cosigner variant: the combined income becomes the borrower's
        annual_income_cents plus the consenting cosigner's
        cosigner_annual_income_cents, and the rest of the debt-to-income
        computation is identical"

        Borrower income 4,000,000, principal 8,000,000, term 60 (AMORT 0.0188):
        est_monthly = 150400, annual = 1,804,800; borrower-only dti = 0.4512.
        Add a CONSENTED cosigner income 2,000,000 -> denom 6,000,000 ->
        dti = 1804800/6000000 = 0.300800 -> 0.3008.

        Design: Difficulty/dual_variant_calc/dti_borrower_only_vs_with_cosigner
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 8_000_000,
                                   "requested_term_months": 60, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 2_000_000},
            cosigner_consents=False,
        )
        app_before = bundle["application"]
        assert app_before["dti_ratio"] == pytest.approx(0.4512, abs=1e-9), (
            f"borrower-only dti should be 0.4512, got {app_before['dti_ratio']}"
        )

        consent_cosigner(bundle["cosigner"])
        app_after = get_application(app_before["id"])
        assert app_after["dti_ratio"] == pytest.approx(0.3008, abs=1e-9), (
            f"with-cosigner dti should be 0.3008, got {app_after['dti_ratio']}"
        )

    def test_cosigner_consent_lowers_dti_below_borrower_only(self, api):
        """PRD 3.3: "Because the denominator grows, the ratio falls, which can
        flip an otherwise-failing application to within limit at the boundary."

        Design: Difficulty/dual_variant_calc/dti_borrower_only_vs_with_cosigner
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 8_000_000,
                                   "requested_term_months": 60, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 2_000_000},
            cosigner_consents=False,
        )
        borrower_only = bundle["application"]["dti_ratio"]
        consent_cosigner(bundle["cosigner"])
        with_cosigner = get_application(bundle["application"]["id"])["dti_ratio"]
        assert with_cosigner < borrower_only, (
            f"with-cosigner dti {with_cosigner} must be below borrower-only {borrower_only}"
        )
        assert with_cosigner == pytest.approx(0.3008, abs=1e-9)


class TestEstimatedVsLockedApr:
    def test_estimated_and_locked_apr_diverge_with_autopay(self, api):
        """PRD 3.2: "Each offer's estimated_apr_bps is computed as the prequal
        estimate: the grid cell's base_apr_bps, plus the cell's index_apr_bps if
        the offer's rate type is VARIABLE (otherwise zero), plus a band surcharge
        keyed on the application's soft_pull_fico_band."
        PRD 3.4: "first subtract the autopay discount of 25 basis points if and
        only if autopay_elected is true, then from that running value subtract
        the member-tier discount keyed on the borrower's member_tier"

        FIXED base 650, soft pull NEAR_PRIME surcharge 150 -> estimated 800.
        Autopay on, member NONE -> locked 800 - 25 - 0 = 775.

        Design: Difficulty/dual_variant_calc/estimated_apr_vs_locked_apr_offer
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        offer = bundle["offers"][0]
        assert offer["estimated_apr_bps"] == 800, (
            f"estimated_apr_bps should be 800, got {offer['estimated_apr_bps']}"
        )

        borrower = bundle["borrower"]
        app = bundle["application"]
        headers = make_borrower_headers(borrower["id"])
        locked = validate_success(api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": True},
            headers))
        assert locked["locked_apr_bps"] == 775, (
            f"locked_apr_bps should be 775 (800 - 25 autopay), got {locked['locked_apr_bps']}"
        )

    def test_locked_apr_not_equal_estimated_apr(self, api):
        """PRD 3.4: "On a successful lock, the offer's final locked_apr_bps is
        computed from the offer's estimated_apr_bps in a pinned order"

        Design: Difficulty/dual_variant_calc/estimated_apr_vs_locked_apr_offer
        """
        bundle = setup_locked_application(
            autopay_elected=True,
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        offer = get_offer(bundle["locked_offer"]["id"])
        assert offer["estimated_apr_bps"] == 800
        assert offer["locked_apr_bps"] == 775
        assert offer["estimated_apr_bps"] != offer["locked_apr_bps"]


class TestLockedAprFloorClamp:
    def test_floor_clamp_lifts_locked_apr_to_floor(self, api):
        """PRD 3.4: "The result is finally clamped so it never falls below the
        APR floor of 200 basis points; the floor is applied last, after both
        discounts."

        FIXED base 150, soft pull PRIME surcharge 50 -> estimated 200.
        Autopay on, member NONE -> 200 - 25 - 0 = 175, clamped UP to floor 200.

        Design: Difficulty/combinatorial_formula/locked_apr_nested_discount_floor_clamp_mode_a
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "PRIME",
                            "base_apr_bps": 150, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "SUPER_PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        offer = bundle["offers"][0]
        assert offer["estimated_apr_bps"] == 200, (
            f"estimated should be 200 (150 base + 50 PRIME surcharge), got {offer['estimated_apr_bps']}"
        )
        borrower = bundle["borrower"]
        app = bundle["application"]
        headers = make_borrower_headers(borrower["id"])
        locked = validate_success(api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": True},
            headers))
        assert locked["locked_apr_bps"] == 200, (
            f"175 after autopay must clamp UP to floor 200, got {locked['locked_apr_bps']}"
        )

    def test_locked_apr_never_below_floor(self, api):
        """PRD 3.4: "The result is finally clamped so it never falls below the
        APR floor of 200 basis points; the floor is applied last, after both
        discounts."

        Design: Difficulty/combinatorial_formula/locked_apr_nested_discount_floor_clamp_mode_a
        """
        bundle = setup_locked_application(
            autopay_elected=True,
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "PRIME",
                            "base_apr_bps": 150, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "SUPER_PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        offer = get_offer(bundle["locked_offer"]["id"])
        assert offer["locked_apr_bps"] >= 200, (
            f"locked_apr_bps must never be below floor 200, got {offer['locked_apr_bps']}"
        )
        assert offer["locked_apr_bps"] == 200
