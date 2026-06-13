"""Core domain logic: trust ledger, calculations, cascades, derived fields.

All monetary values are integer cents. Rate multiplications round half-up to
whole cents (PRD §2.7). Allocation waterfalls are exact integer arithmetic.
"""
from decimal import Decimal

import db
import errors
from errors import err
from services.common import (
    round_half_up_cents, round_ratio_4dp, pct_of_cents, days_between, add_days,
    parse_date,
)

# --- Constants (SCAFFOLD §1.3) ---------------------------------------------
MIN_CREDIT = 620
MAX_RTI = Decimal("0.40")
MAX_DTI = Decimal("0.45")

STATE_INTEREST_RATE = {
    "CA": Decimal("0.0000"),
    "NY": Decimal("0.0150"),
    "IL": Decimal("0.0050"),
    "FL": Decimal("0.0000"),
    "TX": Decimal("0.0000"),
}
DAYS_PER_YEAR = 365

STATE_CURE_DAYS = {
    "CA": {"NONPAYMENT": 3, "LEASE_VIOLATION": 3, "HOLDOVER": 30},
    "NY": {"NONPAYMENT": 14, "LEASE_VIOLATION": 10, "HOLDOVER": 30},
    "TX": {"NONPAYMENT": 3, "LEASE_VIOLATION": 3, "HOLDOVER": 3},
    "IL": {"NONPAYMENT": 5, "LEASE_VIOLATION": 10, "HOLDOVER": 30},
    "FL": {"NONPAYMENT": 3, "LEASE_VIOLATION": 7, "HOLDOVER": 15},
}
DEFAULT_TURN_DAYS = 14


# --- Trust ledger (PRD §2.8) ------------------------------------------------
def recompute_distributable(prop):
    """distributable_cents = max(0, trust_balance_cents - reserve_floor_cents)."""
    prop["distributable_cents"] = max(
        0, prop["trust_balance_cents"] - prop["reserve_floor_cents"])


def credit_trust(prop, amount_cents):
    """Credit (add) to the property trust; recompute distributable; bump version."""
    if amount_cents == 0:
        return
    prop["trust_balance_cents"] += amount_cents
    recompute_distributable(prop)
    db.touch(prop)


def debit_trust(prop, amount_cents):
    """Debit (subtract) from the property trust. Refuses to drive below zero
    with ERR_TRUST_INSUFFICIENT. Recomputes distributable; bumps version.
    A zero debit is a no-op (no version bump)."""
    if amount_cents == 0:
        return
    if prop["trust_balance_cents"] - amount_cents < 0:
        raise err(errors.ERR_TRUST_INSUFFICIENT,
                  "Trust balance insufficient for this debit")
    prop["trust_balance_cents"] -= amount_cents
    recompute_distributable(prop)
    db.touch(prop)


def property_of_unit(unit):
    return db.properties.get(unit["property_id"])


def property_of_lease(lease):
    unit = db.units.get(lease["unit_id"])
    if unit is None:
        return None
    return property_of_unit(unit)


# --- Lease balance ----------------------------------------------------------
def recompute_lease_balance(lease):
    """Lease.balance_due_cents = sum of amount_outstanding_cents over the
    lease's OPEN/PARTIAL charges. Bumps version."""
    total = 0
    for c in db.rent_charges.values():
        if c["lease_id"] == lease["id"] and c["status"] in ("OPEN", "PARTIAL"):
            total += c["amount_outstanding_cents"]
    lease["balance_due_cents"] = total
    db.touch(lease)


# --- Applicant screening (SCAFFOLD applicant_screening) ---------------------
def run_screening(applicant):
    income = applicant["annual_income_cents"]
    requested = applicant["requested_rent_cents"]
    debt = applicant["monthly_debt_cents"]
    credit = applicant["credit_score"]

    if income == 0:
        applicant["rent_to_income_ratio"] = 999.9999
        applicant["dti_ratio"] = 999.9999
        applicant["screening_decision"] = "FAIL"
        return

    rti = round_ratio_4dp(requested * 12, income)
    dti = round_ratio_4dp((debt + requested) * 12, income)
    applicant["rent_to_income_ratio"] = rti
    applicant["dti_ratio"] = dti

    passes = (
        credit >= MIN_CREDIT
        and Decimal(str(rti)) <= MAX_RTI
        and Decimal(str(dti)) <= MAX_DTI
    )
    applicant["screening_decision"] = "PASS" if passes else "FAIL"


