"""Validation priority conflicts, boundary precision, and cross-entity gating.

Covers the priority-pair conflict instances (PRD §2.10 states the full order verbatim),
boundary-precision instances (check-in upper edge, 7-day refund edge), cross-entity
state dependencies (suspended driver / unlisted spot block booking), temporal-overlap
semantics, and the corner-design validation instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, setup_reserved_booking, setup_suspended_driver,
    create_booking, create_transfer_offer, get_spot_version, get_booking_version,
    set_clock, register_driver, create_pricing_event,
    create_booking_payload, redeem_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: priority_pair_validation_conflict / unlisted vs insufficient_wallet ───

def test_unlisted_spot_preferred_over_insufficient_wallet(api):
    """PRD §2.10: "the business-constraint checks in the order spot time-conflict
    (`ERR_SPOT_TIME_CONFLICT`), pricing-event zone-conflict (`ERR_EVENT_ZONE_CONFLICT`),
    gate-pass validity (`ERR_GATE_PASS_INVALID`), spot-listed (`ERR_SPOT_UNLISTED`),
    driver-not-suspended (`ERR_DRIVER_SUSPENDED`), and transfer-not-to-self
    (`ERR_TRANSFER_TO_SELF`); then the wallet-funding check (`ERR_INSUFFICIENT_WALLET`)".

    A booking on an UNLISTED spot by a zero-wallet driver fails both spot-listed (P40) and
    wallet (P50); the earlier-evaluated ERR_SPOT_UNLISTED is surfaced.

    Design: Difficulty/priority_pair_validation_conflict/unlisted_spot_vs_insufficient_wallet_prefers_state_over_fiscal
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=0, spot_overrides={"zone_code": "Z9"})
    get_success_data(api.unlist_spot(spot["id"], make_host_headers(host["id"])))
    sv = get_spot_version(host["id"], spot["id"])
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", sv),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_SPOT_UNLISTED")


def test_listed_spot_zero_wallet_surfaces_wallet_error(api):
    """PRD §2.10: "then the wallet-funding check (`ERR_INSUFFICIENT_WALLET`)".
    PRD §3.5: "if the driver's `wallet_balance_cents` is below `quoted_amount_cents`, the
    booking is rejected before any mutation with `ERR_INSUFFICIENT_WALLET` (HTTP 402)."

    Control for the priority pair: when the spot IS listed (P40 passes), a zero-wallet driver
    surfaces ERR_INSUFFICIENT_WALLET (P50). This pins that the conflict test's
    ERR_SPOT_UNLISTED is a genuine priority decision, not the only possible error.

    Design: Difficulty/priority_pair_validation_conflict/unlisted_spot_vs_insufficient_wallet_prefers_state_over_fiscal
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=0, spot_overrides={"zone_code": "Z9b"})
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INSUFFICIENT_WALLET")


# ─── Difficulty: priority_pair_validation_conflict / invalid_window vs time_conflict ───

def test_invalid_window_preferred_over_time_conflict(api):
    """PRD §2.10: "then the temporal-window checks (`ERR_INVALID_WINDOW`, then
    `ERR_CHECKIN_WINDOW_CLOSED`); then the business-constraint checks in the order spot
    time-conflict (`ERR_SPOT_TIME_CONFLICT`)".

    A request with end_at == start_at (invalid window, P20) that would also overlap an
    existing booking (P30) surfaces the earlier ERR_INVALID_WINDOW.

    Design: Difficulty/priority_pair_validation_conflict/invalid_window_vs_time_conflict_prefers_temporal_over_constraint
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z10"})
    # Existing RESERVED booking [10:00,12:00).
    b1 = create_booking(spot["id"], driver["id"], "HOURLY",
                        "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    sv2 = get_spot_version(host["id"], spot["id"])
    # New request: end == start (invalid) AND inside [10:00,12:00) (would conflict).
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T11:00:00Z", "2026-04-20T11:00:00Z", sv2),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_valid_window_overlap_surfaces_time_conflict(api):
    """PRD §2.10: "then the business-constraint checks in the order spot time-conflict
    (`ERR_SPOT_TIME_CONFLICT`)".
    PRD §3.3: "any genuine overlap is rejected with `ERR_SPOT_TIME_CONFLICT` (HTTP 409)."

    Control for the priority pair: with a valid window (end > start, P20 passes) that still
    overlaps an existing booking, ERR_SPOT_TIME_CONFLICT (P30) is surfaced. This pins that
    the conflict test's ERR_INVALID_WINDOW is a genuine priority decision.

    Design: Difficulty/priority_pair_validation_conflict/invalid_window_vs_time_conflict_prefers_temporal_over_constraint
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000, spot_overrides={"zone_code": "Z10b"})
    create_booking(spot["id"], driver["id"], "HOURLY",
                   "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    sv2 = get_spot_version(host["id"], spot["id"])
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T11:00:00Z", "2026-04-20T13:00:00Z", sv2),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_SPOT_TIME_CONFLICT")


# ─── Difficulty: boundary_precision_check / checkin_exactly_at_end_plus_grace ───

def test_checkin_exactly_at_end_plus_grace_is_closed(api):
    """PRD §3.4: "Check-in is permitted only when ... the logical clock sits within the
    check-in window: at or after `start_at`, and strictly before `end_at` plus the spot's
    `overstay_grace_minutes`."
    PRD §3.4: "A check-in attempted before `start_at`, or once the window plus grace has
    fully elapsed, is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)".

    Booking [10:00,12:00) grace 15; check-in at exactly 12:15 (= end+grace) is rejected by
    the strict-less-than upper edge.

    Design: Difficulty/boundary_precision_check/checkin_exactly_at_end_plus_grace_is_closed
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "Z11"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T12:00:00Z", spot["version"])
    set_clock("2026-04-08T12:15:00Z")
    res = api.check_in_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


