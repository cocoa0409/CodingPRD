"""Calculations and conservation-aggregation maintenance."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from clock import LOGICAL_CLOCK, add_days
from store import DB, touch


def _round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _D(v):
    return Decimal(str(v))


# --- make_ready_fee ----------------------------------------------------------

def make_ready_fee(owner, survey, hours, variant):
    """variant in {'ESTIMATE', 'FINAL'}; hours is the labor hours to use."""
    labor_rate = _D(owner["make_ready_labor_rate_cents_per_hour"])
    if survey["complexity_class"] == "COMPLEX":
        mult = _D(C.COMPLEXITY_MULTIPLIER_COMPLEX)
    else:
        mult = _D(C.COMPLEXITY_MULTIPLIER_SIMPLE)
    if not survey["make_ready_required"]:
        base_labor = _D(0)
    else:
        base_labor = _D(hours) * labor_rate * mult
    transfer_cost = _D(survey["existing_attacher_count"]) * _D(C.PER_EXISTING_ATTACHER_TRANSFER_CENTS)
    subtotal = base_labor + transfer_cost
    if variant == "ESTIMATE":
        return _round_half_up(subtotal * (_D(1) + _D(C.CONTINGENCY_PCT)))
    return _round_half_up(subtotal)


# --- annual rental (per-line, full-year, proration) --------------------------

def annual_line_cents(owner, space_inches):
    return _round_half_up(_D(owner["annual_rental_rate_cents"]) * _D(space_inches) / _D(12))


def first_year_proration_cents(owner, space_inches, permit_dt):
    full_year = _D(owner["annual_rental_rate_cents"]) * _D(space_inches) / _D(12)
    d = permit_dt.date()
    remaining_days = (date(d.year, 12, 31) - d).days + 1
    return _round_half_up(full_year * _D(remaining_days) / _D(C.DAYS_IN_YEAR))


def annual_rental_true_up(owner, attacher_id, pole_owner_id):
    """Round per line, then sum.  Returns (amount_cents, line_items)."""
    candidates = []
    for att in DB.attachments.values():
        if att["status"] != "ACTIVE":
            continue
        if att["attacher_id"] != attacher_id:
            continue
        pole = DB.poles.get(att["pole_id"])
        if pole is None or pole["pole_owner_id"] != pole_owner_id:
            continue
        candidates.append(att)
    candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
    line_items = []
    total = 0
    for a in candidates:
        line = annual_line_cents(owner, a["allotted_space_inches"])
        total += line
        line_items.append({
            "label": "ANNUAL_RENTAL",
            "attachment_id": a["id"],
            "amount_cents": line,
        })
    return total, line_items


# --- unauthorized finding: penalty + back rental -----------------------------

def penalty_and_back_rental(owner, finding):
    annual_line = annual_line_cents(owner, finding["discovered_space_inches"])
    if finding["discovered_space_inches"] <= C.UNAUTHORIZED_TIER1_MAX_INCHES:
        penalty = C.PENALTY_TIER1_CENTS
    else:
        penalty = C.PENALTY_TIER2_CENTS
    if finding["good_faith"]:
        back_rental = annual_line * C.BACK_RENTAL_GOOD_FAITH_YEARS
    else:
        years = min(finding["estimated_install_years_ago"], C.BACK_RENTAL_BAD_FAITH_MAX_YEARS)
        back_rental = annual_line * years
    return penalty, back_rental


# --- shot clock --------------------------------------------------------------

def compute_shot_clock_status(permit_issued_at, permit_deadline):
    return "ON_TIME" if permit_issued_at <= permit_deadline else "LATE"


# --- conservation aggregations ----------------------------------------------

def recompute_pole(pole):
    occupied = 0
    for att in DB.attachments.values():
        if att["pole_id"] == pole["id"] and att["status"] == "ACTIVE":
            occupied += att["allotted_space_inches"]
    reserved = 0
    for app in DB.applications.values():
        if app["pole_id"] == pole["id"] and app["status"] == "ESTIMATE_ACCEPTED":
            reserved += app["reserved_space_inches"]
    if pole["occupied_space_inches"] != occupied or pole["reserved_space_inches"] != reserved:
        pole["occupied_space_inches"] = occupied
        pole["reserved_space_inches"] = reserved
        touch(pole)


def issue_invoice(attacher, invoice_type, amount_cents, line_items,
                  application_id=None, finding_id=None, pole_owner_id=None):
    now = LOGICAL_CLOCK.now()
    inv = DB.new_record({
        "attacher_id": attacher["id"],
        "pole_owner_id": pole_owner_id,
        "application_id": application_id,
        "finding_id": finding_id,
        "invoice_type": invoice_type,
        "amount_cents": amount_cents,
        "line_items": line_items if line_items is not None else [],
        "issued_at": now,
        "due_at": add_days(now, C.INVOICE_DUE_DAYS),
        "status": "ISSUED",
    })
    DB.invoices[inv["id"]] = inv
    recompute_balance(attacher)
    return inv


def void_invoice(inv):
    inv["status"] = "VOID"
    touch(inv)
    attacher = DB.attachers.get(inv["attacher_id"])
    if attacher is not None:
        recompute_balance(attacher)


def recompute_balance(attacher):
    total = 0
    for inv in DB.invoices.values():
        if inv["attacher_id"] == attacher["id"] and inv["status"] in ("ISSUED", "OVERDUE"):
            total += inv["amount_cents"]
    if attacher["account_balance_cents"] != total:
        attacher["account_balance_cents"] = total
        touch(attacher)
