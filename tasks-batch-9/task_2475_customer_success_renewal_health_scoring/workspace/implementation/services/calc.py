"""Pure arithmetic: every named constant and formula from the calculation
catalogue.  All non-integer arithmetic uses Decimal with ROUND_HALF_UP; money is
whole cents.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

D = Decimal
_CENT = D('0.01')
_ONE = D('1')

# --- usage / adoption -------------------------------------------------------
SEAT_WEIGHT = D('0.60')
DEPTH_WEIGHT = D('0.40')
RECENCY_WEIGHTS = (D('0.50'), D('0.30'), D('0.20'))
ADOPTION_LOOKBACK_ROWS = 3

# --- support ----------------------------------------------------------------
SEVERITY_POINTS = {'S1': D('12'), 'S2': D('7'), 'S3': D('3'), 'S4': D('1')}
SLA_BREACH_POINTS = D('5')
LOW_CSAT_POINTS = D('4')
LOW_CSAT_THRESHOLD = 2
SUPPORT_WINDOW_DAYS = 90
SUPPORT_PENALTY_CAP = D('45.00')

# --- executive engagement ---------------------------------------------------
EXEC_BASE = D('50.00')
SENIOR_CREDIT = D('15.00')
SENIOR_CREDIT_CAP = D('45.00')
JUNIOR_CREDIT = D('5.00')
JUNIOR_CREDIT_CAP = D('15.00')
NO_SHOW_DEBIT = D('20.00')
NO_ECONOMIC_BUYER_DEBIT = D('25.00')
EXEC_WINDOW_DAYS = 180
SENIOR_SENIORITIES = ('CXO', 'VP')
JUNIOR_SENIORITIES = ('DIRECTOR', 'MANAGER')

# --- outcome goals ----------------------------------------------------------
OUTCOME_EMPTY_SUBSTITUTE = D('60.00')
MAX_TOTAL_WEIGHT_BP = 10000

# --- composite health -------------------------------------------------------
ADOPTION_WEIGHT = D('0.35')
SUPPORT_WEIGHT = D('0.25')
EXEC_WEIGHT = D('0.15')
OUTCOME_WEIGHT = D('0.25')
AMBER_FLOOR = D('50.00')
GREEN_FLOOR = D('75.00')
SAVE_FAILURE_PENALTY = D('5.00')

# --- coverage tier ----------------------------------------------------------
HIGH_TOUCH_ARR_FLOOR = 25000000
LOW_TOUCH_ARR_FLOOR = 5000000
DORMANT_LIFECYCLES = ('CHURNED', 'WIN_BACK_TARGETED', 'ARCHIVED')

# --- coverage load ----------------------------------------------------------
BASE_UNITS = {'HIGH_TOUCH': D('9'), 'LOW_TOUCH': D('5'), 'DIGITAL': D('2')}
SEGMENT_MULTIPLIER = {'ENTERPRISE': D('1.50'), 'MIDMARKET': D('1.00'), 'SMB': D('0.50')}
RISK_MULTIPLIER = {'RED': D('1.25'), 'AMBER': D('1.10'), 'GREEN': D('1.00')}
ARR_SURCHARGE_TIERS = ((100000000, 4), (25000000, 2), (5000000, 1))
LOAD_UNITS_FLOOR = 1
LOAD_UNITS_CEIL = 20

# --- time to value ----------------------------------------------------------
TTV_TARGET_DAYS = {'ENTERPRISE': 90, 'MIDMARKET': 60, 'SMB': 30}

# --- renewal likelihood -----------------------------------------------------
COMMIT_HEALTH_FLOOR = D('75.00')
UPSIDE_HEALTH_FLOOR = D('60.00')
NEAR_TERM_DAYS = 60

# --- forecast ---------------------------------------------------------------
CS_LIKELIHOOD_WEIGHT = {
    'COMMIT': D('0.95'),
    'UPSIDE': D('0.70'),
    'AT_RISK': D('0.35'),
    'OMIT': D('0.00'),
}
FINANCE_SEGMENT_RATE = {
    'ENTERPRISE': D('0.90'),
    'MIDMARKET': D('0.80'),
    'SMB': D('0.65'),
}
VARIANCE_TOLERANCE_BP = 500

# --- escalation settlement --------------------------------------------------
SEVERITY_BASE_BP = {'CRITICAL': 300, 'HIGH': 150, 'MEDIUM': 50}
TIER_TWO_FLOOR_CENTS = 1000000
TIER_TWO_BP = 2000
TIER_ONE_FLOOR_CENTS = 250000
TIER_ONE_BP = 1000
COMMITMENT_CREDIT_CAP_BP = 1000

# --- expansion --------------------------------------------------------------
QUAL_HEALTH_WEIGHT = D('0.50')
QUAL_ADOPTION_WEIGHT = D('0.30')
QUAL_ARR_WEIGHT = D('0.20')
ARR_NORMALISER_CENTS = 50000000
EXPANSION_HANDOFF_FLOOR = D('65.00')
OPPORTUNITY_STALE_DAYS = 30

# --- save plays -------------------------------------------------------------
MAX_CONCURRENT_SAVE_PLAYS = 2

# --- executive engagement conflicts ----------------------------------------
EXEC_BUFFER_MINUTES = 30

# --- advocacy ---------------------------------------------------------------
REFERENCE_CALL_CAP = {'ENTERPRISE': 6, 'MIDMARKET': 4, 'SMB': 2}

HEALTH_TIERS = ('RED', 'AMBER', 'GREEN')


def r2(value):
    return D(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(D(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# usage rows
# ---------------------------------------------------------------------------

def seat_utilisation_pct(weekly_active_users, licensed_seats):
    if licensed_seats == 0:
        return D('0.00')
    raw = D(100) * D(weekly_active_users) / D(licensed_seats)
    return r2(min(D('100.00'), raw))


def usage_row_index(seat_util, feature_depth_pct):
    return r2(SEAT_WEIGHT * D(seat_util) + DEPTH_WEIGHT * D(feature_depth_pct))


def adoption_index(usage_rows_recent_first):
    rows = usage_rows_recent_first[:ADOPTION_LOOKBACK_ROWS]
    if not rows:
        return D('0.00')
    numerator = D('0')
    denominator = D('0')
    for weight, row in zip(RECENCY_WEIGHTS, rows):
        numerator += weight * D(row['usage_row_index'])
        denominator += weight
    return r2(numerator / denominator)


# ---------------------------------------------------------------------------
# support
# ---------------------------------------------------------------------------

def ticket_penalty_points(severity, breached_sla, csat_score):
    points = SEVERITY_POINTS.get(severity, D('0'))
    if breached_sla:
        points += SLA_BREACH_POINTS
    if csat_score is not None and csat_score <= LOW_CSAT_THRESHOLD:
        points += LOW_CSAT_POINTS
    return points


def support_risk_penalty(ticket_rows):
    total = D('0')
    for row in ticket_rows:
        total += D(row['penalty_points'])
    return r2(min(SUPPORT_PENALTY_CAP, total))


# ---------------------------------------------------------------------------
# executive engagement
# ---------------------------------------------------------------------------

def exec_engagement_score(held_senior, held_junior, no_shows, has_economic_buyer):
    score = EXEC_BASE
    score += min(SENIOR_CREDIT_CAP, SENIOR_CREDIT * D(held_senior))
    score += min(JUNIOR_CREDIT_CAP, JUNIOR_CREDIT * D(held_junior))
    score -= NO_SHOW_DEBIT * D(no_shows)
    if not has_economic_buyer:
        score -= NO_ECONOMIC_BUYER_DEBIT
    return r2(clamp(score, D('0.00'), D('100.00')))


# ---------------------------------------------------------------------------
# outcome goals
# ---------------------------------------------------------------------------

def attainment_pct(actual_value, target_value):
    if target_value is None or D(target_value) == 0:
        return D('0.00')
    raw = D(100) * D(actual_value) / D(target_value)
    return r2(min(D('100.00'), raw))


def outcome_attainment_index(goal_pairs):
    """goal_pairs is a list of (attainment_pct, weight_bp) for the input set."""
    if not goal_pairs:
        return OUTCOME_EMPTY_SUBSTITUTE
    total_weight = sum(w for _, w in goal_pairs)
    if total_weight == 0:
        return OUTCOME_EMPTY_SUBSTITUTE
    total = D('0')
    for pct, weight in goal_pairs:
        total += r2(D(pct) * D(weight) / D(total_weight))
    return r2(total)


# ---------------------------------------------------------------------------
# composite health
# ---------------------------------------------------------------------------

def health_score(adoption_term, support_component, exec_score, outcome_index):
    return r2(ADOPTION_WEIGHT * D(adoption_term)
              + SUPPORT_WEIGHT * D(support_component)
              + EXEC_WEIGHT * D(exec_score)
              + OUTCOME_WEIGHT * D(outcome_index))


def health_tier(snapshot_score):
    score = D(snapshot_score)
    if score < AMBER_FLOOR:
        return 'RED'
    if score < GREEN_FLOOR:
        return 'AMBER'
    return 'GREEN'


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------

def coverage_tier_assignment(lifecycle_state, arr_cents, segment_band, tier):
    if lifecycle_state in DORMANT_LIFECYCLES:
        return 'DIGITAL'
    if arr_cents >= HIGH_TOUCH_ARR_FLOOR or (segment_band == 'ENTERPRISE' and tier == 'RED'):
        return 'HIGH_TOUCH'
    if arr_cents >= LOW_TOUCH_ARR_FLOOR or tier == 'RED':
        return 'LOW_TOUCH'
    return 'DIGITAL'


def arr_surcharge(arr_cents):
    for floor, surcharge in ARR_SURCHARGE_TIERS:
        if arr_cents >= floor:
            return surcharge
    return 0


def coverage_load_units(coverage_tier, segment_band, health_tier_value, arr_cents):
    raw = r2(BASE_UNITS[coverage_tier]
             * SEGMENT_MULTIPLIER[segment_band]
             * RISK_MULTIPLIER[health_tier_value])
    raw = raw + D(arr_surcharge(arr_cents))
    units = int(raw.to_integral_value(rounding=ROUND_CEILING))
    return int(clamp(units, LOAD_UNITS_FLOOR, LOAD_UNITS_CEIL))


# ---------------------------------------------------------------------------
# renewal
# ---------------------------------------------------------------------------

def renewal_likelihood(lifecycle_state, trended_score, open_save_play_count,
                       days_to_renewal):
    if lifecycle_state in DORMANT_LIFECYCLES:
        return 'OMIT'
    if D(trended_score) >= COMMIT_HEALTH_FLOOR and open_save_play_count == 0:
        return 'COMMIT'
    if D(trended_score) >= UPSIDE_HEALTH_FLOOR and days_to_renewal > NEAR_TERM_DAYS:
        return 'UPSIDE'
    return 'AT_RISK'


def cs_bottom_up_amount(arr_cents, likelihood_category):
    weight = CS_LIKELIHOOD_WEIGHT[likelihood_category]
    return round_half_up_int(D(arr_cents) * weight)


def finance_top_down_amount(arr_cents, segment_band):
    rate = FINANCE_SEGMENT_RATE[segment_band]
    return round_half_up_int(D(arr_cents) * rate)


def variance_state(variance_cents, cs_amount_cents):
    if abs(variance_cents) * 10000 > VARIANCE_TOLERANCE_BP * cs_amount_cents:
        return 'VARIANCE_FLAGGED'
    return 'RECONCILED'


# ---------------------------------------------------------------------------
# escalation settlement
# ---------------------------------------------------------------------------

def settlement_credit(arr_cents, severity, delivered_commitment_total):
    base = round_half_up_int(D(arr_cents) * D(SEVERITY_BASE_BP[severity]) / D(10000))
    pre_reduction = base + delivered_commitment_total
    if pre_reduction >= TIER_TWO_FLOOR_CENTS:
        tier_bp = TIER_TWO_BP
    elif pre_reduction >= TIER_ONE_FLOOR_CENTS:
        tier_bp = TIER_ONE_BP
    else:
        tier_bp = 0
    reduction = round_half_up_int(D(pre_reduction) * D(tier_bp) / D(10000))
    return pre_reduction - reduction


def credit_within_cap(credit_cents, arr_cents):
    return credit_cents * 10000 <= COMMITMENT_CREDIT_CAP_BP * arr_cents


# ---------------------------------------------------------------------------
# expansion
# ---------------------------------------------------------------------------

def qualification_score(trended_health_score, adoption_index_value, arr_cents):
    arr_term = min(D('100.00'), r2(D(100) * D(arr_cents) / D(ARR_NORMALISER_CENTS)))
    return r2(QUAL_HEALTH_WEIGHT * D(trended_health_score)
              + QUAL_ADOPTION_WEIGHT * D(adoption_index_value)
              + QUAL_ARR_WEIGHT * arr_term)
