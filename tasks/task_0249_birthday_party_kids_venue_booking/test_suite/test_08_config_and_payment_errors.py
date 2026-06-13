"""Configuration preconditions and fiscal/state error paths: add-on locking, venue
mismatch, capacity, existence ordering, closed rooms, skill/staff checks, retired
packages, and refund/balance/void rejections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_venue, create_room, create_package, create_staff,
    create_quote_draft_booking, hold_booking, add_addon, add_waiver, sign_waiver,
    assign_staff, take_payment, create_confirmed_booking, create_held_booking,
    reset_clock_base, set_clock,
)

VM = "venue_manager_headers"
COORD = "coordinator_headers"
FIN = "finance_clerk_headers"


# ─── Corner: validations / addon_locked_after_confirm ──────────────────────────

def test_remove_addon_after_confirm_rejected(api, coordinator_headers):
    """PRD 3.3: "Add-ons enrich a booking and are added only while the booking is in
    `QUOTE_DRAFT` or `HELD`; attempting to add or remove an add-on in any other state
    is rejected with `ERR_ADDON_LOCKED`, because add-ons are immutable once the booking
    is `CONFIRMED`."

    Design: Corner/validations/addon_locked_after_confirm
    """
    ctx = create_confirmed_booking(
        children_count=1, base_price_cents=30000, included_children=1,
        addons=[("CAKE", 4500)], pay_amount=34500)
    bid = ctx["booking"]["id"]
    addons, _ = _list_add_ons(api, bid, coordinator_headers)
    addon = addons[0]
    res = api.delete_add_on(bid, addon["id"], coordinator_headers)
    validate_error(res, "ERR_ADDON_LOCKED")
    addons, _ = _list_add_ons(api, bid, coordinator_headers)
    assert [a for a in addons if a["id"] == addon["id"]][0]["status"] == "ACTIVE"


# ─── Corner: validations / venue_mismatch_on_booking_create ────────────────────

def test_venue_mismatch_on_booking_create(api, coordinator_headers):
    """PRD 3.2: "if `room.venue_id` does not equal `package.venue_id` the create is
    rejected with `ERR_VENUE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/venue_mismatch_on_booking_create
    """
    v1 = create_venue(weather_dependent=False)
    v2 = create_venue(weather_dependent=False)
    room = create_room(v1["id"], name="Rm", max_capacity=20, buffer_minutes=30)
    package = create_package(v2["id"], base_price_cents=30000, included_children=8,
                             per_extra_child_cents=1500, base_duration_minutes=120,
                             deposit_pct=0.25)
    reset_clock_base()
    res = api.create_booking(
        {"room_id": room["id"], "package_id": package["id"],
         "event_start_utc": "2026-07-01T10:00:00Z", "children_count": 8}, coordinator_headers)
    validate_error(res, "ERR_VENUE_MISMATCH", expected_status=422)


# ─── Corner: validations / capacity_exceeded_over_max ──────────────────────────

def test_capacity_exceeded_over_max_on_hold(api, coordinator_headers):
    """PRD 3.7: "The committed head count — children plus adults — must not exceed the
    room's `max_capacity`, or the hold is rejected with `ERR_ROOM_CAPACITY_EXCEEDED`."

    Design: Corner/validations/capacity_exceeded_over_max
    """
    venue, room, package = setup_config(max_capacity=10, included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"],
                                         children_count=8, adults_count=3)  # 11 > 10
    res = api.hold_booking(booking["id"], coordinator_headers)
    validate_error(res, "ERR_ROOM_CAPACITY_EXCEEDED")
    booking = validate_success(api.get_booking(booking["id"], coordinator_headers), 200)
    assert booking["status"] == "QUOTE_DRAFT"


# ─── Corner: validations / existence_before_state_priority ─────────────────────

def test_existence_checked_before_state_on_confirm(api, coordinator_headers):
    """PRD 2.7: "a missing booking yields `ERR_BOOKING_NOT_FOUND` before the child is
    ever consulted".
    PRD 2.8: "(3) existence of path-referenced resources, left to right" precedes
    "(6) the target entity being in a state that admits the requested transition".

    Design: Corner/validations/existence_before_state_priority
    """
    res = api.confirm_booking("00000000-0000-4000-8000-000000000000", coordinator_headers)
    validate_error(res, "ERR_BOOKING_NOT_FOUND", expected_status=404)


# ─── Corner: errors / error_room_closed_on_hold ────────────────────────────────

def test_hold_on_closed_room_rejected(api, coordinator_headers, venue_manager_headers):
    """PRD 3.7: "The room must be `OPEN`, or the hold is rejected with
    `ERR_ROOM_CLOSED`."

    Design: Corner/errors/error_room_closed_on_hold
    """
    venue, room, package = setup_config()
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    validate_success(api.close_room(room["id"], venue_manager_headers), 200)
    res = api.hold_booking(booking["id"], coordinator_headers)
    validate_error(res, "ERR_ROOM_CLOSED")
    booking = validate_success(api.get_booking(booking["id"], coordinator_headers), 200)
    assert booking["status"] == "QUOTE_DRAFT"


# ─── Corner: errors / error_skill_mismatch_on_assignment ───────────────────────

def test_skill_mismatch_on_assignment(api, coordinator_headers):
    """PRD 3.6: "the requested `role_on_event` must appear in that member's `skills`,
    or the assignment is rejected with `ERR_SKILL_MISMATCH`."

    Design: Corner/errors/error_skill_mismatch_on_assignment
    """
    venue, room, package = setup_config()
    staff = create_staff(venue["id"], "Host Only", ["HOST"])
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    hold_booking(booking["id"])
    res = api.create_staff_assignment(
        booking["id"], {"staff_member_id": staff["id"], "role_on_event": "ENTERTAINER"},
        coordinator_headers)
    validate_error(res, "ERR_SKILL_MISMATCH")


# ─── Corner: errors / error_staff_inactive_on_assignment ───────────────────────

def test_inactive_staff_assignment_rejected(api, coordinator_headers, venue_manager_headers):
    """PRD 3.6: "The staff member must be `AVAILABLE` — an inactive one is rejected
    with `ERR_STAFF_INACTIVE`".

    Design: Corner/errors/error_staff_inactive_on_assignment
    """
    venue, room, package = setup_config()
    staff = create_staff(venue["id"], "Host H", ["HOST"])
    validate_success(api.deactivate_staff_member(staff["id"], venue_manager_headers), 200)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    hold_booking(booking["id"])
    res = api.create_staff_assignment(
        booking["id"], {"staff_member_id": staff["id"], "role_on_event": "HOST"},
        coordinator_headers)
    validate_error(res, "ERR_STAFF_INACTIVE")


# ─── Corner: errors / error_package_retired_on_create ──────────────────────────

def test_retired_package_rejects_booking_create(api, coordinator_headers, venue_manager_headers):
    """PRD 3.1: "a manager may retire it to `RETIRED`, after which it rejects new
    quotes with `ERR_PACKAGE_RETIRED`."

    Design: Corner/errors/error_package_retired_on_create
    """
    venue, room, package = setup_config()
    validate_success(api.retire_package(package["id"], venue_manager_headers), 200)
    res = api.create_booking(
        {"room_id": room["id"], "package_id": package["id"],
         "event_start_utc": "2026-07-01T10:00:00Z", "children_count": 8}, coordinator_headers)
    validate_error(res, "ERR_PACKAGE_RETIRED")


# ─── Corner: errors / error_refund_exceeds_paid ────────────────────────────────

def test_refund_exceeding_paid_rejected(api, finance_clerk_headers):
    """PRD 3.11: "A manual refund may not exceed what has been paid: a `REFUND` whose
    `amount_cents` is greater than the current `amount_paid_cents` is rejected with
    `ERR_REFUND_EXCEEDS_PAID` (HTTP 402)."

    Design: Corner/errors/error_refund_exceeds_paid
    """
    venue, room, package, booking = create_held_booking(children_count=8, base_price_cents=30000)
    bid = booking["id"]
    take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    res = api.create_payment(bid, {"direction": "REFUND", "amount_cents": 8000,
                                   "purpose": "BALANCE"}, finance_clerk_headers)
    validate_error(res, "ERR_REFUND_EXCEEDS_PAID", expected_status=402)


# ─── Corner: errors / error_balance_outstanding_on_complete ────────────────────

def test_complete_with_outstanding_balance_rejected(api, coordinator_headers):
    """PRD 3.10: "The balance must be clear: after recomputing the bill against the
    settlement total, `balance_due_cents` must be at most zero, or completion is
    rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 402)."

    Design: Corner/errors/error_balance_outstanding_on_complete
    """
    # quote 30000, only deposit 7500 paid; balance 22500 outstanding at completion.
    ctx = create_confirmed_booking(children_count=8, base_price_cents=30000,
                                   included_children=8, pay_amount=7500)
    bid = ctx["booking"]["id"]
    set_clock("2026-07-01T13:00:00Z")
    res = api.complete_booking(bid, coordinator_headers)
    validate_error(res, "ERR_BALANCE_OUTSTANDING", expected_status=402)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "CONFIRMED"


# ─── Corner: errors / error_refund_immutable_void ──────────────────────────────

def test_void_refund_payment_rejected(api, finance_clerk_headers):
    """PRD 3.11: "only inbound charges may be voided — a `REFUND`-direction payment is
    immutable and a void attempt against it is rejected with `ERR_REFUND_IMMUTABLE`."

    Design: Corner/errors/error_refund_immutable_void
    """
    venue, room, package, booking = create_held_booking(children_count=8)
    bid = booking["id"]
    take_payment(bid, 9000, direction="CHARGE", purpose="DEPOSIT")
    refund = take_payment(bid, 4000, direction="REFUND", purpose="BALANCE")
    res = api.void_payment(bid, refund["id"], finance_clerk_headers)
    validate_error(res, "ERR_REFUND_IMMUTABLE")
    # The refund payment is unchanged.
    payments, _ = _list_payments(api, bid, finance_clerk_headers)
    assert [p for p in payments if p["id"] == refund["id"]][0]["status"] == "SETTLED"


# ─── helpers ───────────────────────────────────────────────────────────────────

def _list_add_ons(api, booking_id, headers):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_add_ons(booking_id, headers))


def _list_payments(api, booking_id, headers):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_payments(booking_id, headers))
