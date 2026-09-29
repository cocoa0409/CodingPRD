"""Aggregate ceilings, uniqueness, referential mismatch and the fiscal gates."""

from test_helpers import (
    MONDAY_NOON,
    TEST_USERS,
    TUESDAY_NOON,
    ApiErrorId,
    activate_rule,
    add_employee_with_period,
    api_client,
    cancel_order_as_employee,
    confirm_order,
    create_benefit_period_payload,
    create_credit_claim_payload,
    create_employee,
    create_employee_group_payload,
    create_group,
    create_group_order,
    create_order_payload,
    create_program,
    create_restaurant,
    deliver_order,
    draft_order,
    draft_rule,
    final_close,
    get_success_data,
    make_employee_headers,
    open_period,
    order_line,
    place_order,
    place_order_raw,
    read_employee,
    read_group,
    read_group_order,
    read_order,
    read_period,
    set_clock,
    setup_program_base,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLATFORM = TEST_USERS["platform_admin_headers"]
_PROGRAM = TEST_USERS["program_admin_headers"]
_DRAFTER = TEST_USERS["controller_drafter_headers"]
_APPROVER = TEST_USERS["controller_approver_headers"]


def test_the_daily_ceiling_counts_live_orders_per_utc_date_and_a_cancel_frees_a_slot():
    """A limit of one blocks the second Monday order but never the Tuesday one.

    PRD §3.5: "Then the daily ceiling: counting the employee's orders on the
    requested UTC calendar date that are `PLACED`, `CONFIRMED`, or `DELIVERED`, that
    count must be strictly below the pinned rule's `daily_meal_limit`, or the
    placement is `ERR_DAILY_MEAL_LIMIT_EXCEEDED`. Cancelled orders do not count, so
    cancelling frees a slot for the same day."

    Design: Corner/validations/daily_meal_limit_counts_live_orders_per_utc_day_and_a_cancel_frees_the_slot
    """
    ns = setup_scenario()
    first = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
        ),
        ns.employee,
    )
    second = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T13:00:00Z",
        lines=[order_line("Green Curry", 1000, 1)],
    )
    third = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at=TUESDAY_NOON,
    )

    validate_error(
        place_order_raw(second, ns.employee),
        ApiErrorId.ERR_DAILY_MEAL_LIMIT_EXCEEDED,
    )
    assert place_order(third, ns.employee)["fulfillment_status"] == "PLACED", (
        "the count is per UTC calendar date, not per benefit period"
    )

    cancelled = cancel_order_as_employee(first, ns.employee)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOIDED"

    retried = place_order(second, ns.employee)
    assert retried["fulfillment_status"] == "PLACED"

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 3574, "the Tuesday order plus the retried Monday"


def _delivered_two_line_order():
    ns = setup_scenario()
    order = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
            lines=[
                order_line("Pad Thai", 1000, 1),
                order_line("Spring Rolls", 500, 1),
            ],
        ),
        ns.employee,
    )
    assert order["subtotal_cents"] == 1500
    assert order["tax_cents"] == 132
    assert order["covered_base_cents"] == 2381
    ns.order = deliver_order(confirm_order(order, ns.restaurant), ns.restaurant)
    return ns


