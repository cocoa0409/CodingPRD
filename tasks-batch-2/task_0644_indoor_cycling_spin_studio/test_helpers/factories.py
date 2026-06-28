"""Payload factories — one per entity, input fields only."""


def create_studio_payload(**overrides) -> dict:
    """Studio create body. name + city required; penalty policy fields optional."""
    defaults = {"name": "Downtown", "city": "NYC"}
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": "Main"}
    defaults.update(overrides)
    return defaults


def create_bike_payload(**overrides) -> dict:
    defaults = {"position_row": 1, "position_col": 1, "label": "A1"}
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {"email": "i1@x.com", "full_name": "Instr One"}
    defaults.update(overrides)
    return defaults


def create_session_payload(room_id, instructor_id, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "instructor_id": instructor_id,
        "start_utc": "2026-06-20T18:00:00Z",
        "end_utc": "2026-06-20T19:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def register_member_payload(home_studio_id, **overrides) -> dict:
    defaults = {
        "email": "m1@x.com",
        "full_name": "Mem One",
        "home_studio_id": home_studio_id,
    }
    defaults.update(overrides)
    return defaults


def create_credit_pack_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "kind": "CLASS_PACK",
        "purchased_credits": 5,
        "price_cents": 5000,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(member_id, bike_id, expected_session_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "bike_id": bike_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def join_waitlist_payload(member_id, credit_pack_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "credit_pack_id": credit_pack_id}
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "BOTTLE",
        "name": "Water Bottle",
        "unit_price_cents": 1000,
        "stock_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_retail_order_payload(member_id, studio_id, product_id, quantity, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "studio_id": studio_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def refund_pack_payload(expected_pack_version, **overrides) -> dict:
    defaults = {"expected_pack_version": expected_pack_version}
    defaults.update(overrides)
    return defaults
