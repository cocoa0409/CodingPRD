"""Resource serializers. Each returns the documented field set (SCAFFOLD §1.1,
PRD §2.4). Common fields id/created_at/updated_at/version on all versioned
resources; GarmentNote carries only id/created_at."""


def _common(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def plan_view(r):
    v = _common(r)
    v.update({
        "tier": r["tier"],
        "monthly_fee_cents": r["monthly_fee_cents"],
        "included_wash_fold_grams": r["included_wash_fold_grams"],
        "overage_rate_cents_per_kg": r["overage_rate_cents_per_kg"],
        "dryclean_discount_pct": r["dryclean_discount_pct"],
        "rush_waived": r["rush_waived"],
        "active": r["active"],
    })
    return v


def customer_view(r):
    v = _common(r)
    v.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "default_address": r["default_address"],
        "zone_code": r["zone_code"],
        "wallet_credit_cents": r["wallet_credit_cents"],
        "risk_score": r["risk_score"],
        "status": r["status"],
    })
    return v


def subscription_view(r):
    v = _common(r)
    v.update({
        "customer_id": r["customer_id"],
        "plan_id": r["plan_id"],
        "cycle_start_utc": r["cycle_start_utc"],
        "cycle_wash_fold_grams_used": r["cycle_wash_fold_grams_used"],
        "outstanding_balance_cents": r["outstanding_balance_cents"],
        "status": r["status"],
    })
    return v


def route_window_view(r):
    v = _common(r)
    v.update({
        "zone_code": r["zone_code"],
        "window_kind": r["window_kind"],
        "start_utc": r["start_utc"],
        "end_utc": r["end_utc"],
        "stop_capacity": r["stop_capacity"],
        "booked_stops": r["booked_stops"],
        "status": r["status"],
    })
    return v


def locker_view(r):
    v = _common(r)
    v.update({
        "zone_code": r["zone_code"],
        "location_label": r["location_label"],
        "compartment_count": r["compartment_count"],
        "hold_buffer_minutes": r["hold_buffer_minutes"],
        "status": r["status"],
    })
    return v


def order_view(r):
    v = _common(r)
    v.update({
        "customer_id": r["customer_id"],
        "subscription_id": r["subscription_id"],
        "pickup_window_id": r["pickup_window_id"],
        "delivery_window_id": r["delivery_window_id"],
        "handoff_method": r["handoff_method"],
        "rush": r["rush"],
        "ready_by_utc": r["ready_by_utc"],
        "estimate_total_cents": r["estimate_total_cents"],
        "final_total_cents": r["final_total_cents"],
        "risk_flag": r["risk_flag"],
        "status": r["status"],
    })
    return v


def garment_view(r):
    v = _common(r)
    v.update({
        "order_id": r["order_id"],
        "service_type": r["service_type"],
        "declared_weight_grams": r["declared_weight_grams"],
        "declared_piece_count": r["declared_piece_count"],
        "actual_weight_grams": r["actual_weight_grams"],
        "actual_piece_count": r["actual_piece_count"],
        "alteration_fee_cents": r["alteration_fee_cents"],
        "estimate_line_cents": r["estimate_line_cents"],
        "final_line_cents": r["final_line_cents"],
        "status": r["status"],
    })
    return v


def garment_note_view(r):
    # Append-only: only id and created_at, plus its documented input/system fields.
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "garment_id": r["garment_id"],
        "note_kind": r["note_kind"],
        "severity": r["severity"],
        "description": r["description"],
        "logged_by_role": r["logged_by_role"],
    }


def locker_assignment_view(r):
    v = _common(r)
    v.update({
        "order_id": r["order_id"],
        "locker_id": r["locker_id"],
        "compartment_index": r["compartment_index"],
        "hold_start_utc": r["hold_start_utc"],
        "hold_end_utc": r["hold_end_utc"],
        "status": r["status"],
    })
    return v


def claim_view(r):
    v = _common(r)
    v.update({
        "order_id": r["order_id"],
        "subject_kind": r["subject_kind"],
        "garment_id": r["garment_id"],
        "declared_value_cents": r["declared_value_cents"],
        "settlement_cents": r["settlement_cents"],
        "appeal_count": r["appeal_count"],
        "status": r["status"],
    })
    return v


def invoice_view(r):
    v = _common(r)
    v.update({
        "order_id": r["order_id"],
        "gross_cents": r["gross_cents"],
        "subscription_credit_cents": r["subscription_credit_cents"],
        "wallet_applied_cents": r["wallet_applied_cents"],
        "amount_due_cents": r["amount_due_cents"],
        "status": r["status"],
    })
    return v
