"""Serialize internal records to JSON-ready dicts per SCAFFOLD §1.1.

Internal records store datetimes as aware datetime objects and carry private
helper keys (prefixed with '_'). Serializers emit only the declared fields with
datetimes rendered as ISO 8601 UTC strings.
"""
from db import iso

# Primary (versioned) records expose id/created_at/updated_at/version.
# Ledger records (CreditLedgerEntry, Payment) expose only id/created_at.


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def _ledger_common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
    }


def plan_out(r):
    out = _common(r)
    out.update({
        "tier": r["tier"],
        "monthly_fee_cents": r["monthly_fee_cents"],
        "included_floats_per_cycle": r["included_floats_per_cycle"],
        "rollover_cap": r["rollover_cap"],
        "member_discount_pct": r["member_discount_pct"],
        "retail_float_cents": r["retail_float_cents"],
        "active": r["active"],
    })
    return out


def member_out(r):
    out = _common(r)
    out.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "status": r["status"],
        "orientation_completed": r["orientation_completed"],
        "waiver_signed_version": r["waiver_signed_version"],
        "no_show_strikes": r["no_show_strikes"],
    })
    return out


def membership_out(r):
    out = _common(r)
    out.update({
        "member_id": r["member_id"],
        "plan_id": r["plan_id"],
        "status": r["status"],
        "credit_balance": r["credit_balance"],
        "cycle_index": r["cycle_index"],
        "cycle_start_utc": iso(r["cycle_start_utc"]),
        "cycle_end_utc": iso(r["cycle_end_utc"]),
        "monthly_fee_cents_snapshot": r["monthly_fee_cents_snapshot"],
    })
    return out


def tank_out(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "capacity_kind": r["capacity_kind"],
        "turnover_buffer_minutes": r["turnover_buffer_minutes"],
        "operational_status": r["operational_status"],
        "sanitation_status": r["sanitation_status"],
    })
    return out


def sanitation_out(r):
    out = _common(r)
    out.update({
        "tank_id": r["tank_id"],
        "booking_id": r["booking_id"],
        "kind": r["kind"],
        "status": r["status"],
        "started_utc": iso(r["started_utc"]),
        "ends_utc": iso(r["ends_utc"]),
        "duration_minutes": r["duration_minutes"],
    })
    return out


def attendant_out(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "active": r["active"],
    })
    return out


def orientation_out(r):
    out = _common(r)
    out.update({
        "member_id": r["member_id"],
        "attendant_id": r["attendant_id"],
        "start_utc": iso(r["start_utc"]),
        "end_utc": iso(r["end_utc"]),
        "status": r["status"],
        "waiver_version": r["waiver_version"],
    })
    return out


def booking_out(r):
    out = _common(r)
    out.update({
        "member_id": r["member_id"],
        "tank_id": r["tank_id"],
        "membership_id": r["membership_id"],
        "session_minutes": r["session_minutes"],
        "is_couples": r["is_couples"],
        "start_utc": iso(r["start_utc"]),
        "end_utc": iso(r["end_utc"]),
        "status": r["status"],
        "pay_source": r["pay_source"],
        "gift_card_id": r["gift_card_id"],
        "deposit_cents": r["deposit_cents"],
        "provisional_charge_cents": r["provisional_charge_cents"],
        "final_charge_cents": r["final_charge_cents"],
        "credits_consumed": r["credits_consumed"],
    })
    return out


def gift_card_out(r):
    out = _common(r)
    out.update({
        "code": r["code"],
        "initial_balance_cents": r["initial_balance_cents"],
        "remaining_balance_cents": r["remaining_balance_cents"],
        "status": r["status"],
    })
    return out


def credit_ledger_out(r):
    out = _ledger_common(r)
    out.update({
        "membership_id": r["membership_id"],
        "booking_id": r["booking_id"],
        "reason": r["reason"],
        "delta": r["delta"],
    })
    return out


def payment_out(r):
    out = _ledger_common(r)
    out.update({
        "booking_id": r["booking_id"],
        "gift_card_id": r["gift_card_id"],
        "kind": r["kind"],
        "source": r["source"],
        "amount_cents": r["amount_cents"],
    })
    return out
