"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "GUARDIAN_NAME": "Test Guardian",
    "GUARDIAN_EMAIL": "guardian@example.com",
    "GUARDIAN_PHONE": "555-0100",
    "CHILD_NAME": "Test Child",
    "CHILD_BIRTH_DATE": "2020-01-15",
    "PLAN_NAME": "PLUS",
    "PLAN_MONTHLY_FEE_CENTS": 4900,
    "PLAN_CREDITS": 8,
    "PLAN_PARTY_DISCOUNT_PCT": 0.10,
    "PLAN_CAFE_DISCOUNT_PCT": 0.10,
    "PLAN_SOCKS_INCLUDED": True,
    "PACKAGE_NAME": "STD",
    "PACKAGE_DURATION_MINUTES": 120,
    "PACKAGE_BASE_PRICE_CENTS": 30000,
    "PACKAGE_INCLUDED_CHILDREN": 10,
    "PACKAGE_EXTRA_CHILD_PRICE_CENTS": 1500,
    "PACKAGE_CAFE_CREDIT_CENTS": 2000,
    "ROOM_NAME": "Room A",
    "ROOM_CAPACITY_CHILDREN": 20,
    "MENU_ITEM_NAME": "Latte",
    "MENU_ITEM_PRICE_CENTS": 425,
    "SLOT_CAPACITY": 10,
}


def create_membership_plan_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "monthly_fee_cents": DEFAULTS["PLAN_MONTHLY_FEE_CENTS"],
        "included_session_credits": DEFAULTS["PLAN_CREDITS"],
        "party_discount_pct": DEFAULTS["PLAN_PARTY_DISCOUNT_PCT"],
        "cafe_discount_pct": DEFAULTS["PLAN_CAFE_DISCOUNT_PCT"],
        "socks_included": DEFAULTS["PLAN_SOCKS_INCLUDED"],
    }
    defaults.update(overrides)
    return defaults


def create_guardian_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["GUARDIAN_NAME"],
        "email": DEFAULTS["GUARDIAN_EMAIL"],
        "phone": DEFAULTS["GUARDIAN_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CHILD_NAME"],
        "birth_date": DEFAULTS["CHILD_BIRTH_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(expected_guardian_version, **overrides) -> dict:
    defaults = {"expected_guardian_version": expected_guardian_version}
    defaults.update(overrides)
    return defaults


def create_session_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_date": "2026-06-06",
        "start_at": "2026-06-06T14:00:00Z",
        "end_at": "2026-06-06T15:30:00Z",
        "capacity": DEFAULTS["SLOT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(session_slot_id, child_id, guardian_id, **overrides) -> dict:
    defaults = {
        "session_slot_id": session_slot_id,
        "child_id": child_id,
        "guardian_id": guardian_id,
        "visit_type": "RESERVATION",
        "booked_duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_party_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "capacity_children": DEFAULTS["ROOM_CAPACITY_CHILDREN"],
    }
    defaults.update(overrides)
    return defaults


def create_party_package_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PACKAGE_NAME"],
        "duration_minutes": DEFAULTS["PACKAGE_DURATION_MINUTES"],
        "base_price_cents": DEFAULTS["PACKAGE_BASE_PRICE_CENTS"],
        "included_children": DEFAULTS["PACKAGE_INCLUDED_CHILDREN"],
        "extra_child_price_cents": DEFAULTS["PACKAGE_EXTRA_CHILD_PRICE_CENTS"],
        "cafe_credit_cents": DEFAULTS["PACKAGE_CAFE_CREDIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_party_booking_payload(party_room_id, party_package_id, guardian_id,
                                 expected_party_room_version, **overrides) -> dict:
    defaults = {
        "party_room_id": party_room_id,
        "party_package_id": party_package_id,
        "guardian_id": guardian_id,
        "start_at": "2026-06-08T10:00:00Z",
        "child_count": 10,
        "expected_party_room_version": expected_party_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_cafe_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MENU_ITEM_NAME"],
        "price_cents": DEFAULTS["MENU_ITEM_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cafe_order_payload(guardian_id, lines, **overrides) -> dict:
    defaults = {
        "guardian_id": guardian_id,
        "lines": lines,
        "child_ids": [],
    }
    defaults.update(overrides)
    return defaults


def order_line(menu_item_id, quantity) -> dict:
    return {"menu_item_id": menu_item_id, "quantity": quantity}


def create_staff_member_payload(**overrides) -> dict:
    defaults = {"full_name": "Staff Member", "role": "FRONT_DESK"}
    defaults.update(overrides)
    return defaults


def create_sanitation_task_payload(party_room_id, **overrides) -> dict:
    defaults = {
        "party_room_id": party_room_id,
        "kind": "BALL_PIT_WASH",
        "due_at": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "kind": "INJURY",
        "severity": "LOW",
        "description": "incident description",
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_adjustment_payload(points, note="adjustment", **overrides) -> dict:
    defaults = {"points": points, "note": note}
    defaults.update(overrides)
    return defaults
