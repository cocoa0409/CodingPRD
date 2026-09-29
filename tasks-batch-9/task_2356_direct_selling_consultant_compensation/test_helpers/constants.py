"""Domain constants for the Direct Selling Consultant Compensation API.

Every literal here is stated in PRD.md: plan policy defaults (PRD §3.1), the
default rank ladder (PRD §3.1), the logical clock's pre-set value (PRD §2.5),
the pagination bounds (PRD §2.3) and the enrollment agreement default (PRD §3.2).
"""

API_PREFIX = "/direct-selling"

# PRD §2.5 — "Before it is ever set, the clock reads 2026-08-01T00:00:00Z."
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.2 — the optional agreement_version defaults to AGR-2026-01.
DEFAULT_AGREEMENT_VERSION = "AGR-2026-01"

# PRD §2.3 — limit defaults to 10, minimum 1, maximum 100; offset defaults to 0.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

# PRD §3.1 — every plan policy field and its default.
PLAN_DEFAULTS = {
    "compression_mode": "DYNAMIC",
    "point_value_cents": 100,
    "payline_min_pv_points": 200,
    "pv_bonus_min_points": 100,
    "active_leg_min_points": 300,
    "senior_rank_bump_bp": 200,
    "pv_bonus_cap_cents": 50_000,
    "probation_keep_bp": 5_000,
    "withhold_tier_threshold_cents": 20_000,
    "withhold_low_bp": 1_000,
    "withhold_high_bp": 2_500,
    "min_payout_cents": 2_500,
    "consecutive_qualifying_periods": 2,
    "maintenance_grace_periods": 1,
    "seventy_rule_bp": 7_000,
    "buyback_rate_bp": 9_000,
    "buyback_window_days": 365,
    "restock_fee_bp": 500,
    "restock_free_limit_cents": 45_000,
    "sanction_cooloff_days": 30,
    "appeal_window_days": 14,
    "reinstatement_window_days": 180,
    "max_identity_attempts": 2,
    "flat_shipping_cents": 995,
    "free_shipping_threshold_cents": 25_000,
}

# PRD §3.1 — the default pv_bonus_bands ladder.
PV_BONUS_BANDS_DEFAULT = [
    {"upper_points": 500, "rate_bp": 500},
    {"upper_points": 1_500, "rate_bp": 900},
    {"upper_points": None, "rate_bp": 1_300},
]

# PRD §3.1 — the default four-rung rank ladder.
RANK_LADDER_DEFAULT = [
    {
        "rank_code": "CONSULTANT",
        "rank_order": 1,
        "required_pv_points": 0,
        "required_gv_points": 0,
        "required_active_legs": 0,
        "override_levels": 0,
        "override_bp_by_level": [],
    },
    {
        "rank_code": "SENIOR_CONSULTANT",
        "rank_order": 2,
        "required_pv_points": 300,
        "required_gv_points": 1_200,
        "required_active_legs": 1,
        "override_levels": 1,
        "override_bp_by_level": [500],
    },
    {
        "rank_code": "DIRECTOR",
        "rank_order": 3,
        "required_pv_points": 500,
        "required_gv_points": 3_000,
        "required_active_legs": 1,
        "override_levels": 3,
        "override_bp_by_level": [800, 400, 200],
    },
    {
        "rank_code": "EXECUTIVE_DIRECTOR",
        "rank_order": 4,
        "required_pv_points": 800,
        "required_gv_points": 10_000,
        "required_active_legs": 3,
        "override_levels": 5,
        "override_bp_by_level": [900, 500, 300, 200, 100],
    },
]

# PRD §3.9 — the four distribution bands, in order.
DISTRIBUTION_BUCKET_BOUNDS = [
    {"lower_cents": 0, "upper_cents": 0},
    {"lower_cents": 1, "upper_cents": 9_999},
    {"lower_cents": 10_000, "upper_cents": 49_999},
    {"lower_cents": 50_000, "upper_cents": None},
]

# PRD §3.7 — the disciplinary ladder positions.
SANCTION_LADDER = {"WARNING": 1, "PROBATION": 2, "SUSPENSION": 3, "TERMINATION": 4}

# Tax jurisdictions used by the suite. PRD §3.1 derives tax_basis_mode and
# remitter from facilitator_agreement_active.
JURISDICTION_TX = {"state_code": "TX", "tax_rate_bp": 825, "facilitator_agreement_active": True}
JURISDICTION_NV = {"state_code": "NV", "tax_rate_bp": 685, "facilitator_agreement_active": False}

