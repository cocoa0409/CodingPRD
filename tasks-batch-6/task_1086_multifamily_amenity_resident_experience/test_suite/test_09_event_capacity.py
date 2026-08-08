"""Event capacity allocation boundary: registration at reserved_count ==
capacity waitlists.

Queue A (Difficulty):
boundary_precision_check/event_register_at_capacity_waitlists.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    validate_success,
)


def _setup_full_event_second_registrant(api):
    """Published event capacity 1 fee 500; resident A already RESERVED so
    reserved_count == 1. Returns (event_id, res_b_id)."""
    prop = fx.new_property(api, name="Fir", address="6 Fir St", guest_parking_capacity=5)
    unit_a = fx.new_unit(api, prop["id"], unit_number="602")
    unit_b = fx.new_unit(api, prop["id"], unit_number="603")
    res_a = fx.new_resident(api, unit_a["id"], full_name="Jo", email="jo@x.com")
    res_b = fx.new_resident(api, unit_b["id"], full_name="Kai", email="kai@x.com")
    fx.set_clock(api, "2026-05-20T00:00:00Z")
    event = fx.get_success_data(api.create_event(
        {"property_id": prop["id"], "title": "Yoga",
         "start_at": "2026-06-20T09:00:00Z", "end_at": "2026-06-20T10:00:00Z",
         "capacity": 1, "fee_cents": 500}, fx.PM))
    fx.get_success_data(api.publish_event(event["id"], fx.PM))
    fx.register_resident(api, event["id"], res_a["id"])
    return event["id"], res_b["id"]


def test_registration_at_capacity_is_waitlisted(api):
    """PRD §3.4: "When `reserved_count` has reached `capacity` (they are equal),
    the registration is instead created `WAITLISTED` with `fee_charged_cents` of
    zero and no charge, and the event's `waitlist_count` is increased by one."

    With reserved_count == capacity (1), the next registration is WAITLISTED and
    charges nothing.

    Design: Difficulty/boundary_precision_check/event_register_at_capacity_waitlists
    """
    event_id, res_b_id = _setup_full_event_second_registrant(api)
    reg = validate_success(
        api.register_event(event_id, {"resident_id": res_b_id}, make_resident_headers(res_b_id)),
        expected_status=201,
    )
    assert reg["status"] == "WAITLISTED"
    assert reg["fee_charged_cents"] == 0


def test_waitlisted_registration_updates_event_counts(api):
    """PRD §3.4: "Allocation is by a strict capacity comparison: if the event's
    `reserved_count` is strictly less than its `capacity`, the registration is
    created `RESERVED`, ..."

    After the boundary registration, reserved_count stays 1 and waitlist_count
    becomes 1.

    Design: Difficulty/boundary_precision_check/event_register_at_capacity_waitlists
    """
    event_id, res_b_id = _setup_full_event_second_registrant(api)
    validate_success(
        api.register_event(event_id, {"resident_id": res_b_id}, make_resident_headers(res_b_id)),
        expected_status=201,
    )
    event = validate_success(api.get_event(event_id, fx.PM))
    assert event["reserved_count"] == 1
    assert event["waitlist_count"] == 1
