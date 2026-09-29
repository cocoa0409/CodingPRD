"""Calculation rules (PRD sections 2.7, 2.9, 3.3-3.8)."""
from decimal import Decimal

from store import (dec, money, clamp, floor_int, ceil_int, whole_days_between,
                   add_days)

# --- constants ------------------------------------------------------------
PERIL_WEIGHT = {"HURRICANE": Decimal("1.15"), "WILDFIRE": Decimal("1.25"),
                "FLOOD": Decimal("1.20"), "HAIL": Decimal("0.95"),
                "WINTER_STORM": Decimal("0.90"), "EARTHQUAKE": Decimal("1.30")}
ACCESS_ADJUSTMENT = {"ACCESSIBLE": Decimal("0"), "RESTRICTED": Decimal("6"),
                     "INACCESSIBLE": Decimal("12")}
ALE_BONUS = Decimal("10")
SEVERITY_INDEX_WEIGHT = Decimal("20")
CAT_SEVERE_FLOOR = Decimal("75.00")
COMPLEX_FLOOR = Decimal("50.00")
STANDARD_FLOOR = Decimal("25.00")

LINE_ADVANCE_PCT = {"DWELLING": Decimal("0.30"), "CONTENTS": Decimal("0.25"),
                    "ALE": Decimal("0.50"), "OTHER_STRUCTURES": Decimal("0.20")}
TIER_MULTIPLIER = {"CAT_SEVERE": Decimal("1.00"), "COMPLEX": Decimal("0.85"),
                   "STANDARD": Decimal("0.60"), "FAST_TRACK": Decimal("0.40")}
TIER_RESERVE_FACTOR = {"CAT_SEVERE": Decimal("0.85"), "COMPLEX": Decimal("0.65"),
                       "STANDARD": Decimal("0.45"), "FAST_TRACK": Decimal("0.25")}

INDEPENDENT_RATE_FACTOR = Decimal("1.35")
PREMIUM_MID_FLOOR = Decimal("5000.00")
PREMIUM_HIGH_FLOOR = Decimal("20000.00")
PREMIUM_MID_RATE = Decimal("0.06")
PREMIUM_HIGH_RATE = Decimal("0.11")

PERIL_DEV_FACTOR = {"HURRICANE": Decimal("1.40"), "WILDFIRE": Decimal("1.55"),
                    "FLOOD": Decimal("1.65"), "HAIL": Decimal("1.20"),
                    "WINTER_STORM": Decimal("1.10"), "EARTHQUAKE": Decimal("1.80")}
REPORT_RATE = Decimal("0.35")

CREDENTIAL_PENALTY = {"VALID": Decimal("0"), "EXPIRING": Decimal("15"),
                      "WAIVED": Decimal("8"), "EXPIRED": Decimal("100")}
FATIGUE_STEP = Decimal("3")
FATIGUE_CAP = Decimal("30")
CERT_BONUS = Decimal("5")

DESK_LOSS_CEILING = Decimal("10000.00")
BASE_ACK_DAYS = 15
REST_BUFFER_HOURS = 12
LICENSE_WARNING_DAYS = 30
MAX_REOPENS = 2
RESTRICTED_STRAIN_THRESHOLD = 3
FROZEN_STRAIN_THRESHOLD = 8

POSTURE_ORDER = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}


def stricter(a, b):
    return a if POSTURE_ORDER[a] >= POSTURE_ORDER[b] else b


# --- claim severity -------------------------------------------------------
def severity_score(claim, event):
    lines = claim["coverage_lines"]
    total_limit = sum((dec(l["limit_amount"]) for l in lines), Decimal(0))
    divisor = total_limit if total_limit >= Decimal(1) else Decimal(1)
    ratio = dec(claim["reported_loss_amount"]) / divisor
    base = Decimal(100) * (ratio if ratio < Decimal(1) else Decimal(1))
    weight = PERIL_WEIGHT[event["peril_type"]]
    access = ACCESS_ADJUSTMENT[claim["access_status"]]
    ale = any(l["coverage_code"] == "ALE" and dec(l["estimated_damage_amount"]) > 0
              for l in lines)
    raw = (base * weight) + access + (ALE_BONUS if ale else Decimal(0)) \
        + (SEVERITY_INDEX_WEIGHT * dec(event["expected_severity_index"]))
    score = money(clamp(raw, Decimal(0), Decimal(100)))
    if score >= CAT_SEVERE_FLOOR:
        tier = "CAT_SEVERE"
    elif score >= COMPLEX_FLOOR:
        tier = "COMPLEX"
    elif score >= STANDARD_FLOOR:
        tier = "STANDARD"
    else:
        tier = "FAST_TRACK"
    return score, tier


# --- initial case reserve (raw sum, single rounding at the end) -----------
def initial_case_reserve(claim):
    eligible = Decimal(0)
    for line in claim["coverage_lines"]:
        capped = min(dec(line["estimated_damage_amount"]), dec(line["limit_amount"]))
        val = capped - dec(line["deductible_amount"])
        if val < 0:
            val = Decimal(0)
        eligible += val
    basis = max(dec(claim["reported_loss_amount"]), eligible)
    return money(basis * TIER_RESERVE_FACTOR[claim["triage_tier"]])


