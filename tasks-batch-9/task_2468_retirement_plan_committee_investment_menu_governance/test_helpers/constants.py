"""Numeric constants, defaults and derived-value helpers stated by the PRD.

Every literal here is quoted from the PRD prose; the helpers re-implement the
PRD's arithmetic (half-up rounding, floors, clamps) so tests can express an
expectation as a formula instead of a magic number where that is clearer.
"""

from decimal import ROUND_HALF_UP, Decimal

# --------------------------------------------------------------------------
# The two clocks (PRD §2.4)
# --------------------------------------------------------------------------

#: "Before any call to this endpoint the logical clock reads exactly
#: 2026-08-01T00:00:00Z; the server never falls back to real wall-clock time."
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

#: A brand-new plan starts at fiscal quarter 0.
INITIAL_FISCAL_QUARTER_INDEX = 0

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0

# --------------------------------------------------------------------------
# Plan registration defaults and domains (PRD §3.1)
# --------------------------------------------------------------------------

DEFAULT_QUORUM_MIN_VOTING_MEMBERS = 3
QUORUM_MIN_VOTING_MEMBERS_RANGE = (2, 9)
DEFAULT_VOTING_THRESHOLD_PCT = 0.6000
VOTING_THRESHOLD_PCT_RANGE = (0.5000, 1.0000)
DEFAULT_MAX_VOTING_SEATS = 7
MAX_VOTING_SEATS_RANGE = (2, 11)
DEFAULT_NOTICE_LEAD_DAYS_REQUIRED = 30
DEFAULT_BLACKOUT_BUFFER_DAYS = 3
MENU_SLOT_CAPACITY_RANGE = (3, 40)
MIN_PARTICIPANT_ACCOUNT_COUNT = 1

#: A charter needs at least this many non-retired voting seats.
MIN_VOTING_SEATS_FOR_CHARTER = 2

# --------------------------------------------------------------------------
# Fiduciary training (PRD §3.2)
# --------------------------------------------------------------------------

DEFAULT_VALIDITY_QUARTERS = 8
VALIDITY_QUARTERS_RANGE = (1, 20)
#: "score_pct must be present and at least 80"
TRAINING_PASSING_SCORE_PCT = 80.00
#: A waiver basis long enough to satisfy both stated floors (8 and 12).
MIN_WAIVER_BASIS_LENGTH = 12

# --------------------------------------------------------------------------
# Policy statement defaults (PRD §3.3)
# --------------------------------------------------------------------------

DEFAULT_WATCH_TRIGGER_SCORE_MAX = 40.00
DEFAULT_REMEDIATION_TRIGGER_SCORE_MAX = 25.00
DEFAULT_CURE_MARGIN_POINTS = 10.00
DEFAULT_EXPENSE_PEER_MULTIPLE = 1.25
DEFAULT_MIN_TRACK_RECORD_QUARTERS = 12
DEFAULT_STYLE_DRIFT_R2_FLOOR = 0.8000
DEFAULT_WATCH_GRACE_QUARTERS = 2
WATCH_GRACE_QUARTERS_RANGE = (1, 8)

#: The five composite weights must sum to exactly 1.00, in this key order.
WEIGHT_KEYS = ("performance", "peer", "expense", "style", "manager")

# --------------------------------------------------------------------------
# Menu posture ladder (PRD §2.9)
# --------------------------------------------------------------------------

#: at_risk_slot_ratio at or above this relaxes no further than RESTRICTED.
POSTURE_RESTRICTED_RATIO = 0.2500
#: at_risk_slot_ratio at or above this is FROZEN.
POSTURE_FROZEN_RATIO = 0.5000

# --------------------------------------------------------------------------
# Composite score (PRD §3.5)
# --------------------------------------------------------------------------

TRAILING_3Y_WEIGHT = Decimal("0.6")
TRAILING_5Y_WEIGHT = Decimal("0.4")
PERFORMANCE_COMPONENT_BASE = Decimal("50.00")
#: Every basis point of net expense above the peer median costs this much.
EXPENSE_PENALTY_PER_BP = Decimal("2")
#: Points lost per unit of style-drift shortfall below the floor.
STYLE_PENALTY_PER_UNIT = Decimal("500")
MANAGER_CHANGE_CAP = Decimal("40.00")
MANAGER_TENURE_MULTIPLIER_ON_CHANGE = Decimal("2")
MANAGER_BASE_NO_CHANGE = Decimal("40.00")
MANAGER_TENURE_MULTIPLIER_NO_CHANGE = Decimal("3")

# --------------------------------------------------------------------------
# Notice lead time (PRD §3.7)
# --------------------------------------------------------------------------

NOTICE_SURCHARGE_REENROLLMENT_DAYS = 30
NOTICE_SURCHARGE_QDIA_ERISA_DAYS = 30
NOTICE_SURCHARGE_MAP_TO_QDIA_NON_QDIA_DAYS = 15