# Catalogue products used by the suite.
PRODUCT_KIT = {
    "sku": "KIT-STD",
    "name": "Standard Starter Kit",
    "wholesale_price_cents": 9_900,
    "srp_cents": 14_900,
    "volume_points_per_unit": 0,
    "is_starter_kit": True,
}
PRODUCT_SERUM = {
    "sku": "SERUM",
    "name": "Renewal Serum",
    "wholesale_price_cents": 2_000,
    "srp_cents": 4_000,
    "volume_points_per_unit": 20,
}
PRODUCT_SAMPLE = {
    "sku": "SAMPLE",
    "name": "Sample Sachet Pack",
    "wholesale_price_cents": 100,
    "srp_cents": 200,
    "volume_points_per_unit": 1,
    "buyback_eligible": False,
}
PRODUCT_CATALOG = {
    "sku": "CATALOG",
    "name": "Printed Catalogue",
    "wholesale_price_cents": 100,
    "srp_cents": 200,
    "volume_points_per_unit": 0,
    "commissionable": False,
}
PRODUCT_SACHET = {
    "sku": "SACHET",
    "name": "Single Sachet",
    "wholesale_price_cents": 100,
    "srp_cents": 200,
    "volume_points_per_unit": 1,
}

# Period windows. PRD §3.4 — period_start is inclusive, period_end exclusive.
PERIOD_2026_07 = {
    "period_code": "2026-07",
    "period_start": "2026-07-01T00:00:00Z",
    "period_end": "2026-08-01T00:00:00Z",
}
PERIOD_2026_08 = {
    "period_code": "2026-08",
    "period_start": "2026-08-01T00:00:00Z",
    "period_end": "2026-09-01T00:00:00Z",
}

# Opaque operator identifiers (PRD §2.1) used consistently by the suite so that
# the segregation-of-duties checks of PRD §2.11 can be exercised deliberately.
ANALYST_USER_ID = "ANALYST-1"
CONTROLLER_USER_ID = "FC-1"
COMPLIANCE_USER_ID = "CO-1"
COMPLIANCE_USER_ID_2 = "CO-2"
LEGAL_USER_ID = "LEGAL-1"
ADMIN_USER_ID = "ADMIN-1"


def round_half_up(numerator: int, denominator: int) -> int:
    """PRD §2.6 rounding: exact rational rounded to nearest whole cent, halves away from zero."""
    if denominator == 0:
        raise ZeroDivisionError("denominator must be non-zero")
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    n, d = abs(numerator), abs(denominator)
    return sign * ((2 * n + d) // (2 * d))


def apply_rate_bp(amount_cents: int, rate_bp: int) -> int:
    """PRD §2.6 — multiply by the rate in basis points, divide by 10,000, round half up."""
    return round_half_up(amount_cents * rate_bp, 10_000)


def expected_kit_tax_cents(product: dict, jurisdiction: dict) -> int:
    """PRD §3.2 — the taxable basis is srp_cents under a facilitator agreement, wholesale otherwise."""
    basis = (
        product["srp_cents"]
        if jurisdiction["facilitator_agreement_active"]
        else product["wholesale_price_cents"]
    )
    return apply_rate_bp(basis, jurisdiction["tax_rate_bp"])


def expected_kit_total_cents(product: dict, jurisdiction: dict) -> int:
    """PRD §3.2 — kit_total_cents is kit_charge_cents plus kit_tax_cents."""
    return product["wholesale_price_cents"] + expected_kit_tax_cents(product, jurisdiction)


def expected_order_total_cents(lines, jurisdiction: dict, plan=None) -> int:
    """PRD §3.3 — per-line tax rounded on the line, plus flat shipping below the free threshold.

    `lines` is a sequence of (product_dict, quantity) pairs.
    """
    plan = plan or PLAN_DEFAULTS
    merchandise = sum(p["wholesale_price_cents"] * q for p, q in lines)
    tax = 0
    for product, quantity in lines:
        if jurisdiction["facilitator_agreement_active"]:
            basis = product["srp_cents"] * quantity
        else:
            basis = product["wholesale_price_cents"] * quantity
        tax += apply_rate_bp(basis, jurisdiction["tax_rate_bp"])
    threshold = plan.get("free_shipping_threshold_cents", PLAN_DEFAULTS["free_shipping_threshold_cents"])
    flat = plan.get("flat_shipping_cents", PLAN_DEFAULTS["flat_shipping_cents"])
    shipping = flat if merchandise < threshold else 0
    return merchandise + tax + shipping
