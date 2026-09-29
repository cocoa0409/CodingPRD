"""Parallel order dimensions, the group-order collection cycle, and claim joins."""

from test_helpers import (
    LINES_THREE_1000,
    ApiErrorId,
    add_employee_with_period,
    add_member_order,
    api_client,
    confirm_order,
    create_group_order,
    deliver_order,
    draft_order,
    lock_group_order,
    make_employee_headers,
    place_order,
    raise_claim,
    read_claim_refund_entries,
    read_group_order,
    read_order,
    read_period,
    reopen_group_order,
    resolve_claim,
    setup_resolved_claim,
    setup_scenario,
    setup_settled_claim,
    settle_claim,
    validate_error,
)

_TIPPED_THREE_LINES = {"lines": LINES_THREE_1000, "tip_cents": 200}
_MISSING_ITEM_CLAIM = {
    "claim_type": "MISSING_ITEM",
    "line_index": 0,
    "claimed_cents": 1000,
}


def test_settlement_partially_refunds_while_the_fulfilment_dimension_stays_delivered():
    """A partial refund advances only the settlement axis of the order.

    PRD §3.8: "When the cumulative refund after this settlement —
    `employer_refunded_cents` plus `employee_refunded_cents` plus the newly
    approved amount — remains strictly below `gross_total_cents`, the order moves
    `CAPTURED → PARTIALLY_REFUNDED`; a further such settlement keeps it at
    `PARTIALLY_REFUNDED`, with the ledger simply accumulating."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_delivered_stays_while_settlement_partially_refunds
    """
    ns = setup_settled_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides=_MISSING_ITEM_CLAIM,
        order_overrides=_TIPPED_THREE_LINES,
    )

    assert ns.order["fulfillment_status"] == "DELIVERED"
    assert ns.order["settlement_status"] == "PARTIALLY_REFUNDED"
    assert ns.order["employee_refunded_cents"] == 427
    assert ns.order["employer_refunded_cents"] == 573
    assert ns.order["net_charged_cents"] == 3363
    assert ns.order["employer_net_cents"] == 1927


def test_settlement_leaves_the_delivery_stamp_and_fulfilment_state_untouched():
    """The two dimensions are independent: settling does not re-deliver.

    PRD §3.7: "On success, `delivered_at` is stamped with the logical clock,
    `net_charged_cents` is set to `gross_total_cents`, and `employer_net_cents` is
    set to `employer_covered_cents`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_delivered_stays_while_settlement_partially_refunds
    """
    ns = setup_resolved_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides=_MISSING_ITEM_CLAIM,
        order_overrides=_TIPPED_THREE_LINES,
    )
    delivered_at = ns.order["delivered_at"]
    assert ns.order["fulfillment_status"] == "DELIVERED"

    settle_claim(ns.claim)
    after = read_order(ns.order["id"])

    assert after["delivered_at"] == delivered_at
    assert after["fulfillment_status"] == "DELIVERED"
    assert after["settlement_status"] == "PARTIALLY_REFUNDED"


def _collecting_group_order():
    ns = setup_scenario(clock="2026-08-04T10:00:00Z")
    ns.group_order = create_group_order(
        ns,
        ns.employee,
        cutoff_at="2026-08-04T11:00:00Z",
        window_start="2026-08-04T12:00:00Z",
        window_end="2026-08-04T12:30:00Z",
        per_person_limit_cents=3000,
    )
    ns.member_order = add_member_order(
        ns,
        ns.employee,
        ns.period,
        ns.group_order,
        place=True,
        requested_delivery_at="2026-08-04T12:00:00Z",
    )
    return ns


def test_a_group_order_reopens_twice_and_the_third_attempt_is_refused():
    """The reopen ceiling of 2 terminates the collection cycle.

    PRD §3.6: "and `reopen_count` must still be below the reopen ceiling of 2, so
    a group order may cycle back into collection at most twice and a third attempt
    is `ERR_REOPEN_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/group_order_cycles_lock_reopen_twice_then_third_reopen_rejected
    """
    ns = _collecting_group_order()

    lock_group_order(ns.group_order, ns.employee)
    first = reopen_group_order(ns.group_order, ns.employee)
    assert first["status"] == "COLLECTING"
    assert first["reopen_count"] == 1

    lock_group_order(ns.group_order, ns.employee)
    second = reopen_group_order(ns.group_order, ns.employee)
    assert second["status"] == "COLLECTING"
    assert second["reopen_count"] == 2

    locked = lock_group_order(ns.group_order, ns.employee)
    assert locked["status"] == "LOCKED"

    response = api_client.reopen_group_order(
        ns.group_order["id"], make_employee_headers(ns.employee["id"])
    )
    validate_error(response, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED)

    final = read_group_order(ns.group_order["id"])
    assert final["status"] == "LOCKED", "the refused reopen leaves the roster frozen"
    assert final["reopen_count"] == 2


