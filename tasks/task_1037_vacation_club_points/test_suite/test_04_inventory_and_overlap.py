"""Nightly occupancy, member single-occupancy overlap, and capacity conservation.

Queue A: rto_unittype_aggregate_capacity_overlap,
rto_member_calendar_single_occupancy_overlap, ci_unit_nights_conserved_book_then_full_cancel.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_reservation_payload,
    make_member_headers,
    member_current_bucket,
    new_member,
    new_reservation,
    new_resort,
    new_unit_type,
    set_clock,
    setup_member_and_unit_type,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── rto_unittype_aggregate_capacity_overlap ──────────────────────────────

def test_overlapping_night_on_full_unit_rejected(api):
    """PRD §2.10: "A candidate range fits only when, for every one of its nights, the
    count of such occupying reservations is strictly less than the unit type's total
    capacity (total_units)." PRD §3.4: "every requested night must have free capacity
    on the unit type per the occupancy rule in §2.10, or the request is rejected with
    ERR_NO_INVENTORY".

    Design: Difficulty/resource_temporal_overlap/rto_unittype_aggregate_capacity_overlap
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=1)
    new_reservation(world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-08-10", "2026-08-14")
    member_b = new_member(owned_points=5000)
    bucket_b = member_current_bucket(member_b["id"])
    resp = api.create_reservation(
        create_reservation_payload(member_b["id"], world["unit_type"]["id"], bucket_b["id"], "2026-08-12", "2026-08-16"),
        make_member_headers(member_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_INVENTORY.value, 409)


def test_adjacent_booking_on_full_unit_allowed(api):
    """PRD §2.10: "Because ranges are half-open, two reservations that merely abut —
    one departing on the very day the next arrives — do not overlap and do not compete
    for the same night."

    Design: Difficulty/resource_temporal_overlap/rto_unittype_aggregate_capacity_overlap
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=1)
    new_reservation(world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-08-10", "2026-08-14")
    member_b = new_member(owned_points=5000)
    bucket_b = member_current_bucket(member_b["id"])
    res = validate_success(
        api.create_reservation(
            create_reservation_payload(member_b["id"], world["unit_type"]["id"], bucket_b["id"], "2026-08-14", "2026-08-16"),
            make_member_headers(member_b["id"]),
        ),
        201,
    )
    assert res["status"] == "HELD"


# ─── rto_member_calendar_single_occupancy_overlap ─────────────────────────

def _two_unit_types_with_a_hold(api):
    """Member A holds Aug 10-14 on UT1 (total_units 1); UT2 (total_units 5) is free.
    Returns (member_a, bucket_a, ut2_id)."""
    set_clock("2026-07-01T00:00:00Z")
    member_a = new_member(owned_points=5000)
    bucket_a = member_current_bucket(member_a["id"])
    resort = new_resort()
    ut1 = new_unit_type(resort["id"], total_units=1, name="UT1")
    ut2 = new_unit_type(resort["id"], total_units=5, name="UT2")
    new_reservation(member_a["id"], ut1["id"], bucket_a["id"], "2026-08-10", "2026-08-14")
    return member_a, bucket_a, ut2["id"]


def test_member_overlap_on_different_unit_rejected(api):
    """PRD §3.4: "the booking member must not already hold another active reservation
    whose nights overlap the requested nights, or the request is rejected with
    ERR_MEMBER_DATE_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/rto_member_calendar_single_occupancy_overlap
    """
    member_a, bucket_a, ut2_id = _two_unit_types_with_a_hold(api)
    resp = api.create_reservation(
        create_reservation_payload(member_a["id"], ut2_id, bucket_a["id"], "2026-08-12", "2026-08-16"),
        make_member_headers(member_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_DATE_OVERLAP.value, 409)


def test_member_non_overlapping_second_booking_allowed(api):
    """PRD §3.4: "the booking member must not already hold another active reservation
    whose nights overlap the requested nights, or the request is rejected with
    ERR_MEMBER_DATE_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/rto_member_calendar_single_occupancy_overlap
    """
    member_a, bucket_a, ut2_id = _two_unit_types_with_a_hold(api)
    # Aug 14-16 abuts the Aug 10-14 hold; half-open ranges do not overlap.
    res = validate_success(
        api.create_reservation(
            create_reservation_payload(member_a["id"], ut2_id, bucket_a["id"], "2026-08-14", "2026-08-16"),
            make_member_headers(member_a["id"]),
        ),
        201,
    )
    assert res["status"] == "HELD"


# ─── ci_unit_nights_conserved_book_then_full_cancel ───────────────────────

def _book_and_full_cancel_then_context(api):
    """Clock 2026-06-11 (days_out 60 -> FULL cancel). A books Aug 10-14 on a
    total_units=1 unit and cancels; returns (cancelled_res, unit_type_id, member_c, bucket_c)."""
    set_clock("2026-06-11T00:00:00Z")
    member_a = new_member(owned_points=5000)
    bucket_a = member_current_bucket(member_a["id"])
    member_c = new_member(owned_points=5000)
    bucket_c = member_current_bucket(member_c["id"])
    resort = new_resort()
    ut = new_unit_type(resort["id"], total_units=1)
    res_a = new_reservation(member_a["id"], ut["id"], bucket_a["id"], "2026-08-10", "2026-08-14")
    cancelled = validate_success(api.cancel_reservation(res_a["id"], make_member_headers(member_a["id"])), 200)
    return cancelled, ut["id"], member_c, bucket_c


def test_full_cancel_frees_capacity_for_rebooking(api):
    """PRD §3.5: "the reservation moves to CANCELLED, and every night it occupied on
    the unit type is released." PRD §2.10: "a given night is occupied by every
    reservation of that unit type whose status is HELD, CONFIRMED, or COMPLETED".

    Design: Difficulty/compensating_invariant/ci_unit_nights_conserved_book_then_full_cancel
    """
    _, ut_id, member_c, bucket_c = _book_and_full_cancel_then_context(api)
    res_c = validate_success(
        api.create_reservation(
            create_reservation_payload(member_c["id"], ut_id, bucket_c["id"], "2026-08-10", "2026-08-14"),
            make_member_headers(member_c["id"]),
        ),
        201,
    )
    assert res_c["status"] == "HELD"
    assert res_c["points_cost"] == 1000


def test_full_cancel_refunds_entire_cost(api):
    """PRD §3.5: "If days_out is at least 60, the refund is full and refunded_points
    equals the entire points_cost."

    Design: Difficulty/compensating_invariant/ci_unit_nights_conserved_book_then_full_cancel
    """
    cancelled, _, _, _ = _book_and_full_cancel_then_context(api)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_points"] == 1000
