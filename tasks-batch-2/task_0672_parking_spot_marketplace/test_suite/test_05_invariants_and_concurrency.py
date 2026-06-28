"""Conserved-quantity invariants (driver escrow, host ledger) and OCC stale-version.

Covers the compensating-invariant instances (transfer accept conserves driver escrow;
reverse-payout conserves host lifetime ledger) and the corner-design OCC / error /
consistency instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, setup_reserved_booking, setup_pending_transfer_offer,
    setup_no_show_with_earning, create_booking, create_transfer_offer,
    get_spot_version, get_booking_version, set_clock, register_driver,
    create_booking_payload, reverse_payout_payload, create_transfer_offer_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: compensating_invariant / transfer_accept_conserves_driver_escrow ───

def test_transfer_accept_conserves_driver_escrow(api):
    """PRD §3.9: "the recipient's `wallet_balance_cents` is debited by the full
    `quoted_amount_cents` (the recipient assumes the reservation at its original frozen
    quote), and the offering driver's `wallet_balance_cents` is credited the full
    `quoted_amount_cents` (the original holder is made whole)."
    PRD §3.9: "the booking's `quoted_amount_cents` remains the conserved escrow; the tiered
    refund of §3.6 is deliberately not applied here, because a transfer is a full make-whole
    rather than a cancellation."

    Booking quoted 800, holder D_a (funded 5000 -> wallet 4200 after the booking charge), D_b
    funded 5000. After accept: D_a refunded the full 800 -> 5000; D_b charged 800 -> 4200;
    escrow (quoted_amount_cents) unchanged at 800; booking reassigned to D_b.

    Design: Difficulty/compensating_invariant/transfer_accept_conserves_driver_escrow_quoted
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer(
        wallet_a=5000, wallet_b=5000,
        start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T12:00:00Z",
        clock="2026-04-08T09:00:00Z")
    assert booking["quoted_amount_cents"] == 800
    get_success_data(api.accept_transfer_offer(offer["id"], make_driver_headers(db["id"])))

    drv_a = get_success_data(api.get_driver(da["id"], make_driver_headers(da["id"])))
    drv_b = get_success_data(api.get_driver(db["id"], make_driver_headers(db["id"])))
    assert drv_a["wallet_balance_cents"] == 5000, drv_a["wallet_balance_cents"]
    assert drv_b["wallet_balance_cents"] == 4200, drv_b["wallet_balance_cents"]

    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(db["id"])))
    assert b["quoted_amount_cents"] == 800
    assert b["driver_id"] == db["id"]