def test_each_lock_and_reopen_bumps_the_version_without_disturbing_the_roster():
    """Cycling between COLLECTING and LOCKED keeps the single member attached.

    PRD §3.6: "The organiser may reverse that decision by reopening, moving the
    group order `LOCKED → COLLECTING` and incrementing `reopen_count` by 1."

    Design: Difficulty/non_linear_state_machine/group_order_cycles_lock_reopen_twice_then_third_reopen_rejected
    """
    ns = _collecting_group_order()
    current = read_group_order(ns.group_order["id"])
    assert current["member_order_count"] == 1

    for expected_reopen_count in (1, 2):
        locked = lock_group_order(ns.group_order, ns.employee)
        assert locked["version"] == current["version"] + 1, (
            "Both lock and reopen increment the group order's version by 1"
        )
        assert locked["status"] == "LOCKED"
        assert locked["member_order_count"] == 1

        reopened = reopen_group_order(ns.group_order, ns.employee)
        assert reopened["version"] == locked["version"] + 1
        assert reopened["status"] == "COLLECTING"
        assert reopened["reopen_count"] == expected_reopen_count
        assert reopened["member_order_count"] == 1
        current = reopened

    assert read_order(ns.member_order["id"])["fulfillment_status"] == "PLACED"


def _two_delivered_orders_with_claims():
    """Ada and Ben each hold one delivered order and one SUBMITTED claim."""
    ns = setup_scenario()
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )

    ns.orders = {}
    ns.claims = {}
    for key, employee, period in (
        ("ada", ns.employee, ns.period),
        ("ben", ns.ben, ns.ben_period),
    ):
        order = draft_order(employee, period, ns.restaurant, ns.location, **_TIPPED_THREE_LINES)
        order = place_order(order, employee)
        order = confirm_order(order, ns.restaurant)
        order = deliver_order(order, ns.restaurant)
        ns.orders[key] = order
        ns.claims[key] = raise_claim(order, employee, **_MISSING_ITEM_CLAIM)
    return ns


def test_two_routed_claim_states_join_at_settled_with_different_ledger_shapes():
    """Both routed branches converge on SETTLED but write different entries.

    PRD §3.8: "Settlement appends one or two `RefundLedgerEntry` rows with
    `reason` of `CLAIM_SETTLEMENT` and `credit_claim_id` naming the claim: an
    `EMPLOYER_CREDIT` entry for `employer_credit_cents` and an
    `EMPLOYEE_CARD_REFUND` entry for `employee_refund_cents`, each written only
    when its amount is greater than 0."

    Design: Difficulty/non_linear_state_machine/credit_claim_forks_two_routing_states_then_joins_at_settled
    """
    ns = _two_delivered_orders_with_claims()

    ada_claim = resolve_claim(
        ns.claims["ada"], ns.orders["ada"]["id"], routing_basis="EMPLOYEE_FIRST"
    )
    ben_claim = resolve_claim(
        ns.claims["ben"], ns.orders["ben"]["id"], routing_basis="PROPORTIONAL"
    )
    assert ada_claim["status"] == "ROUTED_EMPLOYEE_FIRST"
    assert ben_claim["status"] == "ROUTED_PROPORTIONAL"

    ada_claim = settle_claim(ada_claim)
    ben_claim = settle_claim(ben_claim)
    assert ada_claim["status"] == "SETTLED"
    assert ben_claim["status"] == "SETTLED"

    ada_entries = read_claim_refund_entries(ada_claim["id"])
    assert len(ada_entries) == 1, (
        f"EMPLOYEE_FIRST leaves nothing for the employer, got {ada_entries}"
    )
    assert ada_entries[0]["direction"] == "EMPLOYEE_CARD_REFUND"
    assert ada_entries[0]["amount_cents"] == 1000
    assert ada_entries[0]["reason"] == "CLAIM_SETTLEMENT"
    assert ada_entries[0]["credit_claim_id"] == ada_claim["id"]

    ben_entries = read_claim_refund_entries(ben_claim["id"])
    assert len(ben_entries) == 2
    by_direction = {entry["direction"]: entry["amount_cents"] for entry in ben_entries}
    assert by_direction == {"EMPLOYEE_CARD_REFUND": 427, "EMPLOYER_CREDIT": 573}


def test_the_two_routing_branches_return_different_amounts_to_the_two_budgets():
    """Only the proportional branch returns employer cents to the period.

    PRD §3.8: "The period's `spent_cents` decreases by `employer_credit_cents`
    and its `available_cents` increases by the same amount, returning employer
    money to the budget."

    Design: Difficulty/non_linear_state_machine/credit_claim_forks_two_routing_states_then_joins_at_settled
    """
    ns = _two_delivered_orders_with_claims()

    settle_claim(
        resolve_claim(
            ns.claims["ada"], ns.orders["ada"]["id"], routing_basis="EMPLOYEE_FIRST"
        )
    )
    settle_claim(
        resolve_claim(
            ns.claims["ben"], ns.orders["ben"]["id"], routing_basis="PROPORTIONAL"
        )
    )

    ada_period = read_period(ns.period["id"])
    assert ada_period["spent_cents"] == 2500, "no employer credit was issued"
    assert ada_period["available_cents"] == 47500

    ben_period = read_period(ns.ben_period["id"])
    assert ben_period["spent_cents"] == 1927, "2,500 less the 573-cent employer credit"
    assert ben_period["available_cents"] == 48073
