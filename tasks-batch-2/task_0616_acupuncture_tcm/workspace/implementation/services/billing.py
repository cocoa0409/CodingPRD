"""Billing calculations: visit charge (cash), superbill (insurance), and the
no-show / late-cancel penalty.

Constants (SCAFFOLD §1.3 / PRD 3.7, 3.8):
  CASH_DISCOUNT_PCT      = 0.10
  NO_SHOW_BASE_CENTS     = 5000
  LATE_CANCEL_BASE_CENTS = 2500
  STRIKE_STEP            = 0.5
  STRIKE_CAP             = 3
"""

from decimal import Decimal

from common import public, round_half_up_cents, stamp_new
from db import db

CASH_DISCOUNT_PCT = Decimal("0.10")
NO_SHOW_BASE_CENTS = 5000
LATE_CANCEL_BASE_CENTS = 2500
STRIKE_STEP = Decimal("0.5")
STRIKE_CAP = 3


def attached_addons(appt_id):
    """ATTACHED add-ons of an appointment, ordered by created_at ASC (creation
    order). VOIDED add-ons excluded."""
    items = [
        a
        for a in db.addons.values()
        if a["appointment_id"] == appt_id and a["status"] == "ATTACHED"
    ]
    return sorted(items, key=lambda a: a["_seq"])


def subtotal_for(appt):
    """base_fee_cents + sum(ATTACHED AddOn.fee_cents)."""
    subtotal = appt["base_fee_cents"]
    for a in attached_addons(appt["id"]):
        subtotal += a["fee_cents"]
    return subtotal


def create_visit_charge_cash(appt):
    """Cash variant: produce a Charge with the 10% cash discount (PRD 3.8)."""
    subtotal = subtotal_for(appt)
    discount = round_half_up_cents(Decimal(subtotal) * CASH_DISCOUNT_PCT)
    total_due = subtotal - discount
    charge = {
        "appointment_id": appt["id"],
        "subtotal_cents": subtotal,
        "cash_discount_cents": discount,
        "total_due_cents": total_due,
        "charge_type": "VISIT",
        "status": "OPEN",
    }
    stamp_new(charge)
    db.charges[charge["id"]] = charge
    return charge


def create_superbill(appt, patient):
    """Insurance variant: produce a Superbill with per-line rounded allowances
    (round per line THEN sum) — PRD 3.8 / superbill_reconciliation."""
    rate = Decimal(str(patient.get("coinsurance_rate", 0.0)))
    line_charges = [appt["base_fee_cents"]]
    for a in attached_addons(appt["id"]):
        line_charges.append(a["fee_cents"])
    insurance_allowed = 0
    for line in line_charges:
        insurance_allowed += round_half_up_cents(Decimal(line) * rate)
    patient_responsibility = sum(line_charges) - insurance_allowed
    superbill = {
        "appointment_id": appt["id"],
        "line_charges_cents": line_charges,
        "insurance_allowed_cents": insurance_allowed,
        "patient_responsibility_cents": patient_responsibility,
        "status": "ISSUED",
    }
    stamp_new(superbill)
    db.superbills[superbill["id"]] = superbill
    return superbill


def compute_penalty(transition, prior_strikes, membership_status):
    """no_show_penalty calc (PRD 3.7).

    transition is "NO_SHOW" or "LATE_CANCEL".
    prior_strikes is the patient's strike_count BEFORE this appointment's strike.
    """
    if membership_status == "ACTIVE" and prior_strikes == 0:
        return 0
    tier_base = NO_SHOW_BASE_CENTS if transition == "NO_SHOW" else LATE_CANCEL_BASE_CENTS
    capped = min(prior_strikes, STRIKE_CAP)
    strike_mult = Decimal(1) + Decimal(capped) * STRIKE_STEP
    return round_half_up_cents(Decimal(tier_base) * strike_mult)


def create_penalty_charge(appt, penalty_cents):
    """Create a PENALTY Charge carrying the penalty fee (PRD 3.7)."""
    charge = {
        "appointment_id": appt["id"],
        "subtotal_cents": penalty_cents,
        "cash_discount_cents": 0,
        "total_due_cents": penalty_cents,
        "charge_type": "PENALTY",
        "status": "OPEN",
    }
    stamp_new(charge)
    db.charges[charge["id"]] = charge
    return charge
