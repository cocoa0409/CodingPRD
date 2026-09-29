"""Domain constants, rounding discipline and the pure numeric calculations."""
from decimal import Decimal, ROUND_HALF_UP

# --- tagging ---------------------------------------------------------------
DIMENSION_WEIGHT = {"team": 40, "environment": 35, "application": 25}
ALLOWED_DIMENSIONS = ("team", "environment", "application")

# --- commitments -----------------------------------------------------------
HOURS_PER_PERIOD = 720
KIND_RANK = {"COMPUTE": 1, "DATABASE": 2, "STORAGE": 3}
DISCOUNT_RATE = {"RESERVED_INSTANCE": Decimal("0.40"), "SAVINGS_PLAN": Decimal("0.275")}
COMMITMENT_BUFFER_HOURS = 24
REGION_MAX_HOURLY_COMMIT_CENTS = 500

# --- invoices / disputes / runs -------------------------------------------
DISPUTE_WINDOW_HOURS = 168
MAX_RUN_REOPENS = 2
MAX_DISPUTE_ROUNDS = 3

# --- budgets ---------------------------------------------------------------
BREACH_THRESHOLD_PCT = Decimal("10.00")
WARN_THRESHOLD_PCT = Decimal("5.00")

# --- anomaly detection ----------------------------------------------------
SPIKE_RATIO_MIN = Decimal("1.20")
SPIKE_DELTA_MIN_CENTS = 50000
RATIO_MULTIPLIER = Decimal("25")
MAGNITUDE_DIVISOR = Decimal("100000")
BUDGET_PRESSURE_PCT = Decimal("80.00")

# --- idle / rightsizing ---------------------------------------------------
IDLE_UTILIZATION_MAX_PCT = Decimal("5.00")
RIGHTSIZE_UTILIZATION_MAX_PCT = Decimal("30.00")
MIN_RUN_RATE_CENTS = 20000
IDLE_SAVINGS_FRACTION = Decimal("1.00")
RIGHTSIZE_SAVINGS_FRACTION = Decimal("0.50")
UTILIZATION_WEIGHT = Decimal("0.6")
RUN_RATE_DIVISOR = Decimal("25000")
AUTO_REMEDIATION_SCORE_MIN = Decimal("60.00")
REMEDIATION_WINDOW_HOURS = 72
MAX_SNOOZES = 2

# --- unit economics -------------------------------------------------------
EFFICIENT_MAX_CPU = Decimal("50.00")
STANDARD_MAX_CPU = Decimal("250.00")
OVERHEAD_RATE = {
    "EFFICIENT": Decimal("0.03"),
    "STANDARD": Decimal("0.07"),
    "INEFFICIENT": Decimal("0.12"),
}


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to the given number of decimal places (Decimal result)."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to whole cents (int result)."""
    return int(rhu(value, 0))


def pct2(value):
    """Percentage / 2-decimal figure as a JSON number."""
    return float(rhu(value, 2))


def num4(value):
    return float(rhu(value, 4))


def floor_int(value):
    return int(D(value).to_integral_value(rounding="ROUND_FLOOR"))


# --------------------------------------------------------------------------
# calculation: tag_compliance_evaluation
# --------------------------------------------------------------------------
def tag_compliance(mandatory_dimensions, requested_tags):
    tags = requested_tags or {}
    missing = []
    for dim in mandatory_dimensions:
        value = tags.get(dim)
        if not isinstance(value, str) or value.strip() == "":
            missing.append(dim)
    mandatory_weight = sum(DIMENSION_WEIGHT[d] for d in mandatory_dimensions if d in DIMENSION_WEIGHT)
    satisfied_weight = sum(
        DIMENSION_WEIGHT[d]
        for d in mandatory_dimensions
        if d in DIMENSION_WEIGHT and d not in missing
    )
    if mandatory_weight == 0:
        score = Decimal("0.00")
    else:
        score = rhu(D(satisfied_weight) / D(mandatory_weight) * 100, 2)
    if score == Decimal("100.00"):
        state = "TAGGED"
    elif score == Decimal("0.00"):
        state = "UNTAGGED"
    else:
        state = "PARTIAL"
    return missing, float(score), state


# --------------------------------------------------------------------------
# calculation: idle_and_rightsizing_evaluation (per-resource part)
# --------------------------------------------------------------------------
def waste_score(utilization_pct, monthly_run_rate_cents):
    util_term = (D(100) - D(utilization_pct)) * UTILIZATION_WEIGHT
    rate_term = min(D(40), D(monthly_run_rate_cents) / RUN_RATE_DIVISOR)
    return rhu(min(D(100), util_term + rate_term), 2)