# --- Late-fee sweep (SCAFFOLD late_fee_assessment) --------------------------
def assess_late_fees(lease, as_of_date):
    """Walk eligible RENT charges; create LATE_FEE charges where overdue.
    Returns nothing; recomputes lease balance once at the end."""
    as_of = parse_date(as_of_date)
    # Stable order over source charges so created_at order is deterministic.
    source_charges = sorted(
        [c for c in db.rent_charges.values()
         if c["lease_id"] == lease["id"]
         and c["charge_type"] == "RENT"
         and c["status"] in ("OPEN", "PARTIAL")
         and not c["late_fee_assessed"]],
        key=lambda c: (c.get("created_at", ""), c.get("_seq", 0)),
    )
    for charge in source_charges:
        late_cutoff = parse_date(add_days(charge["due_date"], lease["grace_period_days"]))
        if as_of > late_cutoff:  # strict >; last grace day is on-time
            pct_component = pct_of_cents(lease["monthly_rent_cents"], lease["late_fee_pct"])
            fee_cents = pct_component + lease["late_fee_flat_cents"]
            if fee_cents > 0:
                _create_late_fee_charge(lease, fee_cents, as_of_date)
                charge["late_fee_assessed"] = True
                db.touch(charge)
    recompute_lease_balance(lease)


def _create_late_fee_charge(lease, fee_cents, as_of_date):
    common = db.new_common()
    charge = {
        **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
        "lease_id": lease["id"],
        "charge_type": "LATE_FEE",
        "period_label": None,
        "due_date": as_of_date,
        "amount_cents": fee_cents,
        "amount_paid_cents": 0,
        "amount_outstanding_cents": fee_cents,
        "late_fee_assessed": False,
        "status": "OPEN",
    }
    db.rent_charges[charge["id"]] = charge
    return charge


# --- Payment waterfall (SCAFFOLD payment_waterfall) -------------------------
def apply_payment_waterfall(payment, lease):
    """Allocate payment across OPEN/PARTIAL charges by:
       1. charge_type rank (LATE_FEE=0 before RENT=1)
       2. due_date ASC
       3. created_at ASC (id never used)
    Credits applied_to_rent_cents to the property trust."""
    candidates = [
        c for c in db.rent_charges.values()
        if c["lease_id"] == lease["id"] and c["status"] in ("OPEN", "PARTIAL")
    ]

    def rank(c):
        return 0 if c["charge_type"] == "LATE_FEE" else 1

    candidates.sort(key=lambda c: (rank(c), c["due_date"], c.get("created_at", ""),
                                   c.get("_seq", 0)))

    remaining = payment["amount_cents"]
    applied_to_rent = 0
    breakdown = []
    for charge in candidates:
        if remaining == 0:
            break
        pay = min(remaining, charge["amount_outstanding_cents"])
        if pay <= 0:
            continue
        charge["amount_paid_cents"] += pay
        charge["amount_outstanding_cents"] = charge["amount_cents"] - charge["amount_paid_cents"]
        remaining -= pay
        breakdown.append({"charge_id": charge["id"], "applied_cents": pay})
        if charge["charge_type"] == "RENT":
            applied_to_rent += pay
        # Advance charge state.
        if charge["amount_outstanding_cents"] == 0:
            charge["status"] = "PAID"
        else:
            charge["status"] = "PARTIAL"
        db.touch(charge)

    payment["applied_breakdown"] = breakdown
    payment["applied_to_rent_cents"] = applied_to_rent
    payment["unapplied_cents"] = remaining

    recompute_lease_balance(lease)

    # Credit the property trust with the rent portion.
    if applied_to_rent > 0:
        prop = property_of_lease(lease)
        if prop is not None:
            credit_trust(prop, applied_to_rent)


# --- Deposit settlement (deposit_interest + deposit_settlement) -------------
def compute_deposit_interest(deposit, state_code):
    rate = STATE_INTEREST_RATE.get(state_code, Decimal("0"))
    span_days = days_between(deposit["collected_date"], deposit["settlement_date"])
    if span_days < 0:
        span_days = 0
    full_years = span_days // DAYS_PER_YEAR
    interest = round_half_up_cents(Decimal(deposit["collected_cents"]) * rate * Decimal(full_years))
    return interest


