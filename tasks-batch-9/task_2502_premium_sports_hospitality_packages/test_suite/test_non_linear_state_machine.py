"""Status fields that are not ladders.

A rights deal's status is re-derived by a status function that can leave and
re-enter the same value, and a booking carries two orthogonal status dimensions
on one record whose triggers are disjoint.
"""

from typing import Any, Dict, List

from test_helpers import (
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    assert_block_position,
    assert_booking_dimensions,
    assert_deal_position,
    confirm_tranche,
    daily_run,
    get_success_data,
    gold_sales_floor,
    installments_of,
    issue_credentials,
    make_booking,
    make_committed_deal,
    make_event,
    make_ready_build,
    make_tranche,
    pay_installment,
    read_block,
    read_booking,
    read_client,
    reset_clock,
    set_clock,
)


def _committed_deal_with_a_sixty_unit_promise(api: ApiClient) -> Dict[str, Any]:
    """A 200-unit contract guaranteeing 100 units at 20000 cents each.

    One PENDING tranche promises 60 units, which is not enough to cover the
    guarantee on its own.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=200,
                              guaranteed_minimum_units=100, unit_cost_cents=20000)
    tranche = make_tranche(api, deal["id"], promised_units=60,
                          promised_release_at="2026-09-01T00:00:00.000Z")
    return {"event": event, "deal": deal, "tranche": tranche}


def _read_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))


def _tranche_rows(api: ApiClient, deal_id: str) -> List[Dict[str, Any]]:
    rows = get_success_data(
        api.list_release_tranches(RIGHTS_MANAGER, {"rights_deal_id": deal_id, "limit": 100})
    )
    return rows


def _reserved_gold_booking_with_ready_build(api: ApiClient) -> Dict[str, Any]:
    """A 10-unit CORPORATE booking, unallocated, with a READY build standing by."""
    floor = gold_sales_floor(api)
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=10)
    floor["build"] = make_ready_build(api, floor["event"]["id"])
    floor["booking"] = booking
    floor["installments"] = installments_of(api, booking["id"])
    return floor


# --------------------------------------------------------------------------
# A deal that enters shortfall, leaves it, re-enters it and leaves it again
# --------------------------------------------------------------------------


def test_shortfall_is_declared_by_a_confirmation_and_again_by_a_lapse(
    api: ApiClient,
) -> None:
    """Two different endpoints drive the deal into the same status twice.

    Confirming 60 of a 60-unit promise leaves 60 released against a 100-unit
    guarantee with nothing pending, so the status function declares shortfall
    with 40 units short and a liability of 60 * 20000 + 40 * 12000 == 1680000.
    A replacement promise re-opens the deal; when that promise lapses in the
    rollover, the very same status is declared again by a different endpoint, and
    the numbers are unchanged because no units were released in between.

    PRD §3.2: "Then: if `released_units` is greater than or equal to
    `contracted_units`, the deal is `FULLY_RELEASED`; otherwise, if
    `released_units` plus the pending quantity is strictly below
    `guaranteed_minimum_units`, the deal is `SHORTFALL_DECLARED`; otherwise, if
    `released_units` is above 0, the deal is `PARTIALLY_RELEASED`; otherwise the
    deal is `COMMITTED`."

    Design: Difficulty/non_linear_state_machine/rights_deal_shortfall_reopens_to_partially_released_twice
    """
    scenario = _committed_deal_with_a_sixty_unit_promise(api)
    deal_id = scenario["deal"]["id"]
    assert scenario["deal"]["deal_status"] == "COMMITTED"

    confirm_tranche(api, scenario["tranche"]["id"], deal_id, 60)
    after_confirm = _read_deal(api, deal_id)
    assert_deal_position(after_confirm, released=60, shortfall=40, liability=1680000,
                         status="SHORTFALL_DECLARED")

    replacement = make_tranche(api, deal_id, promised_units=50,
                               promised_release_at="2026-10-01T00:00:00.000Z")
    assert _read_deal(api, deal_id)["deal_status"] == "PARTIALLY_RELEASED"

    set_clock(api, "2026-10-02T00:00:00Z")
    sweep = daily_run(api)
    assert sweep["lapsed_tranche_count"] == 1
    assert sweep["shortfall_deal_count"] == 1

    after_lapse = _read_deal(api, deal_id)
    assert_deal_position(after_lapse, released=60, shortfall=40, liability=1680000,
                         status="SHORTFALL_DECLARED")
    assert after_confirm["deal_status"] == after_lapse["deal_status"]

    lapsed = get_success_data(api.get_release_tranche(replacement["id"], RIGHTS_MANAGER))
    assert lapsed["tranche_state"] == "LAPSED"
    assert lapsed["confirmed_units"] == 0
    assert lapsed["lapsed_at"] == "2026-10-02T00:00:00.000Z"


def test_a_replacement_promise_reopens_the_deal_without_retiring_the_liability(
    api: ApiClient,
) -> None:
    """The same endpoint leaves shortfall twice, and the shortfall units hold.

    From SHORTFALL_DECLARED with 60 units released, a 50-unit promise takes the
    covered quantity back above the guarantee and the deal returns to
    PARTIALLY_RELEASED rather than to COMMITTED, because released units are
    already above 0. After the lapse it is re-entered by a 40-unit promise on the
    boundary sum of exactly 100. In both excursions `shortfall_units` stays at 40
    and the liability stays at 1680000: a promise is not a release.

    PRD §3.2: "Crucially, re-entering `COMMITTED` does **not** zero
    `shortfall_units`: that figure remains the guarantee less the units actually
    released, because only genuine confirmed releases reduce it, and a promise is
    not a release."

    Design: Difficulty/non_linear_state_machine/rights_deal_shortfall_reopens_to_partially_released_twice
    """
    scenario = _committed_deal_with_a_sixty_unit_promise(api)
    deal_id = scenario["deal"]["id"]
    confirm_tranche(api, scenario["tranche"]["id"], deal_id, 60)

    make_tranche(api, deal_id, promised_units=50,
                 promised_release_at="2026-10-01T00:00:00.000Z")
    first_exit = _read_deal(api, deal_id)
    assert_deal_position(first_exit, released=60, shortfall=40, liability=1680000,
                         status="PARTIALLY_RELEASED")

    set_clock(api, "2026-10-02T00:00:00Z")
    daily_run(api)
    assert _read_deal(api, deal_id)["deal_status"] == "SHORTFALL_DECLARED"

    make_tranche(api, deal_id, promised_units=40,
                 promised_release_at="2026-11-01T00:00:00.000Z")
    second_exit = _read_deal(api, deal_id)
    assert_deal_position(second_exit, released=60, shortfall=40, liability=1680000,
                         status="PARTIALLY_RELEASED")
    assert first_exit["deal_status"] == second_exit["deal_status"]


def test_a_further_confirmation_is_a_self_loop_that_moves_only_the_numbers(
    api: ApiClient,
) -> None:
    """Confirming the last 40 units leaves the status exactly where it was.

    The deal was already PARTIALLY_RELEASED; confirming the outstanding promise
    takes released units to 100, retires the shortfall entirely and re-prices the
    liability at 100 * 20000 == 2000000, while the status stays
    PARTIALLY_RELEASED because 100 released is still short of the 200 contracted.
    The three tranche rows record the whole walk.

    PRD §3.2: "This function is what produces the deal's whole middle life:
    `COMMITTED → PARTIALLY_RELEASED` on the first partial release,
    `PARTIALLY_RELEASED → PARTIALLY_RELEASED` as a self-loop on each further
    release that still leaves the contract unfilled, and
    `PARTIALLY_RELEASED → FULLY_RELEASED` or `COMMITTED → FULLY_RELEASED` once
    the contracted quantity is met or beaten."

    Design: Difficulty/non_linear_state_machine/rights_deal_shortfall_reopens_to_partially_released_twice
    """
    scenario = _committed_deal_with_a_sixty_unit_promise(api)
    deal_id = scenario["deal"]["id"]
    confirm_tranche(api, scenario["tranche"]["id"], deal_id, 60)
    lapsing = make_tranche(api, deal_id, promised_units=50,
                           promised_release_at="2026-10-01T00:00:00.000Z")
    set_clock(api, "2026-10-02T00:00:00Z")
    daily_run(api)
    final_promise = make_tranche(api, deal_id, promised_units=40,
                                 promised_release_at="2026-11-01T00:00:00.000Z")
    before = _read_deal(api, deal_id)

    confirm_tranche(api, final_promise["id"], deal_id, 40)
    after = _read_deal(api, deal_id)

    assert before["deal_status"] == "PARTIALLY_RELEASED"
    assert_deal_position(after, released=100, shortfall=0, liability=2000000,
                         status="PARTIALLY_RELEASED")

    rows = {row["id"]: row for row in _tranche_rows(api, deal_id)}
    assert len(rows) == 3
    assert rows[scenario["tranche"]["id"]]["tranche_state"] == "CONFIRMED"
    assert rows[scenario["tranche"]["id"]]["confirmed_units"] == 60
    assert rows[lapsing["id"]]["tranche_state"] == "LAPSED"
    assert rows[lapsing["id"]]["confirmed_units"] == 0
    assert rows[final_promise["id"]]["tranche_state"] == "CONFIRMED"
    assert rows[final_promise["id"]]["confirmed_units"] == 40


# --------------------------------------------------------------------------
# Two orthogonal status dimensions on one booking
# --------------------------------------------------------------------------


def test_a_deposit_settles_while_the_delivery_dimension_is_still_reserved(
    api: ApiClient,
) -> None:
    """Money moves first, on a booking that holds no inventory at all.

    The first schedule line of 474172 is paid against a booking that has never
    been allocated. The pair reads (RESERVED, DEPOSIT_PAID), which no
    single-status model can represent: the money dimension has left its initial
    value while the delivery dimension is still at its own.

    PRD §3.5: "The two status dimensions are genuinely parallel: they live on the
    same record and evolve independently, and an operation that drives one leaves
    the other untouched."

    Design: Difficulty/non_linear_state_machine/booking_parallel_fulfillment_and_payment_dimensions_advance_independently
    """
    scenario = _reserved_gold_booking_with_ready_build(api)
    assert scenario["booking"]["net_price_cents"] == 1580574

    pay_installment(api, scenario["installments"][0]["id"], 474172)
    booking = read_booking(api, scenario["booking"]["id"])

    assert_booking_dimensions(booking, fulfillment_status="RESERVED",
                              payment_status="DEPOSIT_PAID")
    assert booking["paid_cents"] == 474172
    assert booking["allocation_block_id"] is None


def test_allocation_advances_only_the_delivery_dimension(api: ApiClient) -> None:
    """Committing inventory leaves the already-advanced money dimension alone.

    With the deposit paid, allocating the booking moves the pair from
    (RESERVED, DEPOSIT_PAID) to (ALLOCATED, DEPOSIT_PAID). The block records the
    committed units — 10 package units at two ticket units each — without its own
    state moving, because state tracks allocation against target, not sales.

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its
    `allocation_block_id` is set, the block's `committed_units` increases by the
    booking's `units` multiplied by `tickets_per_package`, the block's `version`
    increases by one, and the fixture's `fulfillment_risk_score` and
    `risk_posture` are recomputed. The booking's `payment_status` is untouched."

    Design: Difficulty/non_linear_state_machine/booking_parallel_fulfillment_and_payment_dimensions_advance_independently
    """
    scenario = _reserved_gold_booking_with_ready_build(api)
    pay_installment(api, scenario["installments"][0]["id"], 474172)

    allocated = allocate_booking(api, scenario["booking"]["id"], scenario["block"]["id"])

    assert_booking_dimensions(allocated, fulfillment_status="ALLOCATED",
                              payment_status="DEPOSIT_PAID")
    assert allocated["paid_cents"] == 474172
    assert_block_position(read_block(api, scenario["block"]["id"]),
                          allocated=40, committed=20, released_back=0, state="EXHAUSTED")


def test_the_money_dimension_advances_on_a_threshold_not_on_a_payment_count(
    api: ApiClient,
) -> None:
    """Two of three lines paid is still DEPOSIT_PAID; the third completes it.

    After the second schedule line the booking has paid 1106402 of 1580574 and
    one line is still outstanding, so the money dimension holds at DEPOSIT_PAID.
    The third payment leaves nothing scheduled and it advances to PAID_IN_FULL.
    Only then does credentialing move the delivery dimension to CREDENTIALED,
    minting 10 * (2 + 1) == 30 credentials.

    PRD §3.6: "From `DEPOSIT_PAID`, a payment after which no `SCHEDULE`
    installment of the booking remains in `SCHEDULED` or `OVERDUE` moves it to
    `PAID_IN_FULL`."

    Design: Difficulty/non_linear_state_machine/booking_parallel_fulfillment_and_payment_dimensions_advance_independently
    """
    scenario = _reserved_gold_booking_with_ready_build(api)
    booking_id = scenario["booking"]["id"]
    lines = scenario["installments"]

    pay_installment(api, lines[0]["id"], 474172)
    allocate_booking(api, booking_id, scenario["block"]["id"])

    pay_installment(api, lines[1]["id"], 632230)
    midway = read_booking(api, booking_id)
    assert_booking_dimensions(midway, fulfillment_status="ALLOCATED",
                              payment_status="DEPOSIT_PAID")
    assert midway["paid_cents"] == 1106402

    pay_installment(api, lines[2]["id"], 474172)
    settled = read_booking(api, booking_id)
    assert_booking_dimensions(settled, fulfillment_status="ALLOCATED",
                              payment_status="PAID_IN_FULL")
    assert settled["paid_cents"] == 1580574

    credentialed = issue_credentials(api, booking_id)
    assert_booking_dimensions(credentialed, fulfillment_status="CREDENTIALED",
                              payment_status="PAID_IN_FULL")
    assert credentialed["credentials_issued_count"] == 30

    for line in installments_of(api, booking_id):
        assert line["installment_state"] == "PAID"
        assert line["paid_amount_cents"] == line["amount_cents"]

    client = read_client(api, scenario["client"]["id"])
    assert client["outstanding_cents"] == 0
    assert client["overdue_installment_count"] == 0
    assert_block_position(read_block(api, scenario["block"]["id"]),
                          allocated=40, committed=20, released_back=0, state="EXHAUSTED")
