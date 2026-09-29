"""The money calculations: FPG percentages, the eight-step patient charge, the
PPS encounter rate and the wraparound residual (PRD 3.4, 3.5, 3.6, 3.7)."""

import db
from services import fee_schedule as fs
from validation import dec, money, num, round_half_up


def fpg_percent(declared_annual_income_cents, household_size, guideline):
    """income / guideline_amount * 100, rounded half up to 2 decimals."""
    amount = fs.guideline_amount_cents(guideline, household_size)
    if amount == 0:
        return num(0, 2)
    return num(dec(declared_annual_income_cents) / dec(amount) * dec(100), 2)


def granted_waiver(encounter_id):
    for waiver in db.db.waivers.values():
        if waiver["encounter_id"] == encounter_id and waiver["status"] == "GRANTED":
            return waiver
    return None


# --------------------------------------------------------------------------- #
# patient charge — steps S1..S8, with exactly one rounding (step S4)
# --------------------------------------------------------------------------- #


def patient_charge(payer_type, gross_charge_cents, schedule, verification):
    result = {
        "patient_charge_cents": 0,
        "charge_basis": "THIRD_PARTY",
        "sliding_fee_applied": False,
        "pinned_discount_tier_id": None,
        "income_verification_id": verification["id"] if verification else None,
    }

    # S1 — third-party payers: no sliding fee logic runs at all.
    if payer_type in ("MEDICARE", "MEDICAID_FFS", "PRIVATE"):
        return result

    # S2 — no documentation.
    if verification is None:
        result["charge_basis"] = "FULL_CHARGE_UNVERIFIED"
        result["income_verification_id"] = None
        result["patient_charge_cents"] = gross_charge_cents if payer_type == "SELF_PAY" else 0
        return result

    # S3 — tier selection on the pinned schedule under the half-open band rule.
    tier = fs.select_tier(schedule["id"], verification["fpg_percent"])
    if tier is None:
        result["charge_basis"] = "FULL_CHARGE_UNVERIFIED"
        result["income_verification_id"] = None
        result["patient_charge_cents"] = gross_charge_cents if payer_type == "SELF_PAY" else 0
        return result

    nominal = schedule["nominal_fee_cents"]

    # S4 — the only rounding in the whole calculation.
    if tier["discount_kind"] == "NOMINAL":
        raw = nominal
    elif tier["discount_kind"] == "PERCENT_DISCOUNT":
        raw = money(dec(gross_charge_cents) * (dec(1) - dec(tier["discount_pct"])))
    else:
        raw = gross_charge_cents

    # S5 — cap at the gross charge.
    if raw > gross_charge_cents:
        raw = gross_charge_cents

    # S6 — nominal floor for percent discounts, still capped at gross.
    if tier["discount_kind"] == "PERCENT_DISCOUNT" and raw < nominal:
        raw = min(nominal, gross_charge_cents)

    # S7 — Medicaid managed-care clamp.
    if payer_type == "MEDICAID_MCO" and raw > nominal:
        raw = nominal

    # S8 — record the outcome.
    result["patient_charge_cents"] = raw
    result["charge_basis"] = "SLIDING_FEE_TIER"
    result["sliding_fee_applied"] = True
    result["pinned_discount_tier_id"] = tier["id"]
    result["income_verification_id"] = verification["id"]
    return result


# --------------------------------------------------------------------------- #
# PPS encounter rate — a single rounding after all factors have multiplied
# --------------------------------------------------------------------------- #


def pps_encounter_rate(hc, site, service_definition, payer_type):
    multiplier = dec("1.00")
    if service_definition["service_category"] == "ADDITIONAL":
        multiplier = multiplier * dec("0.85")
    if site["site_type"] == "INTERMITTENT":
        multiplier = multiplier * dec("0.90")
    rate = money(dec(hc["pps_base_rate_cents"]) * multiplier)
    if payer_type == "MEDICARE" and rate > hc["medicare_upper_limit_cents"]:
        rate = hc["medicare_upper_limit_cents"]
    return rate


# --------------------------------------------------------------------------- #
# wraparound residual
# --------------------------------------------------------------------------- #


def counted_patient_portion(encounter):
    if granted_waiver(encounter["id"]) is not None:
        return 0
    return encounter["patient_charge_cents"]


def wraparound_due(encounter):
    if encounter["payer_type"] != "MEDICAID_MCO":
        return 0
    residual = (
        encounter["pps_encounter_rate_cents"]
        - encounter["mco_paid_cents"]
        - counted_patient_portion(encounter)
    )
    return residual if residual > 0 else 0


def recompute_wraparound(encounter):
    """Recompute the residual in place; a residual that moves underneath an
    outstanding claim drives CLAIMED -> REBILL_REQUIRED."""
    if encounter["payer_type"] != "MEDICAID_MCO":
        encounter["wraparound_status"] = "NOT_APPLICABLE"
        encounter["wraparound_due_cents"] = 0
        return
    previous = encounter["wraparound_due_cents"]
    updated = wraparound_due(encounter)
    encounter["wraparound_due_cents"] = updated
    if encounter["wraparound_status"] == "CLAIMED" and updated != previous:
        encounter["wraparound_status"] = "REBILL_REQUIRED"


# --------------------------------------------------------------------------- #
# quality measures
# --------------------------------------------------------------------------- #


def measure_rate_pct(numerator, denominator):
    return num(dec(numerator) / dec(denominator) * dec(100), 1)


def composite_rate_pct(rates):
    if not rates:
        return None
    total = sum((dec(r) for r in rates), dec(0))
    return float(round_half_up(total / dec(len(rates)), 1))
