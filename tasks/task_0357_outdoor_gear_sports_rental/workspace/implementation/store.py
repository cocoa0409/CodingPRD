"""Record factory + mutation helpers.

Mutable resources: version starts at 1, +1 on every mutation; updated_at
refreshed on each mutation (including cascades). Append-only resources carry
only id + created_at.
"""
import db


def _base_mutable():
    now = db.now_dt()
    rid = db.new_id()
    return rid, now


def touch(record):
    """Bump version + refresh updated_at on a mutable record (cascade-aware)."""
    record["version"] += 1
    record["updated_at"] = db.now_dt()


# ---- mutable entity creators ----

def create_gear_type(category, name, size_label, requires_lesson_for_beginner, active):
    rid, now = _base_mutable()
    rec = {
        "id": rid, "category": category, "name": name, "size_label": size_label,
        "requires_lesson_for_beginner": requires_lesson_for_beginner, "active": active,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db.gear_types[rid] = rec
    return rec


def create_rate_card(**f):
    rid, now = _base_mutable()
    rec = {"id": rid, "created_at": now, "updated_at": now, "version": 1}
    rec.update(f)
    db.rate_cards[rid] = rec
    return rec


def create_customer(full_name, email, skill_level):
    rid, now = _base_mutable()
    rec = {
        "id": rid, "full_name": full_name, "email": email, "skill_level": skill_level,
        "standing": "GOOD", "strike_points": 0, "open_loss_balance_cents": 0,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db.customers[rid] = rec
    return rec


def create_addon(kind, category, name, price_cents, capacity_per_slot, active):
    rid, now = _base_mutable()
    rec = {
        "id": rid, "kind": kind, "category": category, "name": name,
        "price_cents": price_cents, "capacity_per_slot": capacity_per_slot, "active": active,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db.addons[rid] = rec
    return rec


def create_gear_unit(gear_type_id, rate_card_id, asset_tag):
    rid, now = _base_mutable()
    rec = {
        "id": rid, "gear_type_id": gear_type_id, "rate_card_id": rate_card_id,
        "asset_tag": asset_tag, "condition": "GOOD", "availability": "AVAILABLE",
        "active_reservation_id": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db.gear_units[rid] = rec
    return rec


def create_reservation(**f):
    rid, now = _base_mutable()
    rec = {
        "id": rid,
        "picked_up_at": None, "returned_at": None,
        "lifecycle_status": "QUOTED", "payment_status": "UNPAID",
        "deposit_cents": 0, "final_total_cents": None, "late_fee_cents": 0,
        "created_at": now, "updated_at": now, "version": 1,
    }
    rec.update(f)
    db.reservations[rid] = rec
    return rec


def create_damage_assessment(reservation_id, checkin_report_id, outcome, charge_cents, waiver_applied, status):
    rid, now = _base_mutable()
    rec = {
        "id": rid, "reservation_id": reservation_id, "checkin_report_id": checkin_report_id,
        "outcome": outcome, "charge_cents": charge_cents, "waiver_applied": waiver_applied,
        "status": status,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db.damage_assessments[rid] = rec
    return rec


# ---- append-only entity creators ----

def create_season_window(category, label, starts_on, ends_on, demand_multiplier_bp):
    rid = db.new_id()
    now = db.now_dt()
    rec = {
        "id": rid, "category": category, "label": label,
        "starts_on": starts_on, "ends_on": ends_on,
        "demand_multiplier_bp": demand_multiplier_bp, "created_at": now,
    }
    db.season_windows[rid] = rec
    return rec


def create_reservation_addon(reservation_id, addon_id, slot_start_at, slot_end_at, price_cents):
    rid = db.new_id()
    now = db.now_dt()
    rec = {
        "id": rid, "reservation_id": reservation_id, "addon_id": addon_id,
        "slot_start_at": slot_start_at, "slot_end_at": slot_end_at,
        "price_cents": price_cents, "created_at": now,
    }
    db.reservation_addons[rid] = rec
    return rec


def create_condition_report(reservation_id, gear_unit_id, phase, condition_rating, notes):
    rid = db.new_id()
    now = db.now_dt()
    rec = {
        "id": rid, "reservation_id": reservation_id, "gear_unit_id": gear_unit_id,
        "phase": phase, "condition_rating": condition_rating, "notes": notes,
        "created_at": now,
    }
    db.condition_reports[rid] = rec
    return rec


def create_ledger_entry(reservation_id, customer_id, entry_type, amount_cents, settled=False):
    rid = db.new_id()
    now = db.now_dt()
    rec = {
        "id": rid, "reservation_id": reservation_id, "customer_id": customer_id,
        "entry_type": entry_type, "amount_cents": amount_cents, "settled": settled,
        "created_at": now,
    }
    db.ledger_entries[rid] = rec
    return rec


# ---- listing helper ----

def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
