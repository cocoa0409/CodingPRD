"""Declared edges, refused jumps and terminal lockdown across the aggregates."""

from test_helpers import (
    DEFAULT_CLOCK,
    TEST_USERS,
    TUESDAY_NOON,
    ApiErrorId,
    activate_rule,
    add_employee_with_period,
    add_member_order,
    api_client,
    cancel_order_as_employee,
    confirm_order,
    create_group,
    create_group_order,
    create_program,
    deliver_order,
    draft_order,
    draft_rule,
    final_close,
    grace_close,
    lock_group_order,
    make_employee_headers,
    make_restaurant_headers,
    place_order,
    place_order_raw,
    read_group,
    read_group_order,
    read_imputed_records,
    read_order,
    read_period,
    read_program,
    reinstate_restaurant,
    set_clock,
    setup_delivered_order,
    setup_drafted_order,
    setup_placed_order,
    setup_program_base,
    setup_scenario,
    suspend_restaurant,
    validate_error,
    validate_paginated,
)

_PROGRAM = TEST_USERS["program_admin_headers"]


def test_a_freshly_drafted_order_reserves_nothing_and_freezes_nothing():
    """DRAFT and UNSETTLED are the two starting states, with no money attached.

    PRD §3.4: "A draft is created with `fulfillment_status` of `DRAFT` and
    `settlement_status` of `UNSETTLED`; no budget is reserved and no fee is
    assessed until placement."

    Design: Corner/state_machines/new_order_is_created_in_draft_and_unsettled_with_nothing_frozen
    """
    ns = setup_drafted_order()

    assert ns.order["fulfillment_status"] == "DRAFT"
    assert ns.order["settlement_status"] == "UNSETTLED"
    assert ns.order.get("placed_at") is None
    assert ns.order.get("delivered_at") is None
    assert ns.order["tip_cents"] == 0
    assert ns.order["employer_covered_cents"] == 0
    assert ns.order["employee_card_cents"] == 0
    assert ns.order["admin_fee_cents"] == 0

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 0
    assert period["available_cents"] == 50000
    assert period["version"] == 1, "drafting does not mutate the benefit period"


def test_placement_advances_both_dimensions_and_freezes_the_authorised_split():
    """One 1,000-cent line prices to 1,787 and the split is frozen at once.

    PRD §3.5: "`fulfillment_status` moves `DRAFT → PLACED` and, in the settlement
    dimension, `settlement_status` moves `UNSETTLED → SPLIT_AUTHORIZED`. Reaching
    `SPLIT_AUTHORIZED` freezes `employer_covered_cents`, `employee_card_cents`, and
    `admin_fee_cents` as the authorised split."

    Design: Corner/state_machines/place_advances_both_order_dimensions_and_freezes_the_1787_employer_share
    """
    ns = setup_placed_order()
    order = ns.order

    assert order["fulfillment_status"] == "PLACED"
    assert order["settlement_status"] == "SPLIT_AUTHORIZED"

    assert order["subtotal_cents"] == 1000
    assert order["tax_cents"] == 88
    assert order["delivery_fee_cents"] == 599
    assert order["service_fee_cents"] == 100
    assert order["covered_base_cents"] == 1787

    assert order["employer_covered_cents"] == 1787
    assert order["employee_card_cents"] == 0
    assert order["admin_fee_cents"] == 89
    assert order["gross_total_cents"] == 1787
    assert order["placed_at"].startswith(DEFAULT_CLOCK[:-1])


