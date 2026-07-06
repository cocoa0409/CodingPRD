"""Business logic: calculations, validation helpers, cascading side effects,
and the logical-clock sweep. All money is integer cents; coinsurance uses
Decimal round-half-up (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db, logical_now
from clock import parse_iso, parse_date, add_months, add_days, add_years
from serializers import supplier_accreditation_status

GA_COINSURANCE_RATE = Decimal("0.80")
LABOR_FLAT_CENTS = 12500
FREE_FITTING_DAYS = 90
PROSTHETIC_WARRANTY_MONTHS = 18
ORTHOSIS_WARRANTY_MONTHS = 12
PROSTHETIC_CATEGORIES = {"LOWER_LIMB_PROSTHETIC", "UPPER_LIMB_PROSTHETIC"}


# --------------------------------------------------------------------------
# Mutation helper: every mutation refreshes updated_at and bumps version.
# --------------------------------------------------------------------------
def touch(entity):
    entity["updated_at"] = logical_now()
    entity["version"] = entity["version"] + 1


def round_half_up_cents(value):
    """Round a Decimal to whole cents using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def calc_prior_auth_requirement(payer_type, device_category):
    """prior_auth_requirement (PRD §3.3). Medicare lower-limb prosthetic or
    spinal orthosis -> True."""
    if payer_type == "MEDICARE" and device_category in ("LOWER_LIMB_PROSTHETIC", "SPINAL_ORTHOSIS"):
        return True
    return False


def calc_claim_line_allowed_final(line, order):
    """claim_line_allowed final variant (PRD §3.6).

    base = fee_schedule_cents * billed_units, branched on modifier.
    """
    base = line["fee_schedule_cents"] * line["billed_units"]
    modifier = line["modifier"]
    if modifier == "KX":
        return base
    if modifier == "GA":
        return round_half_up_cents(Decimal(base) * GA_COINSURANCE_RATE)
    if modifier == "GZ":
        return 0
    # NONE, RT, LT -> neutral
    return base


def recompute_order_allowed_total(order):
    """order_allowed_total final ledger (PRD §3.6): exact sum of allowed_cents
    over ADJUDICATED lines. This is a mutation on the order."""
    lines = [c for c in db.claim_lines.values() if c["device_order_id"] == order["id"]]
    total = sum(c["allowed_cents"] for c in lines if c["adjudication_status"] == "ADJUDICATED")
    if order["allowed_total_cents"] != total:
        order["allowed_total_cents"] = total
        touch(order)
    else:
        order["allowed_total_cents"] = total


def calc_warranty_expiry(delivery_dt, device_category):
    """warranty_window (PRD §3.7). Prosthetic 18mo, orthosis 12mo, calendar months."""
    months = PROSTHETIC_WARRANTY_MONTHS if device_category in PROSTHETIC_CATEGORIES else ORTHOSIS_WARRANTY_MONTHS
    return add_months(delivery_dt, months)


def calc_fabrication_progress(order_id):
    """fabrication_progress (PRD §3.4). round_half_up integer percent; 0 when no
    milestones."""
    ms = [m for m in db.fabrication_milestones.values() if m["device_order_id"] == order_id]
    total_weight = sum(m["weight"] for m in ms)
    if total_weight == 0:
        return 0
    done_weight = sum(m["weight"] for m in ms if m["completed"])
    pct = Decimal(done_weight * 100) / Decimal(total_weight)
    return int(pct.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_milestone_progress(order):
    """Recompute milestone_progress_pct; mutates order only when value changes."""
    new_pct = calc_fabrication_progress(order["id"])
    if order["milestone_progress_pct"] != new_pct:
        order["milestone_progress_pct"] = new_pct
        touch(order)


# --------------------------------------------------------------------------
# DMEPOS compliance gate (PRD §2.9)
# --------------------------------------------------------------------------
def dmepos_compliance_gate(order):
    """Run five checks in fixed order; return (passed, failure_reasons)."""
    reasons = []
    rx = db.prescriptions.get(order["prescription_id"])
    supplier = db.suppliers.get(order["supplier_id"])
    patient = db.patients.get(rx["patient_id"]) if rx else None
    prescribing = db.physicians.get(rx["physician_id"]) if rx else None

    supplier_status = supplier_accreditation_status(supplier, db.current_utc) if supplier else "UNACCREDITED"
    if supplier_status != "ACCREDITED":
        reasons.append("SUPPLIER_NOT_ACCREDITED")
    if not (supplier and supplier["surety_bond_active"]):
        reasons.append("NO_SURETY_BOND")
    if patient and patient["payer_type"] == "MEDICARE" and not (prescribing and prescribing["pecos_enrolled"]):
        reasons.append("PHYSICIAN_NOT_PECOS")
    if not (rx and rx["status"] == "CONSUMED"):
        reasons.append("RX_NOT_CONSUMED")
    if rx and order["fitting_practitioner_id"] == rx["physician_id"]:
        reasons.append("SEGREGATION_VIOLATION")

    return (len(reasons) == 0, reasons)


# --------------------------------------------------------------------------
# Logical clock sweep (PRD §3.9)
# --------------------------------------------------------------------------
def sweep_prior_auth_expiry():
    """Sweep PriorAuths in {SUBMITTED, PENDED} whose decision_deadline has been
    passed by the logical clock -> EXPIRED."""
    clock = parse_iso(db.current_utc)
    for auth in db.prior_auths.values():
        if auth["status"] in ("SUBMITTED", "PENDED"):
            deadline = auth.get("decision_deadline")
            if deadline is not None and clock > parse_iso(deadline):
                auth["status"] = "EXPIRED"
                touch(auth)