def test_a_bad_line_index_is_reported_even_when_the_amount_is_also_impossible():
    """Rank 35 precedes rank 36, so 9,999 on line 7 still reads as the index.

    PRD §2.10: "`line_index` is present and addresses an existing line when
    `claim_type` is `MISSING_ITEM`, and is absent when `claim_type` is
    `NEVER_DELIVERED` — otherwise `ERR_LINE_INDEX_INVALID` (422). Applies to
    credit-claim creation."

    PRD §2.10: "The claimed or approved amount does not exceed the order's
    remaining refundable amount, and for a `MISSING_ITEM` claim does not exceed the
    addressed line's base plus that line's rounded tax — otherwise
    `ERR_CLAIM_EXCEEDS_ORDER` (422). Applies to credit-claim creation and to claim
    resolution."

    Design: Corner/validations/credit_claim_line_index_rules_depend_on_claim_type_and_win_over_the_amount_check
    """
    ns = _delivered_two_line_order()
    employee_headers = make_employee_headers(ns.employee["id"])

    def attempt(**overrides):
        return api_client.create_credit_claim(
            create_credit_claim_payload(ns.order["id"], **overrides), employee_headers
        )

    validate_error(
        attempt(claim_type="MISSING_ITEM", claimed_cents=544),
        ApiErrorId.ERR_LINE_INDEX_INVALID,
    )
    validate_error(
        attempt(claim_type="MISSING_ITEM", claimed_cents=544, line_index=7),
        ApiErrorId.ERR_LINE_INDEX_INVALID,
    )
    precedence = validate_error(
        attempt(claim_type="MISSING_ITEM", claimed_cents=9999, line_index=7),
        ApiErrorId.ERR_LINE_INDEX_INVALID,
    )
    assert precedence["error_id"] != ApiErrorId.ERR_CLAIM_EXCEEDS_ORDER.value, (
        "both rules are violated; the earlier rank determines the response"
    )
    validate_error(
        attempt(claim_type="NEVER_DELIVERED", claimed_cents=2381, line_index=0),
        ApiErrorId.ERR_LINE_INDEX_INVALID,
    )
    validate_error(
        attempt(claim_type="MISSING_ITEM", claimed_cents=9999, line_index=1),
        ApiErrorId.ERR_CLAIM_EXCEEDS_ORDER,
    )

    claim = get_success_data(
        attempt(claim_type="MISSING_ITEM", claimed_cents=544, line_index=1)
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["claimed_cents"] == 544
    assert claim["approved_cents"] == 0

    _rows, meta = validate_paginated(
        api_client.list_credit_claims(_DRAFTER, params={"order_id": ns.order["id"]})
    )
    assert meta["total_count"] == 1, "none of the five refusals persisted a row"


def test_group_name_email_dock_label_and_period_month_all_collide():
    """Case is folded on three names and the month is unique per employee.

    PRD §2.10: "An employee group's `name`, an employee's `email`, and a delivery
    location's `label` are each unique within their program, compared
    case-insensitively — otherwise `ERR_DUPLICATE_NAME` (409). Applies to
    employee-group creation, delivery-location creation, and employee enrolment."

    PRD §2.10: "`period_month` is unique per employee — otherwise
    `ERR_DUPLICATE_PERIOD_MONTH` (409). Applies to benefit-period opening."

    Design: Corner/validations/case_insensitive_uniqueness_violations_return_the_duplicate_errors
    """
    ns = setup_program_base()
    employee, _period = add_employee_with_period(ns)

    validate_error(
        api_client.create_employee_group(
            ns.program["id"],
            create_employee_group_payload(name="engineering", headcount_planned=1),
            _PROGRAM,
        ),
        ApiErrorId.ERR_DUPLICATE_NAME,
    )
    validate_error(
        api_client.create_employee(
            {
                "program_id": ns.program["id"],
                "group_id": ns.group["id"],
                "full_name": "Ada Clone",
                "email": "ADA@ACME.TEST",
            },
            _PROGRAM,
        ),
        ApiErrorId.ERR_DUPLICATE_NAME,
    )
    validate_error(
        api_client.create_delivery_location(
            ns.program["id"],
            {"label": "hq lobby", "grid_x_km": 1.0, "grid_y_km": 1.0},
            _PROGRAM,
        ),
        ApiErrorId.ERR_DUPLICATE_NAME,
    )
    validate_error(
        api_client.create_benefit_period(
            create_benefit_period_payload(employee["id"], period_month="2026-08"),
            _PROGRAM,
        ),
        ApiErrorId.ERR_DUPLICATE_PERIOD_MONTH,
    )

    _groups, group_meta = validate_paginated(
        api_client.list_employee_groups(ns.program["id"], _PROGRAM)
    )
    assert group_meta["total_count"] == 1

    docks, dock_meta = validate_paginated(
        api_client.list_delivery_locations(
            ns.program["id"], make_employee_headers(employee["id"])
        )
    )
    assert dock_meta["total_count"] == 1
    assert docks[0]["label"] == "HQ Lobby"


def test_an_order_naming_another_employees_period_is_a_period_employee_mismatch():
    """Both rows exist in the same program, so the defect is the ownership link.

    PRD §2.10: "`benefit_period_id` belongs to `employee_id` — otherwise
    `ERR_PERIOD_EMPLOYEE_MISMATCH` (422). Applies to order drafting."

    Design: Corner/validations/order_pointing_at_another_employees_period_is_a_period_employee_mismatch
    """
    ns = setup_program_base()
    ada, ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Byron", "email": "ada@acme.test"}
    )
    _ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Lovelace", "email": "ben@acme.test"}
    )

    error = validate_error(
        api_client.create_order(
            create_order_payload(
                ada["id"],
                ben_period["id"],
                ns.restaurant["id"],
                ns.location["id"],
                requested_delivery_at=MONDAY_NOON,
            ),
            make_employee_headers(ada["id"]),
        ),
        ApiErrorId.ERR_PERIOD_EMPLOYEE_MISMATCH,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH.value, (
        "both periods sit in the same meal program"
    )

    assert read_period(ada_period["id"])["version"] == 1
    assert read_period(ben_period["id"])["version"] == 1

    _rows, meta = validate_paginated(
        api_client.list_orders(_PROGRAM, params={"benefit_period_id": ben_period["id"]})
    )
    assert meta["total_count"] == 0


def test_a_rollover_predecessor_must_be_closed_and_may_be_consumed_only_once():
    """August must close first, and its carry-forward cents spend exactly once.

    PRD §2.10: "`predecessor_period_id`, when supplied, names a `CLOSED` period of
    the same employee whose `period_month` is strictly earlier — otherwise
    `ERR_PREDECESSOR_NOT_CLOSED` (409). Applies to benefit-period opening."

    PRD §3.3: "The predecessor's `rollover_out_cents` is copied into the new
    period's `rollover_in_cents`; with no predecessor, `rollover_in_cents` is 0."

    Design: Corner/validations/rollover_predecessor_must_be_closed_and_may_only_be_consumed_once
    """
    ns = setup_program_base(
        program_overrides={"rollover_policy": "CAPPED_PCT", "rollover_cap_pct": 0.25}
    )
    employee, august = add_employee_with_period(ns)

    def open_september(month="2026-09"):
        return api_client.create_benefit_period(
            create_benefit_period_payload(
                employee["id"],
                period_month=month,
                predecessor_period_id=august["id"],
            ),
            _PROGRAM,
        )

    validate_error(open_september(), ApiErrorId.ERR_PREDECESSOR_NOT_CLOSED)

    closed = final_close(august["id"])
    assert closed["rollover_out_cents"] == 12500
    assert closed["forfeited_cents"] == 37500

    september = get_success_data(open_september())
    assert september["rollover_in_cents"] == 12500
    assert september["allocated_cents"] == 62500
    assert september["available_cents"] == 62500

    validate_error(
        open_september("2026-10"), ApiErrorId.ERR_PREDECESSOR_ALREADY_CONSUMED
    )

    rows, meta = validate_paginated(
        api_client.list_benefit_periods(
            _PROGRAM, params={"predecessor_period_id": august["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == september["id"]


def test_adding_the_cuisine_to_the_program_turns_the_refusal_into_a_placement():
    """The allow-list is read live at placement, never pinned at draft time.

    PRD §2.10: "The restaurant's `cuisine` is a member of the program's
    `eligible_cuisines` — otherwise `ERR_CUISINE_NOT_ELIGIBLE` (422). Applies to
    placement and group-order creation. This is independent of distance."

    PRD §2.12: "Editing a program's policy selectors mutates the program row —
    bumping its `version` by 1 and refreshing `updated_at` — and recomputes nothing."

    Design: Corner/validations/adding_the_cuisine_to_the_program_turns_the_rejected_place_into_a_success
    """
    ns = setup_program_base(
        restaurant_overrides={
            "name": "Sushi Nine",
            "cuisine": "SUSHI",
            "grid_x_km": 1.0,
            "grid_y_km": 0.0,
            "delivery_radius_km": 12.0,
        }
    )
    employee, period = add_employee_with_period(ns)
    order = draft_order(
        employee,
        period,
        ns.restaurant,
        ns.location,
        requested_delivery_at=MONDAY_NOON,
        lines=[order_line("Nigiri Set", 1000, 1)],
    )

    _before, before_meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"],
            make_employee_headers(employee["id"]),
            params={"delivery_location_id": ns.location["id"]},
        )
    )
    assert before_meta["total_count"] == 0

    validate_error(
        place_order_raw(order, employee, expected_version=1),
        ApiErrorId.ERR_CUISINE_NOT_ELIGIBLE,
    )

    validate_success(
        api_client.patch_meal_program(
            ns.program["id"], {"eligible_cuisines": ["THAI", "SUSHI"]}, _PLATFORM
        )
    )

    after, after_meta = validate_paginated(
        api_client.list_eligible_restaurants(
            ns.program["id"],
            make_employee_headers(employee["id"]),
            params={"delivery_location_id": ns.location["id"]},
        )
    )
    assert after_meta["total_count"] == 1
    assert after[0]["id"] == ns.restaurant["id"]

    placed = validate_success(place_order_raw(order, employee, expected_version=1))
    assert placed["fulfillment_status"] == "PLACED", (
        "version 1 is still current because the refused attempt bumped nothing"
    )
    assert placed["covered_base_cents"] == 1787
    assert placed["employer_covered_cents"] == 1787


def test_a_future_dated_rule_blocks_both_activation_and_the_period_it_would_fund():
    """Nothing is activatable or fundable until the clock reaches September.

    PRD §3.2: "The rule must be in `DRAFT`, or the request is `ERR_INVALID_STATE`;
    the same-person attempt is `ERR_SEGREGATION_OF_DUTIES`; and a rule whose
    `effective_from` is strictly after the current logical clock is not yet
    activatable and is refused with `ERR_RULE_NOT_EFFECTIVE`."

    PRD §2.10: "The employee's group has exactly one budget rule in `ACTIVE`
    status — otherwise `ERR_NO_ACTIVE_BUDGET_RULE` (409). Applies to benefit-period
    opening."

    Design: Corner/validations/a_future_dated_rule_cannot_be_activated_and_a_ruleless_group_cannot_open_a_period
    """
    set_clock("2026-08-01T00:00:00Z")
    program = create_program()
    group = create_group(program["id"], name="Contractors", headcount_planned=1)
    rule = draft_rule(group["id"], effective_from="2026-09-01T00:00:00Z")
    employee = create_employee(
        program["id"], group["id"], full_name="Eve Turing", email="eve@acme.test"
    )

    validate_error(
        api_client.activate_budget_rule(
            rule["id"], {"expected_employee_group_version": 1}, _APPROVER
        ),
        ApiErrorId.ERR_RULE_NOT_EFFECTIVE,
    )
    rows, _meta = validate_paginated(api_client.list_budget_rules(group["id"], _DRAFTER))
    assert rows[0]["status"] == "DRAFT"

    validate_error(
        api_client.create_benefit_period(
            create_benefit_period_payload(employee["id"], period_month="2026-09"),
            _PROGRAM,
        ),
        ApiErrorId.ERR_NO_ACTIVE_BUDGET_RULE,
    )

    set_clock("2026-09-01T00:00:00Z")
    activated = activate_rule(rule["id"], group["id"], expected_employee_group_version=1)
    assert activated["status"] == "ACTIVE"
    assert read_group(group["id"])["version"] == 2

    september = open_period(employee["id"], period_month="2026-09")
    assert september["allocated_cents"] == 50000
    assert september["budget_rule_id"] == rule["id"]


def test_one_live_order_blocks_deactivation_and_the_final_close_alike():
    """Draining first, then the cascade parks the period and locks placement out.

    PRD §3.3: "It is refused with `ERR_EMPLOYEE_HAS_OPEN_ORDERS` while the employee
    still holds any order in `PLACED` or `CONFIRMED`, because a deactivation must
    never orphan a live reservation."

    PRD §2.10: "No order attached to the period is `PLACED` or `CONFIRMED` —
    otherwise `ERR_PERIOD_HAS_OPEN_ORDERS` (409). Applies to period close, and only
    when the requested `mode` is `FINAL`; `mode` `GRACE` is precisely the mechanism
    for draining those orders and is never blocked by this rule."

    PRD §2.10: "The ordering employee is `ACTIVE` — otherwise
    `ERR_EMPLOYEE_INACTIVE` (409). Applies to placement and group-order creation."

    Design: Corner/validations/live_orders_block_deactivation_and_final_close_and_an_inactive_employee_cannot_place
    """
    ns = setup_scenario()
    order = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
        ),
        ns.employee,
    )

    validate_error(
        api_client.deactivate_employee(ns.employee["id"], _PROGRAM),
        ApiErrorId.ERR_EMPLOYEE_HAS_OPEN_ORDERS,
    )
    validate_error(
        api_client.close_benefit_period(ns.period["id"], {"mode": "FINAL"}, _PROGRAM),
        ApiErrorId.ERR_PERIOD_HAS_OPEN_ORDERS,
    )

    cancel_order_as_employee(order, ns.employee)
    deactivated = validate_success(
        api_client.deactivate_employee(ns.employee["id"], _PROGRAM)
    )
    assert deactivated["status"] == "INACTIVE"
    assert read_employee(ns.employee["id"])["status"] == "INACTIVE"

    august = read_period(ns.period["id"])
    assert august["status"] == "GRACE", "the cascade drains the OPEN period"
    assert august["version"] > 1

    september = open_period(ns.employee["id"], period_month="2026-09")
    assert september["status"] == "OPEN"
    error = validate_error(
        place_order_raw(
            draft_order(
                ns.employee,
                september,
                ns.restaurant,
                ns.location,
                requested_delivery_at="2026-09-01T12:00:00Z",
            ),
            ns.employee,
        ),
        ApiErrorId.ERR_EMPLOYEE_INACTIVE,
    )
    assert error["error_id"] != ApiErrorId.ERR_PERIOD_NOT_OPEN.value, (
        "the September period is OPEN; it is the employee that is INACTIVE"
    )


def test_the_group_checks_cover_emptiness_mismatch_the_limit_and_the_lock():
    """Four different group refusals, then the one order that satisfies them all.

    PRD §3.6: "A lock requires at least one attached member order; locking an
    empty group order is `ERR_GROUP_ORDER_EMPTY`."

    PRD §2.10: "A member order's `restaurant_id` and `delivery_location_id` equal
    the group order's — otherwise `ERR_GROUP_ORDER_MISMATCH` (422). Applies to order
    drafting."

    PRD §2.10: "A member order's pre-fee base is within the group order's
    `per_person_limit_cents` — otherwise `ERR_PER_PERSON_LIMIT_EXCEEDED` (422).
    Applies to placement."

    PRD §2.10: "The referenced group order is `COLLECTING` — otherwise
    `ERR_GROUP_ORDER_NOT_COLLECTING` (409). Applies to order drafting and placement."

    Design: Corner/validations/group_membership_validations_cover_mismatch_emptiness_and_the_per_person_limit
    """
    ns = setup_program_base(
        clock="2026-08-03T09:00:00Z",
        program_overrides={"eligible_cuisines": ["THAI", "SALAD"]},
        rule_overrides={"daily_meal_limit": 3},
    )
    salad_mid = create_restaurant(
        name="Salad Mid",
        cuisine="SALAD",
        grid_x_km=6.0,
        grid_y_km=0.0,
        delivery_radius_km=12.0,
    )
    ada, ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Byron", "email": "ada@acme.test"}
    )
    ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Lovelace", "email": "ben@acme.test"}
    )
    group_order = create_group_order(ns, ada)
    ada_headers = make_employee_headers(ada["id"])

    validate_error(
        api_client.lock_group_order(group_order["id"], ada_headers),
        ApiErrorId.ERR_GROUP_ORDER_EMPTY,
    )

    validate_error(
        api_client.create_order(
            create_order_payload(
                ada["id"],
                ada_period["id"],
                salad_mid["id"],
                ns.location["id"],
                requested_delivery_at="2026-08-03T12:00:00Z",
                lines=[order_line("Cobb Salad", 1000, 1)],
                group_order_id=group_order["id"],
            ),
            ada_headers,
        ),
        ApiErrorId.ERR_GROUP_ORDER_MISMATCH,
    )

    oversized = draft_order(
        ada,
        ada_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T12:00:00Z",
        lines=[order_line("Banquet Tray", 5013, 1)],
        group_order_id=group_order["id"],
    )
    validate_error(
        place_order_raw(oversized, ada), ApiErrorId.ERR_PER_PERSON_LIMIT_EXCEEDED
    )
    assert read_order(oversized["id"])["fulfillment_status"] == "DRAFT"

    member = place_order(
        draft_order(
            ada,
            ada_period,
            ns.restaurant,
            ns.location,
            requested_delivery_at="2026-08-03T12:00:00Z",
            group_order_id=group_order["id"],
        ),
        ada,
    )
    assert member["fulfillment_status"] == "PLACED"
    assert read_group_order(group_order["id"])["member_order_count"] == 1

    locked = validate_success(
        api_client.lock_group_order(group_order["id"], ada_headers)
    )
    assert locked["status"] == "LOCKED"

    validate_error(
        api_client.create_order(
            create_order_payload(
                ben["id"],
                ben_period["id"],
                ns.restaurant["id"],
                ns.location["id"],
                requested_delivery_at="2026-08-03T12:00:00Z",
                group_order_id=group_order["id"],
            ),
            make_employee_headers(ben["id"]),
        ),
        ApiErrorId.ERR_GROUP_ORDER_NOT_COLLECTING,
    )

    rows, _meta = validate_paginated(
        api_client.list_group_orders(_PROGRAM, params={"program_id": ns.program["id"]})
    )
    locked_rows = [row for row in rows if row["status"] == "LOCKED"]
    assert len(locked_rows) == 1
    assert locked_rows[0]["id"] == group_order["id"]
    assert locked_rows[0]["member_order_count"] == 1


