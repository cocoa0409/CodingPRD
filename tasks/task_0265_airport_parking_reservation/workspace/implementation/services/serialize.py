"""Serialize internal records to public JSON (PRD entity field lists)."""
from timeutil import format_iso


def _common(rec):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }
    return out


def serialize_customer(rec):
    out = _common(rec)
    out.update(
        {
            "email": rec["email"],
            "full_name": rec["full_name"],
            "no_show_strikes": rec["no_show_strikes"],
            "status": rec["status"],
        }
    )
    return out


def serialize_vehicle(rec):
    out = _common(rec)
    out.update(
        {
            "customer_id": rec["customer_id"],
            "plate": rec["plate"],
            "size_class": rec["size_class"],
            "is_ev": rec["is_ev"],
        }
    )
    return out


def serialize_lot(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "kind": rec["kind"],
            "standard_capacity": rec["standard_capacity"],
            "oversized_capacity": rec["oversized_capacity"],
            "ev_capacity": rec["ev_capacity"],
            "available_standard_count": rec["available_standard_count"],
            "available_oversized_count": rec["available_oversized_count"],
            "available_ev_count": rec["available_ev_count"],
            "in_out_allowed": rec["in_out_allowed"],
        }
    )
    return out


def serialize_rate_plan(rec):
    out = _common(rec)
    out.update(
        {
            "lot_id": rec["lot_id"],
            "rate_mode": rec["rate_mode"],
            "hourly_cents": rec["hourly_cents"],
            "daily_cap_cents": rec["daily_cap_cents"],
            "valet_surcharge_cents": rec["valet_surcharge_cents"],
            "oversized_multiplier_bps": rec["oversized_multiplier_bps"],
            "ev_surcharge_cents_per_day": rec["ev_surcharge_cents_per_day"],
            "active": rec["active"],
        }
    )
    return out


def serialize_cancellation_policy(rec):
    out = _common(rec)
    out.update(
        {
            "lot_id": rec["lot_id"],
            "free_cancel_hours": rec["free_cancel_hours"],
            "late_cancel_fee_bps": rec["late_cancel_fee_bps"],
            "prepay_discount_bps": rec["prepay_discount_bps"],
        }
    )
    return out


def serialize_reservation(rec):
    out = _common(rec)
    out.update(
        {
            "customer_id": rec["customer_id"],
            "lot_id": rec["lot_id"],
            "vehicle_id": rec["vehicle_id"],
            "rate_plan_id": rec["rate_plan_id"],
            "shuttle_trip_id": rec["shuttle_trip_id"],
            "stall_class": rec["stall_class"],
            "scheduled_start": format_iso(rec["scheduled_start"]),
            "scheduled_end": format_iso(rec["scheduled_end"]),
            "actual_in": format_iso(rec["actual_in"]),
            "actual_out": format_iso(rec["actual_out"]),
            "prepaid": rec["prepaid"],
            "occupancy_status": rec["occupancy_status"],
            "settlement_status": rec["settlement_status"],
            "rate_snapshot": rec["rate_snapshot"],
            "provisional_quote_cents": rec["provisional_quote_cents"],
            "final_charge_cents": rec["final_charge_cents"],
            "overstay_cents": rec["overstay_cents"],
        }
    )
    return out


def serialize_stall_hold(rec):
    out = _common(rec)
    out.update(
        {
            "lot_id": rec["lot_id"],
            "reservation_id": rec["reservation_id"],
            "stall_class": rec["stall_class"],
            "hold_start": format_iso(rec["hold_start"]),
            "hold_end": format_iso(rec["hold_end"]),
            "status": rec["status"],
        }
    )
    return out


def serialize_shuttle_trip(rec):
    out = _common(rec)
    out.update(
        {
            "lot_id": rec["lot_id"],
            "depart_at": format_iso(rec["depart_at"]),
            "seat_capacity": rec["seat_capacity"],
            "seats_taken": rec["seats_taken"],
            "status": rec["status"],
        }
    )
    return out


def serialize_payment_txn(rec):
    # PaymentTxn has only id + created_at (no updated_at / version) per PRD §2.4.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "reservation_id": rec["reservation_id"],
        "kind": rec["kind"],
        "amount_cents": rec["amount_cents"],
        "note": rec["note"],
    }
