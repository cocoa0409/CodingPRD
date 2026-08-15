"""Core services: entity scaffolding, lazy expiry, ledger, price resolution."""

from decimal import Decimal

import db
from util import new_id, now_stamp, D, r0_int
from response import iso8601_ms


# ---------------------------------------------------------------------------
# Entity scaffolding
# ---------------------------------------------------------------------------

def scaffold_entity(store, fields: dict, common=True):
    eid = new_id()
    now = now_stamp(db.CLOCK)
    entity = {"id": eid}
    if common:
        entity["created_at"] = now
        entity["updated_at"] = now
        entity["version"] = 1
    else:
        # CreditLedgerEntry: only id and created_at
        entity["created_at"] = now
    entity.update(fields)
    store[eid] = entity
    return entity


def touch(entity, common=True):
    """Bump updated_at + version on mutation."""
    entity["updated_at"] = now_stamp(db.CLOCK)
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lazy expiry evaluations (against the logical clock)
# ---------------------------------------------------------------------------

def lazy_recommendation(rec):
    if rec["status"] == "APPROVED" and db.CLOCK.now() > rec["_valid_until"]:
        rec["status"] = "EXPIRED"
        rec["updated_at"] = now_stamp(db.CLOCK)
        rec["version"] += 1


def lazy_plan(plan):
    if plan["status"] == "APPROVED" and db.CLOCK.now() > plan["_valid_to"]:
        plan["status"] = "EXPIRED"
        plan["updated_at"] = now_stamp(db.CLOCK)
        plan["version"] += 1


def lazy_permit(permit):
    if permit["status"] == "ACTIVE" and permit.get("_expires_at") is not None \
            and db.CLOCK.now() > permit["_expires_at"]:
        permit["status"] = "EXPIRED"
        permit["updated_at"] = now_stamp(db.CLOCK)
        permit["version"] += 1


def lazy_price_sheet(sheet):
    if sheet["status"] == "PUBLISHED" and db.CLOCK.now() >= sheet["_effective_to"]:
        sheet["status"] = "EXPIRED"
        sheet["updated_at"] = now_stamp(db.CLOCK)
        sheet["version"] += 1


def lazy_program(program):
    if program["status"] == "ENROLLMENT_OPEN" and db.CLOCK.now() > program["_enrollment_close_on"]:
        program["status"] = "ENROLLMENT_CLOSED"
        program["updated_at"] = now_stamp(db.CLOCK)
        program["version"] += 1


def lazy_all():
    """Re-evaluate lazy states globally — used after a clock move."""
    for rec in db.recommendations.values():
        lazy_recommendation(rec)
    for plan in db.nutrient_plans.values():
        lazy_plan(plan)
    for permit in db.permits.values():
        lazy_permit(permit)
    for sheet in db.price_sheets.values():
        lazy_price_sheet(sheet)
    for program in db.prepay_programs.values():
        lazy_program(program)


# ---------------------------------------------------------------------------
# Ledger & derived balances
# ---------------------------------------------------------------------------

def recompute_grower_balances(grower):
    credit_used = 0
    prepay_balance = 0
    entries = [e for e in db.ledger_entries.values() if e["grower_id"] == grower["id"]]
    entries.sort(key=lambda e: e["_seq"])
    for e in entries:
        t = e["entry_type"]
        amt = e["amount_cents"]
        if t == "INVOICE_POSTED":
            credit_used += amt
        elif t == "PAYMENT_RECEIVED":
            credit_used -= abs(amt)
        elif t == "REBATE_CREDIT":
            credit_used -= abs(amt)
        elif t == "PREPAY_FUNDED":
            prepay_balance += amt
        elif t == "PREPAY_DRAWN":
            prepay_balance -= abs(amt)
        elif t == "PREPAY_FORFEITED":
            prepay_balance -= abs(amt)
        elif t == "PREPAY_REFUNDED":
            prepay_balance -= abs(amt)
    grower["credit_used_cents"] = credit_used
    grower["prepay_balance_cents"] = prepay_balance


_seq_counter = [0]


def append_ledger(grower_id, entry_type, amount_cents, reference_id):
    """Append a CreditLedgerEntry; snapshots derived balances immediately after."""
    grower = db.growers[grower_id]
    _seq_counter[0] += 1
    entry = scaffold_entity(
        db.ledger_entries,
        {
            "grower_id": grower_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "reference_id": reference_id,
            "resulting_credit_used_cents": 0,
            "resulting_prepay_balance_cents": 0,
        },
        common=False,
    )
    entry["_seq"] = _seq_counter[0]
    recompute_grower_balances(grower)
    entry["resulting_credit_used_cents"] = grower["credit_used_cents"]
    entry["resulting_prepay_balance_cents"] = grower["prepay_balance_cents"]
    return entry


def booked_exposure_cents(grower_id) -> int:
    total = 0
    for o in db.blend_orders.values():
        if o["grower_id"] != grower_id:
            continue
        if o["fulfillment_status"] in ("BOOKED", "SCHEDULED") and o["payment_status"] != "CANCELLED":
            total += o.get("provisional_total_cents") or 0
    return total


def exposure_balance_cents(grower) -> int:
    return grower["credit_used_cents"] + booked_exposure_cents(grower["id"])


# ---------------------------------------------------------------------------
# Price resolution
# ---------------------------------------------------------------------------

def current_published_sheet(product_id, instant=None):
    """The PUBLISHED sheet whose half-open window contains `instant` (default: clock now)."""
    if instant is None:
        instant = db.CLOCK.now()
    for s in db.price_sheets.values():
        if s["product_id"] != product_id:
            continue
        lazy_price_sheet(s)
        if s["status"] != "PUBLISHED":
            continue
        if s["_effective_from"] <= instant < s["_effective_to"]:
            return s
    return None


# ---------------------------------------------------------------------------
# Serialization (strip internal keys)
# ---------------------------------------------------------------------------

def now_stamp_helper() -> str:
    return now_stamp(db.CLOCK)


def public(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_tons(value):
    """Tonnage values are carried at 3 decimals; emit as float/int cleanly."""
    d = D(value)
    return float(d)


def recompute_season_closed_tons(grower):
    total = Decimal(0)
    for o in db.blend_orders.values():
        if o["grower_id"] == grower["id"] and o["fulfillment_status"] == "CLOSED":
            total += D(o.get("tons_total") or 0)
    grower["season_closed_tons"] = float(total)