def test_an_overage_with_no_card_on_file_is_the_only_payment_required_answer():
    """The 2,250-cent remainder is permitted by policy but has no instrument.

    PRD §3.5: "Last, if `employee_card_cents` is positive and the employee's
    `personal_card_on_file` is false, the placement is refused with
    `ERR_PERSONAL_CARD_REQUIRED`, which is the only condition in this system
    answered with HTTP 402."

    PRD §3.3: "A `ProgramAdmin` enrols an employee by supplying `program_id`,
    `group_id`, `full_name`, and `email`, plus an optional `personal_card_on_file`
    flag that defaults to false."

    Design: Corner/validations/an_overage_without_a_card_on_file_is_payment_required
    """
    ns = setup_program_base(rule_overrides={"overage_policy": "PERSONAL_CARD"})
    employee = get_success_data(
        api_client.create_employee(
            {
                "program_id": ns.program["id"],
                "group_id": ns.group["id"],
                "full_name": "Fay Hamilton",
                "email": "fay@acme.test",
            },
            _PROGRAM,
        )
    )
    assert employee["personal_card_on_file"] is False
    period = open_period(employee["id"])

    order = draft_order(
        employee,
        period,
        ns.restaurant,
        ns.location,
        requested_delivery_at=MONDAY_NOON,
        lines=[order_line("Family Curry", 2000, 2)],
    )
    error = validate_error(
        place_order_raw(order, employee), ApiErrorId.ERR_PERSONAL_CARD_REQUIRED
    )
    assert error["error_id"] != ApiErrorId.ERR_OVERAGE_NOT_PERMITTED.value, (
        "the pinned overage_policy is PERSONAL_CARD, so the remainder is legal"
    )

    assert read_order(order["id"])["fulfillment_status"] == "DRAFT"
    refreshed = read_period(period["id"])
    assert refreshed["reserved_cents"] == 0
    assert refreshed["version"] == 1
