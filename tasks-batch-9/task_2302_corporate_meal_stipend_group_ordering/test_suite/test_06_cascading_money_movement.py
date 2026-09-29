"""One write fanning out to periods, program rollups, payroll and the ledger."""

from test_helpers import (
    LINES_THREE_1000,
    add_employee_with_period,
    api_client,
    assert_budget_partition,
    confirm_order,
    create_group_order,
    deliver_order,
    draft_order,
    make_employee_headers,
    order_line,
    place_order,
    read_employee,
    read_imputed_records,
    read_order,
    read_order_refund_entries,
    read_period,
    read_program,
    settle_claim,
    setup_resolved_claim,
    setup_scenario,
    validate_success,
)

_TIPPED_THREE_LINES = {"lines": LINES_THREE_1000, "tip_cents": 200}
_MISSING_ITEM_CLAIM = {
    "claim_type": "MISSING_ITEM",
    "line_index": 0,
    "claimed_cents": 1000,
}


def _two_confirmed_orders_on_consecutive_days():
    ns = setup_scenario()
    ns.first = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T12:00:00Z",
        **_TIPPED_THREE_LINES,
    )
    ns.second = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-04T12:00:00Z",
        **_TIPPED_THREE_LINES,
    )
    ns.first = confirm_order(place_order(ns.first, ns.employee), ns.restaurant)
    ns.second = confirm_order(place_order(ns.second, ns.employee), ns.restaurant)
    return ns


def test_delivery_moves_the_reservation_into_spend_and_recomputes_program_rollups():
    """Capture changes bucket inside the partition and re-derives the program.

    PRD §3.7: "The period's `reserved_cents` decreases by
    `employer_covered_cents` while its `spent_cents` increases by the same amount —
    the money changes bucket without changing the partition total — and the
    period's `version` increments by 1."

    Design: Difficulty/transitive_cascade/deliver_cascades_period_program_imputed_record_and_flips_employee_flag
    """
    ns = _two_confirmed_orders_on_consecutive_days()
    deliver_order(ns.first, ns.restaurant)
    second = deliver_order(ns.second, ns.restaurant)

    assert second["fulfillment_status"] == "DELIVERED"
    assert second["settlement_status"] == "CAPTURED"
    assert second["tax_month"] == "2026-08"

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 0
    assert period["spent_cents"] == 5000
    assert period["available_cents"] == 45000
    assert_budget_partition(period)

    program = read_program(ns.program["id"])
    assert program["program_spent_cents"] == 5000
    assert program["program_reserved_cents"] == 0
    assert program["mtd_employer_captured_cents"] == 5000


def test_delivery_accrues_payroll_and_flips_the_employee_flag_at_the_threshold():
    """The second de-minimis accrual carries the year-to-date figure to 1,000.

    PRD §3.7: "The record's `taxable_cents` is the sum of `taxable_cents` over
    the month's delivered orders and its `gross_employer_paid_cents` is the sum of
    `employer_net_cents` over the same orders."

    Design: Difficulty/transitive_cascade/deliver_cascades_period_program_imputed_record_and_flips_employee_flag
    """
    ns = _two_confirmed_orders_on_consecutive_days()

    deliver_order(ns.first, ns.restaurant)
    after_first = read_employee(ns.employee["id"])
    assert after_first["ytd_imputed_cents"] == 500
    assert after_first["tax_treatment_flag"] == "NONE"

    second = deliver_order(ns.second, ns.restaurant)
    assert second["taxable_cents"] == 500

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1, "both August deliveries share one monthly bucket"
    record = records[0]
    assert record["tax_month"] == "2026-08"
    assert record["status"] == "ACCRUING"
    assert record["gross_employer_paid_cents"] == 5000
    assert record["taxable_cents"] == 1000

    after_second = read_employee(ns.employee["id"])
    assert after_second["ytd_imputed_cents"] == 1000
    assert after_second["tax_treatment_flag"] == "W2_IMPUTED"


def test_settlement_writes_the_ledger_and_walks_the_order_totals_back():
    """One settlement re-derives every charge total on the order.

    PRD §3.8: "It then re-derives `employer_refunded_cents` and
    `employee_refunded_cents` as the cumulative credits issued against the order,
    recomputes `net_charged_cents` as `gross_total_cents` less both cumulative
    figures, and recomputes `employer_net_cents` as `employer_covered_cents` less
    `employer_refunded_cents` — the figure that lands in the period's
    `spent_cents`."

    Design: Difficulty/transitive_cascade/settle_cascades_ledger_order_period_program_record_and_employee
    """
    ns = setup_resolved_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides=_MISSING_ITEM_CLAIM,
        order_overrides=_TIPPED_THREE_LINES,
    )
    settle_claim(ns.claim)

    entries = read_order_refund_entries(ns.order["id"])
    assert len(entries) == 2
    by_direction = {entry["direction"]: entry["amount_cents"] for entry in entries}
    assert by_direction == {"EMPLOYEE_CARD_REFUND": 427, "EMPLOYER_CREDIT": 573}

    order = read_order(ns.order["id"])
    assert order["employer_refunded_cents"] == 573
    assert order["employee_refunded_cents"] == 427
    assert order["net_charged_cents"] == 3363
    assert order["employer_net_cents"] == 1927
    assert order["taxable_cents"] == 0, (
        "1,927 sits below the 2,000-cent de-minimis floor"
    )


