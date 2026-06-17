"""Entity serializers.

Field sets trace to SCAFFOLD §1.1 entities. Common fields per PRD §2.4:
the full quartet (id, created_at, updated_at, version) applies to every entity
EXCEPT LockerRental and ClockState, which carry only id and created_at.
"""

_QUARTET = ("id", "created_at", "updated_at", "version")


def _quartet(rec):
    return {k: rec[k] for k in _QUARTET}


def park(rec):
    out = _quartet(rec)
    out.update({
        "name": rec["name"],
        "timezone": rec["timezone"],
        "total_gate_capacity": rec["total_gate_capacity"],
        "weather_status": rec["weather_status"],
        "resident_zip_prefixes": list(rec["resident_zip_prefixes"]),
        "open_window_count": rec["open_window_count"],
        "rain_check_value_cents": rec["rain_check_value_cents"],
    })
    return out


def pricing_policy(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "product_type": rec["product_type"],
        "base_price_cents": rec["base_price_cents"],
        "resident_discount_pct": rec["resident_discount_pct"],
        "group_threshold": rec["group_threshold"],
        "group_discount_pct": rec["group_discount_pct"],
        "combo_price_cents": rec["combo_price_cents"],
        "active": rec["active"],
    })
    return out


def entry_window(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "starts_at": rec["starts_at"],
        "ends_at": rec["ends_at"],
        "window_capacity": rec["window_capacity"],
        "reserved_count": rec["reserved_count"],
        "admitted_count": rec["admitted_count"],
        "status": rec["status"],
    })
    return out


def cabana(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "label": rec["label"],
        "tier": rec["tier"],
        "daily_rate_cents": rec["daily_rate_cents"],
        "turnover_buffer_minutes": rec["turnover_buffer_minutes"],
    })
    return out


def locker(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "bank_code": rec["bank_code"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
    })
    return out


def guest(rec):
    out = _quartet(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "zip_code": rec["zip_code"],
        "height_cm": rec["height_cm"],
        "wallet_credit_cents": rec["wallet_credit_cents"],
    })
    return out


def order(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "guest_id": rec["guest_id"],
        "product_type": rec["product_type"],
        "party_size": rec["party_size"],
        "food_beverage_combo": rec["food_beverage_combo"],
        "resident_rate_applied": rec["resident_rate_applied"],
        "group_rate_applied": rec["group_rate_applied"],
        "subtotal_cents": rec["subtotal_cents"],
        "total_cents": rec["total_cents"],
        "wallet_credit_used_cents": rec["wallet_credit_used_cents"],
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
    })
    return out


def admission(rec):
    out = _quartet(rec)
    out.update({
        "order_id": rec["order_id"],
        "park_id": rec["park_id"],
        "guest_id": rec["guest_id"],
        "entry_window_id": rec["entry_window_id"],
        "product_type": rec["product_type"],
        "ticket_price_cents": rec["ticket_price_cents"],
        "status": rec["status"],
        "freeze_days_used": rec["freeze_days_used"],
        "frozen_at": rec["frozen_at"],
        "band_color": rec["band_color"],
    })
    return out


def cabana_rental(rec):
    out = _quartet(rec)
    out.update({
        "cabana_id": rec["cabana_id"],
        "order_id": rec["order_id"],
        "park_id": rec["park_id"],
        "entry_window_id": rec["entry_window_id"],
        "starts_at": rec["starts_at"],
        "ends_at": rec["ends_at"],
        "price_cents": rec["price_cents"],
        "status": rec["status"],
    })
    return out


def locker_rental(rec):
    # PRD §2.4: LockerRental carries only id and created_at.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "locker_id": rec["locker_id"],
        "order_id": rec["order_id"],
        "starts_at": rec["starts_at"],
        "ends_at": rec["ends_at"],
        "hours_billed": rec["hours_billed"],
        "price_cents": rec["price_cents"],
    }


def rain_check(rec):
    out = _quartet(rec)
    out.update({
        "park_id": rec["park_id"],
        "guest_id": rec["guest_id"],
        "source_kind": rec["source_kind"],
        "source_ref_id": rec["source_ref_id"],
        "value_cents": rec["value_cents"],
        "status": rec["status"],
    })
    return out


def clock_state(rec):
    # PRD §2.4: ClockState carries only id and created_at.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "current_utc": rec["current_utc"],
    }
