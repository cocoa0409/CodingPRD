"""Booking precedence, capacity boundary, and interval-overlap semantics tests.

Difficulty queue (A) instances for priority_pair_validation_conflict, boundary_precision_check,
and resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, create_phleb, create_route_day, create_order,
    get_route_day_version, book, drive_to_arrived,
    setup_scheduled_appointment,
    ApiErrorId, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_stale_version_reported_before_window_conflict(api):
    """PRD §2.8: "In that case the booking is rejected with ERR_ROUTE_DAY_VERSION_STALE and an
    HTTP 412 status, before it can over-subscribe the route day's stop_capacity."
    PRD §2.7: "Notably, on appointment booking the route-day version check runs before any of the
    route-day business preconditions."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_window_conflict
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    stale_v = rd["version"]  # version observed before any booking lands
    o1 = create_order(partner["id"], panel_code="CMP14")
    # First booking on the SAME window advances the route day's version, making stale_v stale.
    book(o1["id"], rd["id"], rd["version"],
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    o2 = create_order(partner["id"], panel_code="CMP14")
    # O2 carries the stale version AND requests an overlapping window 09:00-09:30.
    resp = api.book_appointment(o2["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z",
        "expected_route_day_version": stale_v,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_VERSION_STALE.value, 412)
    order2 = validate_success(api.get_lab_order(o2["id"], _PROVIDER))
    assert order2["status"] == "ORDERED", f"expected ORDERED, got {order2['status']}"


def test_stale_version_keeps_route_day_count_unchanged(api):
    """PRD §2.8: "the booking is rejected with ERR_ROUTE_DAY_VERSION_STALE and an HTTP 412 status,
    before it can over-subscribe the route day's stop_capacity."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_window_conflict
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    stale_v = rd["version"]
    o1 = create_order(partner["id"], panel_code="CMP14")
    book(o1["id"], rd["id"], rd["version"],
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    o2 = create_order(partner["id"], panel_code="CMP14")
    resp = api.book_appointment(o2["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z",
        "expected_route_day_version": stale_v,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_VERSION_STALE.value, 412)
    rd_after = validate_success(api.get_route_day(rd["id"], _DISPATCHER))
    # The rejected booking must not over-subscribe: only the first booking counts.
    assert rd_after["booked_stop_count"] == 1, \
        f"stale booking must not increment the count, got {rd_after['booked_stop_count']}"


def test_order_state_check_reported_before_route_day_full(api):
    """PRD §3.4: "In either case the order must be in ORDERED or REDRAW_REQUIRED; a booking attempt
    against an order in any other status is rejected with ERR_ORDER_NOT_SCHEDULABLE."
    PRD §2.7: "Business-rule checks that follow — such as panel acceptance, phlebotomist
    availability, territory matching, capacity, and window conflict — are evaluated after the
    state check; the specific orderings among them are described alongside the workflows in §3."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_route_day_full
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=1)
    o1 = create_order(partner["id"], panel_code="CMP14")
    book(o1["id"], rd["id"], rd["version"],
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    rd_v2 = get_route_day_version(rd["id"])  # current (non-stale) version
    o2 = create_order(partner["id"], panel_code="CMP14")
    validate_success(api.cancel_order(o2["id"], _PROVIDER))  # O2 now CANCELLED
    # Booking a CANCELLED order onto a FULL route day: state check (p7) wins over full (p13).
    resp = api.book_appointment(o2["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T10:00:00Z",
        "window_end_utc": "2026-02-01T10:30:00Z",
        "expected_route_day_version": rd_v2,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE.value, 409)


def test_cancelled_order_cannot_be_booked_regardless_of_capacity(api):
    """PRD §3.4: "the order must be in ORDERED or REDRAW_REQUIRED; a booking attempt against an
    order in any other status is rejected with ERR_ORDER_NOT_SCHEDULABLE."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_route_day_full
    """
    # A CANCELLED order booked onto a route day with spare capacity still fails on the order-state
    # check, confirming the state guard is the controlling rejection.
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    o = create_order(partner["id"], panel_code="CMP14")
    validate_success(api.cancel_order(o["id"], _PROVIDER))
    resp = api.book_appointment(o["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z",
        "expected_route_day_version": rd["version"],
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE.value, 409)


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check
# ---------------------------------------------------------------------------

def test_route_day_capacity_is_strict_less_than(api):
    """PRD §3.4: "The route day's current booked_stop_count must be strictly less than its
    stop_capacity at booking time, or the request fails with ERR_ROUTE_DAY_FULL."

    Design: Difficulty/boundary_precision_check/route_day_capacity_strict_less_than
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=1)
    o1 = create_order(partner["id"], panel_code="CMP14")
    # booked_stop_count 0 < 1 -> first booking succeeds.
    appt1 = book(o1["id"], rd["id"], rd["version"],
                 window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    assert appt1["status"] == "SCHEDULED"
    rd_v2 = get_route_day_version(rd["id"])
    o2 = create_order(partner["id"], panel_code="CMP14")
    # booked_stop_count 1 < 1 is false -> second booking rejected.
    resp = api.book_appointment(o2["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T10:00:00Z",
        "window_end_utc": "2026-02-01T10:30:00Z",
        "expected_route_day_version": rd_v2,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_FULL.value, 409)
    rd_final = validate_success(api.get_route_day(rd["id"], _DISPATCHER))
    assert rd_final["booked_stop_count"] == 1, f"expected 1, got {rd_final['booked_stop_count']}"


def test_first_booking_at_capacity_one_succeeds(api):
    """PRD §3.4: "The route day's current booked_stop_count must be strictly less than its
    stop_capacity at booking time, or the request fails with ERR_ROUTE_DAY_FULL."

    Design: Difficulty/boundary_precision_check/route_day_capacity_strict_less_than
    """
    # At the boundary, booked_stop_count 0 is strictly less than stop_capacity 1, so the very
    # first booking onto a capacity-1 route day must succeed.
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=1)
    o1 = create_order(partner["id"], panel_code="CMP14")
    appt1 = book(o1["id"], rd["id"], rd["version"],
                 window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    assert appt1["status"] == "SCHEDULED", f"first booking must succeed, got {appt1['status']}"
    rd_after = validate_success(api.get_route_day(rd["id"], _DISPATCHER))
    assert rd_after["booked_stop_count"] == 1


def test_complete_draw_with_zero_specimens_rejected(api):
    """PRD §3.6: "Completion is allowed only when exactly specimens_required_count specimens exist
    for the order, all of them in COLLECTED status; any other collected count is rejected with
    ERR_SPECIMEN_COUNT_MISMATCH."

    Design: Difficulty/boundary_precision_check/complete_draw_zero_specimen_count_mismatch
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    drive_to_arrived(ctx, kit_tube_count=3)  # ARRIVED, zero specimens collected
    from test_helpers import make_phlebotomist_headers
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    validate_error(api.complete_draw(ctx["appt_id"], phleb_headers),
                   ApiErrorId.ERR_SPECIMEN_COUNT_MISMATCH.value)
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "ARRIVED", f"expected ARRIVED, got {appt['status']}"


def test_complete_draw_with_fewer_than_required_specimens_rejected(api):
    """PRD §3.6: "Completion is allowed only when exactly specimens_required_count specimens exist
    for the order, all of them in COLLECTED status; any other collected count is rejected with
    ERR_SPECIMEN_COUNT_MISMATCH."

    Design: Difficulty/boundary_precision_check/complete_draw_zero_specimen_count_mismatch
    """
    # required_tube_count is 3; collect only 2, so the collected count (2) != required (3).
    from test_helpers import make_phlebotomist_headers, collect_specimens, collect_specimen_payload
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    drive_to_arrived(ctx, kit_tube_count=3)
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(api.collect_specimen(ctx["appt_id"], collect_specimen_payload("T1"), phleb_headers))
    get_success_data(api.collect_specimen(ctx["appt_id"], collect_specimen_payload("T2"), phleb_headers))
    validate_error(api.complete_draw(ctx["appt_id"], phleb_headers),
                   ApiErrorId.ERR_SPECIMEN_COUNT_MISMATCH.value)
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "ARRIVED"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap
# ---------------------------------------------------------------------------

def test_appointment_windows_back_to_back_are_allowed(api):
    """PRD §3.4: "The overlap test uses half-open semantics, so back-to-back stops are allowed:
    one appointment ending exactly when another begins is not a conflict."

    Design: Difficulty/resource_temporal_overlap/appointment_window_half_open_no_conflict_at_touch
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    o1 = create_order(partner["id"], panel_code="CMP14")
    book(o1["id"], rd["id"], rd["version"],
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    rd_v2 = get_route_day_version(rd["id"])
    o2 = create_order(partner["id"], panel_code="CMP14")
    appt2 = book(o2["id"], rd["id"], rd_v2,
                 window_start_utc="2026-02-01T09:30:00Z", window_end_utc="2026-02-01T10:00:00Z")
    assert appt2["status"] == "SCHEDULED", f"expected SCHEDULED, got {appt2['status']}"
    order2 = validate_success(api.get_lab_order(o2["id"], _PROVIDER))
    assert order2["status"] == "SCHEDULED"
    rd_final = validate_success(api.get_route_day(rd["id"], _DISPATCHER))
    assert rd_final["booked_stop_count"] == 2, f"expected 2, got {rd_final['booked_stop_count']}"


def test_overlapping_appointment_window_is_rejected(api):
    """PRD §3.4: "the half-open interval [window_start_utc, window_end_utc) must lie within the
    route day's [shift_start_utc, shift_end_utc] and must not overlap any other booked
    appointment's window on the same route day."
    PRD §3.4: "A window that falls outside the shift or that overlaps an existing booked window
    is rejected with ERR_APPOINTMENT_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/appointment_window_half_open_no_conflict_at_touch
    """
    # The complement of the back-to-back case: a genuinely overlapping window (09:15 falls inside
    # the existing 09:00-09:30 stop) conflicts under the half-open rule.
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    o1 = create_order(partner["id"], panel_code="CMP14")
    book(o1["id"], rd["id"], rd["version"],
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z")
    rd_v2 = get_route_day_version(rd["id"])
    o2 = create_order(partner["id"], panel_code="CMP14")
    resp = api.book_appointment(o2["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:15:00Z",
        "window_end_utc": "2026-02-01T09:45:00Z",
        "expected_route_day_version": rd_v2,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_CONFLICT.value, 409)


def test_route_day_shift_touching_endpoints_conflict(api):
    """PRD §3.2: "this comparison uses closed-interval semantics: touching endpoints conflict, so
    a new shift whose start equals an existing open shift's end (or whose end equals an existing
    open shift's start) is a conflict, because a phlebotomist may not run two shifts that abut.
    A violation is rejected with ERR_ROUTE_DAY_SHIFT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/route_day_shift_closed_interval_touch_conflict
    """
    phleb = create_phleb()
    create_route_day(phleb["id"], service_date="2026-02-01",
                     shift_start_utc="2026-02-01T08:00:00Z", shift_end_utc="2026-02-01T12:00:00Z",
                     stop_capacity=5)
    resp = api.create_route_day(phleb["id"], {
        "territory_code": "SF_BAY", "service_date": "2026-02-01",
        "shift_start_utc": "2026-02-01T12:00:00Z", "shift_end_utc": "2026-02-01T16:00:00Z",
        "stop_capacity": 5,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_SHIFT_OVERLAP.value, 409)


def test_route_day_shift_end_touching_existing_start_conflict(api):
    """PRD §3.2: "a new shift whose start equals an existing open shift's end (or whose end equals
    an existing open shift's start) is a conflict, because a phlebotomist may not run two shifts
    that abut. A violation is rejected with ERR_ROUTE_DAY_SHIFT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/route_day_shift_closed_interval_touch_conflict
    """
    # The mirror adjacency: the new shift's END equals the existing shift's START (08:00).
    phleb = create_phleb()
    create_route_day(phleb["id"], service_date="2026-02-01",
                     shift_start_utc="2026-02-01T08:00:00Z", shift_end_utc="2026-02-01T12:00:00Z",
                     stop_capacity=5)
    resp = api.create_route_day(phleb["id"], {
        "territory_code": "SF_BAY", "service_date": "2026-02-01",
        "shift_start_utc": "2026-02-01T04:00:00Z", "shift_end_utc": "2026-02-01T08:00:00Z",
        "stop_capacity": 5,
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_SHIFT_OVERLAP.value, 409)
