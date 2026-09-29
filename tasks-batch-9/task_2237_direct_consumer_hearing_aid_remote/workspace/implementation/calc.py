"""The sixteen normative calculations (PRD 2.6 and section 3).

Every monetary value is an integer number of cents rounded half up; the
declared one-decimal quantities are rounded half up exactly once.  Rounding
ORDER is normative and is reproduced literally below.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import db, now, days, table_rows

# ------------------------------------------------------------------ constants
SEVERE_LOSS_DB = Decimal("71.0")
ASYMMETRY_DB = Decimal("15.0")
ADVISORY_REFERRAL_THRESHOLD = Decimal("2.5")

W_PTN = Decimal("0.40")
W_DIFF = Decimal("0.25")
W_SIN = Decimal("0.20")
W_ASYM = Decimal("0.15")
PROVIDER_ATTENUATION = Decimal("0.85")
MANDATORY_FLAG_POINTS = Decimal("6.0")
ADVISORY_POINT_FACTOR = Decimal("2.0")
BAND_MODERATE_MIN = Decimal("35.0")
BAND_HIGH_MIN = Decimal("65.0")

SALES_TAX_RATE = Decimal("0.0725")

SECONDS_PER_DAY = 86400
MAX_TOTAL_PAUSED_DAYS = 60

ACCESSORY_RATE_FACTOR = Decimal("0.5")
DAMAGE_RATE = Decimal("0.15")
REFURB_RATE = Decimal("0.05")

REPAIR_ELIGIBLE_CAP_CENTS = 50000
CARE_PLAN_ELIGIBLE_CYCLES = 12

PREMIUM_SURCHARGE_CENTS = 2000
SERVICE_FEE_CENTS = 495
SERVICE_FEE_WAIVER_THRESHOLD_CENTS = 9900
LOYALTY_TIER1_CYCLES = 6
LOYALTY_TIER1_RATE = Decimal("0.10")
LOYALTY_TIER2_CYCLES = 12
LOYALTY_TIER2_RATE = Decimal("0.15")
LOYALTY_DISCOUNT_CAP_CENTS = 1500
CYCLE_DAYS = 30

BASE_DEDUCTIBLE_CENTS = 9900
AGE_TIER1_MONTHS = 12
AGE_TIER1_MULT = Decimal("0.5")
AGE_TIER2_MONTHS = 24
AGE_TIER2_MULT = Decimal("1.0")
AGE_TIER3_MULT = Decimal("1.5")
SECOND_CLAIM_SURCHARGE_CENTS = 5000
KIND_FACTOR = {"DEFECT": Decimal("0.0"), "DAMAGE": Decimal("0.75"), "LOSS": Decimal("1.0")}

FREE_EXCHANGE_COUNT = 2
EXCHANGE_FEE_CENTS = 1900
PREMIUM_DISCOUNT_FACTOR = Decimal("0.5")

SLA_CREDIT_PER_DAY_CENTS = 500
SLA_CREDIT_CAP_CENTS = 5000
PREMIUM_CREDIT_MULT = Decimal("2.0")

NO_SHOW_FEE_CENTS = 2500
LATE_CANCEL_FEE_CENTS = 1000
WARRANTY_DAYS = 730
RETURN_DEADLINE_DAYS = 14
FAILURE_PAUSE_THRESHOLD = Decimal("25.0")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def cents(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def one_dp(value):
    return float(D(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------- 1. red_flag_referral_trigger
SYMPTOM_TABLE = (
    ("SUDDEN_LOSS", "SUDDEN_UNILATERAL_LOSS", "MANDATORY_REFERRAL", Decimal("0.0")),
    ("DRAINAGE", "ACTIVE_DRAINAGE", "MANDATORY_REFERRAL", Decimal("0.0")),
    ("VERTIGO", "VERTIGO", "MANDATORY_REFERRAL", Decimal("0.0")),
    ("DEFORMITY", "VISIBLE_DEFORMITY", "MANDATORY_REFERRAL", Decimal("0.0")),
    ("PAIN", "EAR_PAIN", "ADVISORY", Decimal("1.5")),
    ("TINNITUS_ONE_EAR", "UNILATERAL_TINNITUS", "ADVISORY", Decimal("1.0")),
    ("WAX", "IMPACTED_CERUMEN", "ADVISORY", Decimal("1.0")),
)


def red_flag_referral_trigger(session, patient, policy):
    """Returns (findings, outcome, advisory_sum) with findings in detection order."""
    findings = []
    seen = set()

    def add(code, severity, weight):
        if code in seen:
            return
        seen.add(code)
        findings.append({"code": code, "severity": severity, "weight": one_dp(weight)})

    codes = session.get("symptom_codes") or []
    for symptom, code, severity, weight in SYMPTOM_TABLE:
        if symptom in codes:
            add(code, severity, weight)
    min_age = 18 if policy is None else int(policy.get("min_age_years", 18))
    if int(patient.get("age_years") or 0) < min_age:
        add("AGE_BELOW_MINIMUM", "MANDATORY_REFERRAL", Decimal("0.0"))
    if D(session.get("pure_tone_avg_db")) >= SEVERE_LOSS_DB:
        add("SEVERE_LOSS_THRESHOLD", "MANDATORY_REFERRAL", Decimal("0.0"))
    if D(session.get("asymmetry_db")) >= ASYMMETRY_DB:
        add("SUDDEN_UNILATERAL_LOSS", "MANDATORY_REFERRAL", Decimal("0.0"))

    mandatory = [f for f in findings if f["severity"] == "MANDATORY_REFERRAL"]
    advisory_sum = D(one_dp(sum((D(f["weight"]) for f in findings
                                if f["severity"] == "ADVISORY"), Decimal("0"))))
    if mandatory:
        outcome = "RED_FLAG"
    elif advisory_sum >= ADVISORY_REFERRAL_THRESHOLD:
        outcome = "RED_FLAG"
    elif advisory_sum > 0:
        outcome = "ADVISORY_PASS"
    else:
        outcome = "PASS"
    return findings, outcome, one_dp(advisory_sum)


# ----------------------------------------------------- 2. candidacy_risk_score
def risk_band(score):
    value = D(score)
    if value < BAND_MODERATE_MIN:
        return "LOW"
    if value < BAND_HIGH_MIN:
        return "MODERATE"
    return "HIGH"


def _risk_base(session):
    ptn = min(Decimal("1.0"), D(session.get("pure_tone_avg_db")) / Decimal("90.0"))
    diff = D(session.get("self_reported_difficulty_score")) / Decimal("40.0")
    sin = Decimal("1.0") - (D(session.get("speech_in_noise_pct")) / Decimal("100.0"))
    asym = min(Decimal("1.0"), D(session.get("asymmetry_db")) / Decimal("25.0"))
    return Decimal("100.0") * (W_PTN * ptn + W_DIFF * diff + W_SIN * sin + W_ASYM * asym)


def candidacy_risk_score(session, variant, cleared_mandatory=0, advisory_weight_total=0.0):
    if session is None:
        return 0.0
    base = _risk_base(session)
    if variant == "PROVISIONAL_SELF_REPORTED":
        return one_dp(base)
    adjusted = (base * PROVIDER_ATTENUATION
                + MANDATORY_FLAG_POINTS * D(cleared_mandatory)
                + ADVISORY_POINT_FACTOR * D(advisory_weight_total))
    return one_dp(min(Decimal("100.0"), adjusted))


def latest_scored_session(patient_id):
    rows = [s for s in table_rows(db.screening_sessions)
            if s.get("patient_id") == patient_id and s.get("status") == "SCORED"]
    if not rows:
        return None
    rows.sort(key=lambda s: (s.get("scored_at") or s["created_at"], s["created_at"],
                             s.get("_seq", 0)))
    return rows[-1]


# ------------------------------------------------- 3. order_total_composition
def order_total_composition(order):
    device_subtotal = int(order["list_price_cents"]) - int(order["discount_cents"])
    taxable_base = device_subtotal + int(order["accessory_subtotal_cents"])
    tax = cents(D(taxable_base) * SALES_TAX_RATE)
    total = device_subtotal + int(order["accessory_subtotal_cents"]) + int(order["shipping_cents"]) + tax
    order["tax_cents"] = tax
    order["total_cents"] = total
    return order


# --------------------------------------------------------- 4. trial_days_used
def _interval_bounds(interval, window_end):
    start = interval.get("pause_start_utc")
    end = interval.get("pause_end_utc")
    if end is None:
        end = window_end
    return start, end


def _paused_seconds(intervals, window_end):
    prepared = []
    for index, interval in enumerate(intervals or []):
        start, end = _interval_bounds(interval, window_end)
        if start is None:
            continue
        if end < start:
            end = start
        prepared.append((start, end, index))
    prepared.sort(key=lambda item: (item[0], item[2]))
    merged = []
    for start, end, _ in prepared:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total = 0
    for start, end in merged:
        total += max(0, int((end - start).total_seconds()))
    return total


def trial_days_used(trial):
    """Fixpoint recompute of paused_days / days_used / effective_end_utc."""
    started = trial.get("started_at")
    nominal_end = trial.get("nominal_end_utc")
    if started is None or nominal_end is None:
        return trial
    extension = int(trial.get("extension_days_granted") or 0)
    paused_days = int(trial.get("paused_days") or 0)
    clock = now()
    for _ in range(24):
        effective_end = nominal_end + days(paused_days + extension)
        window_end = min(clock, effective_end)
        seconds = _paused_seconds(trial.get("pause_intervals"), window_end)
        new_paused = int(seconds // SECONDS_PER_DAY)
        if new_paused == paused_days:
            break
        paused_days = new_paused
    effective_end = nominal_end + days(paused_days + extension)
    window_end = min(clock, effective_end)
    elapsed = int(max(0, (window_end - started).total_seconds()) // SECONDS_PER_DAY)
    trial["paused_days"] = paused_days
    trial["days_used"] = max(0, elapsed - paused_days)
    trial["effective_end_utc"] = effective_end
    return trial


# -------------------------------------------------- 5. return_refund_settlement
def return_refund_settlement(auth, order, policy):
    device_component = int(order["list_price_cents"]) - int(order["discount_cents"])
    accessory_component = int(order["accessory_subtotal_cents"])
    mode = order.get("pinned_restocking_mode")
    days_used_at_issue = int(auth.get("days_used_at_issue") or 0)

    if mode == "PROHIBITED":
        variant = "WAIVED"
    elif days_used_at_issue == 0:
        variant = "WAIVED"
    elif mode == "FLAT_PCT":
        variant = "FLAT_PCT"
    else:
        variant = "PRORATED_DAILY"

    pct = D(policy.get("restocking_fee_pct") or 0)
    daily_rate = int(policy.get("restocking_daily_rate_cents") or 0)
    cap = int(policy.get("restocking_fee_cap_cents") or 0)
    shipping_refundable = bool(policy.get("shipping_refundable"))

    if variant == "FLAT_PCT":
        device_restock = cents(D(device_component) * pct)
        accessory_restock = cents(D(accessory_component) * pct * ACCESSORY_RATE_FACTOR)
    elif variant == "PRORATED_DAILY":
        device_restock = daily_rate * min(days_used_at_issue, int(order["pinned_trial_days"]))
        accessory_restock = 0
    else:
        device_restock = 0
        accessory_restock = 0

    grade = auth.get("inspection_grade")
    if grade == "DAMAGED":
        damage_surcharge = cents(D(device_component) * DAMAGE_RATE)
    elif grade == "REFURBISHABLE":
        damage_surcharge = cents(D(device_component) * REFURB_RATE)
    else:
        damage_surcharge = 0

    raw = device_restock + accessory_restock + damage_surcharge
    restocking = raw if cap == 0 else min(raw, cap)
    non_refundable_shipping = 0 if shipping_refundable else int(order["shipping_cents"])
    refund = max(0, int(order["captured_cents"]) - restocking - non_refundable_shipping)

    auth["restocking_variant"] = variant
    auth["restocking_fee_cents"] = restocking
    auth["non_refundable_shipping_cents"] = non_refundable_shipping
    auth["refund_amount_cents"] = refund
    return auth


# ------------------------------------------------- 6. reimbursement_allocation
def reimbursement_allocation(claim):
    if not claim.get("documentation_complete"):
        eligible = 0
    elif claim["subject_kind"] == "DEVICE_ORDER":
        order = db.device_orders.get(claim.get("device_order_id")) or {}
        available = max(0, int(order.get("captured_cents") or 0)
                        - int(order.get("refunded_cents") or 0)
                        - int(order.get("retained_cents") or 0))
        eligible = min(int(claim["claimed_amount_cents"]), available)
    elif claim["subject_kind"] == "REPAIR_ORDER":
        eligible = min(int(claim["claimed_amount_cents"]), REPAIR_ELIGIBLE_CAP_CENTS)
    else:
        plan = db.care_plan_subscriptions.get(claim.get("care_plan_subscription_id")) or {}
        eligible = min(int(claim["claimed_amount_cents"]),
                       int(plan.get("last_charge_cents") or 0) * CARE_PLAN_ELIGIBLE_CYCLES)

    insurance = min(eligible, max(0, int(claim.get("insurance_benefit_cap_cents") or 0)
                                  - int(claim.get("insurance_benefit_used_cents") or 0)))
    remaining = eligible - insurance
    fsa = min(remaining, int(claim.get("fsa_balance_cents") or 0))
    claim["eligible_amount_cents"] = eligible
    claim["insurance_paid_cents"] = insurance
    claim["fsa_paid_cents"] = fsa
    claim["patient_responsibility_cents"] = eligible - insurance - fsa
    return claim


# --------------------------------------------------- 7. care_plan_cycle_charge
def care_plan_cycle_charge(plan, tier=None):
    plan_tier = tier or plan["plan_tier"]
    subtotal = int(plan["base_fee_cents"]) + (PREMIUM_SURCHARGE_CENTS if plan_tier == "PREMIUM" else 0)
    service_fee = 0 if subtotal >= SERVICE_FEE_WAIVER_THRESHOLD_CENTS else SERVICE_FEE_CENTS
    base = subtotal + service_fee
    ordinal = int(plan.get("cycle_ordinal") or 0)
    if ordinal >= LOYALTY_TIER2_CYCLES:
        rate = LOYALTY_TIER2_RATE
    elif ordinal >= LOYALTY_TIER1_CYCLES:
        rate = LOYALTY_TIER1_RATE
    else:
        rate = Decimal("0.0")
    loyalty = min(LOYALTY_DISCOUNT_CAP_CENTS, cents(D(base) * rate))
    last_charge = max(0, base - loyalty)
    return {
        "subtotal_cents": subtotal,
        "service_fee_cents": service_fee,
        "fee_inclusive_base_cents": base,
        "loyalty_discount_cents": loyalty,
        "last_charge_cents": last_charge,
    }


def prorated_charge(last_charge_cents, cycle_end_utc):
    if cycle_end_utc is None:
        return int(last_charge_cents)
    seconds = (cycle_end_utc - now()).total_seconds()
    remaining_days = int(math.ceil(seconds / float(SECONDS_PER_DAY)))
    return cents(D(last_charge_cents) * D(remaining_days) / D(CYCLE_DAYS))


# ------------------------------------------------------ 8. warranty_deductible
def months_between(start, end):
    if start is None or end is None:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    anchor = start.replace(year=start.year + (start.month - 1 + months) // 12,
                           month=(start.month - 1 + months) % 12 + 1)
    if anchor > end:
        months -= 1
    return max(0, months)


def warranty_deductible(claim, device):
    age_months = months_between(device.get("shipped_at"), now())
    if age_months <= AGE_TIER1_MONTHS:
        age_mult = AGE_TIER1_MULT
    elif age_months <= AGE_TIER2_MONTHS:
        age_mult = AGE_TIER2_MULT
    else:
        age_mult = AGE_TIER3_MULT
    kind_factor = KIND_FACTOR.get(claim["claim_kind"], Decimal("0.0"))
    surcharge = 0 if int(claim.get("claim_ordinal") or 1) == 1 else SECOND_CLAIM_SURCHARGE_CENTS
    deductible = cents(D(BASE_DEDUCTIBLE_CENTS) * age_mult * kind_factor) + surcharge
    return age_months, deductible


# ---------------------------------------------------- 9. provider_daily_capacity
CAPACITY_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED")


def booked_minutes(provider_id, focus_date, exclude_id=None):
    total = 0
    for session in db.remote_fitting_sessions.values():
        if session.get("provider_id") != provider_id:
            continue
        if exclude_id is not None and session["id"] == exclude_id:
            continue
        if session.get("status") not in CAPACITY_STATUSES:
            continue
        start = session.get("scheduled_start_utc")
        if start is None or start.date() != focus_date:
            continue
        total += int(session.get("duration_minutes") or 0)
    return total


def utilization(booked, capacity):
    if not capacity:
        return 0.0
    return one_dp(Decimal("100.0") * D(booked) / D(capacity))


def capacity_accepts(provider, focus_date, duration_minutes, exclude_id=None):
    booked = booked_minutes(provider["id"], focus_date, exclude_id)
    return booked + int(duration_minutes) <= int(provider["daily_capacity_minutes"]), booked


# ------------------------------------------------------ 10. fitting_slot_overlap
def slot_conflict(provider, cand_start, cand_end, exclude_id=None):
    buffer_minutes = int(provider.get("buffer_minutes") or 0)
    widened_start = cand_start - days(0) - _minutes(buffer_minutes)
    widened_end = cand_end + _minutes(buffer_minutes)
    for session in db.remote_fitting_sessions.values():
        if session.get("provider_id") != provider["id"]:
            continue
        if exclude_id is not None and session["id"] == exclude_id:
            continue
        if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        start = session.get("scheduled_start_utc")
        end = session.get("scheduled_end_utc")
        if start is None or end is None:
            continue
        if widened_start < end and start < widened_end:
            return True
    return False


def _minutes(count):
    from datetime import timedelta
    return timedelta(minutes=count)


# ------------------------------------------- 11. trial_pause_interval_overlap
def check_pause_allowed(trial):
    for interval in trial.get("pause_intervals") or []:
        if interval.get("pause_end_utc") is None:
            raise ApiError("ERR_PAUSE_INTERVAL_OVERLAP")
    if int(trial.get("paused_days") or 0) >= MAX_TOTAL_PAUSED_DAYS:
        raise ApiError("ERR_PAUSE_BUDGET_EXHAUSTED")


# ---------------------------------------------------- 12. campaign_window_overlap
def campaign_window_conflict(campaign):
    start = campaign.get("window_start_utc")
    end = campaign.get("window_end_utc")
    for other in db.firmware_campaigns.values():
        if other["id"] == campaign["id"]:
            continue
        if other.get("model") != campaign.get("model"):
            continue
        if other.get("status") not in ("SCHEDULED", "ROLLING", "PAUSED"):
            continue
        other_start = other.get("window_start_utc")
        other_end = other.get("window_end_utc")
        if other_start is None or other_end is None:
            continue
        if start <= other_end and other_start <= end:
            return True
    return False


# --------------------------------------------------------- 13. fit_exchange_fee
def fit_exchange_fee(order, trial, plan):
    ordinal = 1 + sum(1 for x in db.fit_exchanges.values()
                      if x.get("device_order_id") == order["id"]
                      and x.get("status") in ("SHIPPED", "COMPLETED"))
    if trial is not None and trial.get("status") in ("ACTIVE", "PAUSED"):
        fee = 0
    elif ordinal <= FREE_EXCHANGE_COUNT:
        fee = 0
    elif (plan is not None and plan.get("plan_tier") == "PREMIUM"
          and plan.get("status") in ("ACTIVE", "PAST_DUE")):
        fee = cents(D(EXCHANGE_FEE_CENTS) * PREMIUM_DISCOUNT_FACTOR)
    else:
        fee = EXCHANGE_FEE_CENTS
    return ordinal, fee


# -------------------------------------------------------- 14. repair_sla_credit
def repair_sla_credit(repair, plan):
    received = repair.get("received_at")
    closed = repair.get("closed_at")
    if received is None or closed is None:
        return 0, 0
    turnaround = int(max(0, (closed - received).total_seconds()) // SECONDS_PER_DAY)
    days_over = max(0, turnaround - int(repair.get("sla_days") or 0))
    mult = PREMIUM_CREDIT_MULT if (plan is not None and plan.get("plan_tier") == "PREMIUM") else Decimal("1.0")
    credit = min(SLA_CREDIT_CAP_CENTS, cents(D(days_over) * D(SLA_CREDIT_PER_DAY_CENTS) * mult))
    return turnaround, credit


# --------------------------------------------------- 15. firmware_cohort_selection
def eligible_devices(campaign):
    from services import plan_for_device

    candidates = []
    for device in db.devices.values():
        if device.get("status") != "WITH_PATIENT":
            continue
        if device.get("model") != campaign.get("model"):
            continue
        if device.get("firmware_version") != campaign.get("from_version"):
            continue
        blocked = any(r.get("device_id") == device["id"]
                      and r.get("status") in ("KIT_SENT", "RECEIVED", "IN_REPAIR")
                      for r in db.repair_orders.values())
        if blocked:
            continue
        enrolled = any(fr.get("device_id") == device["id"]
                       and fr.get("firmware_campaign_id") == campaign["id"]
                       and fr.get("status") in ("PENDING", "OFFERED", "INSTALLING", "INSTALLED")
                       for fr in db.firmware_rollouts.values())
        if enrolled:
            continue
        if not campaign.get("is_mandatory_safety"):
            plan = plan_for_device(device)
            if plan is None or plan.get("status") not in ("ACTIVE", "TRIALING"):
                continue
            if not plan.get("firmware_auto_update_enabled"):
                continue
        candidates.append(device)
    candidates.sort(key=lambda d: (d.get("warranty_expires_at") or now(),
                                   d["created_at"], d.get("serial_number") or ""))
    return candidates


# ------------------------------------------------ 16. referral_provider_selection
def select_referral_provider(patient, referral, cand_start, cand_end, duration_minutes):
    focus_date = cand_start.date()
    candidates = []
    triggering = referral.get("triggering_screening_session_id")
    invalidator = None
    if triggering:
        session = db.screening_sessions.get(triggering)
        if session is not None:
            invalidator = session.get("_invalidated_by_provider_id")
    for provider in table_rows(db.providers):
        if provider.get("provider_type") != "LICENSED_AUDIOLOGIST":
            continue
        if provider.get("status") != "ACTIVE":
            continue
        if patient.get("state_code") not in (provider.get("licensed_state_codes") or []):
            continue
        if invalidator is not None and provider["id"] == invalidator:
            continue
        accepts, booked = capacity_accepts(provider, focus_date, duration_minutes)
        if not accepts:
            continue
        if slot_conflict(provider, cand_start, cand_end):
            continue
        candidates.append((utilization(booked, provider["daily_capacity_minutes"]),
                           provider["created_at"], provider.get("npi") or "", provider))
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_PROVIDER")
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]
