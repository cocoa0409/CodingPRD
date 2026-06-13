"""TradeIn lifecycle side-effect helpers (PRD 3.4-3.7; scaffold state machine).

These functions own the cascading mutations. Each resource touched by a cascade
gets its own updated_at/version bump via models.touch() (PRD 2.9).
"""
from clock import clock
from db import db
from models import new_record, touch
from util import iso_now, parse_iso, add_hours, new_id
from services import calc
from services.lookups import locked_quote_of


def _now():
    return clock.now()


def make_quote(trade_in, kind, graded_subtotal, promo_bonus_cents, amount_cents,
               price_lock_hours):
    """Create a LOCKED Quote and set lock_expires_at = created_at + price_lock_hours."""
    rec = new_record("Quote", {
        "trade_in_id": trade_in["id"],
        "kind": kind,
        "graded_subtotal_cents": graded_subtotal,
        "promo_bonus_cents": promo_bonus_cents,
        "amount_cents": amount_cents,
        "lock_expires_at": None,
        "status": "LOCKED",
    })
    created_dt = parse_iso(rec["created_at"])
    rec["lock_expires_at"] = iso_now(add_hours(created_dt, price_lock_hours))
    db.quotes[rec["id"]] = rec
    return rec


def make_disposition(trade_in, disposition, reason=None):
    rec = new_record("DispositionRecord", {
        "trade_in_id": trade_in["id"],
        "disposition": disposition,
        "reason": reason,
    })
    db.disposition_records[rec["id"]] = rec
    return rec


def quote_initial(trade_in, model, campaign, catalog):
    """DRAFT->QUOTED side effects: mint a LOCKED INITIAL quote, set locked_quote_id."""
    graded_subtotal = calc.graded_value(
        model,
        trade_in["declared_grade"],
        trade_in["declared_defects"],
        trade_in["declared_powers_on"],
    )
    bonus = calc.promo_bonus(graded_subtotal, campaign)
    amount = calc.quote_amount(graded_subtotal, bonus)

    quote = make_quote(trade_in, "INITIAL", graded_subtotal, bonus, amount,
                       catalog["price_lock_hours"])
    trade_in["status"] = "QUOTED"
    trade_in["locked_quote_id"] = quote["id"]
    touch(trade_in)
    return quote


def run_inspection(trade_in, model, catalog, verified_grade, verified_defects,
                   verified_powers_on):
    """Create an Inspection record, compute inspected value + outcome.

    Returns the inspection record (not yet acted on). The caller decides whether
    this is the first /inspect (with full fork) or a /reinspect.
    """
    inspected_value = calc.graded_value(model, verified_grade, verified_defects,
                                        verified_powers_on)
    locked = locked_quote_of(trade_in)
    locked_amount = locked["amount_cents"] if locked else 0
    outcome = calc.inspection_outcome(
        inspected_value,
        locked_amount,
        catalog["requote_tolerance_pct"],
        catalog["recycle_floor_value_cents"],
    )
    rec = new_record("Inspection", {
        "trade_in_id": trade_in["id"],
        "graded_at": iso_now(_now()),
        "verified_grade": verified_grade,
        "verified_defects": verified_defects,
        "verified_powers_on": verified_powers_on,
        "inspected_value_cents": inspected_value,
        "outcome": outcome,
    })
    db.inspections[rec["id"]] = rec
    return rec, inspected_value, outcome


def apply_match(trade_in):
    """INSPECTED->ACCEPTED (MATCH): honor the locked INITIAL quote."""
    locked = locked_quote_of(trade_in)
    locked["status"] = "HONORED"
    touch(locked)
    trade_in["status"] = "ACCEPTED"
    trade_in["final_value_cents"] = locked["amount_cents"]
    touch(trade_in)


def apply_requote(trade_in, inspected_value, catalog):
    """INSPECTED->REQUOTED: supersede prior quote, mint a LOCKED REQUOTE quote."""
    prior = locked_quote_of(trade_in)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    new_q = make_quote(trade_in, "REQUOTE", inspected_value, 0, inspected_value,
                       catalog["price_lock_hours"])
    trade_in["status"] = "REQUOTED"
    trade_in["locked_quote_id"] = new_q["id"]
    touch(trade_in)
    return new_q


def apply_recycle(trade_in):
    """INSPECTED->RECYCLED: supersede prior quote, create RECYCLE disposition."""
    prior = locked_quote_of(trade_in)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    make_disposition(trade_in, "RECYCLE")
    trade_in["status"] = "RECYCLED"
    touch(trade_in)