def test_settlement_walks_back_through_the_period_program_payroll_and_employee():
    """Refunding employer cents reconciles all four downstream ledgers.

    PRD §3.8: "Accrual is then re-run on the reduced `employer_net_cents`,
    reconciling the imputed-income record's `taxable_cents` and
    `gross_employer_paid_cents` and the employee's `ytd_imputed_cents` and
    `tax_treatment_flag`."

    Design: Difficulty/transitive_cascade/settle_cascades_ledger_order_period_program_record_and_employee
    """
    ns = setup_resolved_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides=_MISSING_ITEM_CLAIM,
        order_overrides=_TIPPED_THREE_LINES,
    )
    settle_claim(ns.claim)

    period = read_period(ns.period["id"])
    assert period["spent_cents"] == 1927
    assert period["available_cents"] == 48073
    assert_budget_partition(period)

    program = read_program(ns.program["id"])
    assert program["program_spent_cents"] == 1927

    record = read_imputed_records(ns.employee["id"])[0]
    assert record["gross_employer_paid_cents"] == 1927
    assert record["taxable_cents"] == 0

    employee = read_employee(ns.employee["id"])
    assert employee["ytd_imputed_cents"] == 0
    assert employee["tax_treatment_flag"] == "NONE"


def _group_order_with_two_placed_members():
    ns = setup_scenario(clock="2026-08-04T10:00:00Z")
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ns.group_order = create_group_order(
        ns,
        ns.employee,
        cutoff_at="2026-08-04T11:00:00Z",
        window_start="2026-08-04T12:00:00Z",
        window_end="2026-08-04T12:30:00Z",
        per_person_limit_cents=3000,
    )
    ns.member_orders = []
    for employee, period, item in (
        (ns.employee, ns.period, "Pad Thai"),
        (ns.ben, ns.ben_period, "Green Curry"),
    ):
        order = draft_order(
            employee,
            period,
            ns.restaurant,
            ns.location,
            group_order_id=ns.group_order["id"],
            requested_delivery_at="2026-08-04T12:00:00Z",
            lines=[order_line(item, 1000, 1)],
        )
        ns.member_orders.append(place_order(order, employee))
    return ns


def test_cancelling_a_group_order_releases_every_member_reservation():
    """The cascade reaches two different employees' benefit periods.

    PRD §3.6: "Cancellation cascades: every attached member order that is still
    `DRAFT` or `PLACED` is cancelled too, each placed one releasing its
    `employer_covered_cents` from its period's `reserved_cents` back to
    `available_cents` and incrementing that period's `version` by 1, exactly as an
    individual cancellation would."

    Design: Difficulty/transitive_cascade/group_cancel_fans_out_to_member_orders_and_their_distinct_periods
    """
    ns = _group_order_with_two_placed_members()
    for order in ns.member_orders:
        assert order["employer_covered_cents"] == 1188
    assert read_program(ns.program["id"])["program_reserved_cents"] == 2376

    cancelled = validate_success(
        api_client.cancel_group_order(
            ns.group_order["id"], make_employee_headers(ns.employee["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    for order in ns.member_orders:
        refreshed = read_order(order["id"])
        assert refreshed["fulfillment_status"] == "CANCELLED"
        assert refreshed["settlement_status"] == "VOIDED"

    for period_id in (ns.period["id"], ns.ben_period["id"]):
        period = read_period(period_id)
        assert period["reserved_cents"] == 0
        assert period["spent_cents"] == 0
        assert period["available_cents"] == 50000
        assert_budget_partition(period)

    assert read_program(ns.program["id"])["program_reserved_cents"] == 0


def test_voiding_a_member_order_writes_only_the_employer_credit_entry():
    """With nothing on the personal card the void writes a single ledger row.

    PRD §3.8: "A `RefundLedgerEntry` is appended with `direction` of
    `EMPLOYER_CREDIT` and `amount_cents` equal to `employer_covered_cents`
    whenever that figure is greater than 0, and a second entry with `direction` of
    `EMPLOYEE_CARD_REFUND` and `amount_cents` equal to `employee_card_cents`
    whenever that figure is greater than 0; both carry `reason` of `ORDER_VOID` and
    both leave `credit_claim_id` absent, because no claim drove them."

    Design: Difficulty/transitive_cascade/group_cancel_fans_out_to_member_orders_and_their_distinct_periods
    """
    ns = _group_order_with_two_placed_members()
    assert ns.member_orders[0]["employee_card_cents"] == 0

    validate_success(
        api_client.cancel_group_order(
            ns.group_order["id"], make_employee_headers(ns.employee["id"])
        )
    )

    entries = read_order_refund_entries(ns.member_orders[0]["id"])
    assert len(entries) == 1, f"only the employer side moved, got {entries}"
    assert entries[0]["direction"] == "EMPLOYER_CREDIT"
    assert entries[0]["amount_cents"] == 1188
    assert entries[0]["reason"] == "ORDER_VOID"
    assert entries[0].get("credit_claim_id") is None

    order = read_order(ns.member_orders[0]["id"])
    assert order["net_charged_cents"] == 0
    assert order["employer_net_cents"] == 0
    assert order["admin_fee_cents"] == 0
