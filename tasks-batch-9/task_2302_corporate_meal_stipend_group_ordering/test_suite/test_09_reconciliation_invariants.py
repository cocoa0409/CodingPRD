"""The compensating identities: order cash, the budget partition, imputed accrual."""

from test_helpers import (
    LINES_THREE_1000,
    assert_budget_partition,
    assert_cash_conservation,
    assert_imputed_conservation,
    confirm_order,
    deliver_order,
    draft_order,
    final_close,
    place_order,
    raise_claim,
    read_claim,
    read_employee,
    read_imputed_records,
    read_order,
    read_order_refund_entries,
    read_period,
    resolve_claim,
    round_half_up,
    settle_claim,
    setup_scenario,
    setup_settled_claim,
)

_TIPPED_THREE_LINES = {"lines": LINES_THREE_1000, "tip_cents": 200}
_MISSING_ITEM_CLAIM = {
    "claim_type": "MISSING_ITEM",
    "line_index": 0,
    "claimed_cents": 1000,
}


def _proportionally_refunded_order():
    return setup_settled_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides=_MISSING_ITEM_CLAIM,
        order_overrides=_TIPPED_THREE_LINES,
    )


def test_cash_conservation_survives_a_proportional_partial_refund():
    """The 4,363-cent charge still reconciles once 1,000 has been split back.

    PRD §2.7: "Cash conservation requires that, for any order,
    `net_charged_cents` equals `gross_total_cents` less `employer_refunded_cents`
    less `employee_refunded_cents`, and that the sum of all `amount_cents` on the
    order's refund ledger entries equals `employer_refunded_cents` plus
    `employee_refunded_cents`."

    Design: Difficulty/compensating_invariant/order_cash_conservation_holds_after_proportional_partial_refund
    """
    ns = _proportionally_refunded_order()
    order = read_order(ns.order["id"])
    entries = read_order_refund_entries(order["id"])

    assert order["gross_total_cents"] == 4363
    assert order["employer_refunded_cents"] == 573
    assert order["employee_refunded_cents"] == 427
    assert order["net_charged_cents"] == 3363
    assert (
        order["gross_total_cents"]
        - order["employer_refunded_cents"]
        - order["employee_refunded_cents"]
        == order["net_charged_cents"]
    )
    assert_cash_conservation(order, entries)

    assert order["employer_covered_cents"] == 2500
    assert order["employer_net_cents"] == 1927
    assert order["employer_covered_cents"] - order["employer_refunded_cents"] == 1927

    employee_remaining = order["employee_card_cents"] - order["employee_refunded_cents"]
    assert employee_remaining == 1436, "1,863 on the personal card less the 427 refunded"
    assert order["net_charged_cents"] == order["employer_net_cents"] + employee_remaining


def test_the_refund_ledger_rows_sum_to_each_side_of_the_approved_amount():
    """Two immutable rows account for the whole 1,000 cents, split 573 and 427.

    PRD §3.8: "The routing split itself has two variants, and the employer side
    absorbs the rounding residue in both, so `employee_refund_cents` plus
    `employer_credit_cents` always equals `approved_cents` exactly."

    Design: Difficulty/compensating_invariant/order_cash_conservation_holds_after_proportional_partial_refund
    """
    ns = _proportionally_refunded_order()
    entries = read_order_refund_entries(ns.order["id"])

    employer_rows = [e for e in entries if e["direction"] == "EMPLOYER_CREDIT"]
    employee_rows = [e for e in entries if e["direction"] == "EMPLOYEE_CARD_REFUND"]
    assert sum(e["amount_cents"] for e in employer_rows) == 573
    assert sum(e["amount_cents"] for e in employee_rows) == 427

    claim = read_claim(ns.claim["id"])
    assert claim["approved_cents"] == 1000
    assert claim["employer_credit_cents"] + claim["employee_refund_cents"] == 1000


def _period_after_one_captured_order():
    """One 3,000-cent three-line order with a 200-cent tip, delivered."""
    ns = setup_scenario()
    order = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location, **_TIPPED_THREE_LINES
    )
    ns.order = confirm_order(place_order(order, ns.employee), ns.restaurant)
    return ns


def test_the_budget_partition_identity_holds_at_open_placement_and_delivery():
    """Reserving and then capturing 2,500 only moves cents between buckets.

    PRD §2.7: "Consequently `allocated_cents` always equals the sum of
    `available_cents`, `reserved_cents`, `spent_cents`, `forfeited_cents`, and
    `rollover_out_cents`, and that identity must hold after every placement,
    delivery, cancellation, settlement, and close."

    Design: Difficulty/compensating_invariant/benefit_period_partition_invariant_holds_at_open_place_deliver_and_final_close
    """
    ns = setup_scenario()
    at_open = read_period(ns.period["id"])
    assert at_open["allocated_cents"] == 50000
    assert at_open["available_cents"] == 50000
    assert at_open["reserved_cents"] == 0
    assert at_open["spent_cents"] == 0
    assert at_open["forfeited_cents"] == 0
    assert at_open["rollover_out_cents"] == 0
    assert_budget_partition(at_open)

    order = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location, **_TIPPED_THREE_LINES
    )
    order = place_order(order, ns.employee)
    assert order["employer_covered_cents"] == 2500

    after_place = read_period(ns.period["id"])
    assert after_place["available_cents"] == 47500
    assert after_place["reserved_cents"] == 2500
    assert after_place["spent_cents"] == 0
    assert_budget_partition(after_place)

    deliver_order(confirm_order(order, ns.restaurant), ns.restaurant)

    after_deliver = read_period(ns.period["id"])
    assert after_deliver["available_cents"] == 47500
    assert after_deliver["reserved_cents"] == 0
    assert after_deliver["spent_cents"] == 2500
    assert_budget_partition(after_deliver)


