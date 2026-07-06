"""The budget roll-up: committed vs projected spend, per-booking deposit rounding,
the fiscal boundary on book, and the book-then-cancel conservation invariant.

All queue A: dual_variant_calc, combinatorial deposit rounding, boundary precision,
and the compensating money invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    PLANNER,
    setup_booking_ready,
    setup_booked_booking,
    create_booking,
    book_booking,
    get_event,
)


# ---------------------------------------------------------------------------
# Helpers local to this file
# ---------------------------------------------------------------------------
def _setup_committed_vs_projected():
    """Booking A BOOKED at 3,000,000; booking B left PROPOSED at estimated 2,000,000."""
    event, vendor = setup_booking_ready(total_budget_cents=10_000_000)
    booking_a = create_booking(event["id"], vendor["id"], estimated_cost_cents=1_500_000)
    book_booking(booking_a["id"], 3_000_000)
    create_booking(event["id"], vendor["id"], estimated_cost_cents=2_000_000)  # stays PROPOSED
    return get_event(event["id"])


def _setup_two_bookings_at_100005():
    """Two bookings each BOOKED at contracted 100,005 on a 100,000,000 budget."""
    event, vendor = setup_booking_ready(total_budget_cents=100_000_000)
    booking_a = create_booking(event["id"], vendor["id"], estimated_cost_cents=100_000)
    booked_a = book_booking(booking_a["id"], 100_005)
    booking_b = create_booking(event["id"], vendor["id"], estimated_cost_cents=100_000)
    book_booking(booking_b["id"], 100_005)
    return get_event(event["id"]), booked_a


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: committed vs projected spend
# ---------------------------------------------------------------------------
def test_committed_spend_counts_only_booked(api):
    """PRD §3.3: "The `committed_spend_cents` is the sum of `contracted_cost_cents` over
    the bookings that are in `BOOKED` or `COMPLETED`."

    Booking A is BOOKED at 3,000,000; the PROPOSED booking B is excluded from committed.

    Design: Difficulty/dual_variant_calc/budget_committed_vs_projected_spend
    """
    event = _setup_committed_vs_projected()
    assert event["committed_spend_cents"] == 3_000_000


def test_projected_spend_adds_proposed_at_estimate(api):
    """PRD §3.3: "The `projected_spend_cents` is a forward-looking figure summed over
    bookings that are `PROPOSED`, `BOOKED`, or `COMPLETED`, counting each `BOOKED` or
    `COMPLETED` booking at its `contracted_cost_cents` and each `PROPOSED` booking at its
    `estimated_cost_cents`; it diverges from the committed figure exactly when a proposed
    booking exists."
    PRD §3.3: "The `budget_balance_cents` is `total_budget_cents` minus
    `committed_spend_cents`."

    Projected = 3,000,000 (A booked) + 2,000,000 (B proposed at estimate) = 5,000,000;
    balance = 10,000,000 - 3,000,000 = 7,000,000.

    Design: Difficulty/dual_variant_calc/budget_committed_vs_projected_spend
    """
    event = _setup_committed_vs_projected()
    assert event["projected_spend_cents"] == 5_000_000
    assert event["budget_balance_cents"] == 7_000_000
    assert event["projected_spend_cents"] != event["committed_spend_cents"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: deposit rounded per line, then summed
# ---------------------------------------------------------------------------
def test_deposit_rounds_half_up_per_booking(api):
    """PRD §3.3: "The `deposit_cents` is 30 percent of `contracted_cost_cents`, rounded
    half up to whole cents. The `balance_cents` is then the exact remainder —
    `contracted_cost_cents` minus `deposit_cents` — and is never independently
    re-rounded, so deposit and balance always sum back to the contracted amount."

    round_half_up(100005 * 0.30) = round_half_up(30001.5) = 30002; balance = 70003.

    Design: Difficulty/combinatorial_formula/deposit_round_per_line_then_sum
    """
    _event, booked_a = _setup_two_bookings_at_100005()
    assert booked_a["deposit_cents"] == 30_002
    assert booked_a["balance_cents"] == 70_003
    assert booked_a["deposit_cents"] + booked_a["balance_cents"] == 100_005


def test_total_deposits_due_rounds_per_line_then_sums(api):
    """PRD §3.3: "The `total_deposits_due_cents` sums, over only the bookings currently
    in `BOOKED` status, 30 percent of each booking's `contracted_cost_cents` rounded half
    up per booking, with those per-booking rounded deposits then added together."

    Per-line rounding: 30002 + 30002 = 60004 (a sum-then-round would give 60003).

    Design: Difficulty/combinatorial_formula/deposit_round_per_line_then_sum
    """
    event, _booked_a = _setup_two_bookings_at_100005()
    assert event["total_deposits_due_cents"] == 60_004


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: fiscal budget boundary on book
# ---------------------------------------------------------------------------
def test_book_exact_budget_fill_succeeds(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    Committing exactly to the 5,000,000 budget is accepted (must-not-exceed): committed
    5,000,000, balance 0.

    Design: Difficulty/boundary_precision_check/budget_exact_fill_then_overflow_on_book
    """
    event, vendor = setup_booking_ready(total_budget_cents=5_000_000)
    booking_a = create_booking(event["id"], vendor["id"], estimated_cost_cents=4_000_000)
    data = validate_success(
        api.book_vendor_booking(booking_a["id"], {"contracted_cost_cents": 5_000_000}, PLANNER)
    )
    assert data["status"] == "BOOKED"
    event_after = get_event(event["id"])
    assert event_after["committed_spend_cents"] == 5_000_000
    assert event_after["budget_balance_cents"] == 0


