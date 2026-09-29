"""Two conserved quantities, each proved by undoing an operation that moved it.

Cancelling an allocated sale hands back exactly the units it took, and cancelling
a part-paid sale accounts for every cent that entered the system exactly once.
"""

from typing import Any, Dict

from test_helpers import (
    FINANCE_CONTROLLER,
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    assert_block_position,
    assert_deal_position,
    assert_schedule_amounts,
    assert_schedule_conservation,
    assert_settlement_identity,
    assert_total_count,
    cancel_booking,
    get_success_data,
    gold_sales_floor,
    installments_of,
    make_booking,
    pay_installment,
    read_block,
    read_booking,
    read_client,
)

# A ten-unit CORPORATE sale of the canonical GOLD package on a fully released
# fixture: 1771150 gross, 141692 discounted away, 48884 of commission and no
# guarantee surcharge.
TEN_UNIT_NET = 1580574
TEN_UNIT_SCHEDULE = [474172, 632230, 474172]
FIRST_INSTALLMENT = 474172
TIER_FEE = 158057


def _allocated_ten_unit_sale(api: ApiClient) -> Dict[str, Any]:
    """A ten-unit CORPORATE booking committed against a forty-unit block.

    The block's target is exactly forty units and the release fills it, so the
    block sits at `EXHAUSTED` before any sale is committed — which makes it
    visible that committing and releasing back never move that state.
    """
    floor = gold_sales_floor(api)
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                           channel="CORPORATE", units=10)
    assert booking["net_price_cents"] == TEN_UNIT_NET
    floor["booking"] = booking
    floor["before"] = read_block(api, floor["block"]["id"])
    floor["allocated"] = allocate_booking(api, booking["id"], floor["block"]["id"])
    return floor


def _part_paid_allocated_sale(api: ApiClient) -> Dict[str, Any]:
    """The same sale, with its first installment settled in full.

    474172 cents of the client's money now sits against the booking, which is
    more than the fee any later cancellation can charge, so the compensation has
    to be a partial refund rather than a demand for more money.
    """
    scenario = _allocated_ten_unit_sale(api)
    lines = installments_of(api, scenario["booking"]["id"])
    assert_schedule_amounts(lines, TEN_UNIT_SCHEDULE)
    assert_schedule_conservation(lines, TEN_UNIT_NET)

    paid = pay_installment(api, lines[0]["id"], FIRST_INSTALLMENT)
    assert paid["installment_state"] == "PAID"
    assert paid["paid_amount_cents"] == FIRST_INSTALLMENT

    scenario["lines"] = lines
    scenario["booking_before"] = read_booking(api, scenario["booking"]["id"])
    scenario["client_before"] = read_client(api, scenario["client"]["id"])
    return scenario


def _read_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))


# --------------------------------------------------------------------------
# Units: what the allocation took, the cancellation gives back
# --------------------------------------------------------------------------


def test_cancelling_an_allocation_hands_back_exactly_the_units_it_took(
    api: ApiClient,
) -> None:
    """The twenty ticket units the sale consumed return in full, and only those.

    Ten package units at two tickets each consume twenty ticket units, so
    `committed_units` rises 0 to 20 on allocation and falls back to 0 on
    cancellation while `released_back_units` rises by the same twenty. The
    allocation itself is untouched at forty throughout, and the difference
    between allocated and committed — the free capacity — is restored to exactly
    the forty it started at.

    PRD §3.8: "Cancelling from `ALLOCATED` additionally returns the units: the
    block's `committed_units` decreases by the booking's `units` multiplied by
    `tickets_per_package` and its `released_back_units` increases by the same
    figure, with `block_state` left untouched."

    Design: Difficulty/compensating_invariant/allocation_units_restored_exactly_after_allocate_then_cancel
    """
    scenario = _allocated_ten_unit_sale(api)
    block_id = scenario["block"]["id"]
    assert_block_position(scenario["before"], allocated=40, committed=0,
                          released_back=0, state="EXHAUSTED")

    after_allocate = read_block(api, block_id)
    assert_block_position(after_allocate, allocated=40, committed=20,
                          released_back=0, state="EXHAUSTED")

    cancelled = cancel_booking(api, scenario["booking"]["id"])

    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["allocation_block_id"] is None
    after_cancel = read_block(api, block_id)
    assert_block_position(after_cancel, allocated=40, committed=0,
                          released_back=20, state="EXHAUSTED")

    # The compensation is exact in both directions: the free capacity is back to
    # where it began, and the quantity handed back equals the quantity taken.
    free_before = scenario["before"]["allocated_units"] - scenario["before"]["committed_units"]
    free_after = after_cancel["allocated_units"] - after_cancel["committed_units"]
    assert free_after == free_before == 40
    taken = after_allocate["committed_units"] - scenario["before"]["committed_units"]
    handed_back = (after_cancel["released_back_units"]
                   - scenario["before"]["released_back_units"])
    assert handed_back == taken == 20