# --- advance cap (each line rounded first, then summed) -------------------
def advance_cap(claim, mandate_pct):
    cap_from_lines = Decimal(0)
    for line in claim["coverage_lines"]:
        capped = min(dec(line["estimated_damage_amount"]), dec(line["limit_amount"]))
        val = capped - dec(line["deductible_amount"])
        if val < 0:
            val = Decimal(0)
        cap_from_lines += money(val * LINE_ADVANCE_PCT[line["coverage_code"]])
    if mandate_pct is None:
        mandate_floor = money(0)
    else:
        mandate_floor = money(dec(claim["reported_loss_amount"]) * dec(mandate_pct))
    tiered = money(cap_from_lines * TIER_MULTIPLIER[claim["triage_tier"]])
    return max(tiered, mandate_floor)


# --- reserve revision -----------------------------------------------------
def reserve_revision_delta(claim, current_case_reserve):
    total_deductible = sum((dec(l["deductible_amount"]) for l in claim["coverage_lines"]),
                           Decimal(0))
    target = dec(claim["verified_damage_amount"]) - total_deductible
    if target < 0:
        target = Decimal(0)
    target = money(target)
    return money(target - dec(current_case_reserve))


# --- inspection mode -----------------------------------------------------
def inspection_mode(claim):
    access = claim["access_status"]
    tier = claim.get("triage_tier")
    if access == "INACCESSIBLE" and tier in ("COMPLEX", "CAT_SEVERE"):
        return "AERIAL"
    if access == "INACCESSIBLE":
        return "DESK"
    if access == "RESTRICTED" and tier == "FAST_TRACK":
        return "DESK"
    if tier == "FAST_TRACK" and dec(claim["reported_loss_amount"]) <= DESK_LOSS_CEILING:
        return "DESK"
    return "FIELD"


# --- acknowledgement deadline -------------------------------------------
def claim_deadline(anchor, extension_days):
    return add_days(add_days(anchor, BASE_ACK_DAYS), extension_days)


# --- deployment cost -----------------------------------------------------
def deployment_cost(deployment, adjuster, block, variant):
    if variant == "PROVISIONAL":
        settle_end = deployment["window_end_utc"]
        per_diem_eligible = 1
    else:
        settle_end = min(deployment["window_end_utc"], deployment["demobilized_at_utc"])
        per_diem_eligible = 1 if (adjuster["employment_type"] == "STAFF"
                                 or deployment.get("housing_block_id") is None) else 0
    nights = whole_days_between(deployment["window_start_utc"], settle_end)
    if nights < 1:
        nights = 1
    nights_d = Decimal(nights)
    rate_factor = Decimal("1.00") if adjuster["employment_type"] == "STAFF" \
        else INDEPENDENT_RATE_FACTOR
    base_labor = money(dec(adjuster["daily_rate"]) * rate_factor * nights_d)
    per_diem_total = money(dec(adjuster["per_diem_rate"]) * nights_d
                          * Decimal(per_diem_eligible))
    if deployment["role_type"] != "DESK" and deployment.get("housing_block_id") \
            and block is not None:
        housing_share = money(dec(block["nightly_rate"])
                              * Decimal(int(deployment["rooms_reserved"])) * nights_d)
    else:
        housing_share = money(0)
    subtotal = money(base_labor + per_diem_total + housing_share)
    if subtotal >= PREMIUM_HIGH_FLOOR:
        tier, rate = "TIER_HIGH", PREMIUM_HIGH_RATE
    elif subtotal >= PREMIUM_MID_FLOOR:
        tier, rate = "TIER_MID", PREMIUM_MID_RATE
    else:
        tier, rate = "TIER_NONE", Decimal("0.00")
    premium = money(subtotal * rate)
    return money(subtotal + premium), tier


# --- adjuster surge capacity score ---------------------------------------
def surge_capacity_score(adjuster, open_assignment_count, cumulative_hours):
    load_ratio = dec(open_assignment_count) / dec(adjuster["max_open_claims"])
    if load_ratio > Decimal(1):
        load_ratio = Decimal(1)
    availability = Decimal(100) * (Decimal(1) - load_ratio)
    penalty = CREDENTIAL_PENALTY[adjuster["credential_status"]]
    full_days = floor_int(dec(cumulative_hours) / Decimal(24))
    fatigue = Decimal(full_days) * FATIGUE_STEP
    if fatigue > FATIGUE_CAP:
        fatigue = FATIGUE_CAP
    bonus = (CERT_BONUS if adjuster["desk_certified"] else Decimal(0)) \
        + (CERT_BONUS if adjuster["aerial_certified"] else Decimal(0))
    raw = availability - penalty - fatigue + bonus
    return money(clamp(raw, Decimal(0), Decimal(100)))


# --- event loss estimate -------------------------------------------------
def event_loss_estimate(event, method, reported_component, initial_case_claim_count):
    reported = money(reported_component)
    if method == "EXPOSURE_BASED":
        modeled = dec(event["exposure_count"]) * dec(event["avg_insured_value"]) \
            * dec(event["expected_severity_index"]) \
            * PERIL_DEV_FACTOR[event["peril_type"]]
        ibnr = modeled - reported
        if ibnr < 0:
            ibnr = Decimal(0)
        ibnr = money(ibnr)
    else:
        count = initial_case_claim_count
        divisor = Decimal(count) if count > 0 else Decimal(1)
        avg = reported / divisor
        ultimate = ceil_int(dec(event["exposure_count"])
                            * dec(event["expected_severity_index"]) * REPORT_RATE)
        delta = ultimate - count
        if delta < 0:
            delta = 0
        ibnr = avg * Decimal(delta)
        if ibnr < 0:
            ibnr = Decimal(0)
        ibnr = money(ibnr)
    return reported, ibnr, money(reported + ibnr)