def test_a_final_close_carves_the_unused_bucket_without_changing_the_total():
    """47,500 unused splits into a 12,500 rollover and 35,000 forfeited.

    PRD §3.9: "Under `CAPPED_PCT`, the cap is `allocated_cents` multiplied by
    `rollover_cap_pct`, rounded half-up to a whole cent, and `rollover_out_cents` is
    the smaller of the unused amount and that cap."

    Design: Difficulty/compensating_invariant/benefit_period_partition_invariant_holds_at_open_place_deliver_and_final_close
    """
    ns = _period_after_one_captured_order()
    deliver_order(ns.order, ns.restaurant)

    closed = final_close(ns.period["id"])
    assert closed["status"] == "CLOSED"
    assert closed["spent_cents"] == 2500
    assert closed["rollover_out_cents"] == 12500
    assert closed["forfeited_cents"] == 35000
    assert closed["available_cents"] == 0
    assert closed["reserved_cents"] == 0
    assert_budget_partition(closed)

    cap = round_half_up(50000 * 0.25)
    assert cap == 12500
    assert closed["rollover_out_cents"] == min(47500, cap), (
        "the 25 percent cap bites well below the 47,500 that was unused"
    )
    assert closed["forfeited_cents"] == 47500 - closed["rollover_out_cents"]


def _two_delivered_august_orders():
    ns = setup_scenario()
    ns.orders = []
    for requested in ("2026-08-03T12:00:00Z", "2026-08-04T12:00:00Z"):
        order = draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=requested,
            **_TIPPED_THREE_LINES,
        )
        order = place_order(order, ns.employee)
        order = confirm_order(order, ns.restaurant)
        ns.orders.append(deliver_order(order, ns.restaurant))
    return ns


def _refund_the_first_order(ns):
    claim = raise_claim(ns.orders[0], ns.employee, **_MISSING_ITEM_CLAIM)
    claim = resolve_claim(claim, ns.orders[0]["id"], routing_basis="PROPORTIONAL")
    return settle_claim(claim)


def test_a_refund_pulls_the_year_to_date_total_back_below_the_threshold():
    """Two accruals reach 1,000 and W2_IMPUTED; one refund reverts both.

    PRD §3.7: "the flag reads `W2_IMPUTED` once `ytd_imputed_cents` reaches the
    reporting threshold of 1,000 cents — ten dollars — and reads `NONE` below
    that."

    Design: Difficulty/compensating_invariant/refund_pulls_ytd_imputed_back_below_threshold_and_restores_flag_to_none
    """
    ns = _two_delivered_august_orders()
    before = read_employee(ns.employee["id"])
    assert before["ytd_imputed_cents"] == 1000
    assert before["tax_treatment_flag"] == "W2_IMPUTED"

    _refund_the_first_order(ns)

    after = read_employee(ns.employee["id"])
    assert after["ytd_imputed_cents"] == 500, (
        "the refunded order's employer_net_cents of 1,927 is now below de minimis"
    )
    assert after["tax_treatment_flag"] == "NONE", "the flag is re-derived, not latched"

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1
    assert records[0]["gross_employer_paid_cents"] == 4427
    assert records[0]["taxable_cents"] == 500


def test_imputed_conservation_holds_per_record_and_per_order_after_the_refund():
    """Only the refunded order loses its taxable amount; the other keeps 500.

    PRD §2.7: "Imputed-income conservation requires that an employee's
    `ytd_imputed_cents` always equals the sum of `taxable_cents` across all of that
    employee's `ImputedIncomeRecord` rows, and that each record's `taxable_cents`
    equals the sum of `taxable_cents` across the delivered orders in its month."

    Design: Difficulty/compensating_invariant/refund_pulls_ytd_imputed_back_below_threshold_and_restores_flag_to_none
    """
    ns = _two_delivered_august_orders()
    _refund_the_first_order(ns)

    refunded = read_order(ns.orders[0]["id"])
    untouched = read_order(ns.orders[1]["id"])
    assert refunded["employer_net_cents"] == 1927
    assert refunded["taxable_cents"] == 0
    assert untouched["employer_net_cents"] == 2500
    assert untouched["taxable_cents"] == 500

    records = read_imputed_records(ns.employee["id"])
    assert records[0]["taxable_cents"] == refunded["taxable_cents"] + untouched["taxable_cents"]
    assert_imputed_conservation(read_employee(ns.employee["id"]), records)

    period = read_period(ns.period["id"])
    assert period["spent_cents"] == 4427, "5,000 captured less the 573-cent credit"
    assert period["available_cents"] == 45573
    assert_budget_partition(period)