def test_transfer_accept_reassigns_and_increments_transfer_count(api):
    """PRD §3.9: "Acceptance reassigns the reservation by setting the booking's `driver_id`
    to `to_driver_id`, increments the booking's `transfer_count` by one".

    After accept, the booking's driver_id is the recipient and transfer_count is 1.

    Design: Difficulty/compensating_invariant/transfer_accept_conserves_driver_escrow_quoted
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer(
        wallet_a=5000, wallet_b=5000,
        start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T12:00:00Z",
        clock="2026-04-08T09:00:00Z")
    assert booking["transfer_count"] == 0
    get_success_data(api.accept_transfer_offer(offer["id"], make_driver_headers(db["id"])))
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(db["id"])))
    assert b["driver_id"] == db["id"]
    assert b["transfer_count"] == 1, b["transfer_count"]


# ─── Difficulty: compensating_invariant / reverse_payout_conserves_host_lifetime ───

def test_reverse_payout_conserves_host_lifetime_ledger(api):
    """PRD §3.6: "A successful reversal posts a `PayoutLedgerEntry` of type `REVERSAL` whose
    `amount_cents` is the exact negation of the original earning entry's `amount_cents` (no
    re-derivation), recomputes the host's `lifetime_payout_cents` so that it nets back to its
    value before this booking's earning".
    PRD §3.7: "The gross is `final_amount_cents` when the booking checked out, or the frozen
    `quoted_amount_cents` when the booking was a no-show (a no-show bills the quote)."

    Booking quoted 3000 (HOURLY 3h surge 2.5x) marked NO_SHOW: EARNING net = 3000 -
    round_half_up(3000*0.15=450) = 2550, lifetime 2550. reverse-payout posts REVERSAL -2550,
    netting lifetime back to 0.

    Design: Difficulty/compensating_invariant/reverse_payout_conserves_host_lifetime_ledger
    """
    host, driver, spot, booking = setup_no_show_with_earning(
        host_overrides={"platform_fee_bps": 1500},
        spot_overrides={"base_hourly_cents": 400, "zone_code": "DT-17", "overstay_grace_minutes": 15},
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T13:00:00Z", rate_kind="HOURLY",
        pricing_event={"zone_code": "DT-17", "window_start": "2026-04-08T00:00:00Z",
                       "window_end": "2026-04-09T00:00:00Z", "surge_multiplier_bps": 25000},
        wallet_cents=5000, setup_clock="2026-04-08T09:00:00Z", expiry_clock="2026-04-08T13:20:00Z")
    assert booking["quoted_amount_cents"] == 3000

    host_after_earning = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after_earning["lifetime_payout_cents"] == 2550, host_after_earning["lifetime_payout_cents"]

    bv = get_booking_version(driver["id"], booking["id"])
    rev = get_success_data(api.reverse_payout(booking["id"], reverse_payout_payload(bv), ADMIN))
    assert rev["entry_type"] == "REVERSAL"
    assert rev["amount_cents"] == -2550, rev["amount_cents"]

    host_after_rev = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after_rev["lifetime_payout_cents"] == 0, host_after_rev["lifetime_payout_cents"]


def test_no_show_posts_earning_on_quoted(api):
    """PRD §3.4: "Marking a no-show advances `occupancy_status` from `RESERVED` to `NO_SHOW`,
    sets `settlement_status` to `SETTLED` (a no-show earns no refund), posts a host earning
    on the quoted amount as described in §3.7".
    PRD §3.7: "The gross is `final_amount_cents` when the booking checked out, or the frozen
    `quoted_amount_cents` when the booking was a no-show (a no-show bills the quote)."

    A no-show booking quoted 3000 at fee 1500 bps posts EARNING net 2550, lifetime 2550.

    Design: Difficulty/compensating_invariant/reverse_payout_conserves_host_lifetime_ledger
    """
    host, driver, spot, booking = setup_no_show_with_earning(
        host_overrides={"platform_fee_bps": 1500},
        spot_overrides={"base_hourly_cents": 400, "zone_code": "DT-17b", "overstay_grace_minutes": 15},
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T13:00:00Z", rate_kind="HOURLY",
        pricing_event={"zone_code": "DT-17b", "window_start": "2026-04-08T00:00:00Z",
                       "window_end": "2026-04-09T00:00:00Z", "surge_multiplier_bps": 25000},
        wallet_cents=5000, setup_clock="2026-04-08T09:00:00Z", expiry_clock="2026-04-08T13:20:00Z")
    assert booking["occupancy_status"] == "NO_SHOW"
    assert booking["settlement_status"] == "SETTLED"
    host_after = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after["lifetime_payout_cents"] == 2550


# ─── Corner: errors / OCC ────────────────────────────────────────────────────

def test_reverse_payout_on_reserved_booking_rejected(api):
    """PRD §3.6: "a reversal attempted on a booking with no posted earning, or whose earning
    was already reversed, is rejected with `ERR_NO_REVERSIBLE_PAYOUT` (HTTP 409)."

    reverse-payout on a still-RESERVED booking (no posted EARNING) returns
    ERR_NO_REVERSIBLE_PAYOUT.

    Design: Corner/errors/error_no_reversible_payout_on_reserved_booking
    """
    host, driver, spot, booking = setup_reserved_booking(spot_overrides={"zone_code": "ZER1"})
    bv = get_booking_version(driver["id"], booking["id"])
    res = api.reverse_payout(booking["id"], reverse_payout_payload(bv), ADMIN)
    validate_error(res, "ERR_NO_REVERSIBLE_PAYOUT")


def test_stale_booking_version_on_second_transfer_offer(api):
    """PRD §2.7: "If that value does not match the booking's current `version` — for instance
    because a prior offer creation or a check-in has already advanced the booking's `version`
    — the create is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)".
    PRD §3.9: "On creation the server copies the offering driver into the offer's
    `from_driver_id`, sets its `status` to `PENDING`, and increments the underlying booking's
    `version`."

    After a first offer bumps Booking.version, creating a second offer with the pre-first
    booking version returns ERR_STALE_BOOKING_VERSION.

    Design: Corner/errors/stale_booking_version_on_transfer_offer
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer(
        wallet_a=5000, wallet_b=5000,
        start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z", clock=None)
    dc = register_driver()
    stale_bv = booking["version"]  # version BEFORE the first offer was created
    res = api.create_transfer_offer(
        create_transfer_offer_payload(booking["id"], dc["id"], stale_bv),
        make_driver_headers(da["id"]))
    validate_error(res, "ERR_STALE_BOOKING_VERSION")


def test_stale_spot_version_on_second_booking(api):
    """PRD §2.7: "If that value does not match the spot's current `version` — for instance
    because a prior accepted booking on the same spot already advanced the spot's `version`,
    changing which windows remain free — the create is rejected with `ERR_STALE_SPOT_VERSION`
    (HTTP 412)".

    After one booking advances Spot.version, a second create carrying the pre-first spot
    version returns ERR_STALE_SPOT_VERSION.

    Design: Corner/errors/stale_spot_version_on_booking_create
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000, spot_overrides={"zone_code": "ZER3"})
    stale_sv = spot["version"]
    create_booking(spot["id"], driver["id"], "HOURLY",
                   "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", stale_sv)
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "HOURLY",
                               "2026-04-20T13:00:00Z", "2026-04-20T14:00:00Z", stale_sv),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_STALE_SPOT_VERSION")


def test_spot_version_increments_on_booking(api):
    """PRD §2.4: "`version` — an integer that starts at its initial value and increments by
    one on every mutation."
    PRD §3.5: "the spot's `version` is incremented (its availability footprint has changed)."

    A new spot starts at version 1; after one booking GET /spots shows version 2; supplying
    that fresh version on a second booking succeeds.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_spot_mutation
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=10000, spot_overrides={"zone_code": "ZCC1"})
    assert spot["version"] == 1
    create_booking(spot["id"], driver["id"], "HOURLY",
                   "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    sv2 = get_spot_version(host["id"], spot["id"])
    assert sv2 == 2, sv2
    b2 = create_booking(spot["id"], driver["id"], "HOURLY",
                        "2026-04-20T11:00:00Z", "2026-04-20T12:00:00Z", sv2)
    assert b2["occupancy_status"] == "RESERVED"


def test_clock_default_makes_early_checkin_window_closed(api):
    """PRD §2.9: "On startup the clock reads exactly `2026-04-01T00:00:00Z`; until it is
    explicitly set it remains at that default and never falls back to the host's wall clock."
    PRD §3.4: "A check-in attempted before `start_at`, or once the window plus grace has
    fully elapsed, is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)".

    With no clock set (default 2026-04-01), a check-in for a 2026-04-08 window is before
    start_at and rejected with ERR_CHECKIN_WINDOW_CLOSED.

    Design: Corner/cross_cutting_complexity_layers/clock_default_makes_early_booking_window_deterministic
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZCC2"})
    # Deliberately do NOT set the clock; it stays at the 2026-04-01 default.
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    res = api.check_in_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


def test_stale_booking_version_on_reverse_payout(api):
    """PRD §2.7: "The same `expected_booking_version` field, checked against the booking's
    current `version` and rejected on mismatch with `ERR_STALE_SPOT_VERSION` semantics for
    stale parents, also guards the admin payout-reversal operation described in §3.6; that
    reversal request carries `expected_booking_version` and is rejected on a version
    mismatch."

    A no-show bumps Booking.version (EARNING posted). A reverse-payout carrying the
    pre-no-show version is rejected with ERR_STALE_SPOT_VERSION (the error_id PRD §2.7 pins
    for the reverse-payout stale-parent check).

    Design: Corner/cross_cutting_complexity_layers/stale_booking_version_on_reverse_payout
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZCC3"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    pre_no_show_version = booking["version"]
    set_clock("2026-04-08T11:20:00Z")
    get_success_data(api.mark_no_show(booking["id"], ADMIN))
    res = api.reverse_payout(booking["id"], reverse_payout_payload(pre_no_show_version), ADMIN)
    validate_error(res, "ERR_STALE_SPOT_VERSION")


# ─── Corner: consistency_model ───────────────────────────────────────────────

def test_booking_create_charges_wallet_atomically(api):
    """PRD §3.5: "When a booking is created, the freshly computed `quoted_amount_cents` is
    charged against the driver's wallet: the driver's `wallet_balance_cents` is debited by
    that amount, the booking's `settlement_status` is set to `SETTLED`".
    PRD §2.5: "the server applies every downstream effect immediately and synchronously as
    part of the same operation; there is no eventual consistency."

    A driver funded 5000 books a 2h HOURLY at base 400 (quote 800): immediately after, the
    booking is SETTLED and GET /drivers shows wallet 4200.

    Design: Corner/consistency_model/booking_create_charges_wallet_in_same_response
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "ZCM1"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    assert booking["settlement_status"] == "SETTLED"
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["wallet_balance_cents"] == 4200, drv["wallet_balance_cents"]
