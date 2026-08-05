"""Business calculations, state cascades, and cross-entity side effects.

Convention: helper functions here mutate field values but do NOT bump version.
Route handlers call helpers.touch(...) exactly once per affected entity so that
a single API operation advances each entity's version at most once.
"""
from decimal import Decimal

import store
from store import (
    DB, clock_now_iso, clock_now_date, to_date, parse_iso, add_months, rhu, D, iso,
)
from helpers import touch

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations / PRD)
# ---------------------------------------------------------------------------
INSURANCE_RIDER_ANNUAL_RATE_BP = 150
PRECIOUS_METAL_SURCHARGE_ANNUAL_RATE_BP = 50
INVOICE_DUE_DAYS = 30
DELINQUENCY_GRACE_DAYS = 15
LATE_TIER1_RATE = D("0.05")
LATE_TIER2_RATE = D("0.10")
LATE_TIER3_RATE = D("0.15")
SIZE_MULTIPLIER = {"SMALL": D("1.00"), "MEDIUM": D("1.25"), "LARGE": D("1.50"), "JUMBO": D("2.00")}
MIN_LATE_FEE_CENTS = 2500
MAX_LATE_FEE_CENTS = 25000
DAYS_PER_MONTH_APPROX = 30
DAYS_PER_YEAR = 365
ADMIN_FEE_CENTS = 5000
REQUIRED_WITNESSES = 2
CLEANUP_BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def rental_box(rental):
    return DB["boxes"].get(rental["box_id"])


def rental_box_type(rental):
    box = rental_box(rental)
    if not box:
        return None
    return DB["box_types"].get(box["box_type_id"])


def rental_invoices(rental):
    return [i for i in DB["invoices"].values() if i["rental_id"] == rental["id"]]


def rental_payments(rental):
    return [p for p in DB["payments"].values() if p["rental_id"] == rental["id"]]


# ---------------------------------------------------------------------------
# Balance / paid-through recompute (field-only; no version bump)
# ---------------------------------------------------------------------------
def recompute_balance(rental):
    total = 0
    for inv in rental_invoices(rental):
        if inv["status"] == "OPEN":
            total += inv["total_cents"] - inv["amount_paid_cents"]
    rental["balance_due_cents"] = total
    recompute_paid_through(rental)
    return total


def recompute_paid_through(rental):
    latest = None
    for inv in rental_invoices(rental):
        if inv["status"] == "PAID":
            pe = inv.get("period_end")
            if pe and (latest is None or pe > latest):
                latest = pe
    rental["paid_through_date"] = latest


# ---------------------------------------------------------------------------
# Invoice charge computation (per-component round then sum)
# ---------------------------------------------------------------------------
def precious_metal_surcharge(rental):
    total = 0
    for item in DB["inventory_items"].values():
        if item["rental_id"] != rental["id"]:
            continue
        if item["category"] != "PRECIOUS_METAL":
            continue
        if item["status"] == "RELEASED":
            continue
        total += rhu(D(item["declared_value_cents"]) * PRECIOUS_METAL_SURCHARGE_ANNUAL_RATE_BP / 10000)
    return total


def insurance_rider_charge(rental):
    if not rental.get("insurance_rider_enabled"):
        return 0
    return rhu(D(rental["declared_contents_value_cents"]) * INSURANCE_RIDER_ANNUAL_RATE_BP / 10000)


def compute_invoice_charges(rental, invoice, base_rent):
    rider = insurance_rider_charge(rental)
    surcharge = precious_metal_surcharge(rental)
    invoice["base_rent_cents"] = base_rent
    invoice["insurance_rider_cents"] = rider
    invoice["precious_metal_surcharge_cents"] = surcharge
    if "late_fee_cents" not in invoice or invoice["late_fee_cents"] is None:
        invoice["late_fee_cents"] = 0
    invoice["total_cents"] = base_rent + rider + surcharge + invoice["late_fee_cents"]


def base_rent_for_full_term(rental):
    term = rental.get("plan_term_months", 12)
    annual = rental["annual_rate_cents"]
    if term == 12:
        return annual
    return rhu(D(annual) * term / 12)


def base_rent_for_period(rental, period_start, period_end):
    d0 = to_date(period_start)
    d1 = to_date(period_end)
    days = (d1 - d0).days
    return rhu(D(rental["annual_rate_cents"]) * days / DAYS_PER_YEAR)