def test_delivering_before_confirming_is_refused_and_strands_no_reservation():
    """The undeclared jump is a 409 that leaves the reservation exactly in place.

    PRD §2.10: "The addressed entity is in a state from which the requested
    transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every
    action endpoint, and covers repeat invocation such as placing an already-placed
    order, terminal-state lockdown, and undeclared jumps such as delivering before
    confirming."

    Design: Corner/state_machines/deliver_before_confirm_is_invalid_state_and_leaves_the_reservation_intact
    """
    ns = setup_placed_order()
    restaurant_headers = make_restaurant_headers(ns.restaurant["id"])

    validate_error(
        api_client.deliver_order(ns.order["id"], restaurant_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 1787
    assert period["spent_cents"] == 0
    assert period["version"] == 2, "only the placement moved the period"
    assert read_imputed_records(ns.employee["id"]) == []

    confirmed = confirm_order(ns.order, ns.restaurant)
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["settlement_status"] == "SPLIT_AUTHORIZED", (
        "confirmation moves no money at all"
    )

    delivered = deliver_order(confirmed, ns.restaurant)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "CAPTURED"
    assert read_period(ns.period["id"])["spent_cents"] == 1787


def test_a_delivered_order_can_no_longer_be_cancelled():
    """Cancellation exists only before delivery, so capture closes that door.

    PRD §3.8: "Cancellation before delivery has three flavours distinguished by
    the state it starts from, and the actor differs at the end."

    PRD §2.10: "The addressed entity is in a state from which the requested
    transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every
    action endpoint, and covers repeat invocation such as placing an already-placed
    order, terminal-state lockdown, and undeclared jumps such as delivering before
    confirming."

    Design: Corner/state_machines/cancelling_a_delivered_order_is_rejected_as_invalid_state
    """
    ns = setup_delivered_order()

    validate_error(
        api_client.cancel_order(
            ns.order["id"], make_employee_headers(ns.employee["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    order = read_order(ns.order["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settlement_status"] == "CAPTURED"
    assert order["net_charged_cents"] == 1787
    assert order["employer_net_cents"] == 1787

    _rows, meta = validate_paginated(
        api_client.list_order_refund_entries(ns.order["id"], _PROGRAM)
    )
    assert meta["total_count"] == 0, "a refused cancel writes no ledger row"


def test_a_cancelled_draft_refuses_placement_confirmation_and_a_second_cancel():
    """CANCELLED and VOIDED are terminal, so all three follow-ups are 409s.

    PRD §3.8: "An `Employee` may cancel their own order from `DRAFT`, which moves
    `fulfillment_status` to `CANCELLED` and `settlement_status` `UNSETTLED → VOIDED`
    with no ledger entries whatsoever — a never-authorised order leaves no money
    trail."

    Design: Corner/state_machines/a_cancelled_draft_order_refuses_place_confirm_and_a_second_cancel
    """
    ns = setup_drafted_order()
    employee_headers = make_employee_headers(ns.employee["id"])

    cancelled = cancel_order_as_employee(ns.order, ns.employee)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOIDED"

    validate_error(
        place_order_raw(ns.order, ns.employee), ApiErrorId.ERR_INVALID_STATE
    )
    validate_error(
        api_client.confirm_order(
            ns.order["id"], make_restaurant_headers(ns.restaurant["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api_client.cancel_order(ns.order["id"], employee_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )

    _rows, meta = validate_paginated(
        api_client.list_order_refund_entries(ns.order["id"], _PROGRAM)
    )
    assert meta["total_count"] == 0

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 0
    assert period["available_cents"] == 50000
    assert period["version"] == 1


def test_reactivating_an_active_rule_reports_the_state_not_the_stale_version():
    """Rank 8 fires before rank 13, so the replay is a 409 and never a 412.

    PRD §3.2: "The rule must be in `DRAFT`, or the request is `ERR_INVALID_STATE`;
    the same-person attempt is `ERR_SEGREGATION_OF_DUTIES`; and a rule whose
    `effective_from` is strictly after the current logical clock is not yet
    activatable and is refused with `ERR_RULE_NOT_EFFECTIVE`."

    Design: Corner/state_machines/re_activating_an_already_active_budget_rule_is_invalid_state_not_a_repeat_bump
    """
    program = create_program()
    group = create_group(program["id"])
    rule = draft_rule(group["id"])
    activated = activate_rule(rule["id"], group["id"], expected_employee_group_version=1)
    assert activated["status"] == "ACTIVE"

    error = validate_error(
        api_client.activate_budget_rule(
            rule["id"],
            {"expected_employee_group_version": 1},
            TEST_USERS["controller_approver_headers"],
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_EMPLOYEE_GROUP_VERSION.value, (
        "the supplied version is one behind, but the state gate is evaluated first"
    )

    refreshed_group = read_group(group["id"])
    assert refreshed_group["version"] == 2, "no second bump followed the refusal"
    assert refreshed_group["active_rule_count"] == 1

    rows, _meta = validate_paginated(
        api_client.list_budget_rules(
            group["id"], TEST_USERS["controller_drafter_headers"]
        )
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["rule_sequence"] == 1


def test_grace_and_final_take_two_different_edges_out_of_open():
    """GRACE only pauses the period; FINAL carves the unused allocation.

    PRD §3.9: "Mode `GRACE` moves the period `OPEN → GRACE`, increments its
    `version` by 1, and does exactly one thing: it stops new placements while
    leaving in-flight `PLACED` and `CONFIRMED` orders free to be confirmed and
    delivered."

    PRD §3.9: "`forfeited_cents` is then the unused amount minus
    `rollover_out_cents`, and `available_cents` is driven to 0, which restores the
    partition identity of §2.7 exactly."

    Design: Corner/state_machines/close_mode_grace_and_close_mode_final_take_different_edges_out_of_open
    """
    ns = setup_program_base()
    _ada, ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    _ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )

    paused = grace_close(ada_period["id"])
    assert paused["status"] == "GRACE"
    assert paused["version"] == 2
    assert paused["allocated_cents"] == 50000
    assert paused["available_cents"] == 50000, "GRACE moves no cents at all"
    assert paused["rollover_out_cents"] == 0
    assert paused["forfeited_cents"] == 0

    closed = final_close(ben_period["id"])
    assert closed["status"] == "CLOSED"
    assert closed["version"] == 2
    assert closed["allocated_cents"] == 50000
    assert closed["rollover_out_cents"] == 12500
    assert closed["forfeited_cents"] == 37500
    assert closed["available_cents"] == 0


def test_a_reopen_after_the_cutoff_reports_the_clock_not_the_reopen_ceiling():
    """Reopening is guarded by the cutoff even on the very first attempt.

    PRD §3.6: "Reopening is bounded twice over: the logical clock must still be
    strictly before `cutoff_at`, or the request is `ERR_GROUP_CUTOFF_PASSED`, and
    `reopen_count` must still be below the reopen ceiling of 2, so a group order may
    cycle back into collection at most twice and a third attempt is
    `ERR_REOPEN_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/group_reopen_is_guarded_by_the_cutoff_clock_not_only_by_the_locked_state
    """
    ns = setup_scenario(clock="2026-08-03T09:00:00Z")
    group_order = create_group_order(ns, ns.employee)
    add_member_order(ns, ns.employee, ns.period, group_order, place=True)
    locked = lock_group_order(group_order, ns.employee)
    assert locked["status"] == "LOCKED"
    assert locked["member_order_count"] == 1

    set_clock("2026-08-03T11:45:00Z")

    error = validate_error(
        api_client.reopen_group_order(
            group_order["id"], make_employee_headers(ns.employee["id"])
        ),
        ApiErrorId.ERR_GROUP_CUTOFF_PASSED,
    )
    assert error["error_id"] != ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED.value, (
        "the ceiling of 2 is untouched; it is the 11:30 cutoff that has passed"
    )

    frozen = read_group_order(group_order["id"])
    assert frozen["status"] == "LOCKED"
    assert frozen["reopen_count"] == 0
    assert frozen["member_order_count"] == 1


def test_each_placement_bubbles_up_into_the_program_level_rollups():
    """Two employees' reservations sum on the program, then one becomes spend.

    PRD §2.7: "`program_spent_cents` is the sum of `employer_net_cents` over all
    non-voided orders in the program. `program_reserved_cents` is the sum of
    `reserved_cents` over every benefit period in the program whose status is `OPEN`
    or `GRACE`."

    Design: Corner/state_machines/place_bubbles_each_reservation_up_to_the_program_rollup_totals
    """
    ns = setup_scenario(
        employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )

    ada_order = place_order(
        draft_order(ns.employee, ns.period, ns.restaurant, ns.location), ns.employee
    )
    place_order(draft_order(ben, ben_period, ns.restaurant, ns.location), ben)

    after_placements = read_program(ns.program["id"])
    assert after_placements["program_reserved_cents"] == 3574, "1,787 twice over"
    assert after_placements["program_spent_cents"] == 0

    deliver_order(confirm_order(ada_order, ns.restaurant), ns.restaurant)

    after_capture = read_program(ns.program["id"])
    assert after_capture["program_reserved_cents"] == 1787
    assert after_capture["program_spent_cents"] == 1787
    assert after_capture["mtd_employer_captured_cents"] == 1787

    ada = read_period(ns.period["id"])
    assert ada["reserved_cents"] == 0
    assert ada["spent_cents"] == 1787

    ben_read = read_period(ben_period["id"])
    assert ben_read["reserved_cents"] == 1787
    assert ben_read["spent_cents"] == 0


def test_suspension_hides_a_restaurant_yet_a_confirmed_order_still_delivers():
    """The suspension blocks new placements without disturbing history.

    PRD §3.1: "Suspension bumps the restaurant's `version` and takes it out of
    eligibility search and out of new placements immediately, but it does not
    disturb history: an order already `CONFIRMED` may still be delivered, and no
    delivered order is re-priced."

    Design: Corner/state_machines/suspending_a_restaurant_hides_it_from_selection_yet_a_confirmed_order_still_delivers
    """
    ns = setup_placed_order()
    ns.order = confirm_order(ns.order, ns.restaurant)
    later = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at=TUESDAY_NOON,
    )

    suspended = suspend_restaurant(ns.restaurant["id"])
    assert suspended["status"] == "SUSPENDED"

    _rows, meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"],
            _PROGRAM,
            params={"delivery_location_id": ns.location["id"]},
        )
    )
    assert meta["total_count"] == 0, "a suspended restaurant leaves the search"

    validate_error(
        place_order_raw(later, ns.employee), ApiErrorId.ERR_RESTAURANT_NOT_ELIGIBLE
    )

    delivered = deliver_order(ns.order, ns.restaurant)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "CAPTURED"

    reinstated = reinstate_restaurant(ns.restaurant["id"])
    assert reinstated["status"] == "ELIGIBLE"
    rows, meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"],
            _PROGRAM,
            params={"delivery_location_id": ns.location["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ELIGIBLE"

    assert read_order(ns.order["id"])["employer_covered_cents"] == 1787, (
        "no delivered order is re-priced"
    )