def test_the_units_handed_back_are_recorded_separately_and_are_sellable_again(
    api: ApiClient,
) -> None:
    """`released_back_units` is a ledger of returns, not a netting adjustment.

    After the cancellation the block reports twenty units returned while still
    reporting forty allocated, so the return is recorded alongside the
    allocation rather than deducted from it. The deal's own view of the block is
    equally unmoved: it still has twenty unallocated units, exactly as it did
    before the sale existed. The proof that the compensation was real rather
    than cosmetic is that a fresh twenty-unit sale, needing all forty of the
    block's ticket units, now commits successfully.

    PRD §2.9: "Committing a booking against a block, or releasing one back, moves
    `committed_units` and `released_back_units` but never touches `block_state`."

    PRD §3.5: "Finally the block must actually have the units free: its
    `allocated_units` less its `committed_units` must be at least the booking's
    `units` multiplied by the package's `tickets_per_package`, and a shortfall is
    `ERR_ALLOCATION_UNITS_UNAVAILABLE`."

    Design: Difficulty/compensating_invariant/allocation_units_restored_exactly_after_allocate_then_cancel
    """
    scenario = _allocated_ten_unit_sale(api)
    block_id = scenario["block"]["id"]
    deal_id = scenario["deal"]["id"]
    assert_deal_position(_read_deal(api, deal_id), released=60, shortfall=0,
                         liability=480000, status="FULLY_RELEASED", unallocated=20)

    cancel_booking(api, scenario["booking"]["id"])

    returned = read_block(api, block_id)
    assert returned["released_back_units"] == 20
    assert returned["allocated_units"] == 40, "a return is not netted off the allocation"
    assert_deal_position(_read_deal(api, deal_id), released=60, shortfall=0,
                         liability=480000, status="FULLY_RELEASED", unallocated=20)

    resale = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                          channel="CORPORATE", units=20)
    assert resale["net_price_cents"] == 3023707
    committed_again = allocate_booking(api, resale["id"], block_id)

    assert committed_again["fulfillment_status"] == "ALLOCATED"
    assert committed_again["allocation_block_id"] == block_id
    assert_block_position(read_block(api, block_id), allocated=40, committed=40,
                          released_back=20, state="EXHAUSTED")


# --------------------------------------------------------------------------
# Cents: every cent that arrived is retained, returned, or still owed
# --------------------------------------------------------------------------


