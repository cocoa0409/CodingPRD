"""Reservation point-cost chart, booking window, and pre-hold validation ordering.

Queue A: cf_reservation_point_chart_mode_a, bpc_booking_window_inclusive_boundary,
ppvc_temporal_beats_constraint_on_reservation_create.
Queue B: reservation validation / not-found / insufficient-points / pagination corners.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
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
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── cf_reservation_point_chart_mode_a ────────────────────────────────────

def test_point_cost_sums_seasonal_dayclass_cells(api):
    """PRD §3.4: "Its points_cost is the sum, over each individual night in that
    range, of the one chart cell that applies to that night. For each night, the
    season is high when the month of that night is June, July, August, or December,
    and low in every other month; the day class is weekend when that night falls on
    a Friday or a Saturday, and weekday otherwise."

    Design: Difficulty/combinatorial_formula/cf_reservation_point_chart_mode_a
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=1, clock="2026-02-01T00:00:00Z")
    # Mar 2 (Mon) .. Mar 7: four weekday LOW nights (150) + Fri Mar 6 weekend LOW (200) = 800.
    res = validate_success(
        api.create_reservation(
            create_reservation_payload(
                world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"],
                "2026-03-02", "2026-03-07",
            ),
            world["member_headers"],
        ),
        201,
    )
    assert res["nights"] == 5
    assert res["points_cost"] == 800


