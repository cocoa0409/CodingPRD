"""Business logic: pacing tiers, incentive pricing, fraud screen, sampling,
evaluation adjustment recomputation, and trade-ally performance scoring.

All formulas follow SCAFFOLD.yaml section 1.3 and PRD sections 2.7 / 3.
Money is integer cents; tier factors are exact Decimals; per-line rounding
is round-half-up BEFORE summation (mandatory rounding order).
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now_iso

# --- Status vocabularies ---
COMMITTED_STATUSES = (
    "SUBMITTED",
    "PRE_INSPECTION",
    "POST_INSPECTION",
    "VERIFIED",
    "APPROVED",
    "PAID",
)
CLOSE_BLOCKING_STATUSES = ("SUBMITTED", "PRE_INSPECTION", "POST_INSPECTION", "VERIFIED")
ALLY_OPEN_STATUSES = ("DRAFT", "SUBMITTED", "PRE_INSPECTION", "POST_INSPECTION", "VERIFIED")

# --- Fraud screen constants ---
SAME_SERVICE_ADDRESS_WEIGHT = 40
SAME_SERVICE_ADDRESS_WINDOW_DAYS = 30
ALLY_BURST_WEIGHT = 25
ALLY_BURST_COUNT = 5
ALLY_BURST_WINDOW_DAYS = 7
INVOICE_GAP_WEIGHT = 15
INVOICE_GAP_WINDOW_DAYS = 7
SUSPECT_THRESHOLD = 50

# --- Inspection sampling constants ---
SAMPLE_EVERY_N = 5
LARGE_CLAIM_KWH_THRESHOLD = 10000

# --- Pacing tier constants ---
MID_TIER_FLOOR_PCT = 50
HIGH_TIER_FLOOR_PCT = 80
MID_TIER_FACTOR = Decimal("0.80")
HIGH_TIER_FACTOR = Decimal("0.50")
STANDARD_TIER_FACTOR = Decimal("1.00")

# --- Standing tier thresholds ---
PREFERRED_FLOOR = 90
STANDARD_FLOOR = 70


def to_date(s):
    """Parse a validated YYYY-MM-DD string into a date."""
    return date.fromisoformat(s)


def submitted_date(app):
    """Date component of an application's submitted_at timestamp."""
    return date.fromisoformat(app["submitted_at"][:10])


def round_half_up_int(value):
    """Round a Decimal to an integer, half-up (never banker's rounding)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_ratio(numerator, denominator):
    """round_half_up(numerator / denominator) for integer inputs."""
    return round_half_up_int(Decimal(numerator) / Decimal(denominator))


def touch(rec):
    """Register a mutation: version +1 and updated_at refreshed."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# =============================================================================
# pacing_tier_selection (scaffold 1.3)
# =============================================================================
def committed_pct(py):
    """floor(100 * committed_cents / budget_cap_cents) at this moment."""
    return (100 * py["committed_cents"]) // py["budget_cap_cents"]


def pacing_tier(pct):
    """Boundaries inclusive on the lower edge: 50 -> MID, 80 -> HIGH."""
    if pct >= HIGH_TIER_FLOOR_PCT:
        return "HIGH_TIER", HIGH_TIER_FACTOR
    if pct >= MID_TIER_FLOOR_PCT:
        return "MID_TIER", MID_TIER_FACTOR
    return "STANDARD_TIER", STANDARD_TIER_FACTOR


def price_line(measure, quantity, tier_factor):
    """round_half_up(base_rate_cents * quantity * tier_factor, 0)."""
    raw = Decimal(measure["base_rate_cents"]) * Decimal(quantity) * tier_factor
    return round_half_up_int(raw)


# =============================================================================
# inspection_sampling_decision (scaffold 1.3)
# =============================================================================
def sampling_decision(app):
    """n = applications in the same program year that already reached
    SUBMITTED-or-beyond before this one (submitted_at set). Then the rules OR:
    every Nth submission, or claimed_kwh >= LARGE_CLAIM_KWH_THRESHOLD."""
    n = sum(
        1
        for other in store.applications.values()
        if other["program_year_id"] == app["program_year_id"]
        and other["submitted_at"] is not None
    )
    if (n + 1) % SAMPLE_EVERY_N == 0:
        return True
    return app["claimed_kwh"] >= LARGE_CLAIM_KWH_THRESHOLD