def settle_deposit(deposit, lease, prop, damage_deductions_cents):
    """Run interest + deduction waterfall. Mutates deposit; debits trust on a
    positive refund. Returns nothing.

    Raises ERR_TRUST_INSUFFICIENT (checked after computing refund) if the trust
    cannot cover a positive refund — and that check is the LAST thing, so no
    deposit mutation is committed if it fails (caller mutates after success)."""
    state_code = prop["state_code"]
    interest = compute_deposit_interest(deposit, state_code)

    available = deposit["collected_cents"] + interest
    d_arrears = min(available, lease["balance_due_cents"])
    available -= d_arrears
    d_damage = min(available, damage_deductions_cents)
    available -= d_damage
    deductions = d_arrears + d_damage
    refund = available

    total_available = deposit["collected_cents"] + interest
    is_forfeited = (refund == 0 and deductions == total_available)

    # Trust solvency is the last guard (validation priority 14): check before
    # committing any deposit mutation.
    if not is_forfeited and refund > 0:
        debit_trust(prop, refund)

    deposit["interest_accrued_cents"] = interest
    deposit["deductions_cents"] = deductions
    deposit["refund_cents"] = refund
    deposit["status"] = "FORFEITED" if is_forfeited else "SETTLED"


# --- Eviction cure deadline (SCAFFOLD eviction_cure_deadline) ---------------
def compute_cure_deadline(notice_date, state_code, reason):
    cure_days = STATE_CURE_DAYS[state_code][reason]
    return add_days(notice_date, cure_days)


# --- Owner statement net (SCAFFOLD owner_statement_net) ---------------------
def _period_month(date_str):
    """Return 'YYYY-MM' for an ISO date string."""
    return date_str[:7]


def compute_owner_statement(statement, prop, owner):
    """Compute gross/fee/maintenance/net for the statement, per its basis."""
    period = statement["period_label"]
    # Leases whose unit belongs to this property.
    unit_ids = {u["id"] for u in db.units.values() if u["property_id"] == prop["id"]}
    lease_ids = {l["id"] for l in db.leases.values() if l["unit_id"] in unit_ids}

    if statement["basis"] == "CASH":
        gross = sum(
            p["applied_to_rent_cents"]
            for p in db.payments.values()
            if p["lease_id"] in lease_ids
            and _period_month(p["received_date"]) == period
        )
    else:  # ACCRUAL
        gross = sum(
            c["amount_cents"]
            for c in db.rent_charges.values()
            if c["lease_id"] in lease_ids
            and c["charge_type"] == "RENT"
            and c.get("period_label") == period
        )

    management_fee = pct_of_cents(gross, owner["management_fee_pct"])

    maintenance = sum(
        w["actual_cost_cents"]
        for w in db.work_orders.values()
        if w["unit_id"] in unit_ids
        and w["status"] == "COMPLETED"
        and w["charge_to_owner"] is True
        and w.get("completed_date")
        and _period_month(w["completed_date"]) == period
    )

    net = max(0, gross - management_fee - maintenance)

    statement["gross_cents"] = gross
    statement["management_fee_cents"] = management_fee
    statement["maintenance_cents"] = maintenance
    statement["net_to_owner_cents"] = net


# --- Cascades ---------------------------------------------------------------
def open_turnover(unit, opened_date):
    """Auto-open a TurnoverProject (eviction cascade hop 4)."""
    common = db.new_common()
    project = {
        **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
        "unit_id": unit["id"],
        "opened_date": opened_date,
        "target_ready_date": add_days(opened_date, DEFAULT_TURN_DAYS),
        "make_ready_cost_cents": 0,
        "status": "OPEN",
    }
    db.turnovers[project["id"]] = project
    return project


def terminate_lease_via_eviction(lease, enforce_date):
    """Drive Lease ACTIVE -> TERMINATED with the eviction cascade:
       hop 1: lease -> TERMINATED
       hop 2: tenant -> FORMER
       hop 3: unit -> VACANT_TURN, active_lease_id -> null
       hop 4: auto-open TurnoverProject (opened_date = enforce_date)."""
    lease["status"] = "TERMINATED"
    db.touch(lease)

    tenant = db.tenants.get(lease.get("tenant_id"))
    if tenant is not None and tenant["status"] != "FORMER":
        tenant["status"] = "FORMER"
        db.touch(tenant)

    unit = db.units.get(lease["unit_id"])
    if unit is not None:
        unit["occupancy_status"] = "VACANT_TURN"
        unit["active_lease_id"] = None
        db.touch(unit)
        open_turnover(unit, enforce_date)
