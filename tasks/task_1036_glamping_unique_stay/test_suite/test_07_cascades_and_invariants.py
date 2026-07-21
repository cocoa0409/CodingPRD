"""Multi-hop cascades (delist, permit-reject) and conserved-quantity invariants
(host payout ledger, listing occupancy nights).

Covers difficulty queue A (transitive cascade, compensating invariant).
"""
from test_helpers import (
    validate_success, get_success_data,
    make_host_headers, make_guest_headers,
)
import test_helpers.fixtures as fx

MODERATE_KW = dict(site_type="YURT", max_guests=4, min_nights=2,
                   base_nightly_rate_cents=20000, cleaning_fee_cents=5000,
                   cancellation_policy="MODERATE", rate_cents=25000,
                   rate_end="2026-09-01T00:00:00Z")


# ------------------- difficulty: transitive_cascade (4a) delist chain
def test_delist_cascades_booking_payout_statuses(api):
    """PRD §3.8: "Each booking on the listing in `CONFIRMED` or `CHECKED_IN` is
    moved to `CANCELLED` with a full refund — the refund fraction is forced to the
    full base regardless of the listing's `cancellation_policy`, so the host
    retains nothing. For each such cancelled booking, its scheduled payout is
    `VOIDED` with `final_amount_cents` of 0; the host's `pending_payout_cents` is
    decremented by that payout's `estimated_amount_cents`; the booking's
    `refund_amount_cents` is credited to the guest's `wallet_credit_cents`; the
    booking's `payment_status` becomes `REFUNDED`; and the listing's
    `reserved_nights_count` is decremented by that booking's `nights`."

    Design: Difficulty/transitive_cascade/delist_cascade_booking_payout_host_ledger
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    hh = make_host_headers(env["host"]["id"])
    listing = validate_success(api.delist_listing(env["listing"]["id"], hh), 200)
    assert listing["status"] == "DELISTED"
    booking = get_success_data(api.get_booking(env["booking"]["id"], hh))
    assert booking["status"] == "CANCELLED"
    assert booking["payment_status"] == "REFUNDED"
    payout = fx.get_payout(env["host"]["id"], env["booking"]["id"])
    assert payout["status"] == "VOIDED"
    assert payout["final_amount_cents"] == 0


def test_delist_reconciles_host_ledger_guest_wallet_and_occupancy(api):
    """PRD §3.8: "the host's `pending_payout_cents` is decremented by that payout's
    `estimated_amount_cents`; the booking's `refund_amount_cents` is credited to
    the guest's `wallet_credit_cents`; the booking's `payment_status` becomes
    `REFUNDED`; and the listing's `reserved_nights_count` is decremented by that
    booking's `nights`."

    Full refund of the 80000 base credits the guest wallet with 80000, returns
    host pending to 0, and releases the 3 reserved nights.

    Design: Difficulty/transitive_cascade/delist_cascade_booking_payout_host_ledger
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    hh = make_host_headers(env["host"]["id"])
    get_success_data(api.delist_listing(env["listing"]["id"], hh))
    host = get_success_data(api.get_host(env["host"]["id"], hh))
    assert host["pending_payout_cents"] == 0
    guest = get_success_data(api.get_guest(env["guest"]["id"],
                                           make_guest_headers(env["guest"]["id"])))
    assert guest["wallet_credit_cents"] == 80000
    listing = get_success_data(api.get_listing(env["listing"]["id"], hh))
    assert listing["reserved_nights_count"] == 0


