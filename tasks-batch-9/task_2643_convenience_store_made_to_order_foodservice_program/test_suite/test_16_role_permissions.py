"""Who may act, and on which row.

Three different gates wear the same 403: the endpoint's role list, the two
segregation-of-duties comparisons that read an actor id off an earlier step,
and the row-level ownership check that only the entity-backed `Customer` role
is subject to. A role list alone satisfies none of the last two.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

E = H.ApiErrorId

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
U7_ASSOCIATE = H.make_associate_headers(H.UNKNOWN_USER_ID)
U7_SHIFT_LEAD = H.make_shift_lead_headers(H.UNKNOWN_USER_ID)
LEAD_9 = H.make_shift_lead_headers(H.SHIFT_LEAD_9_USER_ID)


def test_labor_planning_is_closed_to_everyone_but_the_store_manager(api):
    """All three plan endpoints refuse the make line, then admit the manager.

    The endpoint table is normative — "the authorization column of the endpoint
    table in §4 is the normative list" — and it names `StoreManager` alone for
    all three: "Create a daypart labor plan from a forecast transaction count",
    "Publish a labor plan, authorizing order placement in its daypart" and "Lock
    a published plan so it can no longer be superseded". Guarding only the create
    would leave the other two open, so a `KitchenAssociate` and a `ShiftLead` are
    both turned away with the authorization code: "When the headers are
    well-formed but the named role is not authorized for the endpoint being
    called ... the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    The manager's own path still works, and "Publishing is what authorizes
    trade", moving the plan "`DRAFT → PUBLISHED`" with its version incremented.

    Design: Corner/rbac/kitchen_associate_cannot_publish_a_staffing_plan
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    plan_body = F.staffing_plan_payload(store["version"], daypart="BREAKFAST")

    H.validate_error(
        api.create_staffing_plan(store["id"], plan_body, H.KITCHEN_ASSOCIATE_HEADERS),
        E.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    plan = H.get_success_data(
        api.create_staffing_plan(store["id"], plan_body, H.STORE_MANAGER_HEADERS), 201
    )
    assert plan["status"] == "DRAFT"

    H.validate_error(
        api.publish_staffing_plan(plan["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS),
        E.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    H.validate_error(
        api.lock_staffing_plan(plan["id"], {}, H.SHIFT_LEAD_HEADERS),
        E.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    published = H.get_success_data(
        api.publish_staffing_plan(plan["id"], {}, H.STORE_MANAGER_HEADERS), 200
    )
    assert published["status"] == "PUBLISHED"
    assert published["version"] == 2

    _, meta = H.validate_paginated(
        api.list_staffing_plans(
            store["id"], H.STORE_MANAGER_HEADERS, {"service_date": "2026-08-01"}
        )
    )
    assert meta["total_count"] == 1


def test_the_lead_who_took_the_reading_may_not_sign_off_on_it(api):
    """lead-1 is refused and lead-2, same role, succeeds.

    "Verifying a corrective action requires that the acting `X-User-ID` differ
    from the `logged_by_user_id` recorded on the temperature reading being
    remediated: the associate who took a failing probe reading may not sign off
    on its own remediation." Nothing else differs between the two calls — the
    role is identical, the action is the same `OPEN` row and the cabinet is
    `IMPAIRED` either way — so identity is isolated as the cause, and the code is
    the identity code: "Both violations report `ERR_SEGREGATION_OF_DUTIES` with
    HTTP 403." The successful sign-off "records `verified_by_user_id` as the
    acting `X-User-ID` and `verified_at` as the current logical-clock instant",
    "returns the unit to service" and "resets the unit's
    `consecutive_out_of_range_count` to zero".

    Design: Corner/rbac/same_associate_cannot_verify_their_own_temperature_log
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    reading = X.log_temperature(api, unit["id"], 120, H.SHIFT_LEAD_HEADERS)
    assert reading["logged_by_user_id"] == H.SHIFT_LEAD_1_USER_ID
    action = X.open_corrective_action(
        api, reading["id"], H.SHIFT_LEAD_HEADERS, action_taken="Reseated the case door"
    )

    H.validate_error(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_HEADERS),
        E.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    verified = H.get_success_data(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_2_HEADERS), 200
    )

    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == H.SHIFT_LEAD_2_USER_ID
    assert verified["verified_at"] == CLOCK_EARLY
    restored = X.read_holding_unit(api, unit["id"])
    assert restored["status"] == "OPERATIONAL"
    assert restored["consecutive_out_of_range_count"] == 0


def test_a_lockout_needs_the_safety_lead_even_though_the_lead_is_listed(api):
    """The same pair of callers swap outcomes at the second failing probe.

    A `ShiftLead` "verifies corrective actions that do not involve a locked-out
    unit", while the `FoodSafetyLead` is "the only role permitted to clear a
    locked-out holding unit". Escalation is what moves the line: "A unit in
    `OPERATIONAL` goes `OPERATIONAL → IMPAIRED` ... A unit already in `IMPAIRED`
    goes `IMPAIRED → LOCKED_OUT` when a further out-of-band reading arrives, with
    the counter increasing again to reach 2." Because the lead is still on the
    endpoint's role list, the refusal cannot be the generic one: "if the unit is
    currently `LOCKED_OUT`, the acting `X-User-Role` must be `FoodSafetyLead`; a
    `ShiftLead` attempting to clear a locked-out unit is rejected with
    `ERR_LOCKOUT_REQUIRES_SAFETY_LEAD` (HTTP 403)." The inspection summary then
    clears too, since "`units_locked_out_count` counts those currently in
    `LOCKED_OUT`".

    Design: Corner/rbac/only_food_safety_lead_can_clear_a_locked_out_unit
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])

    X.log_temperature(api, unit["id"], 120, H.KITCHEN_ASSOCIATE_HEADERS)
    assert X.read_holding_unit(api, unit["id"])["status"] == "IMPAIRED"
    second_reading = X.log_temperature(api, unit["id"], 118, H.KITCHEN_ASSOCIATE_HEADERS)
    locked = X.read_holding_unit(api, unit["id"])
    assert locked["status"] == "LOCKED_OUT"
    assert locked["consecutive_out_of_range_count"] == 2

    action = X.open_corrective_action(
        api,
        second_reading["id"],
        H.SHIFT_LEAD_HEADERS,
        action_taken="Called the refrigeration vendor and moved product",
    )

    H.validate_error(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_HEADERS),
        E.ERR_LOCKOUT_REQUIRES_SAFETY_LEAD.value,
        403,
    )

    cleared = H.get_success_data(
        api.verify_corrective_action(action["id"], {}, H.FOOD_SAFETY_LEAD_HEADERS), 200
    )

    assert cleared["status"] == "VERIFIED"
    assert cleared["verified_by_user_id"] == H.FOOD_SAFETY_LEAD_USER_ID
    back_in_service = X.read_holding_unit(api, unit["id"])
    assert back_in_service["status"] == "OPERATIONAL"
    assert back_in_service["consecutive_out_of_range_count"] == 0
    assert X.read_readiness(api, store["id"])["units_locked_out_count"] == 0


def test_the_associate_who_closed_a_ticket_may_not_be_the_one_who_reopens_it(api):
    """u-7 wearing the ShiftLead badge is still u-7 the closer.

    "Reopening a finished kitchen ticket requires that the acting `X-User-ID`
    differ from the `completed_by_user_id` recorded on that ticket: the associate
    who declared a build finished may not be the actor who sends it back for
    rework." The role list is satisfied — "A `ShiftLead`, and only a `ShiftLead`,
    may send a finished ticket back to the make line with a `reason`" — and so is
    the state gate, since the second of the three preconditions is that "the
    owning order's `production_status` must be `IN_PRODUCTION` or `ASSEMBLED`",
    which the still-queued beverage keeps true. Only the identity differs. The
    successful reopen "increases the ticket's own `rework_count` by one and the
    order's `rework_count` by one" and bills the make line: "the store's
    `rework_waste_cents_mtd` increases by the sum, over the reopened ticket's
    lines, of the menu item's `unit_food_cost_cents` multiplied by the line's
    `qty`".

    Design: Corner/rbac/same_user_cannot_reopen_the_ticket_they_completed
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    X.place_order(api, order["id"])
    X.authorize_order(api, order["id"])
    sandwich = X.find_ticket(api, order["id"], "SANDWICH")
    X.start_ticket(api, sandwich["id"], U7_ASSOCIATE)
    closed = X.complete_ticket(api, sandwich["id"], U7_ASSOCIATE)
    assert closed["completed_by_user_id"] == H.UNKNOWN_USER_ID
    assert X.read_order(api, order["id"])["production_status"] == "IN_PRODUCTION"

    self_reopen = api.reopen_kitchen_ticket(
        sandwich["id"], F.reopen_payload("MEAT_WAS_COLD"), U7_SHIFT_LEAD
    )

    H.validate_error(self_reopen, E.ERR_SEGREGATION_OF_DUTIES.value, 403)

    reopened = H.get_success_data(
        api.reopen_kitchen_ticket(
            sandwich["id"], F.reopen_payload("MEAT_WAS_COLD"), LEAD_9
        ),
        200,
    )

    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["rework_count"] == 1
    after_order = X.read_order(api, order["id"])
    assert after_order["production_status"] == "IN_PRODUCTION"
    assert after_order["rework_count"] == 1
    assert X.read_store(api, store["id"])["rework_waste_cents_mtd"] == 300


def test_ownership_is_a_row_check_not_a_role_check(api):
    """Member B holds the right role and is still refused the read and the write.

    The `Customer` role "is the single exception and is **entity-backed**. When
    `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `LoyaltyAccount`", so the decision is made against the row: "a `Customer`
    acting on an order whose `loyalty_account_id` differs from the caller's
    `X-User-ID` is rejected with `ERR_ORDER_NOT_OWNED` (HTTP 403). That ownership
    check guards seven operations: adding a line to an order, deleting a line
    from an order, placing an order, authorizing an order, settling an order,
    picking up an order, and reading a single order." Member A runs the identical
    two calls and both land, which isolates identity rather than role or state as
    the cause; the terminal that opened the draft is exempt because for the other
    six roles "the server never compares it to any entity's `id`".

    Design: Corner/rbac/customer_cannot_touch_another_members_order
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    coffee = X.create_coffee(api)
    member_a = X.create_loyalty_account(api, member_code="M-A", email="a@example.com")
    member_b = X.create_loyalty_account(api, member_code="M-B", email="b@example.com")
    a_headers = H.make_customer_headers(member_a["id"])
    b_headers = H.make_customer_headers(member_b["id"])
    order = X.create_draft_order(api, store["id"], loyalty_account_id=member_a["id"])

    stranger_read = api.get_order(order["id"], b_headers)
    stranger_write = api.create_order_line(
        order["id"], F.order_line_payload(coffee["id"], 1), b_headers
    )

    H.validate_error(stranger_read, E.ERR_ORDER_NOT_OWNED.value, 403)
    H.validate_error(stranger_write, E.ERR_ORDER_NOT_OWNED.value, 403)

    owner_view = H.get_success_data(api.get_order(order["id"], a_headers))
    assert owner_view["loyalty_account_id"] == member_a["id"]
    owner_line = H.get_success_data(
        api.create_order_line(order["id"], F.order_line_payload(coffee["id"], 1), a_headers),
        201,
    )
    assert H.is_valid_uuid(owner_line["id"])

    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 249
    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 1


def test_the_register_and_the_app_capture_the_same_order_and_only_one_earns(api):
    """Two identical three-call sequences, two different identities, one accrual.

    The capture path is shared, not owned: "An order begins life as an empty
    draft opened either by a `StoreTerminal` at the register or touchscreen, or by
    a `Customer` in the mobile app", and the endpoint table lists both roles for
    opening a draft, adding a line and committing it. Both commits therefore
    price identically and snapshot the trading period, since on placement
    "`daypart_at_placement` snapshots the store's `current_daypart`" while the
    money axis stays where it started at `UNPAID`. Only the loyalty leg differs:
    "When the order carries a `loyalty_account_id`, `points_provisional` is
    credited at commit", at "10000 basis points at `BASIC`" with "any fractional
    remainder **discarded** rather than rounded", so 249 cents earns 2 — whereas
    "An anonymous order accrues zero in this variant and leaves no account
    untouched." The credit "is added to the account's `points_balance` and to its
    `lifetime_points_earned`".

    Design: Corner/rbac/both_store_terminal_and_customer_can_place_an_order
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    coffee = X.create_coffee(api)
    member = X.create_loyalty_account(api, member_code="M-A", email="a@example.com")
    member_headers = H.make_customer_headers(member["id"])

    terminal_order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, terminal_order["id"], coffee["id"], 1)
    terminal_placed = X.place_order(api, terminal_order["id"])

    app_order = X.create_draft_order(
        api, store["id"], member_headers, loyalty_account_id=member["id"]
    )
    X.add_order_line(api, app_order["id"], coffee["id"], 1, headers=member_headers)
    app_placed = X.place_order(api, app_order["id"], member_headers)

    assert terminal_placed["production_status"] == "PLACED"
    assert app_placed["production_status"] == "PLACED"
    assert terminal_placed["total_cents"] == 249
    assert app_placed["total_cents"] == 249
    assert terminal_placed["points_provisional"] == 0
    assert app_placed["points_provisional"] == 2
    assert terminal_placed["settlement_status"] == "UNPAID"
    assert app_placed["settlement_status"] == "UNPAID"
    assert terminal_placed["daypart_at_placement"] == "LUNCH"
    assert app_placed["daypart_at_placement"] == "LUNCH"

    account = X.read_loyalty_account(api, member["id"])
    assert account["points_balance"] == 2
    assert account["lifetime_points_earned"] == 2

    _, meta = H.validate_paginated(
        api.list_orders(H.STORE_MANAGER_HEADERS, {"store_id": store["id"]})
    )
    assert meta["total_count"] == 2


def test_authentication_answers_before_existence_and_before_the_schema(api):
    """A headerless call carrying a bogus id and a bad enum still answers 401.

    "If either header is absent or blank, or if `X-User-Role` is not one of the
    seven declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)", and the ordering is what this pins down:
    "Authentication is always evaluated before authorization, and both are
    evaluated before any part of the request body is inspected." So neither the
    unresolvable `store_id` — which would otherwise raise the priority-4 404 —
    nor the `channel` outside "a `channel` of `TOUCHSCREEN`, `MOBILE_PREORDER` or
    `CATERING`" gets a chance to answer first. An undeclared role name is the same
    401, not a 403, because being one of the seven is part of the authentication
    test. Only when the headers are sound does the endpoint's own list speak, and
    creating a chain menu item is a `ChainAdmin` capability: "When the headers are
    well-formed but the named role is not authorized for the endpoint being called
    ... the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/request_with_a_blank_role_header_is_rejected_before_anything_else
    """
    unauthenticated = api.create_order(
        {"store_id": H.NON_EXISTENT_UUID, "channel": "NOT_A_CHANNEL"}, H.NO_AUTH_HEADERS
    )

    H.validate_error(unauthenticated, E.ERR_UNAUTHENTICATED.value, 401)

    undeclared_role = api.get_store(H.NON_EXISTENT_UUID, H.UNRECOGNISED_ROLE_HEADERS)

    H.validate_error(undeclared_role, E.ERR_UNAUTHENTICATED.value, 401)

    wrong_role = api.create_menu_item(F.coffee_payload(), H.STORE_TERMINAL_HEADERS)

    H.validate_error(wrong_role, E.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = H.validate_paginated(api.list_orders(H.STORE_MANAGER_HEADERS))
    assert meta["total_count"] == 0