def test_checkin_one_minute_before_end_plus_grace_allowed(api):
    """PRD §3.4: "at or after `start_at`, and strictly before `end_at` plus the spot's
    `overstay_grace_minutes`."

    Booking [10:00,12:00) grace 15; check-in at 12:14 (one minute before 12:15) is strictly
    inside the window and succeeds (occupancy CHECKED_IN).

    Design: Difficulty/boundary_precision_check/checkin_exactly_at_end_plus_grace_is_closed
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "Z11b"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T12:00:00Z", spot["version"])
    set_clock("2026-04-08T12:14:00Z")
    checked_in = get_success_data(api.check_in_booking(booking["id"], make_driver_headers(driver["id"])))
    assert checked_in["occupancy_status"] == "CHECKED_IN"


# ─── Difficulty: boundary_precision_check / refund_tier_at_exactly_seven_days ───

def test_refund_full_at_exactly_seven_days_lead(api):
    """PRD §3.6: "When the lead time is at least 604800 seconds (7 days), the refund factor
    is the full 10000 basis points."
    PRD §3.6: "The refund is the frozen `quoted_amount_cents` multiplied by the applicable
    refund factor divided by 10000, rounded half up to a whole cent."

    Booking quoted 800, start 2026-04-15T10:00Z; cancel at exactly 7 days before
    (2026-04-08T10:00Z) refunds the full 800, restoring wallet 5000.

    Design: Difficulty/boundary_precision_check/refund_tier_at_exactly_seven_days_lead_is_full
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z12"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-15T10:00:00Z", "2026-04-15T12:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 800
    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.cancel_booking(booking["id"], make_driver_headers(driver["id"])))
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["wallet_balance_cents"] == 5000, drv["wallet_balance_cents"]
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(driver["id"])))
    assert b["settlement_status"] == "REFUNDED"


def test_refund_drops_to_75_percent_just_under_seven_days(api):
    """PRD §3.6: "When the lead time is at least 86400 seconds (1 day) but less than 7 days,
    the refund factor is 7500 basis points (75%)."

    Booking quoted 800, start 2026-04-15T10:00Z; cancel at 6 days 23h 59m before
    (2026-04-08T10:01:00Z, lead < 7 days) refunds 600 (75%), proving the >=7d boundary is
    strict on the lower edge: wallet 5000 - 800 + 600 = 4800.

    Design: Difficulty/boundary_precision_check/refund_tier_at_exactly_seven_days_lead_is_full
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z12b"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-15T10:00:00Z", "2026-04-15T12:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 800
    set_clock("2026-04-08T10:01:00Z")  # one minute short of the 7-day boundary
    get_success_data(api.cancel_booking(booking["id"], make_driver_headers(driver["id"])))
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["wallet_balance_cents"] == 4800, drv["wallet_balance_cents"]


def test_refund_75_percent_at_one_day_lead(api):
    """PRD §3.6: "When the lead time is at least 86400 seconds (1 day) but less than 7 days,
    the refund factor is 7500 basis points (75%)."

    Booking quoted 800, start 2026-04-09T10:00; cancel at exactly 1 day before
    (2026-04-08T10:00) refunds 600 (75%): wallet 5000 - 800 + 600 = 4800.

    Design: Corner/calculations/refund_75_percent_tier_one_day_lead
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "ZCA6"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-09T10:00:00Z", "2026-04-09T12:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 800
    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.cancel_booking(booking["id"], make_driver_headers(driver["id"])))
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["wallet_balance_cents"] == 4800, drv["wallet_balance_cents"]
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(driver["id"])))
    assert b["settlement_status"] == "REFUNDED"


