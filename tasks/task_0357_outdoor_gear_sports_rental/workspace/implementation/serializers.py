"""Serialize stored records to API output dicts.

Mutable resources carry id/created_at/updated_at/version (PRD §2.4).
Append-only resources (SeasonWindow, ReservationAddOn, ConditionReport,
LedgerEntry) carry only id/created_at — no updated_at, no version.
"""
import db


def gear_type(r):
    return {
        "id": r["id"],
        "category": r["category"],
        "name": r["name"],
        "size_label": r["size_label"],
        "requires_lesson_for_beginner": r["requires_lesson_for_beginner"],
        "active": r["active"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def rate_card(r):
    return {
        "id": r["id"],
        "gear_type_id": r["gear_type_id"],
        "hourly_cents": r["hourly_cents"],
        "daily_cents": r["daily_cents"],
        "seasonal_flat_cents": r["seasonal_flat_cents"],
        "deposit_cents": r["deposit_cents"],
        "damage_waiver_cents_per_day": r["damage_waiver_cents_per_day"],
        "late_fee_cents_per_hour": r["late_fee_cents_per_hour"],
        "loss_fee_cents": r["loss_fee_cents"],
        "grace_minutes": r["grace_minutes"],
        "active": r["active"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def season_window(r):
    return {
        "id": r["id"],
        "category": r["category"],
        "label": r["label"],
        "starts_on": db.iso(r["starts_on"]),
        "ends_on": db.iso(r["ends_on"]),
        "demand_multiplier_bp": r["demand_multiplier_bp"],
        "created_at": db.iso(r["created_at"]),
    }


def customer(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "skill_level": r["skill_level"],
        "standing": r["standing"],
        "strike_points": r["strike_points"],
        "open_loss_balance_cents": r["open_loss_balance_cents"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def addon(r):
    return {
        "id": r["id"],
        "kind": r["kind"],
        "category": r["category"],
        "name": r["name"],
        "price_cents": r["price_cents"],
        "capacity_per_slot": r["capacity_per_slot"],
        "active": r["active"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def gear_unit(r):
    return {
        "id": r["id"],
        "gear_type_id": r["gear_type_id"],
        "rate_card_id": r["rate_card_id"],
        "asset_tag": r["asset_tag"],
        "condition": r["condition"],
        "availability": r["availability"],
        "active_reservation_id": r["active_reservation_id"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def reservation(r):
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "gear_unit_id": r["gear_unit_id"],
        "rate_card_id": r["rate_card_id"],
        "pickup_at": db.iso(r["pickup_at"]),
        "due_at": db.iso(r["due_at"]),
        "picked_up_at": db.iso(r["picked_up_at"]),
        "returned_at": db.iso(r["returned_at"]),
        "lifecycle_status": r["lifecycle_status"],
        "payment_status": r["payment_status"],
        "quoted_rate_basis": r["quoted_rate_basis"],
        "quoted_total_cents": r["quoted_total_cents"],
        "deposit_cents": r["deposit_cents"],
        "final_total_cents": r["final_total_cents"],
        "late_fee_cents": r["late_fee_cents"],
        "damage_waiver_opted": r["damage_waiver_opted"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def reservation_addon(r):
    return {
        "id": r["id"],
        "reservation_id": r["reservation_id"],
        "addon_id": r["addon_id"],
        "slot_start_at": db.iso(r["slot_start_at"]),
        "slot_end_at": db.iso(r["slot_end_at"]),
        "price_cents": r["price_cents"],
        "created_at": db.iso(r["created_at"]),
    }


def condition_report(r):
    return {
        "id": r["id"],
        "reservation_id": r["reservation_id"],
        "gear_unit_id": r["gear_unit_id"],
        "phase": r["phase"],
        "condition_rating": r["condition_rating"],
        "notes": r["notes"],
        "created_at": db.iso(r["created_at"]),
    }


def damage_assessment(r):
    return {
        "id": r["id"],
        "reservation_id": r["reservation_id"],
        "checkin_report_id": r["checkin_report_id"],
        "outcome": r["outcome"],
        "charge_cents": r["charge_cents"],
        "waiver_applied": r["waiver_applied"],
        "status": r["status"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def ledger_entry(r):
    return {
        "id": r["id"],
        "reservation_id": r["reservation_id"],
        "customer_id": r["customer_id"],
        "entry_type": r["entry_type"],
        "amount_cents": r["amount_cents"],
        "settled": r["settled"],
        "created_at": db.iso(r["created_at"]),
    }