def test_point_cost_commits_to_paying_bucket(api):
    """PRD §3.4: "the paying bucket's points_used rises by points_cost (committing
    the points), and each night is occupied on the unit type."

    Design: Difficulty/combinatorial_formula/cf_reservation_point_chart_mode_a
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=1, clock="2026-02-01T00:00:00Z")
    new_reservation(
        world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-03-02", "2026-03-07"
    )
    bucket = validate_success(api.get_points_bucket(world["bucket"]["id"], ADMIN), 200)
    assert bucket["points_used"] == 800
    assert bucket["points_available"] == 4200


# ─── bpc_booking_window_inclusive_boundary ────────────────────────────────

def test_booking_at_exactly_window_boundary_succeeds(api):
    """PRD §3.4: "the number of whole days from the current clock date to check_in
    must be greater than zero and at most the member's window length, or the request
    is rejected with ERR_OUTSIDE_BOOKING_WINDOW. ... every other member has the
    standard window of 366 days."

    Design: Difficulty/boundary_precision_check/bpc_booking_window_inclusive_boundary
    """
    # Clock 2026-07-01; check_in 2027-07-02 is exactly now + 366 days.
    world = setup_member_and_unit_type(owned_points=3000, total_units=1, clock="2026-07-01T00:00:00Z")
    res = validate_success(
        api.create_reservation(
            create_reservation_payload(
                world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"],
                "2027-07-02", "2027-07-03",
            ),
            world["member_headers"],
        ),
        201,
    )
    assert res["status"] == "HELD"
    assert res["points_cost"] == 350  # Fri 2027-07-02, HIGH season weekend


def test_booking_one_day_past_window_rejected(api):
    """PRD §3.4: "the number of whole days from the current clock date to check_in
    must be greater than zero and at most the member's window length, or the request
    is rejected with ERR_OUTSIDE_BOOKING_WINDOW."

    Design: Difficulty/boundary_precision_check/bpc_booking_window_inclusive_boundary
    """
    # 2027-07-03 is now + 367 days for a STANDARD member (window 366) -> outside.
    world = setup_member_and_unit_type(owned_points=3000, total_units=1, clock="2026-07-01T00:00:00Z")
    resp = api.create_reservation(
        create_reservation_payload(
            world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"],
            "2027-07-03", "2027-07-04",
        ),
        world["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_BOOKING_WINDOW.value, 422)


# ─── ppvc_temporal_beats_constraint_on_reservation_create ─────────────────

def _setup_full_unit_out_of_window(api):
    """PLATINUM member P fills a total_units=1 unit for 2027-07-16..18 (within 396d);
    returns (unit_type_id, standard_member, standard_bucket)."""
    set_clock("2026-07-01T00:00:00Z")
    member_p = new_member(owned_points=13000)  # PLATINUM, 396-day window
    bucket_p = member_current_bucket(member_p["id"])
    member_s = new_member(owned_points=3000)  # STANDARD, 366-day window
    bucket_s = member_current_bucket(member_s["id"])
    resort = new_resort()
    ut = new_unit_type(resort["id"], total_units=1)
    new_reservation(member_p["id"], ut["id"], bucket_p["id"], "2027-07-16", "2027-07-18")
    return ut["id"], member_s, bucket_s


def test_window_error_when_unit_full_and_out_of_window(api):
    """PRD §2.9: "the booking-window check on reservations and waitlist joins
    (`ERR_OUTSIDE_BOOKING_WINDOW`); (8) inventory and member-overlap checks
    (`ERR_NO_INVENTORY`, `ERR_MEMBER_DATE_OVERLAP`)".
    PRD §3.4: "Next, inventory and overlap are checked together: every requested
    night must have free capacity on the unit type per the occupancy rule in §2.10,
    or the request is rejected with `ERR_NO_INVENTORY`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_temporal_beats_constraint_on_reservation_create
    """
    ut_id, member_s, bucket_s = _setup_full_unit_out_of_window(api)
    resp = api.create_reservation(
        create_reservation_payload(member_s["id"], ut_id, bucket_s["id"], "2027-07-16", "2027-07-18"),
        make_member_headers(member_s["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_BOOKING_WINDOW.value, 422)


def test_window_rejection_creates_no_reservation(api):
    """PRD §3.4: "the number of whole days from the current clock date to `check_in`
    must be greater than zero and at most the member's window length, or the request
    is rejected with `ERR_OUTSIDE_BOOKING_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_temporal_beats_constraint_on_reservation_create
    """
    ut_id, member_s, bucket_s = _setup_full_unit_out_of_window(api)
    resp = api.create_reservation(
        create_reservation_payload(member_s["id"], ut_id, bucket_s["id"], "2027-07-16", "2027-07-18"),
        make_member_headers(member_s["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_BOOKING_WINDOW.value, 422)
    rows, meta = validate_paginated(
        api.list_reservations(ADMIN, params={"member_id": member_s["id"]})
    )
    assert meta["total_count"] == 0, "a window-rejected create must not persist a reservation"


# ─── Queue B: validation / not-found / insufficient / pagination corners ──

def test_checkout_not_after_checkin_rejected(api):
    """PRD §3.4: "The dates must be well formed and `check_out` must be strictly after
    `check_in`, or the request is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/corner_reservation_missing_required_field
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=2)
    resp = api.create_reservation(
        create_reservation_payload(
            world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"],
            "2026-08-14", "2026-08-10",
        ),
        world["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_unknown_unit_type_on_reservation_not_found(api):
    """PRD §2.9: "a missing unit type ERR_UNIT_TYPE_NOT_FOUND ... All referenced
    identifiers — whether in the path or in the request body — are validated for
    existence in left-to-right order".

    Design: Corner/validations/corner_not_found_unit_type_on_reservation
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    resp = api.create_reservation(
        create_reservation_payload(member["id"], NON_EXISTENT_UUID, bucket["id"], "2026-08-10", "2026-08-14"),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_TYPE_NOT_FOUND.value, 404)


def test_unknown_bucket_on_reservation_not_found(api):
    """PRD §2.9: "a missing bucket ERR_POINTS_BUCKET_NOT_FOUND ... the first
    identifier that does not resolve produces the corresponding not-found error
    before any later check runs".

    Design: Corner/validations/corner_not_found_bucket_on_reservation
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=2)
    resp = api.create_reservation(
        create_reservation_payload(
            world["member"]["id"], world["unit_type"]["id"], NON_EXISTENT_UUID, "2026-08-10", "2026-08-14"
        ),
        world["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_POINTS_BUCKET_NOT_FOUND.value, 404)


def test_unit_type_under_unknown_resort_not_found(api):
    """PRD §2.9: "a missing resort `ERR_RESORT_NOT_FOUND`, a missing unit type
    `ERR_UNIT_TYPE_NOT_FOUND`, a missing bucket `ERR_POINTS_BUCKET_NOT_FOUND`".

    Design: Corner/validations/corner_not_found_resort_on_unit_type
    """
    set_clock("2026-07-01T00:00:00Z")
    resp = api.create_unit_type(
        NON_EXISTENT_UUID,
        {"name": "X", "total_units": 1, "points_weekday_low": 150, "points_weekend_low": 200,
         "points_weekday_high": 250, "points_weekend_high": 350},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RESORT_NOT_FOUND.value, 404)


def test_reservation_insufficient_points(api):
    """PRD §3.4: "Finally the fiscal check runs: the paying bucket's points_available
    must cover the computed cost, or the request is rejected with ERR_INSUFFICIENT_POINTS."

    Design: Corner/calculations/corner_insufficient_points_on_reservation
    """
    # owned 200, capacity free (total_units 2); Aug 10-14 costs 1000 > 200.
    world = setup_member_and_unit_type(owned_points=200, total_units=2)
    resp = api.create_reservation(
        create_reservation_payload(
            world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-08-10", "2026-08-14"
        ),
        world["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value, 422)


def test_reservation_list_pagination(api):
    """PRD §2.3: "The limit parameter sets the maximum number of items returned ...
    Every list response includes limit, offset, total_count, and has_more in the
    meta object of the envelope."

    Design: Corner/endpoints/corner_reservation_list_pagination
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=2)
    new_reservation(world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-08-10", "2026-08-14")
    new_reservation(world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-09-10", "2026-09-14")
    rows, meta = validate_paginated(
        api.list_reservations(ADMIN, params={"member_id": world["member"]["id"], "limit": 1})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