# --------------------------------------------------------------------------
# Glidepath fit (PRD §3.8)
# --------------------------------------------------------------------------

GLIDEPATH_REFERENCE = {
    "TO_RETIREMENT": {"equity_at_65_pct": Decimal("35.0"), "landing_point_age": 65},
    "THROUGH_RETIREMENT": {"equity_at_65_pct": Decimal("50.0"), "landing_point_age": 80},
}
GLIDEPATH_COST_ALLOWANCE_BPS = {"CUSTOM": 45, "OFF_THE_SHELF": 30}
GLIDEPATH_EQUITY_GAP_PENALTY = Decimal("1.5")
GLIDEPATH_LANDING_GAP_PENALTY = Decimal("2.0")
#: A qualifying target-date candidate needs at least this much track record.
QDIA_MIN_TRACK_RECORD_QUARTERS = 12

# --------------------------------------------------------------------------
# Provider oversight (PRD §3.9)
# --------------------------------------------------------------------------

#: gross_cost_bps <= 25.00 is TIER_A, <= 45.00 is TIER_B, above is TIER_C.
TIER_A_MAX_GROSS_COST_BPS = Decimal("25.00")
TIER_B_MAX_GROSS_COST_BPS = Decimal("45.00")
TIER_OFFSET_BPS = {
    "TIER_A": Decimal("0.00"),
    "TIER_B": Decimal("5.00"),
    "TIER_C": Decimal("12.00"),
}
RFP_BENCHMARK_PERCENTILE_TRIGGER = Decimal("75.00")
RFP_QUARTER_GAP_TRIGGER = 20
RFP_TOTAL_COST_BPS_TRIGGER = Decimal("60.00")
ASSET_BASED_BPS_RANGE = (0, 200)
BENCHMARK_PERCENTILE_RANGE = (1, 100)

# --------------------------------------------------------------------------
# Field domains shared by funds and scorecards (PRD §3.3, §3.5)
# --------------------------------------------------------------------------

EXPENSE_RATIO_BPS_RANGE = (0, 300)
REVENUE_SHARE_BPS_RANGE = (0, 100)
PEER_MEDIAN_EXPENSE_BPS_RANGE = (1, 300)
PEER_RANK_PCT_RANGE = (1, 100)
STYLE_DRIFT_R2_RANGE = (0.0000, 1.0000)
EQUITY_AT_65_PCT_RANGE = (0.00, 100.00)
LANDING_POINT_AGE_RANGE = (60, 95)
MIN_MINUTES_DOC_REF_LENGTH = 6
RATIONALE_LENGTH_RANGE = (10, 500)
#: A proposal's rationale must reach this length at submission.
MIN_RATIONALE_LENGTH_ON_SUBMIT = 40


# --------------------------------------------------------------------------
# Arithmetic helpers — the PRD rounds half up, always
# --------------------------------------------------------------------------