# ─── Difficulty: cross_entity_state_dependency / driver_suspended blocks booking ───

def test_suspended_driver_cannot_create_booking(api):
    """PRD §3.3: "And the driver's `standing_tier` must not be `SUSPENDED`; a suspended
    driver attempting to book is rejected with `ERR_DRIVER_SUSPENDED` (HTTP 409)."

    A driver suspended by a confirmed NO_SHOW (assessed 12) is rejected with
    ERR_DRIVER_SUSPENDED on a fresh, well-funded booking attempt.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_driver_suspended_booking_to_driver
    """
    host, driver, spot, booking, vr = setup_suspended_driver(no_show_base_points=4, wallet_cents=10000)
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["standing_tier"] == "SUSPENDED"
    sv = get_spot_version(host["id"], spot["id"])
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-25T10:00:00Z", "2026-04-25T11:00:00Z", sv),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_DRIVER_SUSPENDED")


def test_suspended_recipient_cannot_accept_transfer(api):
    """PRD §3.9: "the recipient's `standing_tier` is not `SUSPENDED` (a suspended recipient
    is rejected with `ERR_DRIVER_SUSPENDED`)".

    A Booking->Driver dependency on the transfer-accept path: when the recipient driver is
    SUSPENDED, accepting a PENDING offer is rejected with ERR_DRIVER_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_driver_suspended_booking_to_driver
    """
    from test_helpers import setup_pending_transfer_offer, log_violation, confirm_violation
    host, da, db, spot, booking, offer = setup_pending_transfer_offer(
        wallet_a=5000, wallet_b=5000,
        start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z",
        clock="2026-04-08T09:00:00Z")
    # Suspend the recipient db via a confirmed NO_SHOW (assessed 12) on a separate booking.
    sv2 = get_spot_version(host["id"], spot["id"])
    db_booking = create_booking(spot["id"], db["id"], "HOURLY",
                                "2026-04-21T10:00:00Z", "2026-04-21T11:00:00Z", sv2)
    vr = log_violation(host["id"], db_booking["id"], "NO_SHOW", 4)
    confirm_violation(vr["id"])
    drv_b = get_success_data(api.get_driver(db["id"], make_driver_headers(db["id"])))
    assert drv_b["standing_tier"] == "SUSPENDED"
    res = api.accept_transfer_offer(offer["id"], make_driver_headers(db["id"]))
    validate_error(res, "ERR_DRIVER_SUSPENDED")


# ─── Difficulty: cross_entity_state_dependency / spot_unlisted blocks booking ───

def test_unlisted_spot_cannot_be_booked(api):
    """PRD §3.3: "The spot's `listing_status` must be `LISTED`; booking an `UNLISTED` spot is
    rejected with `ERR_SPOT_UNLISTED` (HTTP 409)."

    A well-funded driver of GOOD standing is still rejected with ERR_SPOT_UNLISTED when the
    spot is UNLISTED.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_spot_unlisted_booking_to_spot
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z14"})
    get_success_data(api.unlist_spot(spot["id"], make_host_headers(host["id"])))
    sv = get_spot_version(host["id"], spot["id"])
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", sv),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_SPOT_UNLISTED")


def test_unlisted_spot_then_relisted_can_be_booked(api):
    """PRD §3.3: "The spot's `listing_status` must be `LISTED`; booking an `UNLISTED` spot is
    rejected with `ERR_SPOT_UNLISTED` (HTTP 409)."
    PRD §3.2: "The host may relist an `UNLISTED` spot, transitioning `listing_status` back
    from `UNLISTED` to `LISTED`."

    The Booking->Spot dependency is keyed on listing_status: a booking is rejected while
    UNLISTED, then succeeds once the same spot is relisted to LISTED.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_spot_unlisted_booking_to_spot
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z14b"})
    get_success_data(api.unlist_spot(spot["id"], make_host_headers(host["id"])))
    sv = get_spot_version(host["id"], spot["id"])
    rejected = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", sv),
        make_driver_headers(driver["id"]))
    validate_error(rejected, "ERR_SPOT_UNLISTED")

    relisted = get_success_data(api.relist_spot(spot["id"], make_host_headers(host["id"])))
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", relisted["version"])
    assert booking["occupancy_status"] == "RESERVED"