# ---------------------------------------------------------------------------
# Late fee escalation
# ---------------------------------------------------------------------------
def days_past_due(invoice):
    due = to_date(invoice["due_date"])
    return (clock_now_date() - due).days


def compute_late_fee(invoice, size_class):
    dpd = days_past_due(invoice)
    if dpd <= 0:
        return 0
    if dpd <= 30:
        rate = LATE_TIER1_RATE
    elif dpd <= 60:
        rate = LATE_TIER2_RATE
    else:
        rate = LATE_TIER3_RATE
    mult = SIZE_MULTIPLIER.get(size_class, D("1.00"))
    outstanding = invoice["total_cents"] - invoice["amount_paid_cents"]
    raw = D(outstanding) * rate * mult
    fee = rhu(raw)
    if fee < MIN_LATE_FEE_CENTS:
        fee = MIN_LATE_FEE_CENTS
    if fee > MAX_LATE_FEE_CENTS:
        fee = MAX_LATE_FEE_CENTS
    return fee


# ---------------------------------------------------------------------------
# First invoice at activation
# ---------------------------------------------------------------------------
def issue_first_invoice(rental):
    from helpers import make_record
    start = parse_iso(rental["start_date"])
    term = rental.get("plan_term_months", 12)
    period_end_dt = add_months(start, term)
    inv = make_record({
        "rental_id": rental["id"],
        "period_start": iso(start),
        "period_end": iso(period_end_dt),
        "base_rent_cents": 0,
        "insurance_rider_cents": 0,
        "precious_metal_surcharge_cents": 0,
        "late_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "due_date": None,
        "issued_on": clock_now_iso(),
        "status": "OPEN",
    })
    # due_date = issued_on + INVOICE_DUE_DAYS
    from datetime import timedelta
    inv["due_date"] = iso(parse_iso(inv["issued_on"]) + timedelta(days=INVOICE_DUE_DAYS))
    compute_invoice_charges(rental, inv, base_rent_for_full_term(rental))
    DB["invoices"][inv["id"]] = inv
    return inv


# ---------------------------------------------------------------------------
# Billing cycle
# ---------------------------------------------------------------------------
def run_billing_cycle():
    issued_invoice_ids = []
    escalated_rental_ids = []

    # 1. Accrue late fees on OPEN past-due invoices.
    for inv in list(DB["invoices"].values()):
        if inv["status"] != "OPEN":
            continue
        if days_past_due(inv) <= 0:
            continue
        rental = DB["rentals"].get(inv["rental_id"])
        if not rental:
            continue
        bt = rental_box_type(rental)
        size_class = bt["size_class"] if bt else "SMALL"
        fee = compute_late_fee(inv, size_class)
        if fee != inv["late_fee_cents"]:
            inv["late_fee_cents"] = fee
            inv["total_cents"] = (inv["base_rent_cents"] + inv["insurance_rider_cents"]
                                  + inv["precious_metal_surcharge_cents"] + fee)
            touch(inv)
            issued_invoice_ids.append(inv["id"])

    # 2. Recompute balances then escalate delinquency.
    for rental in list(DB["rentals"].values()):
        recompute_balance(rental)

    for rental in list(DB["rentals"].values()):
        changed = escalate_rental(rental)
        if changed:
            escalated_rental_ids.append(rental["id"])

    return {"issued_invoice_ids": issued_invoice_ids, "escalated_rental_ids": escalated_rental_ids}


def escalate_rental(rental):
    """Escalate ACTIVE->PAST_DUE->DELINQUENT per clock. Returns True if status changed."""
    open_invoices = [i for i in rental_invoices(rental) if i["status"] == "OPEN"]
    past_due_invoices = [i for i in open_invoices if days_past_due(i) > 0]
    changed = False

    if rental["status"] == "ACTIVE":
        if past_due_invoices and rental["balance_due_cents"] > 0:
            rental["status"] = "PAST_DUE"
            touch(rental)
            changed = True

    if rental["status"] == "PAST_DUE":
        max_dpd = max((days_past_due(i) for i in past_due_invoices), default=0)
        if max_dpd >= DELINQUENCY_GRACE_DAYS:
            rental["status"] = "DELINQUENT"
            rental["delinquent_since"] = clock_now_iso()
            touch(rental)
            box = rental_box(rental)
            if box and box["status"] == "RENTED":
                box["status"] = "DELINQUENT"
                touch(box)
            changed = True

    return changed