def round_half_up(value, places: int = 2) -> Decimal:
    """Round ``value`` half up to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_to_int(value) -> int:
    """Floor a numeric value to a whole number, as the PRD's cent and
    basis-point floors do."""
    return int(Decimal(str(value)) // 1)


def clamp(value: Decimal, low: str = "0.00", high: str = "100.00") -> Decimal:
    """Clamp a component score into its declared range."""
    return max(Decimal(low), min(Decimal(high), value))


def peer_expense_cap_bps(peer_median_expense_bps: int, expense_peer_multiple) -> int:
    """The policy expense cap: peer median times the multiple, floored to whole
    basis points *before* the comparison."""
    return floor_to_int(
        Decimal(str(peer_median_expense_bps)) * Decimal(str(expense_peer_multiple))
    )


def performance_component(excess_bps: int) -> Decimal:
    """50.00 plus the excess basis points divided by 10, clamped to 0..100."""
    return clamp(round_half_up(PERFORMANCE_COMPONENT_BASE + Decimal(excess_bps) / 10))


def trailing_excess_bps(
    fund_3y: int, bench_3y: int, fund_5y: int, bench_5y: int
) -> int:
    """The TRAILING_PERIOD excess: 0.6 of the 3-year difference plus 0.4 of the
    5-year difference, rounded half up to a whole number of basis points."""
    raw = TRAILING_3Y_WEIGHT * Decimal(fund_3y - bench_3y) + TRAILING_5Y_WEIGHT * Decimal(
        fund_5y - bench_5y
    )
    return int(round_half_up(raw, 0))


def peer_component(peer_rank_pct) -> Decimal:
    return round_half_up(Decimal("100.00") - Decimal(str(peer_rank_pct)))


def expense_component(net_expense_ratio_bps: int, peer_median_expense_bps: int) -> Decimal:
    excess = max(0, net_expense_ratio_bps - peer_median_expense_bps)
    return clamp(round_half_up(Decimal("100.00") - EXPENSE_PENALTY_PER_BP * excess))


def style_component(style_drift_r2, style_drift_r2_floor) -> Decimal:
    r2 = Decimal(str(style_drift_r2))
    floor = Decimal(str(style_drift_r2_floor))
    if r2 >= floor:
        return Decimal("100.00")
    return clamp(round_half_up(Decimal("100.00") - STYLE_PENALTY_PER_UNIT * (floor - r2)))


def manager_component(manager_change_flag: bool, manager_tenure_quarters: int) -> Decimal:
    tenure = Decimal(manager_tenure_quarters)
    if manager_change_flag:
        raw = min(MANAGER_CHANGE_CAP, MANAGER_TENURE_MULTIPLIER_ON_CHANGE * tenure)
    else:
        raw = min(
            Decimal("100.00"),
            MANAGER_BASE_NO_CHANGE + MANAGER_TENURE_MULTIPLIER_NO_CHANGE * tenure,
        )
    return round_half_up(raw)


def composite_score(components: dict, weights: dict) -> Decimal:
    """Weight the five already-rounded components in the declared key order and
    round the sum half up exactly once."""
    total = Decimal("0")
    for key in WEIGHT_KEYS:
        total += round_half_up(components[key]) * Decimal(str(weights[key]))
    return round_half_up(total)


def glidepath_fit_score(
    glidepath_type: str,
    construction: str,
    equity_at_65_pct,
    landing_point_age: int,
    net_expense_ratio_bps: int,
) -> Decimal:
    """100.00 minus 1.5 times the equity gap, minus 2.0 times the landing gap,
    minus the cost penalty, rounded half up, then floored at 0.00."""
    ref = GLIDEPATH_REFERENCE[glidepath_type]
    allowance = GLIDEPATH_COST_ALLOWANCE_BPS[construction]
    equity_gap = abs(Decimal(str(equity_at_65_pct)) - ref["equity_at_65_pct"])
    landing_gap = abs(Decimal(landing_point_age) - Decimal(ref["landing_point_age"]))
    over = max(0, net_expense_ratio_bps - allowance)
    cost_penalty = Decimal(over) / 2
    raw = (
        Decimal("100.00")
        - GLIDEPATH_EQUITY_GAP_PENALTY * equity_gap
        - GLIDEPATH_LANDING_GAP_PENALTY * landing_gap
        - cost_penalty
    )
    rounded = round_half_up(raw)
    return rounded if rounded > 0 else Decimal("0.00")


def notice_lead_days(
    plan_notice_lead_days_required: int,
    mapping_strategy: str,
    slot_designation: str,
    erisa_covered: bool,
) -> int:
    """The proposal's derived ``notice_lead_days_required``; the additions stack."""
    days = plan_notice_lead_days_required
    if mapping_strategy == "REENROLLMENT":
        days += NOTICE_SURCHARGE_REENROLLMENT_DAYS
    if slot_designation == "QDIA" and erisa_covered:
        days += NOTICE_SURCHARGE_QDIA_ERISA_DAYS
    if mapping_strategy == "MAP_TO_QDIA" and slot_designation != "QDIA":
        days += NOTICE_SURCHARGE_MAP_TO_QDIA_NON_QDIA_DAYS
    return days


def fee_credit_tier(gross_cost_bps) -> str:
    gross = Decimal(str(gross_cost_bps))
    if gross <= TIER_A_MAX_GROSS_COST_BPS:
        return "TIER_A"
    if gross <= TIER_B_MAX_GROSS_COST_BPS:
        return "TIER_B"
    return "TIER_C"


def support_pct(for_count: int, denominator: int) -> Decimal:
    """for_count times 100 divided by the denominator, rounded half up to four
    decimal places."""
    return round_half_up(Decimal(for_count) * 100 / Decimal(denominator), 4)


def at_risk_slot_ratio(at_risk_slots: int, counted_slots: int) -> Decimal:
    if counted_slots == 0:
        return Decimal("0.0000")
    return round_half_up(Decimal(at_risk_slots) / Decimal(counted_slots), 4)


def menu_posture_for_ratio(ratio) -> str:
    """The posture the ratio alone implies, ignoring the other gates."""
    value = Decimal(str(ratio))
    if value >= Decimal(str(POSTURE_FROZEN_RATIO)):
        return "FROZEN"
    if value >= Decimal(str(POSTURE_RESTRICTED_RATIO)):
        return "RESTRICTED"
    return "OPEN"


def accrual_cents(plan_assets_cents: int, revenue_share_bps: int) -> int:
    """A pool fund's revenue-credit accrual: assets times basis points divided by
    10,000, floored to whole cents *per fund*."""
    return floor_to_int(Decimal(plan_assets_cents) * Decimal(revenue_share_bps) / 10000)


__all__ = [name for name in dir() if not name.startswith("_")]