def test_book_one_cent_over_budget_rejected(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    With committed already at the 5,000,000 budget, a further 1-cent booking overflows.

    Design: Difficulty/boundary_precision_check/budget_exact_fill_then_overflow_on_book
    """
    event, vendor = setup_booking_ready(total_budget_cents=5_000_000)
    booking_a = create_booking(event["id"], vendor["id"], estimated_cost_cents=4_000_000)
    validate_success(
        api.book_vendor_booking(booking_a["id"], {"contracted_cost_cents": 5_000_000}, PLANNER)
    )
    booking_b = create_booking(event["id"], vendor["id"], estimated_cost_cents=1)
    validate_error(
        api.book_vendor_booking(booking_b["id"], {"contracted_cost_cents": 1}, PLANNER),
        ApiErrorId.ERR_BUDGET_EXCEEDED.value,
    )


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: book then cancel conserves the budget
# ---------------------------------------------------------------------------
def test_cancel_booking_restores_committed_spend(api):
    """PRD §3.3: "Cancelling a `BOOKED` booking additionally voids the compensation
    already scheduled: each of the booking's `SCHEDULED` payments transitions
    `SCHEDULED → VOID`, the booking's `contracted_cost_cents` is removed from
    `committed_spend_cents`, and the balance and deposits-due figures are recomputed."

    Design: Difficulty/compensating_invariant/budget_book_then_cancel_conserves_balance
    """
    event, _vendor, booking = setup_booked_booking(
        contracted_cost_cents=2_000_000, total_budget_cents=10_000_000
    )
    validate_success(api.cancel_vendor_booking(booking["id"], PLANNER))
    event_after = get_event(event["id"])
    assert event_after["committed_spend_cents"] == 0
    assert event_after["budget_balance_cents"] == 10_000_000


def test_committed_plus_balance_conserves_total_budget(api):
    """PRD §3.3: "The `budget_balance_cents` is `total_budget_cents` minus
    `committed_spend_cents`."

    The conserved quantity: committed_spend + budget_balance == total_budget with zero
    drift after a book-then-cancel round trip.

    Design: Difficulty/compensating_invariant/budget_book_then_cancel_conserves_balance
    """
    event, _vendor, booking = setup_booked_booking(
        contracted_cost_cents=2_000_000, total_budget_cents=10_000_000
    )
    validate_success(api.cancel_vendor_booking(booking["id"], PLANNER))
    event_after = get_event(event["id"])
    assert (
        event_after["committed_spend_cents"] + event_after["budget_balance_cents"]
        == event_after["total_budget_cents"]
        == 10_000_000
    )
