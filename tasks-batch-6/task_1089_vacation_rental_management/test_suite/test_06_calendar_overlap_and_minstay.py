"""Calendar overlap (half-open, no buffer), min-stay priority, and night conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_pricing_rule_payload, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _listed_with_guest_and_hold(api, hold_check_in, hold_check_out):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    fixtures.create_booking(api, listed["property"]["id"], guest["id"], hold_check_in, hold_check_out)
    return listed["property"]["id"], guest["id"]


def test_adjacent_booking_allowed_halfopen(api):
    """PRD §3.4: "Overlap uses half-open interval semantics so back-to-back stays are
    permitted; a genuine overlap is rejected with `ERR_DATES_UNAVAILABLE`."
    PRD §2.9: "two stays that merely touch at a shared date (one checking out the morning
    another checks in) do not overlap and are both allowed."

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_overlap_rejected_adjacent_allowed
    """
    pid, gid = _listed_with_guest_and_hold(api, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-04T00:00:00Z", "check_out": "2026-07-06T00:00:00Z"}, PM)
    data = validate_success(resp, 201)
    assert data["stay_status"] == "HOLD", f"adjacent booking should succeed, got {data['stay_status']}"


def test_overlapping_booking_rejected_dates_unavailable(api):
    """PRD §3.4: "the requested interval must not overlap any existing booking on the property
    whose `stay_status` is `HOLD`, `CONFIRMED`, or `CHECKED_IN`. Overlap uses half-open
    interval semantics so back-to-back stays are permitted; a genuine overlap is rejected with
    `ERR_DATES_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_overlap_rejected_adjacent_allowed
    """
    pid, gid = _listed_with_guest_and_hold(api, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-03T00:00:00Z", "check_out": "2026-07-05T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE.value)


def _listed_with_minstay_and_hold(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    version = fixtures.get_property_version(api, pid)
    get_success_data(api.create_pricing_rule(pid, create_pricing_rule_payload(
        "MIN_STAY", priority=1, expected_property_version=version, min_nights=3), PM))
    guest = fixtures.create_guest(api)
    fixtures.create_booking(api, pid, guest["id"], "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    return pid, guest["id"]


def test_minstay_beats_dates_unavailable_priority(api):
    """PRD §2.6: order is "8. Business-constraint (domain) — vendor-type and minimum-stay
    checks. 9. Business-temporal — date-overlap and vendor-window checks."
    PRD §3.4: "the number of `nights` must meet any active `MIN_STAY` rule's `min_nights`
    (else `ERR_MIN_STAY_NOT_MET`)".

    Design: Difficulty/priority_pair_validation_conflict/booking_minstay_beats_dates_unavailable
    """
    pid, gid = _listed_with_minstay_and_hold(api)
    # 1-night booking that both under-runs min-stay (1 < 3) AND overlaps the existing HOLD.
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-11T00:00:00Z", "check_out": "2026-07-12T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_MIN_STAY_NOT_MET.value)


def test_minstay_alone_rejects_short_booking(api):
    """PRD §3.4: "the number of `nights` must meet any active `MIN_STAY` rule's `min_nights`
    (else `ERR_MIN_STAY_NOT_MET`)".

    Design: Difficulty/priority_pair_validation_conflict/booking_minstay_beats_dates_unavailable
    """
    pid, gid = _listed_with_minstay_and_hold(api)
    # 1-night booking on non-overlapping dates: only the min-stay rule is violated.
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-20T00:00:00Z", "check_out": "2026-07-21T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_MIN_STAY_NOT_MET.value)


def test_calendar_occupancy_reflects_active_hold(api):
    """PRD §3.3: "It counts the booked night-days within that window ... of any other booking
    on the same property whose `stay_status` is `HOLD`, `CONFIRMED`, `CHECKED_IN`, or
    `CHECKED_OUT` ... and divides that count by thirty, multiplies by one hundred, and takes
    the floor to a whole integer percent."

    Design: Difficulty/compensating_invariant/calendar_nights_conservation_on_cancel
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    before = get_success_data(api.quote_property(pid, {"check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM))
    assert before["occupancy_pct"] == 0, f"expected 0 before booking, got {before['occupancy_pct']}"
    fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    during = get_success_data(api.quote_property(pid, {"check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM))
    assert during["occupancy_pct"] == 10, f"expected 10 with 3 held nights, got {during['occupancy_pct']}"


def test_calendar_nights_released_on_cancel(api):
    """PRD §2.9: "The invariant that available nights plus booked nights plus blocked nights
    equals the total window nights must always hold; creating a booking occupies nights and
    cancelling one releases them, restoring the balance."
    PRD §3.3: "Cancelled and declined bookings never contribute."

    Design: Difficulty/compensating_invariant/calendar_nights_conservation_on_cancel
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    b = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    during = get_success_data(api.quote_property(pid, {"check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM))
    assert during["occupancy_pct"] == 10
    get_success_data(api.cancel_booking(b["id"], PM))
    after = get_success_data(api.quote_property(pid, {"check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM))
    assert after["occupancy_pct"] == 0, f"expected 0 after cancel, got {after['occupancy_pct']}"
