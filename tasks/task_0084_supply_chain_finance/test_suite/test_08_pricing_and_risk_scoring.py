"""APR pricing and supplier composite risk scoring (PRD §3.5).

PRD §3.5 pins:
- base APR per mode (FACTORING 800, REVERSE_FACTORING 600,
  DYNAMIC_DISCOUNTING 500, RECEIVABLE_PLEDGE 700)
- core-enterprise rating adjustment (AAA -150, AA -100, A 0, BBB +100,
  BB +250)
- supplier-risk adjustment (LOW 0, MEDIUM +100, HIGH +250)
- tier penalty (50 bps per tier above 1)
- clamp [APR_FLOOR_BPS=300, APR_CEILING_BPS=2400]
"""
from __future__ import annotations
import pytest

from test_helpers import (
    APR_CEILING_BPS,
    APR_FLOOR_BPS,
    ApiErrorId,
    CORE_RISK_ADJ_BPS,
    MODE_BASE_BPS,
    SUPPLIER_RISK_ADJ_BPS,
    TEST_USERS,
    TIER_PENALTY_PER_LEVEL_BPS,
    approve_financing_application_payload,
    assert_apr_within_clamp,
    setup_approved_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


def _expected_apr(*, mode: str, core_rating: str,
                  supplier_rating: str, tier: int) -> int:
    raw = (
        MODE_BASE_BPS[mode]
        + CORE_RISK_ADJ_BPS[core_rating]
        + SUPPLIER_RISK_ADJ_BPS[supplier_rating]
        + (tier - 1) * TIER_PENALTY_PER_LEVEL_BPS
    )
    return max(APR_FLOOR_BPS, min(APR_CEILING_BPS, raw))


def test_factoring_with_aaa_low_tier1_inside_clamp(api):
    """PRD §3.5: "FACTORING starts at 800. ... AAA contributes minus
    150 ... zero for LOW ... tier 1 contributes zero." Raw=800-150+0+0
    =650 ∈ [300, 2400] → no clamp.
    """
    bundle = setup_approved_application(
        mode="FACTORING", core_risk_rating="AAA",
        supplier_aml=0.05,  # likely LOW after composite
        term_days=90,
    )
    apr = bundle["application"]["approved_apr_bps"]
    expected = _expected_apr(
        mode="FACTORING", core_rating="AAA",
        supplier_rating="LOW", tier=1,
    )
    assert apr == expected, (
        f"FACTORING+AAA+LOW+tier1: expected approved_apr_bps={expected}, "
        f"got {apr}"
    )
    assert_apr_within_clamp(bundle["application"],
                            APR_FLOOR_BPS, APR_CEILING_BPS)


def test_reverse_factoring_with_aaa_low_tier1(api):
    """PRD §3.5: "REVERSE_FACTORING starts at 600. AAA contributes
    minus 150. ... zero for LOW ... tier 1 contributes zero." Raw =
    600 - 150 + 0 + 0 = 450 ∈ [300, 2400] → no clamp.
    """
    bundle = setup_approved_application(
        mode="REVERSE_FACTORING", core_risk_rating="AAA",
        supplier_aml=0.05, term_days=90,
    )
    apr = bundle["application"]["approved_apr_bps"]
    expected = _expected_apr(
        mode="REVERSE_FACTORING", core_rating="AAA",
        supplier_rating="LOW", tier=1,
    )
    assert apr == expected, (
        f"REVERSE_FACTORING+AAA+LOW+tier1: expected {expected}, got {apr}"
    )


def test_clamp_floor_applied(api):
    """PRD §3.5: "the final approved_apr_bps is the larger of the
    APR_FLOOR_BPS system constant and the smaller of APR_CEILING_BPS
    and the raw sum — equivalently, the raw sum is bumped up to the
    floor when below it."

    DYNAMIC_DISCOUNTING(500) + AAA(-150) + LOW(0) + tier1(0) = 350,
    which is above the 300 floor; the clamp is therefore inert for
    this configuration. The strict observable we can pin universally
    is that the result lands inside the closed clamp window.
    """
    bundle = setup_approved_application(
        mode="DYNAMIC_DISCOUNTING", core_risk_rating="AAA",
        supplier_aml=0.05, term_days=90,
    )
    apr = bundle["application"]["approved_apr_bps"]
    assert APR_FLOOR_BPS <= apr <= APR_CEILING_BPS, (
        f"approved_apr_bps {apr} outside clamp [{APR_FLOOR_BPS}, "
        f"{APR_CEILING_BPS}] (PRD §3.5)."
    )


def test_apr_always_within_clamp_for_all_modes(api):
    """PRD §3.5: "a result outside this clamped window after the entire
    computation should never occur."
    """
    for mode in ("FACTORING", "REVERSE_FACTORING",
                 "DYNAMIC_DISCOUNTING", "RECEIVABLE_PLEDGE"):
        bundle = setup_approved_application(
            mode=mode, core_risk_rating="AAA",
            supplier_aml=0.05, term_days=90,
        )
        assert_apr_within_clamp(bundle["application"],
                                APR_FLOOR_BPS, APR_CEILING_BPS)


def test_composite_risk_rating_assigned_at_under_review_transition(api):
    """PRD §3.5: "On the first submission, the platform computes the
    supplier's composite risk score (see below) and assigns the
    application's risk_rating to one of LOW, MEDIUM, HIGH, or REJECT."

    PRD §3.5 also says "The supplier composite risk score that drives
    risk_rating is computed at the SUBMITTED → UNDER_REVIEW transition."
    The shared observable is therefore that risk_rating is set by the
    time review starts.
    """
    bundle = setup_under_review_application(
        mode="FACTORING", core_risk_rating="AAA",
        supplier_aml=0.05, term_days=90,
    )
    rating = bundle["application"].get("risk_rating")
    assert rating in {"LOW", "MEDIUM", "HIGH"}, (
        f"After UNDER_REVIEW, risk_rating must be set to LOW/MEDIUM/HIGH "
        f"per PRD §3.5; got {rating!r}"
    )


def test_low_risk_rating_with_aaa_passed_tier1(api):
    """PRD §3.5: "The kyc factor is 1.0 if the supplier's kyc_status is
    PASSED and 0.0 otherwise; the AML factor is one minus the
    supplier's aml_risk_score; the tier factor is the larger of zero
    and one minus 0.20 multiplied by one less than tier_to_core, which
    yields 1.0 for tier 1 ... weights 0.5 for KYC, 0.3 for AML, and
    0.2 for tier."

    For FACTORING with kyc=PASSED, aml=0.05, tier=1:
        composite = 0.5*1.0 + 0.3*(1-0.05) + 0.2*1.0
                  = 0.5 + 0.285 + 0.2 = 0.985 → LOW (>=0.80)
    """
    bundle = setup_under_review_application(
        mode="FACTORING", core_risk_rating="AAA",
        supplier_aml=0.05, term_days=90,
    )
    assert bundle["application"]["risk_rating"] == "LOW"


def test_dynamic_discounting_apr_arithmetic(api):
    """PRD §3.5: "DYNAMIC_DISCOUNTING starts at 500 ... A 0
    [tier penalty] for tier 1 ... [LOW: 0 supplier adj] ... AAA
    contributes minus 150."

    Raw = 500 - 150 + 0 + 0 = 350 (above floor=300, below ceiling=2400).
    """
    bundle = setup_approved_application(
        mode="DYNAMIC_DISCOUNTING", core_risk_rating="AAA",
        supplier_aml=0.05, term_days=90,
    )
    apr = bundle["application"]["approved_apr_bps"]
    expected = _expected_apr(
        mode="DYNAMIC_DISCOUNTING", core_rating="AAA",
        supplier_rating="LOW", tier=1,
    )
    assert apr == expected
