"""Output projections for each entity (the exact fields returned to clients).

Field sets follow SCAFFOLD §1.1 entities. Internal/private keys (prefixed "_")
are never exposed.
"""


def _base_full(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _base_lean(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def corporate_account(rec):
    out = _base_full(rec)
    out.update({
        "company_name": rec["company_name"],
        "billing_email": rec["billing_email"],
        "negotiated_discount_pct": rec["negotiated_discount_pct"],
        "default_gratuity_pct": rec["default_gratuity_pct"],
        "cancellation_grace_minutes": rec["cancellation_grace_minutes"],
        "status": rec["status"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
    })
    return out


def affiliate(rec):
    out = _base_full(rec)
    out.update({
        "name": rec["name"],
        "market_code": rec["market_code"],
        "payout_share_pct": rec["payout_share_pct"],
        "status": rec["status"],
        "open_farmouts": rec["open_farmouts"],
    })
    return out


def vehicle_class(rec):
    out = _base_full(rec)
    out.update({
        "code": rec["code"],
        "base_fare_cents": rec["base_fare_cents"],
        "per_mile_cents": rec["per_mile_cents"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "included_wait_minutes": rec["included_wait_minutes"],
        "wait_per_minute_cents": rec["wait_per_minute_cents"],
        "status": rec["status"],
    })
    return out


def vehicle(rec):
    out = _base_full(rec)
    out.update({
        "vehicle_class_id": rec["vehicle_class_id"],
        "plate": rec["plate"],
        "turnaround_minutes": rec["turnaround_minutes"],
        "status": rec["status"],
    })
    return out


def chauffeur(rec):
    out = _base_full(rec)
    out.update({
        "full_name": rec["full_name"],
        "home_market_code": rec["home_market_code"],
        "rest_buffer_minutes": rec["rest_buffer_minutes"],
        "status": rec["status"],
        "active_assignment_id": rec["active_assignment_id"],
    })
    return out


def reservation(rec):
    out = _base_full(rec)
    out.update({
        "corporate_account_id": rec["corporate_account_id"],
        "trip_type": rec["trip_type"],
        "vehicle_class_id": rec["vehicle_class_id"],
        "pickup_at": rec["pickup_at"],
        "planned_drop_at": rec["planned_drop_at"],
        "estimated_miles": rec["estimated_miles"],
        "charter_hours": rec["charter_hours"],
        "tolls_cents": rec["tolls_cents"],
        "gratuity_pct_override": rec["gratuity_pct_override"],
        "trip_status": rec["trip_status"],
        "settlement_status": rec["settlement_status"],
        "fulfillment_mode": rec["fulfillment_mode"],
        "quote_estimate_total_cents": rec["quote_estimate_total_cents"],
        "final_total_cents": rec["final_total_cents"],
        "chargeable_wait_minutes": rec["chargeable_wait_minutes"],
        "cancellation_fee_cents": rec["cancellation_fee_cents"],
    })
    return out


def flight_tracking(rec):
    out = _base_full(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "flight_number": rec["flight_number"],
        "scheduled_arrival_at": rec["scheduled_arrival_at"],
        "estimated_arrival_at": rec["estimated_arrival_at"],
        "meet_and_greet": rec["meet_and_greet"],
        "status": rec["status"],
    })
    return out


def assignment(rec):
    out = _base_full(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "chauffeur_id": rec["chauffeur_id"],
        "vehicle_id": rec["vehicle_id"],
        "window_start_at": rec["window_start_at"],
        "window_end_at": rec["window_end_at"],
        "status": rec["status"],
    })
    return out


def farm_out_order(rec):
    out = _base_full(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "affiliate_id": rec["affiliate_id"],
        "offered_payout_cents": rec["offered_payout_cents"],
        "status": rec["status"],
        "decline_reason": rec["decline_reason"],
    })
    return out


def wait_event(rec):
    out = _base_lean(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "kind": rec["kind"],
        "occurred_at": rec["occurred_at"],
    })
    return out


def cancellation_record(rec):
    out = _base_lean(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "tier": rec["tier"],
        "lead_minutes": rec["lead_minutes"],
        "fee_cents": rec["fee_cents"],
    })
    return out


def clock_state(rec):
    return {
        "current_utc": rec.get("current_utc"),
    }
