"""Core domain logic: entity stamping, inventory recompute, ledger/balance
recompute, customer mirrors, overdue arithmetic, and charge posting.

Field naming follows scaffold §1.1 / PRD §2.4:
  - immutable entities (ContainerModel, ProtectionPlan): id, created_at only
  - mutable entities: id, created_at, updated_at, version
"""
import math

from db import db
from clock import fmt_iso
from calculations import late_fee_gross, late_fee_cap

# Charge categories that are debits the customer owes (positive amount_cents).
DEBIT_TYPES = {
    "DELIVERY_FEE", "RENTAL_PRORATION", "RENTAL_CYCLE", "PROTECTION_PREMIUM",
    "PACKING_SUPPLIES", "MOVE", "ACCESS_FEE", "LATE_FEE",
}
CREDIT_TYPES = {"PAYMENT", "ADJUSTMENT"}

# Debit scope under the PROVISIONAL balance variant (ACTIVE / ON_HOLD).
PROVISIONAL_DEBITS = {
    "DELIVERY_FEE", "RENTAL_PRORATION", "RENTAL_CYCLE", "PROTECTION_PREMIUM",
    "PACKING_SUPPLIES", "ACCESS_FEE",
}


# --------------------------------------------------------------------------
# Entity stamping helpers
# --------------------------------------------------------------------------
def stamp_create(immutable=False):
    """Return the common system fields for a newly created entity."""
    now = fmt_iso(db.now())
    base = {"id": db.new_id(), "created_at": now, "_seq": db.next_seq()}
    if not immutable:
        base["updated_at"] = now
        base["version"] = 1
    return base


def touch(entity):
    """Mutation: refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    entity["updated_at"] = fmt_iso(db.now())
    entity["version"] = entity.get("version", 1) + 1


# --------------------------------------------------------------------------
# Serialization: strip internal fields (those prefixed with '_')
# --------------------------------------------------------------------------
def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Inventory availability (calc inventory_availability)
# --------------------------------------------------------------------------
def recompute_inventory(inv_row):
    """reserved/committed/available from the live ContainerUnit set."""
    inv_id = inv_row["id"]
    reserved = 0
    committed = 0
    for u in db.container_units.values():
        if u["depot_inventory_id"] != inv_id:
            continue
        st = u["status"]
        if st == "RESERVED":
            reserved += 1
        elif st in ("DELIVERED", "ON_SITE", "IN_TRANSIT", "RETURNED"):
            committed += 1
    inv_row["reserved_units"] = reserved
    inv_row["committed_units"] = committed
    inv_row["available_units"] = inv_row["total_units"] - reserved - committed
    touch(inv_row)


# --------------------------------------------------------------------------
# Charge posting
# --------------------------------------------------------------------------
def post_charge(agreement_id, charge_type, amount_cents, due_date=None):
    """Create an immutable Charge ledger row (carries full mutable common-field
    set per PRD §2.4: id, created_at, updated_at, version)."""
    c = stamp_create(immutable=False)
    c.update({
        "agreement_id": agreement_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
        "due_date": fmt_iso(due_date) if due_date is not None else None,
        "settled": False,
    })
    db.charges[c["id"]] = c
    return c


def agreement_charges_sorted(agreement_id):
    """All charges for an agreement, oldest-first by created_at (insertion seq
    breaks ties; created_at is monotonic with the logical clock)."""
    rows = [c for c in db.charges.values() if c["agreement_id"] == agreement_id]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return rows


# --------------------------------------------------------------------------
# agreement_balance (calc agreement_balance) + settlement walk
# --------------------------------------------------------------------------
def _in_scope_debit(charge, final):
    if charge["charge_type"] not in DEBIT_TYPES:
        return False
    if final:
        return True
    return charge["charge_type"] in PROVISIONAL_DEBITS


def recompute_balance(agreement):
    """Recompute balance_due_cents and per-charge settled flags (PRD §3.8).

    Walk charges in created_at ASC. The credit pool (sum of -amount over
    PAYMENT/ADJUSTMENT) settles in-scope debits oldest-first. balance_due is
    the sum of in-scope debits minus the credits. Phase selects the variant:
    PROVISIONAL (ACTIVE/ON_HOLD) excludes MOVE+LATE_FEE; FINAL (CLOSING/CLOSED)
    includes everything.
    """
    lifecycle = agreement["lifecycle_status"]
    final = lifecycle in ("CLOSING", "CLOSED")
    charges = agreement_charges_sorted(agreement["id"])

    # Total credits available (negate the stored negative amounts).
    total_credit = sum(-c["amount_cents"] for c in charges
                       if c["charge_type"] in CREDIT_TYPES)

    debit_total = 0
    remaining_credit = total_credit
    for c in charges:
        if _in_scope_debit(c, final):
            amt = c["amount_cents"]
            debit_total += amt
            if remaining_credit >= amt:
                c["settled"] = True
                remaining_credit -= amt
            else:
                c["settled"] = False
        elif c["charge_type"] in DEBIT_TYPES:
            # out-of-scope debit (e.g. MOVE/LATE_FEE while PROVISIONAL) — never
            # settled by the provisional walk, left as-is.
            pass

    balance = debit_total - total_credit
    agreement["balance_due_cents"] = balance
    return balance


# --------------------------------------------------------------------------
# Overdue arithmetic (calc late_fee) — operates on POSTED unsettled debits
# --------------------------------------------------------------------------
def compute_days_overdue(agreement):
    """Whole-day floor of (current clock date - oldest unsettled debit due_date).
    Only debit charges with settled == False and a non-null due_date count.
    0 when everything is settled."""
    from clock import parse_iso
    charges = agreement_charges_sorted(agreement["id"])
    due_dates = [parse_iso(c["due_date"]) for c in charges
                 if c["charge_type"] in DEBIT_TYPES
                 and not c["settled"]
                 and c["due_date"] is not None]
    if not due_dates:
        return 0
    oldest = min(due_dates)
    now = db.now()
    delta_days = math.floor((now - oldest).total_seconds() / 86400.0)
    return max(0, delta_days)


def total_late_fees_posted(agreement_id):
    return sum(c["amount_cents"] for c in db.charges.values()
               if c["agreement_id"] == agreement_id and c["charge_type"] == "LATE_FEE")


# --------------------------------------------------------------------------
# customer_payment_ledger (calc customer_payment_ledger)
# --------------------------------------------------------------------------
def recompute_customer_mirrors(customer_id):
    """lifetime_paid_cents = sum of |PAYMENT| across all this customer's
    agreements; open_balance_cents = sum of balance_due over agreements in
    {RESERVED, ACTIVE, ON_HOLD, CLOSING} (PRD §3.9)."""
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    agreements = [a for a in db.rental_agreements.values()
                  if a["customer_id"] == customer_id]
    agreement_ids = {a["id"] for a in agreements}

    lifetime_paid = 0
    for c in db.charges.values():
        if c["charge_type"] == "PAYMENT" and c["agreement_id"] in agreement_ids:
            lifetime_paid += abs(c["amount_cents"])

    open_balance = 0
    for a in agreements:
        if a["lifecycle_status"] in ("RESERVED", "ACTIVE", "ON_HOLD", "CLOSING"):
            open_balance += a["balance_due_cents"]

    customer["lifetime_paid_cents"] = lifetime_paid
    customer["open_balance_cents"] = open_balance
    touch(customer)
