"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique():
    return next(_counter)


def create_store_payload(**overrides) -> dict:
    defaults = {"name": "Main Store", "region_code": "CA", "session_room_count": 1}
    defaults.update(overrides)
    return defaults


def create_staff_payload(store_id, **overrides) -> dict:
    defaults = {"store_id": store_id, "full_name": "Sam Staff", "role_type": "BOTH"}
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _unique()
    defaults = {"email": f"member{n}@example.com", "full_name": f"Member {n}"}
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = _unique()
    defaults = {
        "sku": f"SKU-{n}",
        "category": "GEAR",
        "name": "Test Product",
        "price_cents": 1000,
        "stock_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(expected_member_version, **overrides) -> dict:
    defaults = {"tier": "CLUB_BASIC", "expected_member_version": expected_member_version}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(member_id, fitter_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "fitter_id": fitter_id,
        "service_type": "SHOE_FITTING",
        "start_at": "2026-07-10T10:00:00Z",
        "end_at": "2026-07-10T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(coach_id, store_id, **overrides) -> dict:
    defaults = {
        "coach_id": coach_id,
        "store_id": store_id,
        "level": "BEGINNER",
        "start_at": "2026-07-12T10:00:00Z",
        "end_at": "2026-07-12T11:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    n = _unique()
    defaults = {
        "name": f"Race {n}",
        "event_date": "2026-08-01T08:00:00Z",
        "packet_capacity": 10,
        "entry_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def order_line_payload(product_id, qty=1, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def renew_payload(payment_outcome, **overrides) -> dict:
    defaults = {"payment_outcome": payment_outcome}
    defaults.update(overrides)
    return defaults


def inventory_adjustment_payload(delta, **overrides) -> dict:
    defaults = {"delta": delta}
    defaults.update(overrides)
    return defaults


def create_shoe_pair_payload(member_id, product_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "product_id": product_id}
    defaults.update(overrides)
    return defaults


def run_log_payload(distance_km, **overrides) -> dict:
    defaults = {"distance_km": distance_km}
    defaults.update(overrides)
    return defaults


def complete_payload(gait_result=None, **overrides) -> dict:
    defaults = {"gait_result": gait_result if gait_result is not None else {"pronation": "NEUTRAL"}}
    defaults.update(overrides)
    return defaults
