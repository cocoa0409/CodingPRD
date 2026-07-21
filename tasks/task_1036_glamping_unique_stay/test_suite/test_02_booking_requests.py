"""Booking-request gates, the computed-nights claim, and listing OCC.

Covers difficulty queue A (boundary precision on min_nights, priority pair
safety-vs-constraint) and corner queue B (request validation gates, OCC layer).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_host_headers, make_guest_headers,
    create_booking_payload,
)
import test_helpers.fixtures as fx


# ------------------------------------------------ corner: computed nights field
def test_booking_computed_nights_ignores_client_input(api):
    """PRD §3.5: "The occupancy interval is the half-open range from `check_in`
    up to but not including `check_out`, and `nights` is the whole number of days
    between them."

    Note: this instance's `quoted_total_cents == 60000` sub-assertion is not
    emitted — the PRD quote formula adds a 12% guest service fee to the summed
    subtotal (§3.5), so a faithful PRD-only reader computes 67200, not 60000;
    the design value is not uniquely PRD-derivable. Only the computed-nights
    claim, which the PRD does uniquely determine, is asserted.

    Design: Corner/entities/booking_computed_nights_ignores_client_input
    """
    env = fx.setup_listed_listing(site_type="CABIN", min_nights=1, rate_cents=20000,
                                  cleaning_fee_cents=0, rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    assert booking["nights"] == 3


# ------------------------------------------------ corner: request-time gates
def test_booking_night_without_rate_rejected(api):
    """PRD §3.5: "every night of the stay must be covered by a seasonal rate
    window, else `ERR_NO_RATE_FOR_DATES` (HTTP 400)"

    Design: Corner/validations/booking_night_without_rate_rejected
    """
    env = fx.setup_listed_listing(min_nights=1, cleaning_fee_cents=0,
                                  rate_end="2026-08-01T00:00:00Z")
    version = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z", version),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_NO_RATE_FOR_DATES")


def test_booking_guest_count_over_max_rejected(api):
    """PRD §3.5: "the `guest_count` must not exceed the listing's `max_guests`,
    else `ERR_MAX_GUESTS_EXCEEDED` (HTTP 400)"

    Design: Corner/validations/booking_guest_count_over_max_rejected
    """
    env = fx.setup_listed_listing(max_guests=4, min_nights=1, cleaning_fee_cents=0,
                                  rate_end="2026-08-01T00:00:00Z")
    version = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z", version,
                               guest_count=5),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_MAX_GUESTS_EXCEEDED")


def test_cancel_from_requested_returns_not_cancellable(api):
    """PRD §3.8: "A guest may cancel a booking that is in `CONFIRMED` or
    `CHECKED_IN`; a cancellation attempt on a booking in any other status is
    rejected with `ERR_BOOKING_NOT_CANCELLABLE` (HTTP 400)."

    Design: Corner/state_machines/cancel_from_requested_returns_not_cancellable
    """
    env = fx.setup_listed_listing(min_nights=1, cleaning_fee_cents=0,
                                  rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    resp = api.cancel_booking(booking["id"], make_guest_headers(env["guest"]["id"]))
    validate_error(resp, "ERR_BOOKING_NOT_CANCELLABLE")


# --------------------------- difficulty: boundary_precision_check (6a) min_nights
def test_min_nights_at_boundary_accepted(api):
    """PRD §3.5: "the stay must be at least the effective minimum nights — the
    covering window's `min_nights_override` if the `check_in` window sets one,
    otherwise the listing's `min_nights` — else `ERR_MIN_NIGHTS_NOT_MET` (HTTP 400)"

    Design: Difficulty/boundary_precision_check/min_nights_boundary_at_and_below
    """
    env = fx.setup_listed_listing(min_nights=2, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    assert booking["nights"] == 2
    assert booking["status"] == "REQUESTED"


def test_min_nights_below_boundary_rejected(api):
    """PRD §3.5: "the stay must be at least the effective minimum nights — the
    covering window's `min_nights_override` if the `check_in` window sets one,
    otherwise the listing's `min_nights` — else `ERR_MIN_NIGHTS_NOT_MET` (HTTP 400)"

    Design: Difficulty/boundary_precision_check/min_nights_boundary_at_and_below
    """
    env = fx.setup_listed_listing(min_nights=2, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE",
                                  rate_end="2026-08-01T00:00:00Z")
    version = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", version),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_MIN_NIGHTS_NOT_MET")


# --------------------- difficulty: priority_pair_validation_conflict (5b)
def test_suspended_listing_beats_min_nights_on_booking_create(api):
    """PRD §3.5: "Several gates guard the request, evaluated in this order: the
    listing must currently be `LISTED`, else `ERR_LISTING_NOT_LISTED` (HTTP 400);
    every night of the stay must be covered by a seasonal rate window, else
    `ERR_NO_RATE_FOR_DATES` (HTTP 400); the stay must be at least the effective
    minimum nights — the covering window's `min_nights_override` if the `check_in`
    window sets one, otherwise the listing's `min_nights` — else
    `ERR_MIN_NIGHTS_NOT_MET` (HTTP 400)"

    A 1-night booking on a SUSPENDED listing with min_nights=2 fails BOTH the
    listing-status and the min-nights gate; the listing-status gate is listed
    first, so ERR_LISTING_NOT_LISTED is returned.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking_create
    """
    env = fx.setup_listed_listing(min_nights=2, cleaning_fee_cents=0,
                                  cancellation_policy="MODERATE",
                                  rate_end="2026-08-01T00:00:00Z")
    version = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    fx.suspend(env["host"]["id"], env["listing"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z", version),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_LISTING_NOT_LISTED")


def test_min_nights_gate_fires_alone_when_listing_is_listed(api):
    """PRD §3.5: "Several gates guard the request, evaluated in this order: the
    listing must currently be `LISTED`, else `ERR_LISTING_NOT_LISTED` (HTTP 400);
    every night of the stay must be covered by a seasonal rate window, else
    `ERR_NO_RATE_FOR_DATES` (HTTP 400); the stay must be at least the effective
    minimum nights — the covering window's `min_nights_override` if the `check_in`
    window sets one, otherwise the listing's `min_nights` — else
    `ERR_MIN_NIGHTS_NOT_MET` (HTTP 400)"

    Contrast to the suspended case: when the higher-priority listing-status gate
    passes (listing is LISTED), the lower-priority min-nights gate is the one that
    fires for a 1-night stay under min_nights=2.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking_create
    """
    env = fx.setup_listed_listing(min_nights=2, cleaning_fee_cents=0,
                                  cancellation_policy="MODERATE",
                                  rate_end="2026-08-01T00:00:00Z")
    version = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z", version),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_MIN_NIGHTS_NOT_MET")


# --------------------------------- corner: OCC layer (cross_cutting)
def test_booking_create_stale_listing_version_returns_stale(api):
    """PRD §2.7: "a booking-request write against a listing requires
    `expected_listing_version` to equal the target listing's current `version`.
    If another writer has advanced the listing's `version` since the guest last
    read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
    guest must re-read the listing and re-quote before trying again."

    Design: Corner/cross_cutting_complexity_layers/booking_create_stale_listing_version_returns_stale
    """
    env = fx.setup_listed_listing(min_nights=1, cleaning_fee_cents=0,
                                  rate_end="2026-08-01T00:00:00Z")
    stale_v = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    # Host bumps the listing version by repricing the rate window.
    fx.reprice_rate(env["host"]["id"], env["rates"][0]["id"], nightly_rate_cents=24000)
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z", stale_v),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_STALE_VERSION")


def test_booking_create_matching_version_succeeds_and_bumps_version(api):
    """PRD §3.5: "Creating the request increments the listing's `version` by 1."
    PRD §2.7: "a booking-request write against a listing requires
    `expected_listing_version` to equal the target listing's current `version`."

    Design: Corner/cross_cutting_complexity_layers/booking_create_matching_version_succeeds
    """
    env = fx.setup_listed_listing(min_nights=1, cleaning_fee_cents=0,
                                  rate_end="2026-08-01T00:00:00Z")
    cur_v = fx.read_listing_version(env["listing"]["id"], env["guest"]["id"])
    resp = api.create_booking(
        env["listing"]["id"],
        create_booking_payload(env["listing"]["id"], env["guest"]["id"],
                               "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z", cur_v),
        make_guest_headers(env["guest"]["id"]),
    )
    booking = validate_success(resp, 201)
    assert booking["status"] == "REQUESTED"
    after = get_success_data(api.get_listing(env["listing"]["id"],
                                             make_guest_headers(env["guest"]["id"])))
    assert after["version"] == cur_v + 1