# ─── Difficulty: resource_temporal_overlap / booking half-open adjacency ───

def test_adjacent_booking_allowed_overlapping_rejected(api):
    """PRD §3.3: "The requested half-open window from `start_at` to `end_at` must not
    intersect any existing booking on the same spot whose `occupancy_status` is `RESERVED`,
    `CHECKED_IN`, or `CHECKED_OUT`; two bookings that merely touch at a boundary, where one's
    `end_at` equals the other's `start_at`, do not conflict because intervals are half-open,
    but any genuine overlap is rejected with `ERR_SPOT_TIME_CONFLICT` (HTTP 409)."

    Existing booking [10:00,12:00). A new booking starting exactly at 12:00 is accepted
    (adjacency); a booking starting at 11:00 (genuine overlap) is rejected.

    Design: Difficulty/resource_temporal_overlap/booking_overlap_half_open_adjacency_allowed
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000, spot_overrides={"zone_code": "Z15"})
    create_booking(spot["id"], driver["id"], "HOURLY",
                   "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    sv2 = get_spot_version(host["id"], spot["id"])
    adj = create_booking(spot["id"], driver["id"], "HOURLY",
                         "2026-04-20T12:00:00Z", "2026-04-20T13:00:00Z", sv2)
    assert adj["occupancy_status"] == "RESERVED"
    sv3 = get_spot_version(host["id"], spot["id"])
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T11:00:00Z", "2026-04-20T13:30:00Z", sv3),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_SPOT_TIME_CONFLICT")


# ─── Difficulty: resource_temporal_overlap / pricing event closed-buffer adjacency ───

def test_booking_starting_exactly_at_prior_end_allowed(api):
    """PRD §3.3: "two bookings that merely touch at a boundary, where one's `end_at` equals
    the other's `start_at`, do not conflict because intervals are half-open".

    Existing booking [10:00,12:00); a new booking [12:00,13:00) that starts exactly at the
    prior end_at is accepted (RESERVED), confirming half-open adjacency.

    Design: Difficulty/resource_temporal_overlap/booking_overlap_half_open_adjacency_allowed
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000, spot_overrides={"zone_code": "Z15b"})
    create_booking(spot["id"], driver["id"], "HOURLY",
                   "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    sv2 = get_spot_version(host["id"], spot["id"])
    adj = create_booking(spot["id"], driver["id"], "HOURLY",
                         "2026-04-20T12:00:00Z", "2026-04-20T13:00:00Z", sv2)
    assert adj["occupancy_status"] == "RESERVED"


def test_pricing_event_within_buffer_rejected(api):
    """PRD §3.3: "A new event is rejected with `ERR_EVENT_ZONE_CONFLICT` (HTTP 409) unless
    there is a gap of at least 3600 seconds (one hour) on both sides between it and every
    other `ACTIVE` event in the same `zone_code`."
    PRD §3.3: "Windows that merely touch, or that sit less than an hour apart on either side,
    are therefore rejected."

    With an ACTIVE event [10:00,12:00) in DT-09, a new event starting 12:30 (only 30 min
    after, gap < 3600s) is rejected with ERR_EVENT_ZONE_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/pricing_event_buffer_closed_adjacency_rejected
    """
    create_pricing_event("DT-09", "2026-04-09T10:00:00Z", "2026-04-09T12:00:00Z", 20000)
    res = api.create_pricing_event(
        {"zone_code": "DT-09", "window_start": "2026-04-09T12:30:00Z",
         "window_end": "2026-04-09T14:00:00Z", "surge_multiplier_bps": 30000}, ADMIN)
    validate_error(res, "ERR_EVENT_ZONE_CONFLICT")


def test_pricing_event_with_sufficient_buffer_allowed(api):
    """PRD §3.3: "A new event is rejected with `ERR_EVENT_ZONE_CONFLICT` (HTTP 409) unless
    there is a gap of at least 3600 seconds (one hour) on both sides between it and every
    other `ACTIVE` event in the same `zone_code`."

    With an ACTIVE event [10:00,12:00) in DT-09b, a new event starting exactly 13:00 (a full
    3600s after the prior end) clears the closed-with-buffer rule and is created ACTIVE.

    Design: Difficulty/resource_temporal_overlap/pricing_event_buffer_closed_adjacency_rejected
    """
    create_pricing_event("DT-09b", "2026-04-09T10:00:00Z", "2026-04-09T12:00:00Z", 20000)
    created = get_success_data(api.create_pricing_event(
        {"zone_code": "DT-09b", "window_start": "2026-04-09T13:00:00Z",
         "window_end": "2026-04-09T14:00:00Z", "surge_multiplier_bps": 30000}, ADMIN))
    assert created["status"] == "ACTIVE"


# ─── Corner: validations ─────────────────────────────────────────────────────

def test_transfer_to_self_rejected(api):
    """PRD §3.9: "The recipient must differ from the current holder; an offer whose recipient
    equals the current holder is rejected with `ERR_TRANSFER_TO_SELF` (HTTP 422)."

    Creating a TransferOffer whose to_driver_id equals the current holder returns
    ERR_TRANSFER_TO_SELF.

    Design: Corner/validations/transfer_to_self_rejected
    """
    host, driver, spot, booking = setup_reserved_booking(spot_overrides={"zone_code": "ZV1"})
    bv = get_booking_version(driver["id"], booking["id"])
    res = api.create_transfer_offer(
        {"booking_id": booking["id"], "to_driver_id": driver["id"],
         "expected_booking_version": bv},
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_TRANSFER_TO_SELF")


def test_insufficient_wallet_on_booking_rejected(api):
    """PRD §3.5: "The wallet must be able to cover the charge; if the driver's
    `wallet_balance_cents` is below `quoted_amount_cents`, the booking is rejected before any
    mutation with `ERR_INSUFFICIENT_WALLET` (HTTP 402)."

    A booking whose quote (800) exceeds a wallet of 500 returns ERR_INSUFFICIENT_WALLET and
    the wallet is unchanged at 500.

    Design: Corner/validations/insufficient_wallet_on_booking_rejected
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=500, spot_overrides={"zone_code": "ZV2"})
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INSUFFICIENT_WALLET")
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["wallet_balance_cents"] == 500, drv["wallet_balance_cents"]


def test_booking_window_outside_availability_rejected(api):
    """PRD §3.3: "the entire window must lie within the spot's availability from
    `availability_start` (inclusive) to `availability_end` (exclusive) ... a violation
    surfaces as `ERR_INVALID_WINDOW` (HTTP 422)."

    A booking ending after the spot's availability_end (2026-05-01) returns
    ERR_INVALID_WINDOW.

    Design: Corner/validations/booking_window_outside_spot_availability_rejected
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=20000, spot_overrides={"zone_code": "ZV3"})
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-30T22:00:00Z", "2026-05-02T00:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_monthly_window_not_30_days_rejected(api):
    """PRD §3.3: "for a `MONTHLY` booking the window must span exactly 30 days; a violation
    surfaces as `ERR_INVALID_WINDOW` (HTTP 422)."

    A MONTHLY booking spanning 29 days (2026-05-01 .. 2026-05-30) returns ERR_INVALID_WINDOW.

    Design: Corner/calculations/monthly_window_not_30_days_rejected
    """
    host, driver, spot = setup_host_driver_spot(
        wallet_cents=200000,
        spot_overrides={"zone_code": "ZCA2", "availability_end": "2026-07-01T00:00:00Z"})
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "MONTHLY",
                               "2026-05-01T00:00:00Z", "2026-05-30T00:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_existence_checked_before_window(api):
    """PRD §2.10: "a request that both references a missing resource and supplies a stale
    version surfaces the missing-resource error, because existence is evaluated before the
    version match."
    PRD §2.10: "existence of all referenced resources, left to right (`ERR_NOT_FOUND`) ...
    then the temporal-window checks (`ERR_INVALID_WINDOW` ...".

    A booking on a non-existent spot_id with an also-invalid window (end == start) surfaces
    ERR_NOT_FOUND (existence, P3) ahead of ERR_INVALID_WINDOW (P20).

    Design: Corner/validations/existence_before_state_on_nonexistent_spot_booking
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "ZV4"})
    res = api.create_booking(
        create_booking_payload("00000000-0000-0000-0000-000000000000", driver["id"], "HOURLY",
                               "2026-04-20T12:00:00Z", "2026-04-20T12:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_gate_redeem_unknown_token_rejected(api):
    """PRD §3.4: "a redemption against a missing pass, a non-matching pass, or a pass whose
    `gate_opens_remaining` has reached 0 is rejected with `ERR_GATE_PASS_INVALID` (HTTP 409)."

    Redeeming an unknown qr_token returns ERR_GATE_PASS_INVALID.

    Design: Corner/validations/gate_redeem_invalid_pass_rejected
    """
    driver = register_driver()
    res = api.redeem_access_pass(redeem_payload("bogus-token"), make_driver_headers(driver["id"]))
    validate_error(res, "ERR_GATE_PASS_INVALID")
