"""Check-in gating, clean completion settlement, and the payout / refund
dual-variant and tier-boundary arithmetic.

Covers difficulty queue A (dual-variant payout, refund tier day boundary) and
corner queue B (check-in gate, full lifecycle settlement).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_host_headers, make_guest_headers,
)
import test_helpers.fixtures as fx

# Common MODERATE/25000/5000 listing kwargs used by the settlement scenarios.
MODERATE_KW = dict(site_type="YURT", max_guests=4, min_nights=2,
                   base_nightly_rate_cents=20000, cleaning_fee_cents=5000,
                   cancellation_policy="MODERATE", rate_cents=25000,
                   rate_end="2026-09-01T00:00:00Z")


# ------------------------------------------------ corner: check-in gate
def test_checkin_before_check_in_date_returns_too_early(api):
    """PRD §3.7: "A host checks a guest in, moving the booking from `CONFIRMED` to
    `CHECKED_IN`, but only once the logical clock's date has reached the
    `check_in` date; an attempt before then is rejected with
    `ERR_CHECKIN_TOO_EARLY` (HTTP 400)."

    Design: Corner/state_machines/checkin_before_check_in_date_returns_too_early
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    # Clock is at its startup default 2026-07-01, before the 07-10 check_in date.
    resp = api.check_in_booking(env["booking"]["id"],
                                make_host_headers(env["host"]["id"]))
    validate_error(resp, "ERR_CHECKIN_TOO_EARLY")


# ------------------------------------------------ corner: full lifecycle
def test_complete_settles_payout_and_host_ledger(api):
    """PRD §3.7: "The scheduled payout moves from `SCHEDULED` to `PAID`, and its
    `final_amount_cents` is set equal to its `estimated_amount_cents` — a clean
    completion pays the full projected estimate."
    PRD §3.7: "`pending_payout_cents` falls by that `estimated_amount_cents`,
    `paid_out_cents` rises by the settled `final_amount_cents`, and
    `completed_stays_count` increases by 1."

    Design: Corner/state_machines/full_booking_lifecycle_complete_settles_ledger
    """
    env = fx.setup_completed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z",
                                     checkin_clock="2026-07-11T00:00:00Z", **MODERATE_KW)
    assert env["booking"]["status"] == "COMPLETED"
    assert env["booking"]["payment_status"] == "PAID"
    host = get_success_data(api.get_host(env["host"]["id"],
                                         make_host_headers(env["host"]["id"])))
    assert host["paid_out_cents"] == 77750
    assert host["pending_payout_cents"] == 0
    assert host["completed_stays_count"] == 1


# ------------------- difficulty: dual_variant_calc (1b) payout est vs final
def test_payout_estimated_fixed_at_accept(api):
    """PRD §3.6: "take the discounted nightly amount plus the add-ons subtotal —
    this stay-and-add-ons figure deliberately excludes the cleaning fee and the
    guest service fee — multiply it by the 3 percent host fee and round once,
    half-up, to get the host fee; then `estimated_amount_cents` is the discounted
    nightly amount plus the add-ons subtotal plus `cleaning_fee_snapshot_cents`
    minus that host fee."

    75000 stay - round(75000*0.03)=2250 + 5000 cleaning = 77750.

    Design: Difficulty/dual_variant_calc/payout_estimated_vs_final_on_partial_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    assert env["payout"]["status"] == "SCHEDULED"
    assert env["payout"]["estimated_amount_cents"] == 77750


def test_payout_final_is_host_retained_share_on_partial_cancel(api):
    """PRD §3.8: "The host's retained gross is the refundable base minus
    `refund_amount_cents`; the host fee on that retained portion is the retained
    gross multiplied by the 3 percent host fee, rounded once, half-up; and the
    host's cancellation earning is the retained gross minus that fee. The scheduled
    payout settles to `VOIDED` with `final_amount_cents` of 0 when the host's
    cancellation earning is 0, or to `PARTIAL` with `final_amount_cents` equal to
    that earning otherwise."
    PRD §3.8: "Under `MODERATE`, the full base is refunded when the cancellation is
    at least 7 days before check-in; a half refund applies when it is at least 1
    day before check-in but fewer than 7; and nothing is refunded otherwise."

    At 6 days (clock 07-04): refund 40000; retained 40000; fee round(40000*0.03)=
    1200; earning 38800 -> PARTIAL.

    Design: Difficulty/dual_variant_calc/payout_estimated_vs_final_on_partial_cancel
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    fx.set_clock("2026-07-04T00:00:00Z")
    get_success_data(api.cancel_booking(env["booking"]["id"],
                                        make_guest_headers(env["guest"]["id"])))
    payout = fx.get_payout(env["host"]["id"], env["booking"]["id"])
    assert payout["status"] == "PARTIAL"
    assert payout["final_amount_cents"] == 38800


# ------------------- difficulty: boundary_precision_check (6b) refund tier
def test_moderate_full_refund_at_seven_days(api):
    """PRD §3.8: "Under `MODERATE`, the full base is refunded when the cancellation
    is at least 7 days before check-in; a half refund applies when it is at least
    1 day before check-in but fewer than 7; and nothing is refunded otherwise."
    PRD §3.8: "The booking's `payment_status` becomes `REFUNDED` when the refund
    equals the full refundable base, or `PARTIALLY_REFUNDED` when the refund is
    greater than zero but less than the full base."

    Refundable base 75000 stay + 5000 cleaning = 80000; at exactly 7 days
    (clock 07-03) the full 80000 is refunded.

    Design: Difficulty/boundary_precision_check/cancellation_refund_tier_day_boundary
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    fx.set_clock("2026-07-03T00:00:00Z")
    data = validate_success(
        api.cancel_booking(env["booking"]["id"],
                           make_guest_headers(env["guest"]["id"])), 200)
    assert data["refund_amount_cents"] == 80000
    assert data["payment_status"] == "REFUNDED"


def test_moderate_half_refund_at_six_days(api):
    """PRD §3.8: "Under `MODERATE`, the full base is refunded when the cancellation
    is at least 7 days before check-in; a half refund applies when it is at least
    1 day before check-in but fewer than 7; and nothing is refunded otherwise."
    PRD §3.8: "The booking's `payment_status` becomes `REFUNDED` when the refund
    equals the full refundable base, or `PARTIALLY_REFUNDED` when the refund is
    greater than zero but less than the full base."

    At 6 days (clock 07-04) only half of the 80000 base — 40000 — is refunded.

    Design: Difficulty/boundary_precision_check/cancellation_refund_tier_day_boundary
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z", **MODERATE_KW)
    fx.set_clock("2026-07-04T00:00:00Z")
    data = validate_success(
        api.cancel_booking(env["booking"]["id"],
                           make_guest_headers(env["guest"]["id"])), 200)
    assert data["refund_amount_cents"] == 40000
    assert data["payment_status"] == "PARTIALLY_REFUNDED"
