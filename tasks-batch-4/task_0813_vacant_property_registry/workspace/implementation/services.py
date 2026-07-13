"""Business operations: common-field bookkeeping, ledger, derived totals,
state transitions, and cascades. No HTTP concerns here."""
import calc
from store import db
from util import now_utc, format_iso, add_days
from envelope import ApiError


# --- common bookkeeping ---------------------------------------------------
def stamp_new(entity, versioned=True):
    entity["id"] = db.new_id()
    entity["_seq"] = db.next_seq()
    entity["created_at"] = format_iso(now_utc())
    if versioned:
        entity["updated_at"] = format_iso(now_utc())
        entity["version"] = 1
    return entity


def touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = format_iso(now_utc())


def get_or_404(collection, resource_id, error_id):
    obj = collection.get(resource_id)
    if obj is None:
        raise ApiError(error_id)
    return obj


# --- derived totals -------------------------------------------------------
def outstanding_balance(property_id):
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["property_id"] == property_id
    )


def lien_balance(property_id):
    return sum(
        l["principal_cents"]
        for l in db.liens.values()
        if l["property_id"] == property_id and l["status"] == "RECORDED"
    )


def open_violation_count(property_id):
    return sum(
        1
        for v in db.violations.values()
        if v["property_id"] == property_id and v["status"] in ("OPEN", "ESCALATED")
    )


# --- ledger + auto suspension --------------------------------------------
def post_ledger(prop, entry_type, amount_cents, source_type, source_id, memo):
    entry = {
        "property_id": prop["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_type": source_type,
        "source_id": source_id,
        "occurred_at": format_iso(db.clock),
        "memo": memo,
    }
    stamp_new(entry, versioned=False)
    db.ledger_entries[entry["id"]] = entry
    apply_suspension(prop)
    return entry


def apply_suspension(prop):
    """React to a balance change on the registration_status axis."""
    balance = outstanding_balance(prop["id"])
    status = prop["registration_status"]
    if status == "ACTIVE" and balance >= calc.SUSPEND_THRESHOLD_CENTS:
        prop["registration_status"] = "SUSPENDED"
        touch(prop)
    elif status == "SUSPENDED" and balance < calc.SUSPEND_THRESHOLD_CENTS:
        prop["registration_status"] = "ACTIVE"
        touch(prop)


# --- fine settlement ------------------------------------------------------
def _finalized_accrual(fine):
    return calc.fine_accrual(
        fine["base_amount_cents"],
        fine["daily_penalty_cents"],
        _parse(fine["assessed_at"]),
        db.clock,
    )


def pay_fine(fine, prop):
    finalized = _finalized_accrual(fine)
    fine["finalized_amount_cents"] = finalized
    fine["paid_at"] = format_iso(db.clock)
    base = fine["base_amount_cents"]
    post_ledger(prop, "FINE_ACCRUAL", finalized - base, "FINE", fine["id"],
                "Fine interest accrued at payment")
    post_ledger(prop, "FINE_PAYMENT", -finalized, "FINE", fine["id"],
                "Fine paid")
    fine["status"] = "PAID"
    touch(fine)


def dispute_fine(fine, reason):
    fine["status"] = "DISPUTED"
    fine["disputed_at"] = format_iso(db.clock)
    fine["dispute_reason"] = reason
    touch(fine)


def deny_dispute(fine):
    fine["status"] = "ASSESSED"
    touch(fine)


def waive_fine(fine, prop):
    fine["status"] = "WAIVED"
    post_ledger(prop, "FINE_WAIVED", -fine["base_amount_cents"], "FINE", fine["id"],
                "Fine waived")
    touch(fine)


def record_lien(fine, prop):
    finalized = _finalized_accrual(fine)
    fine["finalized_amount_cents"] = finalized
    base = fine["base_amount_cents"]
    post_ledger(prop, "FINE_ACCRUAL", finalized - base, "FINE", fine["id"],
                "Fine interest accrued at lien conversion")
    post_ledger(prop, "FINE_LIENED", -finalized, "FINE", fine["id"],
                "Fine converted to lien")
    lien = {
        "property_id": prop["id"],
        "source_fine_id": fine["id"],
        "principal_cents": finalized,
        "interest_rate_bps": calc.LIEN_INTEREST_BPS,
        "recorded_at": format_iso(db.clock),
        "status": "RECORDED",
        "satisfied_at": None,
    }
    stamp_new(lien)
    db.liens[lien["id"]] = lien
    fine["status"] = "LIENED"
    touch(fine)
    return lien


# --- cascades -------------------------------------------------------------
def demolish_property(prop):
    prop["registration_status"] = "DEMOLISHED"
    touch(prop)
    # Hop 1: void violations; Hop 2: waive fines of just-voided violations.
    for v in db.violations.values():
        if v["property_id"] != prop["id"]:
            continue
        if v["status"] in ("OPEN", "ESCALATED", "FINED"):
            v["status"] = "VOIDED"
            touch(v)
            for f in db.fines.values():
                if f["violation_id"] == v["id"] and f["status"] in ("ASSESSED", "DISPUTED"):
                    waive_fine(f, prop)
    # Cascade: demolition listings LISTED/SCHEDULED -> DEMOLISHED.
    for d in db.demolition_listings.values():
        if d["property_id"] == prop["id"] and d["status"] in ("LISTED", "SCHEDULED"):
            d["status"] = "DEMOLISHED"
            touch(d)


def redeem_cascade(prop):
    for d in db.demolition_listings.values():
        if d["property_id"] == prop["id"] and d["status"] in ("LISTED", "SCHEDULED"):
            d["status"] = "REMOVED"
            touch(d)


# --- misc -----------------------------------------------------------------
def registration_expiry(registered_at):
    return format_iso(add_days(registered_at, 365))


def _parse(iso_str):
    from util import parse_iso
    return parse_iso(iso_str)