# =============================================================================
# fraud_risk_score (scaffold 1.3)
# =============================================================================
def fraud_screen(app, today_date):
    """Returns (risk_score, auto_flag_status, triggered flag payloads)."""
    flags = []
    invoice_date = to_date(app["invoice_date"])

    # Rule A — SAME_SERVICE_ADDRESS: half-open trailing 30-day window anchored
    # on this application's invoice_date: [invoice_date - 30d, invoice_date).
    window_a_start = invoice_date - timedelta(days=SAME_SERVICE_ADDRESS_WINDOW_DAYS)
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["program_year_id"] != app["program_year_id"]:
            continue
        if other["status"] not in COMMITTED_STATUSES:
            continue
        if other["service_address"] != app["service_address"]:
            continue
        other_invoice = to_date(other["invoice_date"])
        if window_a_start <= other_invoice < invoice_date:
            flags.append(
                {
                    "flag_kind": "SAME_SERVICE_ADDRESS",
                    "weight": SAME_SERVICE_ADDRESS_WEIGHT,
                    "detail": (
                        "Another application (%s) in this program year shares "
                        "service_address '%s' with invoice_date %s inside the "
                        "trailing 30-day window before this application's "
                        "invoice_date %s"
                        % (
                            other["id"],
                            app["service_address"],
                            other["invoice_date"],
                            app["invoice_date"],
                        )
                    ),
                }
            )
            break

    # Rule B — ALLY_BURST: closed trailing 7-day window anchored on today,
    # counting this application itself.
    window_b_start = today_date - timedelta(days=ALLY_BURST_WINDOW_DAYS)
    burst_count = 1  # the application now being submitted
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["trade_ally_id"] != app["trade_ally_id"]:
            continue
        if other["program_year_id"] != app["program_year_id"]:
            continue
        if other["status"] not in COMMITTED_STATUSES:
            continue
        if other["submitted_at"] is None:
            continue
        if window_b_start <= submitted_date(other) <= today_date:
            burst_count += 1
    if burst_count >= ALLY_BURST_COUNT:
        flags.append(
            {
                "flag_kind": "ALLY_BURST",
                "weight": ALLY_BURST_WEIGHT,
                "detail": (
                    "Trade ally %s has %d applications submitted within the "
                    "trailing 7-day window ending %s (threshold %d)"
                    % (app["trade_ally_id"], burst_count, today_date.isoformat(),
                       ALLY_BURST_COUNT)
                ),
            }
        )

    # Rule C — INVOICE_GAP_SMALL: invoice_date within the closed 7-day window
    # ending today.
    if window_b_start <= invoice_date <= today_date:
        flags.append(
            {
                "flag_kind": "INVOICE_GAP_SMALL",
                "weight": INVOICE_GAP_WEIGHT,
                "detail": (
                    "invoice_date %s is within %d days of the current date %s"
                    % (app["invoice_date"], INVOICE_GAP_WINDOW_DAYS,
                       today_date.isoformat())
                ),
            }
        )

    risk_score = sum(f["weight"] for f in flags)
    auto_flag_status = "SUSPECT" if risk_score >= SUSPECT_THRESHOLD else "CLEAR"
    return risk_score, auto_flag_status, flags


# =============================================================================
# evaluation_adjusted_kwh (scaffold 1.3)
# =============================================================================
def latest_adjustment(program_year_id):
    """The adjustment with max effective_on; ties broken by earliest created."""
    rows = [a for a in store.adjustments.values() if a["program_year_id"] == program_year_id]
    if not rows:
        return None
    max_eff = max(a["effective_on"] for a in rows)
    candidates = [a for a in rows if a["effective_on"] == max_eff]
    return min(candidates, key=lambda a: a["_seq"])


def compute_adjusted_and_goal(py):
    """Returns (adjusted_kwh, goal_attainment_pct) without mutating."""
    adj = latest_adjustment(py["id"])
    if adj is None:
        adjusted = py["reported_kwh"]
    else:
        adjusted = (py["reported_kwh"] * adj["realization_rate_pct"]) // 100
    goal_pct = rhu_ratio(100 * adjusted, py["savings_goal_kwh"])
    return adjusted, goal_pct


def recompute_eval(py):
    adjusted, goal_pct = compute_adjusted_and_goal(py)
    py["adjusted_kwh"] = adjusted
    py["goal_attainment_pct"] = goal_pct


# =============================================================================
# trade_ally_performance_score (scaffold 1.3)
# =============================================================================
def compute_ally_performance(ally_id):
    passed = 0
    completed = 0
    for insp in store.inspections.values():
        parent = store.applications[insp["application_id"]]
        if parent["trade_ally_id"] != ally_id:
            continue
        if insp["outcome"] == "PASSED":
            passed += 1
            completed += 1
        elif insp["outcome"] == "FAILED":
            completed += 1
    if completed == 0:
        score = 100
    else:
        score = rhu_ratio(100 * passed, completed)
    if score >= PREFERRED_FLOOR:
        tier = "PREFERRED"
    elif score >= STANDARD_FLOOR:
        tier = "STANDARD"
    else:
        tier = "PROBATION"
    return score, tier


def recompute_ally(ally_id):
    """Recompute performance standing; a value change is a real mutation
    (version +1, updated_at refreshed per PRD section 2.5)."""
    ally = store.trade_allies[ally_id]
    score, tier = compute_ally_performance(ally_id)
    if score != ally["performance_score"] or tier != ally["standing_tier"]:
        ally["performance_score"] = score
        ally["standing_tier"] = tier
        touch(ally)