def remediation_verdict(utilization_pct, monthly_run_rate_cents):
    """Returns (kind, projected_savings_cents) or (None, None) when not a candidate."""
    util = D(utilization_pct)
    if monthly_run_rate_cents < MIN_RUN_RATE_CENTS:
        return None, None
    if util <= IDLE_UTILIZATION_MAX_PCT:
        return "IDLE_TERMINATE", rhu_cents(D(monthly_run_rate_cents) * IDLE_SAVINGS_FRACTION)
    if util <= RIGHTSIZE_UTILIZATION_MAX_PCT:
        return "RIGHTSIZE", rhu_cents(D(monthly_run_rate_cents) * RIGHTSIZE_SAVINGS_FRACTION)
    return None, None


def task_metrics(resource, kind=None):
    """waste_score / projected savings / auto eligibility from current telemetry."""
    util = D(resource["utilization_pct"])
    rate = resource["monthly_run_rate_cents"]
    derived_kind, savings = remediation_verdict(util, rate)
    effective_kind = kind or derived_kind
    if effective_kind == "IDLE_TERMINATE":
        savings = rhu_cents(D(rate) * IDLE_SAVINGS_FRACTION)
    elif effective_kind == "RIGHTSIZE":
        savings = rhu_cents(D(rate) * RIGHTSIZE_SAVINGS_FRACTION)
    else:
        savings = 0
    score = waste_score(util, rate)
    eligible = bool(score >= AUTO_REMEDIATION_SCORE_MIN and resource.get("environment") != "prod")
    return {
        "waste_score": float(score),
        "projected_savings_cents": savings,
        "auto_remediation_eligible": eligible,
        "observed_utilization_pct": float(rhu(util, 2)),
    }


# --------------------------------------------------------------------------
# calculation: anomaly_spike_detection (scoring part)
# --------------------------------------------------------------------------
def severity_components(spike_ratio, delta_cents, budget_component):
    ratio_component = min(D(50), max(D(0), (D(spike_ratio) - SPIKE_RATIO_MIN) * RATIO_MULTIPLIER))
    magnitude_component = min(D(30), D(delta_cents) / MAGNITUDE_DIVISOR)
    return rhu(ratio_component + magnitude_component + D(budget_component), 2)


def severity_band(score):
    score = D(score)
    if score >= 70:
        return "CRITICAL"
    if score >= 45:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def routed_queue_for(severity):
    if severity in ("HIGH", "CRITICAL"):
        return "CONTROLLER_PAGER"
    if severity == "MEDIUM":
        return "BU_OWNER_INBOX"
    return "WEEKLY_DIGEST"


# --------------------------------------------------------------------------
# calculation: unit_economics_cost_per_unit
# --------------------------------------------------------------------------
def unit_economics(base_allocated_cents, driver_volume):
    provisional = rhu(D(base_allocated_cents) / D(driver_volume), 2)
    if provisional <= EFFICIENT_MAX_CPU:
        tier = "EFFICIENT"
    elif provisional <= STANDARD_MAX_CPU:
        tier = "STANDARD"
    else:
        tier = "INEFFICIENT"
    overhead = rhu_cents(D(base_allocated_cents) * OVERHEAD_RATE[tier])
    final = rhu(D(base_allocated_cents + overhead) / D(driver_volume), 2)
    return {
        "provisional_cost_per_unit_cents": float(provisional),
        "efficiency_tier": tier,
        "platform_overhead_cents": overhead,
        "final_cost_per_unit_cents": float(final),
    }


# --------------------------------------------------------------------------
# calculation: shared_pool_allocation (distribution maths only)
# --------------------------------------------------------------------------
def distribute(pooled_cents, exact_shares):
    """exact_shares: list of Decimal exact shares aligned with participants.

    Returns (allocations, remainder_flags) using floor + largest-fractional-part.
    The caller supplies participants already ordered by BusinessUnit.created_at ASC
    so that fractional-part ties resolve on creation order.
    """
    allocations = [floor_int(share) for share in exact_shares]
    remainder = pooled_cents - sum(allocations)
    flags = [0] * len(allocations)
    if remainder > 0:
        order = sorted(
            range(len(exact_shares)),
            key=lambda i: (-(exact_shares[i] - floor_int(exact_shares[i])), i),
        )
        for idx in order:
            if remainder == 0:
                break
            allocations[idx] += 1
            flags[idx] = 1
            remainder -= 1
    return allocations, flags
