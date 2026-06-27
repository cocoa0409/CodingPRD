"""Resource serialization to the public JSON shape.

Strips internal keys (_seq, _raw_strikes, _technician_earning bookkeeping) and
injects derived fields (Station.sanitation_status, Client.active_no_show_strikes,
etc.) computed against the logical clock at read time.
"""
from datetime_util import format_iso8601
from derive import (station_sanitation, client_effective_strikes)


def _common(rec):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def technician_out(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "license_number": rec["license_number"],
        "license_expiry": rec["license_expiry"],
        "pay_model": rec["pay_model"],
        "commission_pct": rec["commission_pct"],
        "booth_rent_cents": rec["booth_rent_cents"],
        "home_station_id": rec["home_station_id"],
        "status": rec["status"],
        "accrued_earnings_cents": rec["accrued_earnings_cents"],
        "lifetime_no_show_strikes_attributed": rec["lifetime_no_show_strikes_attributed"],
    })
    return out


def station_out(rec):
    out = _common(rec)
    sanitation_status, last_pass_at, in_service_id = station_sanitation(rec)
    out.update({
        "name": rec["name"],
        "requires_autoclave": rec["requires_autoclave"],
        "sanitation_status": sanitation_status,
        "last_pass_sanitation_at": last_pass_at,
        "in_service_appointment_id": in_service_id,
    })
    return out


def sanitation_log_out(rec):
    out = _common(rec)  # only id + created_at (no updated_at/version)
    out.update({
        "station_id": rec["station_id"],
        "logged_by_technician_id": rec["logged_by_technician_id"],
        "cycle_result": rec["cycle_result"],
        "cycle_temp_c": rec["cycle_temp_c"],
        "hold_minutes": rec["hold_minutes"],
    })
    return out


def menu_item_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "category": rec["category"],
        "duration_minutes": rec["duration_minutes"],
        "base_price_cents": rec["base_price_cents"],
        "loyalty_points_award": rec["loyalty_points_award"],
        "requires_sterile_station": rec["requires_sterile_station"],
        "is_active": rec["is_active"],
    })
    return out


def add_on_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "price_cents": rec["price_cents"],
        "extra_minutes": rec["extra_minutes"],
        "is_active": rec["is_active"],
    })
    return out


def client_out(rec):
    out = _common(rec)
    effective_strikes, deposit_required = client_effective_strikes(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "loyalty_points_balance": rec["loyalty_points_balance"],
        "active_no_show_strikes": effective_strikes,
        "deposit_required": deposit_required,
        "last_no_show_at": rec["last_no_show_at"],
    })
    return out


def appointment_out(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "technician_id": rec["technician_id"],
        "station_id": rec["station_id"],
        "service_item_id": rec["service_item_id"],
        "origin": rec["origin"],
        "start_at": rec["start_at"],
        "end_at": rec["end_at"],
        "booking_status": rec["booking_status"],
        "payment_status": rec["payment_status"],
        "deposit_due_cents": rec["deposit_due_cents"],
        "deposit_paid_cents": rec["deposit_paid_cents"],
        "subtotal_cents": rec["subtotal_cents"],
        "loyalty_points_redeemed": rec["loyalty_points_redeemed"],
        "gift_card_id": rec["gift_card_id"],
        "total_charged_cents": rec["total_charged_cents"],
        "technician_earning_cents": rec["technician_earning_cents"],
        "no_show_strike_charged": rec["no_show_strike_charged"],
    })
    return out


def appointment_add_on_out(rec):
    out = _common(rec)  # only id + created_at (no updated_at/version)
    out.update({
        "appointment_id": rec["appointment_id"],
        "add_on_id": rec["add_on_id"],
        "price_cents_snapshot": rec["price_cents_snapshot"],
        "extra_minutes_snapshot": rec["extra_minutes_snapshot"],
    })
    return out


def gift_card_out(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "initial_balance_cents": rec["initial_balance_cents"],
        "balance_cents": rec["balance_cents"],
        "purchaser_client_id": rec["purchaser_client_id"],
        "status": rec["status"],
    })
    return out


def commission_statement_out(rec):
    out = _common(rec)
    out.update({
        "technician_id": rec["technician_id"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "gross_service_cents": rec["gross_service_cents"],
        "technician_payout_cents": rec["technician_payout_cents"],
        "salon_retained_cents": rec["salon_retained_cents"],
        "swept_appointment_count": rec["swept_appointment_count"],
        "status": rec["status"],
    })
    return out
