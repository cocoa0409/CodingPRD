"""Public JSON serializers. Computed fields (balances, liabilities,
allocated amounts) are derived on read per PRD §2.5 / §2.6."""

from db import db
from core import (
    settled_balance,
    pending_hold,
    available_balance,
    last_activity_at,
    program_outstanding_liability,
    program_breakage_recognized,
    program_escheat_liability,
)

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(record):
    return {k: record[k] for k in _COMMON}


def program(p):
    out = _base(p)
    out.update({
        "name": p["name"],
        "default_currency": p["default_currency"],
        "reload_min_cents": p["reload_min_cents"],
        "reload_max_balance_cents": p["reload_max_balance_cents"],
        "hold_ttl_seconds": p["hold_ttl_seconds"],
        "b2b_discount_pct": p["b2b_discount_pct"],
        "outstanding_liability_cents": program_outstanding_liability(p["id"]),
        "breakage_recognized_cents": program_breakage_recognized(p["id"]),
        "escheat_liability_cents": program_escheat_liability(p["id"]),
    })
    return out


def state_rule(r):
    out = _base(r)
    out.update({
        "program_id": r["program_id"],
        "state_code": r["state_code"],
        "expiration_allowed": r["expiration_allowed"],
        "dormancy_fee_allowed": r["dormancy_fee_allowed"],
        "breakage_policy": r["breakage_policy"],
        "escheat_rate": r["escheat_rate"],
        "dormancy_threshold_months": r["dormancy_threshold_months"],
    })
    return out


def campaign(c):
    out = _base(c)
    out.update({
        "program_id": c["program_id"],
        "name": c["name"],
        "bonus_pct": c["bonus_pct"],
        "window_start": c["window_start"],
        "window_end": c["window_end"],
        "status": c["status"],
    })
    return out


def customer(c):
    out = _base(c)
    out.update({
        "email": c["email"],
        "full_name": c["full_name"],
        "residence_state_code": c["residence_state_code"],
        "is_corporate": c["is_corporate"],
    })
    return out


def card(c):
    out = _base(c)
    out.update({
        "program_id": c["program_id"],
        "owner_customer_id": c["owner_customer_id"],
        "form_factor": c["form_factor"],
        "state_code": c["state_code"],
        "lifecycle_status": c["lifecycle_status"],
        "risk_status": c["risk_status"],
        "settled_balance_cents": settled_balance(c["id"]),
        "pending_hold_cents": pending_hold(c["id"]),
        "available_balance_cents": available_balance(c["id"]),
        "last_activity_at": last_activity_at(c),
        "replaced_by_card_id": c["replaced_by_card_id"],
    })
    return out


def ledger_entry(e):
    # LedgerEntry is immutable: id + created_at only (PRD §2.4).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "card_id": e["card_id"],
        "program_id": e["program_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "source_ref_id": e["source_ref_id"],
        "reverses_entry_id": e["reverses_entry_id"],
    }


def hold(h):
    out = _base(h)
    out.update({
        "card_id": h["card_id"],
        "amount_cents": h["amount_cents"],
        "expires_at": h["expires_at"],
        "status": h["status"],
    })
    return out


def redemption(r):
    out = _base(r)
    allocated = sum(
        leg["leg_amount_cents"]
        for leg in db.redemption_legs.values()
        if leg["redemption_id"] == r["id"]
    )
    out.update({
        "program_id": r["program_id"],
        "customer_id": r["customer_id"],
        "requested_amount_cents": r["requested_amount_cents"],
        "card_id_order": list(r["card_id_order"]),
        "allocated_amount_cents": allocated,
        "status": r["status"],
    })
    return out


def redemption_leg(leg):
    # RedemptionLeg is immutable: id + created_at only (PRD §2.4).
    return {
        "id": leg["id"],
        "created_at": leg["created_at"],
        "redemption_id": leg["redemption_id"],
        "card_id": leg["card_id"],
        "leg_amount_cents": leg["leg_amount_cents"],
        "ledger_entry_id": leg["ledger_entry_id"],
    }


def bulk_order(b):
    out = _base(b)
    out.update({
        "program_id": b["program_id"],
        "buyer_customer_id": b["buyer_customer_id"],
        "card_count": b["card_count"],
        "face_value_cents": b["face_value_cents"],
        "state_code": b["state_code"],
        "net_invoice_cents": b["net_invoice_cents"],
        "status": b["status"],
    })
    return out


def replacement(r):
    out = _base(r)
    out.update({
        "old_card_id": r["old_card_id"],
        "new_card_id": r["new_card_id"],
        "reason": r["reason"],
        "transferred_amount_cents": r["transferred_amount_cents"],
        "status": r["status"],
    })
    return out


def refund(r):
    out = _base(r)
    out.update({
        "card_id": r["card_id"],
        "redemption_id": r["redemption_id"],
        "requested_refund_cents": r["requested_refund_cents"],
        "status": r["status"],
    })
    return out


def dormancy_waiver(w):
    out = _base(w)
    out.update({
        "card_id": w["card_id"],
        "window_start": w["window_start"],
        "window_end": w["window_end"],
        "status": w["status"],
    })
    return out