# ---------------------------------------------------------------------------
# Payment cure cascade
# ---------------------------------------------------------------------------
def cure_if_zero(rental):
    """If balance is zero and rental delinquent/past-due, cure back to ACTIVE."""
    if rental["balance_due_cents"] != 0:
        return
    if rental["status"] not in ("PAST_DUE", "DELINQUENT"):
        return
    was_delinquent = rental["status"] == "DELINQUENT"
    rental["status"] = "ACTIVE"
    rental["delinquent_since"] = None
    touch(rental)
    if was_delinquent:
        box = rental_box(rental)
        if box and box["status"] == "DELINQUENT":
            box["status"] = "RENTED"
            touch(box)


# ---------------------------------------------------------------------------
# Surrender refunds
# ---------------------------------------------------------------------------
def monthly_rate(rental):
    return rhu(D(rental["annual_rate_cents"]) / 12)


def days_elapsed(rental):
    start = to_date(rental["start_date"])
    return (clock_now_date() - start).days


def compute_provisional_refund(rental):
    import math
    de = days_elapsed(rental)
    months_elapsed_ceil = math.ceil(de / DAYS_PER_MONTH_APPROX)
    term = rental.get("plan_term_months", 12)
    return max(0, term - months_elapsed_ceil) * monthly_rate(rental)


def outstanding_late_fees(rental):
    total = 0
    for inv in rental_invoices(rental):
        if inv["status"] == "OPEN":
            total += inv["late_fee_cents"]
    return total


def compute_final_refund(rental):
    de = days_elapsed(rental)
    unused_days = max(0, DAYS_PER_YEAR - de)
    gross = rhu(D(rental["annual_rate_cents"]) * unused_days / DAYS_PER_YEAR)
    return max(0, gross - outstanding_late_fees(rental))


# ---------------------------------------------------------------------------
# Proceeds waterfall
# ---------------------------------------------------------------------------
def compute_waterfall(order, rental):
    remaining = order.get("proceeds_cents") or 0
    arrears = rental["balance_due_cents"]
    to_arrears = min(remaining, max(0, arrears))
    remaining -= to_arrears
    to_drilling = min(remaining, order.get("drilling_fee_cents") or 0)
    remaining -= to_drilling
    to_admin = min(remaining, ADMIN_FEE_CENTS)
    remaining -= to_admin
    order["proceeds_to_arrears_cents"] = to_arrears
    order["proceeds_to_drilling_cents"] = to_drilling
    order["proceeds_to_admin_cents"] = to_admin
    order["proceeds_to_escrow_cents"] = remaining


# ---------------------------------------------------------------------------
# Room occupancy + overlap
# ---------------------------------------------------------------------------
def windows_intersect(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def check_box_overlap(box_id, start_dt, end_dt, exclude_id=None):
    for appt in DB["access_appointments"].values():
        if appt["box_id"] != box_id:
            continue
        if appt["id"] == exclude_id:
            continue
        if appt["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start = parse_iso(appt["scheduled_start"])
        a_end = parse_iso(appt["scheduled_end"])
        if windows_intersect(start_dt, end_dt, a_start, a_end):
            return True
    return False


def room_occupancy_count(branch_id, start_dt, end_dt):
    from datetime import timedelta
    buf = timedelta(minutes=CLEANUP_BUFFER_MINUTES)
    count = 0
    for appt in DB["access_appointments"].values():
        if appt["branch_id"] != branch_id:
            continue
        if appt["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start = parse_iso(appt["scheduled_start"]) - buf
        a_end = parse_iso(appt["scheduled_end"]) + buf
        if windows_intersect(start_dt, end_dt, a_start, a_end):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Compliance hold helpers
# ---------------------------------------------------------------------------
def has_open_hold(renter_id):
    for c in DB["compliance_cases"].values():
        if c["renter_id"] == renter_id and c["severity"] == "HOLD" and c["status"] in ("OPEN", "ESCALATED"):
            return True
    return False


def refresh_standing(renter):
    renter["standing"] = "FROZEN" if has_open_hold(renter["id"]) else "GOOD"

