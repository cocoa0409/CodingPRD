"""Pure calculation rules, transcribed from PRD §2.5, §2.9, §2.10 and §3.

Every numeric quantity uses decimal.Decimal; every rounding step is
ROUND_HALF_UP; the pinned rounding orders of PRD §2.5 are honoured
literally.
"""

from decimal import Decimal, ROUND_HALF_UP

D = Decimal
ZERO = D("0.00")


def q2(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    return -(-numerator // denominator)


# --------------------------------------------------------------------------
# Enumerations and constant tables
# --------------------------------------------------------------------------
UPDATE_FREQUENCIES = ("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL", "IRREGULAR")
PIPELINE_CADENCES = ("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL")
SENSITIVITY_CLASSES = ("PUBLIC", "SENSITIVE", "RESTRICTED")
GEOGRAPHIES = ("BLOCK", "TRACT", "COUNTY")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ISSUE_CATEGORIES = ("ACCURACY", "COMPLETENESS", "TIMELINESS", "SCHEMA", "PRIVACY")
CHANGE_TYPES = ("INITIAL", "SCHEDULED_REFRESH", "CORRECTION", "SCHEMA_CHANGE")
FAILURE_CODES = ("SOURCE_UNAVAILABLE", "SCHEMA_DRIFT", "TIMEOUT", "TRANSFORM_ERROR")
BLOCK_REASONS = ("RISK_TOO_HIGH", "AGGREGATION_UNMET", "REVIEWER_JUDGEMENT")
REJECT_REASONS = ("NOT_REPRODUCIBLE", "OUT_OF_SCOPE", "DUPLICATE")
SUSPEND_REASONS = ("FAILURE_STREAK", "REMEDIATION_HOLD", "ADMIN_REQUEST")
RUNNER_STATUSES = ("ACTIVE", "DRAINING", "OFFLINE")

CADENCE_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30, "QUARTERLY": 91, "ANNUAL": 365}
GRACE_DAYS = {"TIER_1": 2, "TIER_2": 7, "TIER_3": 14}
GEO_RANK = {None: 0, "BLOCK": 1, "TRACT": 2, "COUNTY": 3}
SENSITIVITY_MULTIPLIER = {"PUBLIC": D("0.8"), "SENSITIVE": D("1.0"), "RESTRICTED": D("1.4")}
SEVERITY_ORDER = ("CURRENT", "AGING", "STALE", "BREACHED")

TRIAGE_SLA_HOURS = {"LOW": 168, "MEDIUM": 72, "HIGH": 24, "CRITICAL": 8}
CORRECTION_SLA_DAYS = {"LOW": 90, "MEDIUM": 30, "HIGH": 14, "CRITICAL": 5}

PUBLISHED_STATES = ("PUBLISHED", "UNDER_REMEDIATION")

# priority score
W_DEMAND = D("0.45")
W_POLICY = D("0.35")
W_COMMUNITY = D("0.20")
COMMUNITY_VOTE_MULTIPLIER = D(4)
COMMUNITY_CAP = D(100)
TIER_1_MIN = D("75.00")
TIER_2_MIN = D("50.00")

# reidentification
QI_UNIT = D(8)
QI_CAP = D(40)
CELL_HIGH_MIN = 11
CELL_MID_MIN = 5
CELL_FACTOR_LOW = D("0.5")
CELL_FACTOR_MID = D("1.0")
CELL_FACTOR_HIGH = D("2.0")
SMALL_POP_MIN = 5000
SMALL_POP_FACTOR = D("1.25")
RISK_CAP = D("100.00")
AGGREGATION_REQUIRED_MIN = D("35.00")
GEO_COUNTY_MIN = D("60.00")
CLEARANCE_RISK_MAX = D("60.00")

# metadata completeness
METADATA_WEIGHTS = [D("0.30"), D("0.20"), D("0.15"), D("0.15"), D("0.10"), D("0.10")]
PROVENANCE_TARGET_LINES = 24
ATTRIBUTION_ELEMENTS_TOTAL = 6
METADATA_ACCEPT_MIN = D("85.00")

# run settlement
ROWS_PER_COMPUTE_UNIT = 10000
COMPUTE_UNIT_CREDITS = D(4)
ALERT_FEE_CREDITS = D(3)
DISCOUNT_TIER_A_MIN = D(40)
DISCOUNT_TIER_A_PCT = D("0.10")
DISCOUNT_TIER_B_MIN = D(20)
DISCOUNT_TIER_B_PCT = D("0.05")
FAILURE_STREAK_LIMIT = 3

# pipeline escrow
ESCROW_HORIZON_DAYS = 30
ESCROW_PER_RUN_UNITS = 2
ESCROW_CAP_UNITS = 60
DEPARTMENT_WINDOW_CAP = 2

# reputation
REPUTATION_BASE = D(50)
ACCEPT_POINTS = D(6)
REJECT_POINTS = D(4)
SHOWCASE_POINTS = D(2)
DECAY_FACTOR = D("0.80")
REPUTATION_DECAY_PERIOD_DAYS = 30
WEIGHT_HIGH_MIN = D("70.00")
WEIGHT_MID_MIN = D("40.00")
THROTTLE_NET_REJECTS = 3

# engagement
EPOCH_WINDOW = 3
EPOCH_WEIGHTS = [D("0.50"), D("0.30"), D("0.20")]
API_WEIGHT = D("0.60")
DOWNLOAD_WEIGHT = D("0.40")
ENGAGEMENT_NORMALIZER = D(50)

# demand signal
DEMAND_SIGNAL_MULTIPLIER = D(5)
REVIEW_VOTE_MIN = 4

# department posture
BREACHED_WEIGHT = 3
STALE_WEIGHT = 2
REMEDIATION_WEIGHT = 2
OVERDUE_WEIGHT = 1
RESTRICTED_MIN = 2
SUSPENDED_MIN = 6


# --------------------------------------------------------------------------
# dataset_priority_score (PRD §3.1)
# --------------------------------------------------------------------------
def community_pressure(dataset_id, requests):
    total = 0
    for req in requests.values():
        if req["linked_dataset_id"] == dataset_id and req["status"] in ("ACCEPTED", "FULFILLED"):
            total += req["weighted_vote_total"]
    return min(COMMUNITY_CAP, COMMUNITY_VOTE_MULTIPLIER * D(total))


def priority_score(dataset, variant, requests):
    if variant == "AS_OBSERVED":
        demand_term = D(dataset["observed_demand_score"])
    else:
        demand_term = D(dataset["public_demand_score"])
    pressure = community_pressure(dataset["id"], requests)
    return q2(
        W_DEMAND * demand_term
        + W_POLICY * D(dataset["policy_value_score"])
        + W_COMMUNITY * pressure
    )


def priority_tier(score):
    score = D(score)
    if score >= TIER_1_MIN:
        return "TIER_1"
    if score >= TIER_2_MIN:
        return "TIER_2"
    return "TIER_3"


# --------------------------------------------------------------------------
# dataset_engagement_index (PRD §3.8)
# --------------------------------------------------------------------------
def engagement_index(usage_epochs):
    selected = sorted(
        usage_epochs, key=lambda e: (-e["epoch_index"], e["recorded_at"])
    )[:EPOCH_WINDOW]
    weighted = D(0)
    for index, epoch in enumerate(selected):
        value = API_WEIGHT * D(epoch["api_call_count"]) + DOWNLOAD_WEIGHT * D(
            epoch["download_count"]
        )
        weighted += EPOCH_WEIGHTS[index] * value
    return min(D("100.00"), q2(weighted / ENGAGEMENT_NORMALIZER))


# --------------------------------------------------------------------------
# reidentification_risk_score (PRD §3.3)
# --------------------------------------------------------------------------
def reidentification_risk(qi_count, cell_size, population_size, sensitivity_class, variant):
    qi_factor = min(QI_CAP, QI_UNIT * D(qi_count))
    if cell_size >= CELL_HIGH_MIN:
        cell_factor = CELL_FACTOR_LOW
    elif cell_size >= CELL_MID_MIN:
        cell_factor = CELL_FACTOR_MID
    else:
        cell_factor = CELL_FACTOR_HIGH
    if variant == "SCREENING":
        population_factor = D("1.00")
    else:
        population_factor = (
            SMALL_POP_FACTOR if population_size < SMALL_POP_MIN else D("1.00")
        )
    multiplier = SENSITIVITY_MULTIPLIER[sensitivity_class]
    return min(RISK_CAP, q2(qi_factor * cell_factor * population_factor * multiplier))


def aggregation_required(score):
    return D(score) >= AGGREGATION_REQUIRED_MIN


def min_aggregation_geography(score):
    score = D(score)
    if score >= GEO_COUNTY_MIN:
        return "COUNTY"
    if score >= AGGREGATION_REQUIRED_MIN:
        return "TRACT"
    return "BLOCK"


# --------------------------------------------------------------------------
# metadata_completeness_score (PRD §3.2, pinned rounding order)
# --------------------------------------------------------------------------
def metadata_completeness(record, dataset, license_row):
    column_count = dataset["column_count"]
    c1 = min(D(1), D(record["data_dictionary_field_count"]) / D(column_count))
    c2 = min(D(1), D(record["provenance_detail_lines"]) / D(PROVENANCE_TARGET_LINES))
    contact = record["contact_email"] or ""
    c3 = D(1) if "@" in contact else D(0)
    c4 = D(1) if record["declared_update_frequency"] == dataset["update_frequency"] else D(0)
    c5 = D(1) if (license_row is not None and not license_row["retired"]) else D(0)
    c6 = min(D(1), D(record["attribution_element_count"]) / D(ATTRIBUTION_ELEMENTS_TOTAL))
    components = [c1, c2, c3, c4, c5, c6]
    contributions = [
        q2(METADATA_WEIGHTS[i] * components[i] * D(100)) for i in range(6)
    ]
    total = D(0)
    for contribution in contributions:
        total += contribution
    return contributions, q2(total)


# --------------------------------------------------------------------------
# pipeline_run_settlement (PRD §3.6, pinned sequence)
# --------------------------------------------------------------------------
def settle_run(rows_ingested, alert_dispatched):
    units = ceil_div(int(rows_ingested), ROWS_PER_COMPUTE_UNIT)
    compute_credits = q2(D(units) * COMPUTE_UNIT_CREDITS)
    alert_credits = q2(ALERT_FEE_CREDITS) if alert_dispatched else ZERO
    subtotal = q2(compute_credits + alert_credits)
    if subtotal >= DISCOUNT_TIER_A_MIN:
        pct = DISCOUNT_TIER_A_PCT
    elif subtotal >= DISCOUNT_TIER_B_MIN:
        pct = DISCOUNT_TIER_B_PCT
    else:
        pct = D("0.00")
    discount = q2(subtotal * pct)
    total = q2(subtotal - discount)
    return {
        "compute_credits": compute_credits,
        "alert_credits": alert_credits,
        "subtotal_credits": subtotal,
        "reliability_discount_pct": q2(pct),
        "discount_credits": discount,
        "total_charge_credits": total,
    }


# --------------------------------------------------------------------------
# pipeline_credit_escrow (PRD §3.5)
# --------------------------------------------------------------------------
def escrow_required_units(cadence):
    runs_per_month = ceil_div(ESCROW_HORIZON_DAYS, CADENCE_DAYS[cadence])
    return q2(D(min(ESCROW_CAP_UNITS, runs_per_month * ESCROW_PER_RUN_UNITS)))


# --------------------------------------------------------------------------
# member_reputation_score (PRD §3.7)
# --------------------------------------------------------------------------
def reputation(accepted, rejected, showcases, last_credited_at, logical_now):
    raw = (
        REPUTATION_BASE
        + ACCEPT_POINTS * D(accepted)
        - REJECT_POINTS * D(rejected)
        + SHOWCASE_POINTS * D(showcases)
    )
    epochs = 0
    if last_credited_at is not None:
        elapsed = (logical_now - last_credited_at).total_seconds()
        period = REPUTATION_DECAY_PERIOD_DAYS * 86400
        epochs = int(elapsed // period)
        if epochs < 0:
            epochs = 0
    decayed = REPUTATION_BASE + (raw - REPUTATION_BASE) * (DECAY_FACTOR ** epochs)
    clamped = min(D(100), max(D(0), decayed))
    score = q2(clamped)
    if score >= WEIGHT_HIGH_MIN:
        weight = 3
    elif score >= WEIGHT_MID_MIN:
        weight = 2
    else:
        weight = 1
    return epochs, score, weight


# --------------------------------------------------------------------------
# request_demand_signal (PRD §3.8)
# --------------------------------------------------------------------------
def demand_signal(weighted_vote_total):
    return q2(min(D(100), DEMAND_SIGNAL_MULTIPLIER * D(weighted_vote_total)))


# --------------------------------------------------------------------------
# department_compliance_posture (PRD §2.9)
# --------------------------------------------------------------------------
def compliance_posture(risk_points):
    if risk_points >= SUSPENDED_MIN:
        return "SUSPENDED"
    if risk_points >= RESTRICTED_MIN:
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------
# dataset_currency_status (PRD §3.9)
# --------------------------------------------------------------------------
def more_severe(left, right):
    return left if SEVERITY_ORDER.index(left) >= SEVERITY_ORDER.index(right) else right


def next_due_at(update_frequency, last_published_at):
    if update_frequency == "IRREGULAR" or last_published_at is None:
        return None
    from datetime import timedelta

    return last_published_at + timedelta(days=CADENCE_DAYS[update_frequency])


def days_overdue(due, logical_now):
    if due is None or logical_now <= due:
        return 0
    return int((logical_now - due).total_seconds() // 86400)


def clock_currency(due, overdue, tier, high_value_committed, logical_now):
    if due is None or logical_now <= due:
        return "CURRENT"
    grace = GRACE_DAYS[tier]
    if overdue <= grace:
        return "AGING"
    if overdue <= 2 * grace:
        return "STALE"
    return "BREACHED" if high_value_committed else "STALE"
