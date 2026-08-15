"""Calculation rules (scaffold Table 3 / PRD 3.3, 3.4, 3.6, 3.8).

All money is integer cents; rounding is round-half-up everywhere (PRD 2.6).
"""
from datetime import timedelta
from decimal import Decimal

from db import db, touch
from util import dec, round_half_up, round_half_up_int

BURDEN_CAP_MINUTES = 120
REAUTH_THRESHOLD_PCT = Decimal("20.00")


def compute_steering(policy, patient, req,
                     home_allowed_cents, hospital_allowed_cents,
                     home_billed_cents, hospital_billed_cents):
    """site_steering_score: dual variant (COST_RATIO / TRAVEL_BURDEN), 3dp half-up."""
    minutes = int(patient.get("travel_minutes_to_hospital") or 0)
    minutes = max(0, min(minutes, BURDEN_CAP_MINUTES))
    burden_index = Decimal(minutes) / Decimal(BURDEN_CAP_MINUTES)

    if patient.get("rural_resident"):
        variant = "TRAVEL_BURDEN"
        denom = Decimal(int(home_billed_cents))
        cost_ratio = (Decimal(int(hospital_billed_cents)) / denom) if denom != 0 else Decimal(0)
        score = Decimal("1.0") * cost_ratio + Decimal("1.0") * burden_index
    else:
        variant = "COST_RATIO"
        denom = Decimal(int(home_allowed_cents))
        cost_ratio = (Decimal(int(hospital_allowed_cents)) / denom) if denom != 0 else Decimal(0)
        score = Decimal("1.0") * cost_ratio + Decimal("0.5") * burden_index

    steer_score = round_half_up(score, 3)

    requested = req["requested_site_type"]
    site_policy = policy["site_policy"]
    if site_policy == "NO_STEERING":
        recommended, steered = requested, False
    elif steer_score >= dec(policy["steer_threshold"]):
        recommended = "HOME" if site_policy == "STEER_TO_HOME" else "OFFICE"
        steered = (recommended != requested)
    else:
        recommended, steered = requested, False
    return variant, float(steer_score), recommended, steered


def compute_validity_window(policy, patient, decision_dt):
    """auth_validity_window: valid_from = decision date at 00:00:00Z;
    valid_to = min(valid_from + base_days, plan_year_end, valid_from + max_course_days)."""
    valid_from = decision_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if policy["benefit_channel"] == "PHARMACY":
        base_days = int(policy["pharmacy_validity_days"])
    else:
        base_days = int(policy["validity_days"])
    valid_to = min(
        valid_from + timedelta(days=base_days),
        patient["plan_year_end"],
        valid_from + timedelta(days=int(policy["max_course_days"])),
    )
    return valid_from, valid_to


def compute_delta_pct(new_dose_mg, approved_dose_mg):
    """dose_delta_pct: |new - approved| / approved * 100, 2dp half-up; reauth at >= 20.00."""
    approved = int(approved_dose_mg)
    if approved == 0:
        delta = Decimal("0.00")
    else:
        delta = round_half_up(
            Decimal(abs(int(new_dose_mg) - approved)) / Decimal(approved) * Decimal(100), 2)
    return float(delta), bool(delta >= REAUTH_THRESHOLD_PCT)


def compute_estimate(clearance, now, skip_touch_ids=frozenset()):
    """patient_responsibility_estimate: deductible-then-coinsurance waterfall over
    ACTIVE line items in creation order; per-line half-up rounding, then sum;
    capped by the patient's oop_remaining_cents. Patient row is never mutated.

    Re-writes each ACTIVE line's patient_share_cents; lines whose stored share
    actually changes (except freshly created ones in skip_touch_ids) count as
    mutated and get their own version bump per PRD 2.5.
    """
    req = db["authorization_requests"][clearance["authorization_request_id"]]
    policy = db["payer_policies"][req["policy_id"]]
    patient = db["patients"][req["patient_id"]]

    lines = [l for l in db["responsibility_line_items"].values()
             if l["financial_clearance_id"] == clearance["id"] and l["status"] == "ACTIVE"]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))

    deductible_remaining = max(int(patient["deductible_remaining_cents"]), 0)
    discount = dec(policy["discount_rate"])
    coins_pct = dec(policy["coinsurance_pct"])

    total = 0
    for line in lines:
        if clearance["method"] == "ACCUMULATOR_METHOD":
            base = int(line["allowed_amount_cents"])
        else:  # BILLED_CHARGES_METHOD
            base = round_half_up_int(Decimal(int(line["billed_charges_cents"])) * discount)
        ded_applied = min(base, deductible_remaining)
        deductible_remaining -= ded_applied
        coins = round_half_up_int(Decimal(base - ded_applied) * coins_pct)
        share = ded_applied + coins
        if line["patient_share_cents"] != share:
            line["patient_share_cents"] = share
            if line["id"] not in skip_touch_ids:
                touch(line, now)
        total += share
    return min(total, int(patient["oop_remaining_cents"]))


def recompute_clearance(clearance, now, bump=True, skip_touch_ids=frozenset()):
    estimate = compute_estimate(clearance, now, skip_touch_ids=skip_touch_ids)
    clearance["estimated_patient_responsibility_cents"] = estimate
    if bump:
        touch(clearance, now)
    return estimate
