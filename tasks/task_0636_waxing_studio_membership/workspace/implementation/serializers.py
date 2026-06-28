"""Resource serialization with computed/derived fields (PRD 2.5)."""
from db import db
from util import iso
from credits import membership_credit_balance
from strikes import member_active_strike_count


def ser_location(loc):
    return {
        "id": loc["id"],
        "created_at": iso(loc["created_at"]),
        "updated_at": iso(loc["updated_at"]),
        "version": loc["version"],
        "name": loc["name"],
        "state_code": loc["state_code"],
        "open_minute_of_day": loc["open_minute_of_day"],
        "close_minute_of_day": loc["close_minute_of_day"],
        "deposit_required_cents": loc["deposit_required_cents"],
        "no_show_fee_cents": loc["no_show_fee_cents"],
    }


def ser_service_type(s):
    return {
        "id": s["id"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
        "name": s["name"],
        "duration_minutes": s["duration_minutes"],
        "buffer_minutes": s["buffer_minutes"],
        "list_price_cents": s["list_price_cents"],
        "credit_cost": s["credit_cost"],
        "intro_eligible": s["intro_eligible"],
        "active": s["active"],
    }


def ser_product(p):
    return {
        "id": p["id"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
        "name": p["name"],
        "unit_price_cents": p["unit_price_cents"],
        "member_discount_pct": p["member_discount_pct"],
        "stock_qty": p["stock_qty"],
    }


def ser_room(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
        "location_id": r["location_id"],
        "label": r["label"],
        "active": r["active"],
    }


def ser_technician(t):
    return {
        "id": t["id"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
        "location_id": t["location_id"],
        "full_name": t["full_name"],
        "certified_service_ids": list(t["certified_service_ids"]),
        "active": t["active"],
    }


def ser_member(m):
    # intro_used, no_show_strike_count, wallet_credit_cents are computed (PRD 2.5).
    return {
        "id": m["id"],
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
        "home_location_id": m["home_location_id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "intro_used": m["intro_used"],
        "no_show_strike_count": member_active_strike_count(m["id"]),
        "wallet_credit_cents": m["wallet_credit_cents"],
    }


def ser_membership(mb):
    # credit_balance is projected from the ledger (PRD 2.5 / 3.2).
    return {
        "id": mb["id"],
        "created_at": iso(mb["created_at"]),
        "updated_at": iso(mb["updated_at"]),
        "version": mb["version"],
        "member_id": mb["member_id"],
        "tier": mb["tier"],
        "monthly_credit_grant": mb["monthly_credit_grant"],
        "monthly_fee_cents": mb["monthly_fee_cents"],
        "max_rollover_credits": mb["max_rollover_credits"],
        "status": mb["status"],
        "credit_balance": membership_credit_balance(mb["id"]),
        "cycle_anchor_utc": iso(mb["cycle_anchor_utc"]),
        "cycle_index": mb["cycle_index"],
        "freeze_until_utc": iso(mb["freeze_until_utc"]),
        "frozen_cycle_credits": mb["frozen_cycle_credits"],
    }


def ser_ledger_entry(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "membership_id": e["membership_id"],
        "entry_type": e["entry_type"],
        "delta_credits": e["delta_credits"],
        "source_kind": e["source_kind"],
        "source_ref_id": e["source_ref_id"],
        "cycle_index": e["cycle_index"],
    }


def ser_reservation(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
        "member_id": r["member_id"],
        "location_id": r["location_id"],
        "room_id": r["room_id"],
        "technician_id": r["technician_id"],
        "service_type_id": r["service_type_id"],
        "start_utc": iso(r["start_utc"]),
        "end_utc": iso(r["end_utc"]),
        "booking_status": r["booking_status"],
        "settlement_status": r["settlement_status"],
        "payment_method": r["payment_method"],
        "membership_id": r["membership_id"],
        "credits_held": r["credits_held"],
        "deposit_held_cents": r["deposit_held_cents"],
        "charged_amount_cents": r["charged_amount_cents"],
    }


def ser_retail_sale(rs):
    return {
        "id": rs["id"],
        "created_at": iso(rs["created_at"]),
        "updated_at": iso(rs["updated_at"]),
        "version": rs["version"],
        "member_id": rs["member_id"],
        "reservation_id": rs["reservation_id"],
        "product_id": rs["product_id"],
        "quantity": rs["quantity"],
        "status": rs["status"],
        "gross_cents": rs["gross_cents"],
        "discount_cents": rs["discount_cents"],
        "net_cents": rs["net_cents"],
    }


def ser_no_show_strike(s):
    return {
        "id": s["id"],
        "created_at": iso(s["created_at"]),
        "member_id": s["member_id"],
        "reservation_id": s["reservation_id"],
        "strike_kind": s["strike_kind"],
        "fee_charged_cents": s["fee_charged_cents"],
        "status": s["status"],
    }
