"""Compensation plan defaults and rank-ladder helpers (PRD section 3.1)."""

DEFAULT_PV_BONUS_BANDS = [
    {"upper_points": 500, "rate_bp": 500},
    {"upper_points": 1500, "rate_bp": 900},
    {"upper_points": None, "rate_bp": 1300},
]

DEFAULT_RANK_LADDER = [
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
        "required_gv_points": 1200,
        "required_active_legs": 1,
        "override_levels": 1,
        "override_bp_by_level": [500],
    },
    {
        "rank_code": "DIRECTOR",
        "rank_order": 3,
        "required_pv_points": 500,
        "required_gv_points": 3000,
        "required_active_legs": 1,
        "override_levels": 3,
        "override_bp_by_level": [800, 400, 200],
    },
    {
        "rank_code": "EXECUTIVE_DIRECTOR",
        "rank_order": 4,
        "required_pv_points": 800,
        "required_gv_points": 10000,
        "required_active_legs": 3,
        "override_levels": 5,
        "override_bp_by_level": [900, 500, 300, 200, 100],
    },
]

COMPRESSION_MODES = ("DYNAMIC", "STATIC")

MUTABLE_PLAN_FIELDS = (
    "compression_mode",
    "payline_min_pv_points",
    "min_payout_cents",
    "seventy_rule_bp",
    "restock_free_limit_cents",
    "restock_fee_bp",
    "probation_keep_bp",
    "withhold_tier_threshold_cents",
    "pv_bonus_cap_cents",
    "sanction_cooloff_days",
    "appeal_window_days",
    "reinstatement_window_days",
)

# name -> (default, minimum, maximum)
NUMERIC_PLAN_FIELDS = {
    "point_value_cents": (100, 1, None),
    "payline_min_pv_points": (200, 0, None),
    "pv_bonus_min_points": (100, 0, None),
    "active_leg_min_points": (300, 0, None),
    "pv_bonus_cap_cents": (50000, 0, None),
    "senior_rank_bump_bp": (200, 0, 10000),
    "probation_keep_bp": (5000, 0, 10000),
    "withhold_tier_threshold_cents": (20000, 0, None),
    "withhold_low_bp": (1000, 0, 10000),
    "withhold_high_bp": (2500, 0, 10000),
    "min_payout_cents": (2500, 0, None),
    "consecutive_qualifying_periods": (2, 0, None),
    "maintenance_grace_periods": (1, 0, None),
    "seventy_rule_bp": (7000, 0, 10000),
    "buyback_rate_bp": (9000, 0, 10000),
    "buyback_window_days": (365, 0, None),
    "restock_free_limit_cents": (45000, 0, None),
    "restock_fee_bp": (500, 0, 10000),
    "sanction_cooloff_days": (30, 0, None),
    "appeal_window_days": (14, 0, None),
    "reinstatement_window_days": (180, 0, None),
    "max_identity_attempts": (2, 0, None),
    "free_shipping_threshold_cents": (25000, 0, None),
    "flat_shipping_cents": (995, 0, None),
}

# Field emission order for the plan representation.
PLAN_FIELD_ORDER = (
    "plan_code",
    "name",
    "compression_mode",
    "point_value_cents",
    "payline_min_pv_points",
    "pv_bonus_min_points",
    "active_leg_min_points",
    "pv_bonus_bands",
    "pv_bonus_cap_cents",
    "senior_rank_bump_bp",
    "probation_keep_bp",
    "withhold_tier_threshold_cents",
    "withhold_low_bp",
    "withhold_high_bp",
    "min_payout_cents",
    "consecutive_qualifying_periods",
    "maintenance_grace_periods",
    "seventy_rule_bp",
    "buyback_rate_bp",
    "buyback_window_days",
    "restock_free_limit_cents",
    "restock_fee_bp",
    "sanction_cooloff_days",
    "appeal_window_days",
    "reinstatement_window_days",
    "max_identity_attempts",
    "free_shipping_threshold_cents",
    "flat_shipping_cents",
    "rank_ladder",
    "consultant_count",
)


def rung_by_order(plan, rank_order):
    for rung in plan["rank_ladder"]:
        if rung["rank_order"] == rank_order:
            return rung
    return None


def rung_by_code(plan, rank_code):
    for rung in plan["rank_ladder"]:
        if rung["rank_code"] == rank_code:
            return rung
    return None


def base_rung(plan):
    return rung_by_order(plan, 1)


def max_rank_order(plan):
    return max(rung["rank_order"] for rung in plan["rank_ladder"])
