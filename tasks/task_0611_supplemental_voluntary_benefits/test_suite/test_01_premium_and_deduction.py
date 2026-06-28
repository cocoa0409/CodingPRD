"""Premium assessment (GI vs EOI), per-pay-period deduction conversion, and the
guaranteed-issue window boundary.

Difficulty queue A: dual_variant_calc (premium), combinatorial_formula
(deduction tier), boundary_precision_check (GI window end).
"""
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    fixtures,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / premium_gi_vs_eoi_diverge_on_enrollment
# ---------------------------------------------------------------------------
def test_premium_guaranteed_issue_no_surcharge(api):
    """PRD §3.5: "If `enrolled_at` is at or after the period's `gi_window_start`
    and strictly before its `gi_window_end`, then `gi_status` is
    `GUARANTEED_ISSUE` and `weekly_premium_cents` is exactly the product's base
    `weekly_premium_cents`."

    Design: Difficulty/dual_variant_calc/premium_gi_vs_eoi_diverge_on_enrollment
    """
    fixtures.set_clock("2026-03-15T00:00:00Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-03-15T00:00:00Z",
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 1500},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["gi_status"] == "GUARANTEED_ISSUE"
    assert data["weekly_premium_cents"] == 1200


def test_premium_evidence_required_applies_surcharge(api):
    """PRD §3.5: "Otherwise `gi_status` is `EVIDENCE_REQUIRED` and
    `weekly_premium_cents` is the product base scaled by the surcharge: take the
    base, multiply it by one plus the product's `eoi_surcharge_bps` divided by
    10000, and round the result half-up to whole cents."

    Design: Difficulty/dual_variant_calc/premium_gi_vs_eoi_diverge_on_enrollment
    """
    # 1200 * (1 + 1500/10000) = 1200 * 1.15 = 1380
    fixtures.set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-05-01T00:00:00Z",
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 1500},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["gi_status"] == "EVIDENCE_REQUIRED"
    assert data["weekly_premium_cents"] == 1380


# ---------------------------------------------------------------------------
# combinatorial_formula / deduction_tier_selection_by_pay_frequency
# ---------------------------------------------------------------------------
def test_weekly_payroll_deduction_equals_weekly_premium(api):
    """PRD §3.5: "When the employer pays weekly, the per-period deduction equals
    the weekly premium; when the employer pays monthly, the per-period deduction
    is the annual amount divided by twelve and floored, a larger per-period
    figure."

    Design: Difficulty/combinatorial_formula/deduction_tier_selection_by_pay_frequency
    """
    fixtures.set_clock("2026-03-15T00:00:00Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-03-15T00:00:00Z",
        employer_overrides={"pay_periods_per_year": 52},
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    # annual = 1200*52 = 62400; floor(62400/52) = 1200
    assert data["weekly_deduction_cents"] == 1200


def test_monthly_payroll_deduction_is_larger_floored_amount(api):
    """PRD §3.5: "multiply the frozen `weekly_premium_cents` by 52 to obtain the
    annual amount, then divide that annual amount by the employer's
    `pay_periods_per_year` and floor the quotient to whole cents (the dropped
    remainder is carried to the year's final pay period at payroll time)."

    Design: Difficulty/combinatorial_formula/deduction_tier_selection_by_pay_frequency
    """
    fixtures.set_clock("2026-03-15T00:00:00Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-03-15T00:00:00Z",
        employer_overrides={"pay_periods_per_year": 12},
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    # annual = 1200*52 = 62400; floor(62400/12) = 5200
    assert data["weekly_deduction_cents"] == 5200


# ---------------------------------------------------------------------------
# boundary_precision_check / gi_window_end_exclusive_boundary
# ---------------------------------------------------------------------------
def test_gi_window_one_second_before_end_is_guaranteed_issue(api):
    """PRD §3.3: "An enrollment whose stamped creation instant falls at or after
    `gi_window_start` and strictly before `gi_window_end` is treated as
    guaranteed issue, requiring no evidence of insurability and incurring no
    surcharge."

    Design: Difficulty/boundary_precision_check/gi_window_end_exclusive_boundary
    """
    fixtures.set_clock("2026-03-31T23:59:59Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-03-31T23:59:59Z",
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 1500},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["gi_status"] == "GUARANTEED_ISSUE"
    assert data["weekly_premium_cents"] == 1200


def test_gi_window_at_end_instant_is_evidence_required(api):
    """PRD §3.3: "An enrollment created at or after `gi_window_end` — or before
    `gi_window_start` — falls outside the window and requires evidence of
    insurability, incurring the product's surcharge."

    Design: Difficulty/boundary_precision_check/gi_window_end_exclusive_boundary
    """
    fixtures.set_clock("2026-04-01T00:00:00Z")
    _, _, _, _, enr, _ = fixtures.create_pending_enrollment(
        enrolled_at="2026-04-01T00:00:00Z",
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 1500},
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["gi_status"] == "EVIDENCE_REQUIRED"
    assert data["weekly_premium_cents"] == 1380