def test_an_overpaid_cancellation_refunds_the_difference_and_conserves_the_cash(
    api: ApiClient,
) -> None:
    """474172 arrived, 316115 goes back, 158057 stays, and nothing is unaccounted.

    The fixture is 184 days away, so the tier ladder charges ten percent of the
    net price: round_half_up(1580574 * 0.10) == 158057. The client had already
    paid 474172, which is more than that, so the refund leg carries the whole
    difference of 316115 and the balance leg is 0 rather than the negative
    316115 an unclamped subtraction would produce. The cash the provider keeps
    equals the fee to the cent.

    PRD §3.8: "From the fee, `refund_cents` is the pre-cancellation paid amount
    less the fee, floored at 0, and `balance_due_cents` is the fee less the
    pre-cancellation paid amount, also floored at 0. Exactly one of the two can
    be positive, and the conserved identity always holds afterwards: the fee
    equals the pre-cancellation paid amount, less the refund, plus the balance
    due."

    Design: Difficulty/compensating_invariant/cancellation_money_identity_fee_equals_prepaid_minus_refund_plus_balance
    """
    scenario = _part_paid_allocated_sale(api)
    prepaid = scenario["booking_before"]["paid_cents"]
    assert prepaid == FIRST_INSTALLMENT
    assert scenario["booking_before"]["payment_status"] == "DEPOSIT_PAID"

    cancelled = cancel_booking(api, scenario["booking"]["id"])

    assert cancelled["settlement_variant"] == "TIER_SCHEDULE"
    assert cancelled["cancellation_fee_cents"] == TIER_FEE
    assert cancelled["refund_cents"] == 316115
    assert cancelled["balance_due_cents"] == 0
    assert cancelled["payment_status"] == "REFUNDED"
    assert_settlement_identity(cancelled, prepaid)

    # Not a signed subtraction: the balance leg is clamped, not -316115.
    assert cancelled["balance_due_cents"] == 0
    assert TIER_FEE == prepaid - cancelled["refund_cents"] + cancelled["balance_due_cents"]

    # The retained cash is reduced to exactly the fee, and what left the
    # provider is exactly the refund.
    assert cancelled["paid_cents"] == TIER_FEE
    assert prepaid - cancelled["paid_cents"] == cancelled["refund_cents"]


def test_a_refunded_cancellation_raises_no_settlement_line_and_clears_exposure(
    api: ApiClient,
) -> None:
    """A zero balance means no new invoice and no residual credit exposure.

    Because the balance leg came out at 0 the cancellation raises no
    `SETTLEMENT` line at all — the contrast with an under-paid cancellation,
    where exactly one such line appears. The paid line is left alone with its
    full 474172 recorded against it while the two lines that were still owed are
    voided with no ageing. The client's exposure of 1106402 disappears entirely:
    the booking has left the live set, and being `REFUNDED` rather than
    `SETTLEMENT_DUE` it contributes no balance either.

    PRD §3.8: "Every installment of the booking whose `installment_state` is
    `SCHEDULED` or `OVERDUE` moves to `VOIDED` with `days_overdue` reset to 0,
    and where `balance_due_cents` is above 0 exactly one further installment is
    created with `installment_kind` of `SETTLEMENT` for that amount, falling due
    seven days after the logical clock."

    PRD §3.6: "The second is, across the client's bookings whose
    `fulfillment_status` is `CANCELLED` **and** whose `payment_status` is
    `SETTLEMENT_DUE`, that booking's `balance_due_cents`; a cancelled booking
    that has already settled or been refunded contributes nothing."

    Design: Difficulty/compensating_invariant/cancellation_money_identity_fee_equals_prepaid_minus_refund_plus_balance
    """
    scenario = _part_paid_allocated_sale(api)
    booking_id = scenario["booking"]["id"]
    client_id = scenario["client"]["id"]
    assert scenario["client_before"]["outstanding_cents"] == 1106402

    cancel_booking(api, booking_id)

    assert_total_count(
        api.list_payment_installments(FINANCE_CONTROLLER,
                                      {"booking_id": booking_id,
                                       "installment_kind": "SETTLEMENT"}), 0
    )

    lines = installments_of(api, booking_id)
    assert len(lines) == 3
    assert lines[0]["installment_state"] == "PAID"
    assert lines[0]["paid_amount_cents"] == FIRST_INSTALLMENT
    assert [line["installment_state"] for line in lines[1:]] == ["VOIDED", "VOIDED"]
    assert all(line["days_overdue"] == 0 for line in lines)
    assert all(line["installment_kind"] == "SCHEDULE" for line in lines)

    client = read_client(api, client_id)
    assert client["outstanding_cents"] == 0
    assert client["overdue_installment_count"] == 0

    # The unit invariant is maintained by the very same call.
    assert_block_position(read_block(api, scenario["block"]["id"]), allocated=40,
                          committed=0, released_back=20, state="EXHAUSTED")
