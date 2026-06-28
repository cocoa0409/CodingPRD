"""Resource -> API JSON serialization, including computed/derived fields.

Computed fields are reconciled at read time per PRD §2.7. The serializers read
live state from the store so derived counts always reflect current rows.
"""
from db import db
from util import iso_z
from services import packs as pack_svc
from services import members as member_svc


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso_z(rec["created_at"]),
        "updated_at": iso_z(rec["updated_at"]),
        "version": rec["version"],
    }


def studio_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "city": rec["city"],
        "timezone": rec["timezone"],
        "late_cancel_window_minutes": rec["late_cancel_window_minutes"],
        "late_cancel_fee_cents": rec["late_cancel_fee_cents"],
        "no_show_fee_cents": rec["no_show_fee_cents"],
        "status": rec["status"],
    })
    return out


def room_out(rec):
    out = _common(rec)
    # bike_count: number of bikes in this room whose status != RETIRED (PRD §2.7)
    bike_count = sum(
        1 for b in db.bikes.values()
        if b["room_id"] == rec["id"] and b["status"] != "RETIRED"
    )
    out.update({
        "studio_id": rec["studio_id"],
        "name": rec["name"],
        "bike_count": bike_count,
        "status": rec["status"],
    })
    return out


def bike_out(rec):
    out = _common(rec)
    out.update({
        "room_id": rec["room_id"],
        "position_row": rec["position_row"],
        "position_col": rec["position_col"],
        "label": rec["label"],
        "status": rec["status"],
    })
    return out


def instructor_out(rec):
    out = _common(rec)
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "status": rec["status"],
    })
    return out


def session_out(rec):
    out = _common(rec)
    booked_count = sum(
        1 for r in db.reservations.values()
        if r["session_id"] == rec["id"] and r["attendance_status"] == "BOOKED"
    )
    waitlist_count = sum(
        1 for w in db.waitlist_entries.values()
        if w["session_id"] == rec["id"] and w["status"] == "WAITING"
    )
    out.update({
        "studio_id": rec["studio_id"],
        "room_id": rec["room_id"],
        "instructor_id": rec["instructor_id"],
        "start_utc": iso_z(rec["start_utc"]),
        "end_utc": iso_z(rec["end_utc"]),
        "capacity": rec["capacity"],
        "waitlist_capacity": rec["waitlist_capacity"],
        "booked_count": booked_count,
        "waitlist_count": waitlist_count,
        "status": rec["status"],
    })
    return out


def member_out(rec):
    out = _common(rec)
    completed = sum(
        1 for r in db.reservations.values()
        if r["member_id"] == rec["id"] and r["attendance_status"] == "ATTENDED"
    )
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "home_studio_id": rec["home_studio_id"],
        "completed_ride_count": completed,
        "active_strike_count": member_svc.active_strike_count(rec["id"]),
        "account_status": rec["account_status"],
        "wallet_credit_cents": rec["wallet_credit_cents"],
    })
    return out


def credit_pack_out(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "kind": rec["kind"],
        "purchased_credits": rec["purchased_credits"],
        "price_cents": rec["price_cents"],
        "consumed_credits": rec["consumed_credits"],
        "remaining_credits": pack_svc.remaining_credits(rec),
        "activated_at": iso_z(rec["activated_at"]),
        "expires_at": iso_z(rec["expires_at"]),
        "scope": rec["scope"],
        "grant_studio_ids": list(rec["grant_studio_ids"]),
        "status": rec["status"],
    })
    return out


def reservation_out(rec):
    out = _common(rec)
    out.update({
        "session_id": rec["session_id"],
        "member_id": rec["member_id"],
        "bike_id": rec["bike_id"],
        "credit_pack_id": rec["credit_pack_id"],
        "attendance_status": rec["attendance_status"],
        "billing_status": rec["billing_status"],
        "first_ride_discount_applied": rec["first_ride_discount_applied"],
        "shoe_size": rec["shoe_size"],
        "shoe_fee_cents": rec["shoe_fee_cents"],
        "shoe_status": rec["shoe_status"],
        "booked_at": iso_z(rec["booked_at"]),
    })
    return out


def waitlist_out(rec):
    out = _common(rec)
    out.update({
        "session_id": rec["session_id"],
        "member_id": rec["member_id"],
        "credit_pack_id": rec["credit_pack_id"],
        "enqueued_at": iso_z(rec["enqueued_at"]),
        "status": rec["status"],
        "promoted_reservation_id": rec["promoted_reservation_id"],
    })
    return out


def product_out(rec):
    out = _common(rec)
    out.update({
        "studio_id": rec["studio_id"],
        "sku": rec["sku"],
        "name": rec["name"],
        "unit_price_cents": rec["unit_price_cents"],
        "stock_qty": rec["stock_qty"],
        "status": rec["status"],
    })
    return out


def retail_order_out(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "studio_id": rec["studio_id"],
        "product_id": rec["product_id"],
        "quantity": rec["quantity"],
        "pay_from_wallet": rec["pay_from_wallet"],
        "subtotal_cents": rec["subtotal_cents"],
        "wallet_applied_cents": rec["wallet_applied_cents"],
        "card_charged_cents": rec["card_charged_cents"],
        "status": rec["status"],
    })
    return out


def penalty_out(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "reservation_id": rec["reservation_id"],
        "kind": rec["kind"],
        "amount_cents": rec["amount_cents"],
        "counts_as_strike": rec["counts_as_strike"],
        "waived": rec["waived"],
        "charged_at": iso_z(rec["charged_at"]),
    })
    return out
