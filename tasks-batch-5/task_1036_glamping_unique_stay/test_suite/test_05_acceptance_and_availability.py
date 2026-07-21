"""Host acceptance gates: cross-entity listing status, half-open date overlap,
and the state-vs-temporal priority conflict.

Covers difficulty queue A (priority pair, cross-entity dependency, half-open
resource overlap).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_host_headers, make_guest_headers,
)
import test_helpers.fixtures as fx


# ------------------- difficulty: priority_pair_validation_conflict (5a)
def test_accept_declined_booking_returns_invalid_state_not_dates_unavailable(api):
    """PRD §2.9: "Then the target's state admits the requested transition — a
    generic mismatch yields `ERR_INVALID_STATE` (HTTP 400)."
    PRD §3.6: "the requested interval from `check_in` up to but not including
    `check_out` must not overlap any booking on the listing already in `CONFIRMED`
    or `CHECKED_IN`, else `ERR_DATES_UNAVAILABLE` (HTTP 409)."

    Booking B is already DECLINED and also overlaps a CONFIRMED booking; the
    state check (step 6) precedes endpoint business rules (step 7), so accept
    returns ERR_INVALID_STATE, not ERR_DATES_UNAVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_accept
    """
    env = fx.setup_listed_listing(site_type="YURT", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    hh = make_host_headers(env["host"]["id"])
    a = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    fx.accept_booking(env["host"]["id"], a["id"])
    b = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-11T00:00:00Z", "2026-07-14T00:00:00Z")
    get_success_data(api.decline_booking(b["id"], hh))
    resp = api.accept_booking(b["id"], hh)
    validate_error(resp, "ERR_INVALID_STATE")


def test_accept_declined_booking_leaves_status_declined(api):
    """PRD §3.6: "Declining a `REQUESTED` booking moves it to `DECLINED` and
    releases any experience-slot participants it was holding, so the affected
    slots' `reserved_participants` fall accordingly."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_accept
    """
    env = fx.setup_listed_listing(site_type="YURT", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    hh = make_host_headers(env["host"]["id"])
    a = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    fx.accept_booking(env["host"]["id"], a["id"])
    b = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-11T00:00:00Z", "2026-07-14T00:00:00Z")
    get_success_data(api.decline_booking(b["id"], hh))
    api.accept_booking(b["id"], hh)  # rejected; must not change state
    after = get_success_data(api.get_booking(b["id"], hh))
    assert after["status"] == "DECLINED"


# ------------------- difficulty: cross_entity_state_dependency (7a)
def test_accept_on_delisted_listing_returns_not_listed(api):
    """PRD §3.6: "Acceptance is gated: the listing must still be `LISTED`, else
    `ERR_LISTING_NOT_LISTED`, and the requested interval from `check_in` up to but
    not including `check_out` must not overlap any booking on the listing already
    in `CONFIRMED` or `CHECKED_IN`, else `ERR_DATES_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/booking_accept_requires_listing_listed
    """
    env = fx.setup_listed_listing(site_type="CABIN", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE", permit_type="CAMPING",
                                  rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-15T00:00:00Z", "2026-07-17T00:00:00Z")
    get_success_data(api.delist_listing(env["listing"]["id"],
                                        make_host_headers(env["host"]["id"])))
    resp = api.accept_booking(booking["id"], make_host_headers(env["host"]["id"]))
    validate_error(resp, "ERR_LISTING_NOT_LISTED")


def test_delist_leaves_requested_booking_untouched(api):
    """PRD §3.8: "Each booking on the listing in `CONFIRMED` or `CHECKED_IN` is
    moved to `CANCELLED` with a full refund — the refund fraction is forced to the
    full base regardless of the listing's `cancellation_policy`, so the host
    retains nothing."

    Delist only cancels CONFIRMED/CHECKED_IN bookings, so a REQUESTED booking on
    the delisted listing remains REQUESTED; the failed accept changes nothing.

    Design: Difficulty/cross_entity_state_dependency/booking_accept_requires_listing_listed
    """
    env = fx.setup_listed_listing(site_type="CABIN", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE", permit_type="CAMPING",
                                  rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-15T00:00:00Z", "2026-07-17T00:00:00Z")
    get_success_data(api.delist_listing(env["listing"]["id"],
                                        make_host_headers(env["host"]["id"])))
    api.accept_booking(booking["id"], make_host_headers(env["host"]["id"]))
    after = get_success_data(api.get_booking(booking["id"],
                                             make_host_headers(env["host"]["id"])))
    assert after["status"] == "REQUESTED"


# ------------------- difficulty: resource_temporal_overlap (8a) half-open
def test_adjacent_booking_accepted_half_open(api):
    """PRD §3.6: "the requested interval from `check_in` up to but not including
    `check_out` must not overlap any booking on the listing already in `CONFIRMED`
    or `CHECKED_IN`, else `ERR_DATES_UNAVAILABLE` (HTTP 409)."

    A checkout-day == next-checkin-day pair ([.,07-13) and [07-13,.)) does not
    overlap under half-open semantics, so the adjacent booking is accepted.

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_overlap_on_listing
    """
    env = fx.setup_listed_listing(site_type="YURT", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    a = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    fx.accept_booking(env["host"]["id"], a["id"])
    adj = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                             "2026-07-13T00:00:00Z", "2026-07-15T00:00:00Z")
    resp = api.accept_booking(adj["id"], make_host_headers(env["host"]["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"


def test_overlapping_booking_rejected_dates_unavailable(api):
    """PRD §3.6: "the requested interval from `check_in` up to but not including
    `check_out` must not overlap any booking on the listing already in `CONFIRMED`
    or `CHECKED_IN`, else `ERR_DATES_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_overlap_on_listing
    """
    env = fx.setup_listed_listing(site_type="YURT", min_nights=1, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    a = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                           "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    fx.accept_booking(env["host"]["id"], a["id"])
    ovl = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                             "2026-07-12T00:00:00Z", "2026-07-14T00:00:00Z")
    resp = api.accept_booking(ovl["id"], make_host_headers(env["host"]["id"]))
    validate_error(resp, "ERR_DATES_UNAVAILABLE")