# ------------------- difficulty: transitive_cascade (4b) permit-reject chain
def _setup_listed_with_requested_booking_and_second_permit():
    env = fx.setup_listed_listing(site_type="CABIN", max_guests=4, min_nights=1,
                                  base_nightly_rate_cents=20000, cleaning_fee_cents=0,
                                  cancellation_policy="FLEXIBLE", permit_type="CAMPING",
                                  rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-20T00:00:00Z", "2026-07-22T00:00:00Z")
    permit2 = fx.file_permit(env["host"]["id"], env["listing"]["id"],
                             permit_type="SPECIAL_USE", authority_name="State")
    fx.submit_permit(env["host"]["id"], permit2["id"])
    env["booking"] = booking
    env["permit2"] = permit2
    return env


def test_permit_reject_suspends_listed_listing(api):
    """PRD §3.2: "A `REJECT` outcome moves the permit from `SUBMITTED` to
    `REJECTED`, stores the notes, and cascades: if the listing was `LISTED`, it is
    driven to `SUSPENDED`, and that suspension in turn declines every `REQUESTED`
    booking on the listing (§2.8)."

    Design: Difficulty/transitive_cascade/permit_reject_cascade_listing_booking
    """
    env = _setup_listed_with_requested_booking_and_second_permit()
    permit = fx.decide_permit(env["permit2"]["id"], outcome="REJECT",
                              review_notes="Zoning conflict")
    assert permit["status"] == "REJECTED"
    listing = get_success_data(api.get_listing(env["listing"]["id"],
                                               make_host_headers(env["host"]["id"])))
    assert listing["status"] == "SUSPENDED"


def test_permit_reject_cascade_declines_requested_booking(api):
    """PRD §2.8: "When a listing leaves `LISTED` for `SUSPENDED` — whether a host
    suspends it directly or the system suspends it because the listing's permit was
    rejected — every booking on that listing still sitting in `REQUESTED` is moved
    to `DECLINED`."

    Design: Difficulty/transitive_cascade/permit_reject_cascade_listing_booking
    """
    env = _setup_listed_with_requested_booking_and_second_permit()
    fx.decide_permit(env["permit2"]["id"], outcome="REJECT",
                     review_notes="Zoning conflict")
    booking = get_success_data(api.get_booking(env["booking"]["id"],
                                               make_host_headers(env["host"]["id"])))
    assert booking["status"] == "DECLINED"


# ------------------- difficulty: compensating_invariant (9a) payout ledger
def test_pending_payout_returns_to_zero_after_full_refund_cancel(api):
    """PRD §3.6: "When the payout is scheduled, the host's `pending_payout_cents`
    rises by `estimated_amount_cents`, and the listing's `reserved_nights_count`
    rises by the booking's `nights`."
    PRD §3.8: "The host's `pending_payout_cents` falls by the original
    `estimated_amount_cents`, and `paid_out_cents` rises by the payout's settled
    `final_amount_cents`."

    Accept adds 77750; a full-refund (7-day MODERATE) cancel removes exactly
    77750, returning pending_payout_cents to 0.

    Design: Difficulty/compensating_invariant/payout_ledger_conserved_accept_then_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    fx.set_clock("2026-07-03T00:00:00Z")
    get_success_data(api.cancel_booking(env["booking"]["id"],
                                        make_guest_headers(env["guest"]["id"])))
    host = get_success_data(api.get_host(env["host"]["id"],
                                         make_host_headers(env["host"]["id"])))
    assert host["pending_payout_cents"] == 0


def test_paid_out_stays_zero_when_full_refund_voids_payout(api):
    """PRD §2.10: "A host's `paid_out_cents` is the total `final_amount_cents`
    across that host's payouts that have settled to `PAID` or `PARTIAL`."
    PRD §3.8: "The scheduled payout settles to `VOIDED` with `final_amount_cents`
    of 0 when the host's cancellation earning is 0, or to `PARTIAL` with
    `final_amount_cents` equal to that earning otherwise."

    A full refund makes the host earning 0 -> payout VOIDED, so paid_out stays 0.

    Design: Difficulty/compensating_invariant/payout_ledger_conserved_accept_then_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    fx.set_clock("2026-07-03T00:00:00Z")
    get_success_data(api.cancel_booking(env["booking"]["id"],
                                        make_guest_headers(env["guest"]["id"])))
    host = get_success_data(api.get_host(env["host"]["id"],
                                         make_host_headers(env["host"]["id"])))
    assert host["paid_out_cents"] == 0


# ------------------- difficulty: compensating_invariant (9b) occupancy nights
def test_reserved_nights_returns_to_zero_after_cancel(api):
    """PRD §2.10: "A listing's `reserved_nights_count` is the total `nights` across
    that listing's bookings currently in `CONFIRMED` or `CHECKED_IN` — a conserved
    occupancy quantity that rises on confirmation and falls on release."
    PRD §3.8: "The listing's `reserved_nights_count` falls by the booking's
    `nights`."

    Accept reserves 3 nights; a FLEXIBLE cancel releases exactly 3.

    Design: Difficulty/compensating_invariant/occupancy_nights_conserved_accept_then_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z",
                                     site_type="CABIN", max_guests=4, min_nights=1,
                                     base_nightly_rate_cents=20000, cleaning_fee_cents=0,
                                     cancellation_policy="FLEXIBLE",
                                     rate_cents=20000, rate_end="2026-08-01T00:00:00Z")
    hh = make_host_headers(env["host"]["id"])
    get_success_data(api.cancel_booking(env["booking"]["id"],
                                        make_guest_headers(env["guest"]["id"])))
    listing = get_success_data(api.get_listing(env["listing"]["id"], hh))
    assert listing["reserved_nights_count"] == 0


def test_booking_terminal_state_after_cancel_is_cancelled(api):
    """PRD §3.8: "A guest may cancel a booking that is in `CONFIRMED` or
    `CHECKED_IN`; a cancellation attempt on a booking in any other status is
    rejected with `ERR_BOOKING_NOT_CANCELLABLE` (HTTP 400)."
    PRD §2.10: "A listing's `reserved_nights_count` is the total `nights` across
    that listing's bookings currently in `CONFIRMED` or `CHECKED_IN` — a conserved
    occupancy quantity that rises on confirmation and falls on release."

    Design: Difficulty/compensating_invariant/occupancy_nights_conserved_accept_then_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z",
                                     site_type="CABIN", max_guests=4, min_nights=1,
                                     base_nightly_rate_cents=20000, cleaning_fee_cents=0,
                                     cancellation_policy="FLEXIBLE",
                                     rate_cents=20000, rate_end="2026-08-01T00:00:00Z")
    data = validate_success(
        api.cancel_booking(env["booking"]["id"],
                           make_guest_headers(env["guest"]["id"])), 200)
    assert data["status"] == "CANCELLED"
