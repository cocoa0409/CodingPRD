"""One entity's state deciding whether another entity's transition is allowed."""

from test_helpers import (
    LINES_THREE_1000,
    ApiErrorId,
    add_member_order,
    api_client,
    create_group_order,
    deliver_order,
    draft_order,
    final_close,
    grace_close,
    lock_group_order,
    make_employee_headers,
    make_restaurant_headers,
    open_period,
    place_order,
    place_order_raw,
    read_group_order,
    read_imputed_records,
    read_order,
    read_period,
    reinstate_restaurant,
    setup_confirmed_order,
    setup_delivered_order,
    setup_scenario,
    submit_group_order,
    suspend_restaurant,
    validate_error,
)

_TIPPED_THREE_LINES = {"lines": LINES_THREE_1000, "tip_cents": 200}


def _record_for(employee_id, tax_month):
    """The employee's imputed-income record for one YYYY-MM bucket."""
    matches = [
        record
        for record in read_imputed_records(employee_id)
        if record["tax_month"] == tax_month
    ]
    assert len(matches) == 1, f"expected one {tax_month} record, got {matches}"
    return matches[0]


def _grace_period_with_one_confirmed_and_one_drafted_order():
    ns = setup_confirmed_order(order_overrides=_TIPPED_THREE_LINES)
    ns.late_order = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-04T12:00:00Z",
        **_TIPPED_THREE_LINES,
    )
    ns.period = grace_close(ns.period["id"])
    return ns


def test_a_grace_period_refuses_new_placements_but_still_lets_a_delivery_through():
    """GRACE is a drain: it stops the front door without stranding the reservation.

    PRD §3.9: "Mode `GRACE` moves the period `OPEN → GRACE`, increments its
    `version` by 1, and does exactly one thing: it stops new placements while
    leaving in-flight `PLACED` and `CONFIRMED` orders free to be confirmed and
    delivered."

    Design: Difficulty/cross_entity_state_dependency/grace_period_blocks_new_placement_but_still_permits_delivery_of_confirmed_order
    """
    ns = _grace_period_with_one_confirmed_and_one_drafted_order()

    response = place_order_raw(ns.late_order, ns.employee)
    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_OPEN)
    assert read_order(ns.late_order["id"])["fulfillment_status"] == "DRAFT"

    delivered = deliver_order(ns.order, ns.restaurant)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "CAPTURED"


def test_delivering_out_of_a_grace_period_captures_without_reopening_it():
    """The period stays GRACE while its reservation becomes spend.

    PRD §3.9: "Mode `FINAL` moves the period to the terminal `CLOSED`, and it may
    be requested from either `OPEN` or `GRACE` with identical effects."

    Design: Difficulty/cross_entity_state_dependency/grace_period_blocks_new_placement_but_still_permits_delivery_of_confirmed_order
    """
    ns = _grace_period_with_one_confirmed_and_one_drafted_order()
    deliver_order(ns.order, ns.restaurant)

    period = read_period(ns.period["id"])
    assert period["status"] == "GRACE", "delivery does not reopen a drained period"
    assert period["reserved_cents"] == 0
    assert period["spent_cents"] == 2500

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1
    assert records[0]["tax_month"] == "2026-08"
    assert records[0]["status"] == "ACCRUING"
    assert records[0]["taxable_cents"] == 500


def _locked_group_order_with_one_member():
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
    ns.group_order = lock_group_order(ns.group_order, ns.employee)
    return ns


def test_a_suspended_restaurant_blocks_submission_and_reinstatement_unblocks_it():
    """Group submission re-reads the restaurant's live eligibility.

    PRD §3.6: "and it requires the restaurant to still be `ELIGIBLE`, reporting
    `ERR_RESTAURANT_NOT_ELIGIBLE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/restaurant_suspension_blocks_group_submit_and_reinstatement_unblocks_it
    """
    ns = _locked_group_order_with_one_member()
    suspend_restaurant(ns.restaurant["id"])

    response = api_client.submit_group_order(
        ns.group_order["id"], make_employee_headers(ns.employee["id"])
    )
    validate_error(response, ApiErrorId.ERR_RESTAURANT_NOT_ELIGIBLE)

    blocked = read_group_order(ns.group_order["id"])
    assert blocked["status"] == "LOCKED"
    assert blocked["allocated_delivery_fee_cents"] == 0

    reinstate_restaurant(ns.restaurant["id"])
    submitted = submit_group_order(ns.group_order, ns.employee)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["allocated_delivery_fee_cents"] == 1250


