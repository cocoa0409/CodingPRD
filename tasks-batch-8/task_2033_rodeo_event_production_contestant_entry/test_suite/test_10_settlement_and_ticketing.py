"""Contractor settlement dual basis, rodeo settlement disbursement, and
ticket capacity bookkeeping (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_event,
    add_performance,
    assign_judge,
    assignment_for_entry,
    complete_performance,
    compute_payout,
    create_rodeo,
    execute_draw,
    get_performance,
    get_success_data,
    record_rough_result,
    register_and_enter,
    register_judge,
    sell_tickets,
    setup_active_stock,
    TEST_USERS,
    transition_payout,
    transition_rodeo,
    validate_error,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]
BOX = TEST_USERS["box_office_headers"]


def _settled_rodeo():
    """Full lifecycle to SETTLED: two performances on distinct UTC dates, a
    BULL_RIDING event with three verified outs, day_rate 50000 vs per-out
    4000. Returns (rodeo, event, contract, payout)."""
    rodeo = create_rodeo(name="Prescott Frontier Days", city="Prescott")
    event = add_event(
        rodeo["id"], event_code="BULL_RIDING", go_rounds=1,
        entry_fee_cents=2000, added_money_cents=0, per_performance_slots=10,
        payout_places=1,
    )
    p1 = add_performance(
        rodeo["id"], label="Day 1",
        starts_at="2026-08-14T19:00:00Z", ends_at="2026-08-14T22:00:00Z",
    )
    p2 = add_performance(
        rodeo["id"], label="Day 2",
        starts_at="2026-08-15T14:00:00Z", ends_at="2026-08-15T17:00:00Z",
    )
    transition_rodeo(rodeo["id"], "OPEN_ENTRIES")
    contestants, entries = register_and_enter(event["id"], 3, card_prefix="PRCA-20")
    contract, animals = setup_active_stock(
        rodeo["id"], "BULL_RIDING", ["B100", "B200", "B300"],
        day_rate_cents=50000, per_out_fee_cents=4000,
        contractor_name="C5 Rodeo Co",
    )
    transition_rodeo(rodeo["id"], "LOCK_DRAW")
    execute_draw(event["id"], go_round_number=1)
    judge = register_judge("J-2", "Judge Two", "PRCA_CARD")
    assign_judge(judge["id"], p1["id"], "ARENA_1")
    # The draw slots entries round-robin across both performances (PRD §3.5),
    # so the judge must hold an assignment for each performance (PRD §3.4).
    # The two buffered windows sit on different UTC days and cannot conflict.
    assign_judge(judge["id"], p2["id"], "ARENA_1")
    transition_rodeo(rodeo["id"], "START_RODEO")
    for entry, (j1s, j2s) in zip(entries, [(42, 40), (40, 40), (38, 38)]):
        da = assignment_for_entry(entry["id"], status="PENDING")
        verify_result(
            record_rough_result(da["id"], judge["id"], j1s, j2s)["id"]
        )
    complete_performance(p1["id"])
    complete_performance(p2["id"])
    transition_rodeo(rodeo["id"], "COMPLETE_RODEO")
    payout = compute_payout(event["id"], "FINAL")
    transition_payout(payout["id"], "FINALIZE")
    transition_rodeo(rodeo["id"], "SETTLE_RODEO")
    return rodeo, event, contract, payout


def test_settlement_computes_both_bases_and_pays_max(api):
    """PRD §3.7: "Performance days are counted as the distinct UTC calendar
    dates among the rodeo's performances that stand in `SCHEDULED` or
    `COMPLETED` status at settle time, and `day_rate_total_cents` is the
    contract's `day_rate_cents` multiplied by that day count. In parallel,
    outs are counted as the `COMPLETED` draw assignments whose animal belongs
    to the contract, and `per_out_total_cents` is the contract's
    `per_out_fee_cents` multiplied by those outs. The `settlement_cents` paid
    is the larger of the two totals, and `settlement_basis` records which
    basis won: `DAY_RATE` whenever the day-rate total is at least the per-out
    total — a tie pays the day rate — otherwise `PER_OUT`."

    Design: Difficulty/dual_variant_calc/contractor_settlement_day_rate_vs_per_out_basis
    """
    rodeo, event, contract, payout = _settled_rodeo()

    settled = validate_success(api.get_stock_contract(contract["id"], ADMIN), 200)
    assert settled["day_rate_total_cents"] == 100000, (
        f"50000 x 2 distinct performance days, got "
        f"{settled['day_rate_total_cents']}"
    )
    assert settled["per_out_total_cents"] == 12000, (
        f"4000 x 3 completed outs, got {settled['per_out_total_cents']}"
    )
    assert settled["settlement_cents"] == 100000
    assert settled["settlement_basis"] == "DAY_RATE"
    assert settled["status"] == "SETTLED"


def test_settle_disburses_payout_and_settles_contract(api):
    """PRD §3.7: "Settlement disburses: every final payout becomes `DISBURSED`
    (its terminal state), every `ACTIVE` stock contract moves to `SETTLED`
    with its settlement figures computed and stored, and each event whose
    average had zero eligible contestants adds its `average_pool_cents` to the
    rodeo's `unclaimed_purse_cents`."

    Design: Difficulty/dual_variant_calc/contractor_settlement_day_rate_vs_per_out_basis
    """
    rodeo, event, contract, payout = _settled_rodeo()

    payout_after = validate_success(api.get_payout(payout["id"], ADMIN), 200)
    assert payout_after["status"] == "DISBURSED"

    contract_after = validate_success(
        api.get_stock_contract(contract["id"], ADMIN), 200
    )
    assert contract_after["status"] == "SETTLED"

    rodeo_after = get_success_data(api.get_rodeo(rodeo["id"], ADMIN), 200)
    assert rodeo_after["posture"] == "SETTLED"
    # Every contestant qualified in the only go-round, so the average has
    # eligible contestants and nothing rolls to the committee.
    assert rodeo_after["unclaimed_purse_cents"] == 0


def test_order_reaching_exact_capacity_succeeds(api):
    """PRD §3.6: "Capacity is enforced at sale time: the seats already sold —
    the sum of `quantity` over that performance's `PAID` orders — plus the
    requested quantity must not exceed `arena_capacity`. An order that brings
    the total exactly to capacity succeeds; one seat beyond capacity is
    rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/ticket_order_at_exact_capacity_succeeds_plus_one_fails
    """
    rodeo = create_rodeo(name="Vernal Dinosaur", city="Vernal")
    performance = add_performance(rodeo["id"], arena_capacity=100)

    first = sell_tickets(performance["id"], 60)
    assert first["status"] == "PAID"
    second = sell_tickets(performance["id"], 40)
    assert second["status"] == "PAID"

    after = get_performance(performance["id"])
    assert after["sold_tickets"] == 100, (
        f"60 + 40 exactly reaches capacity and is accepted, got "
        f"{after['sold_tickets']}"
    )


def test_one_seat_beyond_capacity_rejected(api):
    """PRD §3.6: "An order that brings the total exactly to capacity succeeds;
    one seat beyond capacity is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/ticket_order_at_exact_capacity_succeeds_plus_one_fails
    """
    rodeo = create_rodeo(name="Vernal Dinosaur", city="Vernal")
    performance = add_performance(rodeo["id"], arena_capacity=100)
    sell_tickets(performance["id"], 60)
    sell_tickets(performance["id"], 40)

    overflow = api.create_ticket_order(
        {"performance_id": performance["id"], "section": "GA", "quantity": 1,
         "unit_price_cents": 2500},
        BOX,
    )
    validate_error(overflow, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    after = get_performance(performance["id"])
    assert after["sold_tickets"] == 100, (
        "the rejected order must not record any seat"
    )
    orders = get_success_data(
        api.list_ticket_orders(BOX, params={"performance_id": performance["id"]}),
        200,
    )
    assert len(orders) == 2


def test_refund_restores_sold_tickets(api):
    """PRD §3.6: "A `BoxOffice` refund of the order addressed by `order_id`
    moves it `PAID` → `REFUNDED` — the order's terminal state — and subtracts
    its quantity from the performance's `sold_tickets`."

    Design: Difficulty/compensating_invariant/ticket_purchase_then_refund_restores_exact_seat_inventory
    """
    rodeo = create_rodeo(name="Sisters Rodeo", city="Sisters")
    performance = add_performance(
        rodeo["id"], label="Saturday", arena_capacity=100,
        starts_at="2026-08-15T14:00:00Z", ends_at="2026-08-15T17:00:00Z",
    )
    first = sell_tickets(performance["id"], 60)
    assert get_performance(performance["id"])["sold_tickets"] == 60
    second = sell_tickets(performance["id"], 40)
    assert get_performance(performance["id"])["sold_tickets"] == 100

    refunded = validate_success(
        api.ticket_order_transition(first["id"], {"action": "REFUND"}, BOX), 200
    )
    assert refunded["status"] == "REFUNDED"
    assert get_performance(performance["id"])["sold_tickets"] == 40


def test_refunded_order_terminal_and_inventory_invariant_holds(api):
    """PRD §3.6: "Capacity is enforced at sale time: the seats already sold —
    the sum of `quantity` over that performance's `PAID` orders — plus the
    requested quantity must not exceed `arena_capacity`."
    PRD §3.6: "A `BoxOffice` refund of the order addressed by `order_id`
    moves it `PAID` → `REFUNDED` — the order's terminal state — and subtracts
    its quantity from the performance's `sold_tickets`."

    Design: Difficulty/compensating_invariant/ticket_purchase_then_refund_restores_exact_seat_inventory
    """
    rodeo = create_rodeo(name="Sisters Rodeo", city="Sisters")
    performance = add_performance(
        rodeo["id"], label="Saturday", arena_capacity=100,
        starts_at="2026-08-15T14:00:00Z", ends_at="2026-08-15T17:00:00Z",
    )
    first = sell_tickets(performance["id"], 60)
    second = sell_tickets(performance["id"], 40)
    validate_success(
        api.ticket_order_transition(first["id"], {"action": "REFUND"}, BOX), 200
    )

    first_after = validate_success(api.get_ticket_order(first["id"], BOX), 200)
    second_after = validate_success(api.get_ticket_order(second["id"], BOX), 200)
    assert first_after["status"] == "REFUNDED"
    assert second_after["status"] == "PAID"

    # The conserved quantity: sold_tickets equals the sum over PAID orders.
    paid_orders = get_success_data(
        api.list_ticket_orders(
            BOX, params={"performance_id": performance["id"], "status": "PAID"}
        ),
        200,
    )
    paid_seats = sum(o["quantity"] for o in paid_orders)
    assert get_performance(performance["id"])["sold_tickets"] == paid_seats == 40

    # A refunded (terminal) order cannot be refunded again.
    resp = api.ticket_order_transition(first["id"], {"action": "REFUND"}, BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
