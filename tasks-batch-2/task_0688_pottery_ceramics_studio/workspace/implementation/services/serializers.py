"""Serializers: convert internal records into API output shape.

Each serializer emits exactly the fields the entity declares in SCAFFOLD §1.1,
including system fields id/created_at/updated_at/version (PRD §2.4). Internal
bookkeeping keys (those prefixed with '_') are never exposed.
"""


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def member(r):
    out = _common(r)
    out.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "phone": r["phone"],
        "tier": r["tier"],
        "point_balance": r["point_balance"],
        "lifetime_points_earned": r["lifetime_points_earned"],
        "status": r["status"],
    })
    return out


def paint_bar_item(r):
    out = _common(r)
    out.update({
        "sku": r["sku"],
        "name": r["name"],
        "category": r["category"],
        "unit_price_cents": r["unit_price_cents"],
        "on_hand_qty": r["on_hand_qty"],
        "reorder_threshold": r["reorder_threshold"],
        "low_stock": r["low_stock"],
        "status": r["status"],
    })
    return out


def studio_visit(r):
    out = _common(r)
    out.update({
        "member_id": r["member_id"],
        "party_size": r["party_size"],
        "visit_type": r["visit_type"],
        "party_booking_id": r["party_booking_id"],
        "studio_fee_cents": r["studio_fee_cents"],
        "bisque_subtotal_cents": r["bisque_subtotal_cents"],
        "supplies_subtotal_cents": r["supplies_subtotal_cents"],
        "provisional_total_cents": r["provisional_total_cents"],
        "points_redeemed": r["points_redeemed"],
        "discount_cents": r["discount_cents"],
        "settled_total_cents": r["settled_total_cents"],
        "points_earned": r["points_earned"],
        "status": r["status"],
    })
    return out


def bisque_piece(r):
    out = _common(r)
    out.update({
        "studio_visit_id": r["studio_visit_id"],
        "kiln_batch_id": r["kiln_batch_id"],
        "sku": r["sku"],
        "name": r["name"],
        "bisque_price_cents": r["bisque_price_cents"],
        "firing_temp": r["firing_temp"],
        "status": r["status"],
        "ready_at": r["ready_at"],
    })
    return out


def kiln_batch(r):
    out = _common(r)
    out.update({
        "kiln_name": r["kiln_name"],
        "firing_temp": r["firing_temp"],
        "capacity_slots": r["capacity_slots"],
        "occupied_slots": r["occupied_slots"],
        "turnaround_hours": r["turnaround_hours"],
        "started_at": r["started_at"],
        "firing_completes_at": r["firing_completes_at"],
        "status": r["status"],
    })
    return out


def party_booking(r):
    out = _common(r)
    out.update({
        "member_id": r["member_id"],
        "package_tier": r["package_tier"],
        "guest_count": r["guest_count"],
        "scheduled_for": r["scheduled_for"],
        "package_total_cents": r["package_total_cents"],
        "deposit_due_cents": r["deposit_due_cents"],
        "deposit_paid_cents": r["deposit_paid_cents"],
        "status": r["status"],
    })
    return out


def class_series(r):
    out = _common(r)
    out.update({
        "title": r["title"],
        "session_count": r["session_count"],
        "seat_capacity": r["seat_capacity"],
        "enrolled_count": r["enrolled_count"],
        "price_cents": r["price_cents"],
        "starts_at": r["starts_at"],
        "status": r["status"],
    })
    return out


def enrollment(r):
    out = _common(r)
    out.update({
        "class_series_id": r["class_series_id"],
        "member_id": r["member_id"],
        "amount_paid_cents": r["amount_paid_cents"],
        "points_earned": r["points_earned"],
        "status": r["status"],
    })
    return out


def ledger_entry(r):
    # Append-only: only id + created_at among the system fields (PRD §2.4).
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "entry_type": r["entry_type"],
        "points_delta": r["points_delta"],
        "source_ref_type": r["source_ref_type"],
        "source_ref_id": r["source_ref_id"],
        "created_at": r["created_at"],
    }