def test_submission_after_reinstatement_reprices_the_sole_member_order():
    """The consolidated 1,250-cent fee lands entirely on the only member.

    PRD §3.6: "Allocation is followed by a full re-pricing of every member order,
    because a member's delivery fee has just changed from 0 to a real number."

    Design: Difficulty/cross_entity_state_dependency/restaurant_suspension_blocks_group_submit_and_reinstatement_unblocks_it
    """
    ns = _locked_group_order_with_one_member()
    suspend_restaurant(ns.restaurant["id"])
    api_client.submit_group_order(
        ns.group_order["id"], make_employee_headers(ns.employee["id"])
    )
    reinstate_restaurant(ns.restaurant["id"])
    submit_group_order(ns.group_order, ns.employee)

    member = read_order(ns.member_order["id"])
    assert member["delivery_fee_cents"] == 1250
    assert member["covered_base_cents"] == 2438
    assert member["employer_covered_cents"] == 2438
    assert member["employee_card_cents"] == 0

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 2438, (
        "the reservation is adjusted by the delta in employer_covered_cents"
    )


def _closed_august_and_open_september():
    ns = setup_delivered_order(
        order_overrides=dict(_TIPPED_THREE_LINES, requested_delivery_at="2026-08-03T12:00:00Z")
    )
    ns.august_period = final_close(ns.period["id"])
    ns.september_period = open_period(
        ns.employee["id"],
        period_month="2026-09",
        predecessor_period_id=ns.august_period["id"],
    )
    return ns


def test_final_close_carries_a_capped_rollover_into_the_successor_period():
    """A 25 percent cap on a 50,000-cent allocation rolls 12,500 forward.

    PRD §3.9: "A period allocated 50,000 cents that spent 2,500 has 47,500
    unused; under a 25 percent cap that is a cap of 12,500, so
    `rollover_out_cents` is 12,500 and `forfeited_cents` is 35,000. A successor
    period naming it as predecessor then opens with `rollover_in_cents` of 12,500
    and `allocated_cents` of 62,500."

    Design: Difficulty/cross_entity_state_dependency/locked_tax_month_record_blocks_deliver_of_a_backdated_order_from_a_later_period
    """
    ns = _closed_august_and_open_september()

    assert ns.august_period["status"] == "CLOSED"
    assert ns.august_period["spent_cents"] == 2500
    assert ns.august_period["rollover_out_cents"] == 12500
    assert ns.august_period["forfeited_cents"] == 35000
    assert ns.august_period["available_cents"] == 0

    assert ns.september_period["rollover_in_cents"] == 12500
    assert ns.september_period["allocated_cents"] == 62500
    assert ns.september_period["available_cents"] == 62500
    assert ns.september_period["status"] == "OPEN"

    august_record = _record_for(ns.employee["id"], "2026-08")
    assert august_record["status"] == "LOCKED", (
        "a final close cascades ACCRUING -> LOCKED for the matching tax month"
    )


def test_a_locked_tax_month_refuses_a_backdated_delivery_from_a_later_period():
    """The month bucket, not the period, decides whether delivery may capture.

    PRD §3.7: "Delivery is refused with `ERR_TAX_MONTH_LOCKED` if the employee's
    imputed-income bucket for the order's month already exists and is `LOCKED` or
    `EXPORTED`; payroll having taken the month is final."

    Design: Difficulty/cross_entity_state_dependency/locked_tax_month_record_blocks_deliver_of_a_backdated_order_from_a_later_period
    """
    ns = _closed_august_and_open_september()
    restaurant_headers = make_restaurant_headers(ns.restaurant["id"])

    backdated = draft_order(
        ns.employee,
        ns.september_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-10T12:00:00Z",
        **_TIPPED_THREE_LINES,
    )
    backdated = place_order(backdated, ns.employee)
    api_client.confirm_order(backdated["id"], restaurant_headers)
    response = api_client.deliver_order(backdated["id"], restaurant_headers)
    validate_error(response, ApiErrorId.ERR_TAX_MONTH_LOCKED)
    assert read_order(backdated["id"])["fulfillment_status"] == "CONFIRMED"

    september = draft_order(
        ns.employee,
        ns.september_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-09-01T12:00:00Z",
        **_TIPPED_THREE_LINES,
    )
    september = place_order(september, ns.employee)
    api_client.confirm_order(september["id"], restaurant_headers)
    delivered = deliver_order(september, ns.restaurant)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["tax_month"] == "2026-09"

    september_record = _record_for(ns.employee["id"], "2026-09")
    assert september_record["status"] == "ACCRUING"
    assert september_record["taxable_cents"] == 500

    august_record = _record_for(ns.employee["id"], "2026-08")
    assert august_record["status"] == "LOCKED"
    assert august_record["taxable_cents"] == 500
    assert august_record["gross_employer_paid_cents"] == 2500
