"""Declared defaults, system fields, request-shape refusals and scoped reads."""

from test_helpers import (
    CONTROLLER_DRAFTER_ID,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    activate_rule,
    add_employee_with_period,
    api_client,
    assert_benefit_period,
    assert_employee_group,
    assert_meal_program,
    assert_refund_ledger_entry,
    assert_restaurant,
    cancel_order_as_employee,
    create_budget_rule_payload,
    create_employee_group_payload,
    create_group,
    create_location,
    create_order_payload,
    create_program,
    create_restaurant,
    draft_rule,
    get_success_data,
    is_valid_uuid,
    make_employee_headers,
    read_group,
    read_order,
    read_order_refund_entries,
    read_period,
    setup_placed_order,
    setup_program_base,
    setup_scenario,
    validate_error,
    validate_paginated,
)

_PLATFORM = TEST_USERS["platform_admin_headers"]
_PROGRAM = TEST_USERS["program_admin_headers"]
_DRAFTER = TEST_USERS["controller_drafter_headers"]
_CLOCK_PREFIX = DEFAULT_CLOCK[:-1]


def test_a_program_created_with_only_its_required_fields_takes_every_default():
    """Five omitted policy selectors materialise at their declared values.

    PRD §3.1: "`max_delivery_radius_km` is the program-wide radius ceiling in
    kilometres, measured from the delivery dock; it is optional, defaults to 8.0,
    and must be greater than 0 and at most 50.0."

    PRD §3.1: "At creation, the three program rollups `program_spent_cents`,
    `program_reserved_cents`, and `mtd_employer_captured_cents` all start at 0."

    Design: Corner/entities/create_meal_program_applies_declared_defaults_for_omitted_optionals
    """
    program = create_program(eligible_cuisines=["THAI", "SALAD", "PIZZA"])
    assert_meal_program(program)

    assert program["employer_name"] == "Acme Corp"
    assert program["billing_account_ref"] == "ACCT-ACME-1"
    assert program["eligible_cuisines"] == ["THAI", "SALAD", "PIZZA"]

    assert program["max_delivery_radius_km"] == 8.0
    assert program["taxable_benefit_method"] == "DE_MINIMIS_EXCLUSION"
    assert program["rollover_policy"] == "CAPPED_PCT"
    assert program["rollover_cap_pct"] == 0.25
    assert program["forecast_basis"] == "COMMITMENT"

    assert program["program_spent_cents"] == 0
    assert program["program_reserved_cents"] == 0
    assert program["mtd_employer_captured_cents"] == 0

    assert program["version"] == 1
    assert program["created_at"].startswith(_CLOCK_PREFIX), (
        "created_at is stamped from the logical clock, which starts at "
        f"{DEFAULT_CLOCK}"
    )


def test_a_new_restaurant_is_eligible_with_a_concurrency_ceiling_of_one():
    """Registration mints the identity fields and the two declared defaults.

    PRD §3.1: "`max_concurrent_group_deliveries` bounds how many submitted group
    orders may have overlapping delivery windows at that restaurant; it is
    optional, defaults to 1, and must be at least 1. A restaurant is created
    `ELIGIBLE` and a `PlatformAdmin` may cycle it between `ELIGIBLE` and
    `SUSPENDED` at will by writing the desired `status`."

    Design: Corner/entities/create_restaurant_returns_system_fields_and_initial_eligible_status
    """
    restaurant = create_restaurant()
    assert_restaurant(restaurant)

    assert restaurant["name"] == "Thai Garden"
    assert restaurant["cuisine"] == "THAI"
    assert restaurant["grid_x_km"] == 3.0
    assert restaurant["grid_y_km"] == 4.0
    assert restaurant["delivery_radius_km"] == 10.0

    assert restaurant["status"] == "ELIGIBLE"
    assert restaurant["max_concurrent_group_deliveries"] == 1

    assert is_valid_uuid(restaurant["id"]), "the id is a server-minted UUID"
    assert restaurant["version"] == 1
    assert restaurant["created_at"] == restaurant["updated_at"]
    assert restaurant["created_at"].startswith(_CLOCK_PREFIX)


def test_a_program_without_a_billing_account_reference_is_refused():
    """A missing required field is a request-shape violation, not a 422.

    PRD §2.10: "Request shape: required fields present, declared types, enum
    domains, numeric ranges, array cardinalities, and pagination bounds —
    otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/entities/create_meal_program_without_billing_account_ref_is_invalid_request
    """
    response = api_client.create_meal_program(
        {"employer_name": "Acme Corp", "eligible_cuisines": ["THAI"]}, _PLATFORM
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value
    assert isinstance(error["message"], str) and error["message"]


def test_a_budget_rule_draft_without_eligible_weekdays_is_refused():
    """The weekday array is required, so its absence is a 400 before any state.

    PRD §3.2: "Eligibility is fixed by `eligible_weekdays`, a non-empty array of
    distinct ISO weekday numbers drawn from 1 through 7, together with
    `eligible_window_start_minute` and `eligible_window_end_minute`, both
    expressed as minutes from UTC midnight."

    Design: Corner/entities/create_budget_rule_without_eligible_weekdays_is_invalid_request
    """
    program = create_program()
    group = create_group(program["id"])

    payload = create_budget_rule_payload()
    payload.pop("eligible_weekdays")
    response = api_client.create_budget_rule(group["id"], payload, _DRAFTER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    refreshed = read_group(group["id"])
    assert refreshed["active_rule_count"] == 0
    assert refreshed["version"] == 1, "a refused draft mutates nothing"

    rows, meta = validate_paginated(api_client.list_budget_rules(group["id"], _DRAFTER))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_budget_rule_draft_with_an_unknown_overage_policy_is_refused():
    """`overage_policy` has exactly two declared members.

    PRD §3.2: "`overage_policy` decides what happens when an order's covered base
    outruns the per-meal cap: it defaults to `PERSONAL_CARD`, meaning the
    remainder is collected from the employee, and may instead be `BLOCK`, meaning
    such an order is simply refused."

    Design: Corner/entities/create_budget_rule_with_unknown_overage_policy_is_invalid_request
    """
    program = create_program()
    group = create_group(program["id"])

    payload = create_budget_rule_payload(overage_policy="DEDUCT_FROM_PAYROLL")
    response = api_client.create_budget_rule(group["id"], payload, _DRAFTER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api_client.list_budget_rules(group["id"], _DRAFTER))
    assert meta["total_count"] == 0, "an unknown enum member persists no row"
    assert rows == []
    assert read_group(group["id"])["active_rule_count"] == 0


def test_a_budget_rule_window_ending_past_midnight_minute_1440_is_refused():
    """1,500 minutes from UTC midnight is outside the declared numeric range.

    PRD §3.2: "The start minute must be at least 0 and at most 1440; the end
    minute must be strictly greater than the start minute and at most 1440."

    Design: Corner/entities/create_budget_rule_with_window_end_minute_above_1440_is_invalid_request
    """
    program = create_program()
    group = create_group(program["id"])

    payload = create_budget_rule_payload(
        eligible_window_start_minute=660, eligible_window_end_minute=1500
    )
    response = api_client.create_budget_rule(group["id"], payload, _DRAFTER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(api_client.list_budget_rules(group["id"], _DRAFTER))
    assert meta["total_count"] == 0


def test_an_order_drafted_with_an_empty_lines_array_is_refused():
    """Zero lines fails the array cardinality check at rank 5.

    PRD §2.10: "This covers a missing required field, an unknown enum member,
    negative cents, an empty `lines` array, a `lines` array longer than 20
    elements, and a `limit` outside 1 through 100."

    Design: Corner/entities/create_order_with_empty_lines_array_is_invalid_request
    """
    ns = setup_scenario()
    payload = create_order_payload(
        ns.employee["id"],
        ns.period["id"],
        ns.restaurant["id"],
        ns.location["id"],
        lines=[],
    )
    response = api_client.create_order(
        payload, make_employee_headers(ns.employee["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api_client.list_orders(_PROGRAM, params={"employee_id": ns.employee["id"]})
    )
    assert meta["total_count"] == 0, "no order row survives a shape violation"


def test_the_group_active_rule_counter_moves_only_when_a_rule_is_activated():
    """`active_rule_count` is derived from activation, never supplied as input.

    PRD §3.1: "A newly created group has `active_rule_count` of 0; that counter
    tracks how many of the group's budget rules are currently `ACTIVE` and is
    invariantly either 0 or 1."

    Design: Corner/entities/employee_group_active_rule_count_is_derived_from_activation_not_input
    """
    program = create_program()
    group = create_group(program["id"])
    assert_employee_group(group)

    before = read_group(group["id"])
    assert before["active_rule_count"] == 0
    assert before["version"] == 1
    assert before["name"] == "Engineering"
    assert before["program_id"] == program["id"]

    rule = draft_rule(group["id"])
    assert rule["status"] == "DRAFT"
    assert rule["drafted_by_user_id"] == CONTROLLER_DRAFTER_ID
    assert read_group(group["id"])["active_rule_count"] == 0, (
        "a DRAFT rule is not an ACTIVE one"
    )

    activated = activate_rule(rule["id"], group["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["rule_sequence"] == 1

    after = read_group(group["id"])
    assert after["active_rule_count"] == 1
    assert after["version"] == 2, "a successful activation increments the group version"


def test_a_refund_ledger_entry_exposes_no_version_and_no_updated_at():
    """The void writes one immutable row and no mutable system fields.

    PRD §2.4: "The single exception is `RefundLedgerEntry`, which is append-only
    and immutable. A refund ledger entry carries only `id` and `created_at`; it has
    no `updated_at` and no `version`, and once written it is never altered or
    deleted."

    Design: Corner/entities/refund_ledger_entry_is_append_only_with_no_version_or_update_endpoint
    """
    ns = setup_placed_order()
    assert ns.order["employer_covered_cents"] == 1787
    assert ns.order["employee_card_cents"] == 0

    cancelled = cancel_order_as_employee(ns.order, ns.employee)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOIDED"

    entries = read_order_refund_entries(ns.order["id"])
    assert len(entries) == 1, f"only the employer side moved, got {entries}"
    entry = entries[0]
    assert_refund_ledger_entry(entry)
    assert entry["direction"] == "EMPLOYER_CREDIT"
    assert entry["amount_cents"] == 1787
    assert entry["reason"] == "ORDER_VOID"
    assert entry.get("credit_claim_id") is None
    assert entry["order_id"] == ns.order["id"]
    assert "version" not in entry
    assert "updated_at" not in entry

    voided = read_order(ns.order["id"])
    assert voided["net_charged_cents"] == 0
    assert voided["admin_fee_cents"] == 0


def test_reading_a_benefit_period_returns_its_pinned_rule_and_opening_partition():
    """The allocation opens wholly available with the other four buckets at 0.

    PRD §3.3: "The period's `allocated_cents` is then the pinned rule's
    `monthly_allocation_cents` plus `rollover_in_cents`, and `available_cents` opens
    at that same figure, with `reserved_cents`, `spent_cents`, `forfeited_cents`,
    and `rollover_out_cents` all at 0."

    Design: Corner/entities/get_benefit_period_by_id_returns_the_stored_allocation_row
    """
    ns = setup_scenario()
    period = read_period(ns.period["id"])
    assert_benefit_period(period)

    assert period["status"] == "OPEN"
    assert period["period_month"] == "2026-08"
    assert period["employee_id"] == ns.employee["id"]
    assert period["budget_rule_id"] == ns.rule["id"], (
        "the rule is pinned at the moment the period is opened"
    )
    assert period.get("predecessor_period_id") is None

    assert period["allocated_cents"] == 50000
    assert period["rollover_in_cents"] == 0
    assert period["available_cents"] == 50000
    assert period["reserved_cents"] == 0
    assert period["spent_cents"] == 0
    assert period["forfeited_cents"] == 0
    assert period["rollover_out_cents"] == 0


def test_the_employee_listing_pages_with_limit_offset_total_count_and_has_more():
    """Three enrolments read back as a 2-then-1 page over a stable total.

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the number of items
    matching the filters before pagination is applied and `has_more` indicates
    whether items remain beyond the current page."

    PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, its
    minimum accepted value is 1, and its maximum accepted value is 100. A `limit`
    below 1 or above 100 is a request-shape violation and yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/list_employees_honours_limit_offset_total_count_and_has_more
    """
    ns = setup_program_base()
    for full_name, email in (
        ("Ada Byron", "ada@acme.test"),
        ("Ben Lovelace", "ben@acme.test"),
        ("Cleo Hopper", "cleo@acme.test"),
    ):
        get_success_data(
            api_client.create_employee(
                {
                    "program_id": ns.program["id"],
                    "group_id": ns.group["id"],
                    "full_name": full_name,
                    "email": email,
                },
                _PROGRAM,
            )
        )

    first_page, first_meta = validate_paginated(
        api_client.list_employees(_PROGRAM, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_employees(_PROGRAM, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    for row in first_page + second_page:
        assert row["personal_card_on_file"] is False, (
            "the flag is optional and defaults to false"
        )
        assert row["tax_treatment_flag"] == "NONE"
        assert row["status"] == "ACTIVE"
        assert row["ytd_imputed_cents"] == 0

    validate_error(
        api_client.list_employees(_PROGRAM, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_reading_an_unknown_order_returns_its_own_not_found_code_and_an_envelope():
    """A 404 still carries the standard error `meta` block.

    PRD §2.10: "The entity addressed by an `{id}` path segment exists — otherwise
    the entity-specific 404: `ERR_MEAL_PROGRAM_NOT_FOUND`,
    `ERR_EMPLOYEE_GROUP_NOT_FOUND`, `ERR_BUDGET_RULE_NOT_FOUND`,
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_BENEFIT_PERIOD_NOT_FOUND`,
    `ERR_RESTAURANT_NOT_FOUND`, `ERR_DELIVERY_LOCATION_NOT_FOUND`,
    `ERR_GROUP_ORDER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_CREDIT_CLAIM_NOT_FOUND`, or `ERR_EXPENSE_EXPORT_NOT_FOUND`."

    Design: Corner/entities/get_order_with_unknown_id_returns_order_not_found
    """
    response = api_client.get_order(NON_EXISTENT_UUID, _PROGRAM)
    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND)
    assert error["error_id"] == ApiErrorId.ERR_ORDER_NOT_FOUND.value

    body = response.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_an_unknown_parent_program_wins_over_a_malformed_child_body():
    """The path identifier is resolved before any child-level validation runs.

    PRD §2.11: "Path identifiers are resolved strictly left to right, and the
    first identifier that fails to resolve determines the 404 that comes back. A
    request for the budget rules of a non-existent employee group returns
    `ERR_EMPLOYEE_GROUP_NOT_FOUND`; the server never proceeds to look for rules.
    The same precedence holds for creation: the parent must exist before any
    child-level validation runs."

    Design: Corner/entities/create_employee_group_under_unknown_program_returns_meal_program_not_found
    """
    valid_body = create_employee_group_payload()
    validate_error(
        api_client.create_employee_group(NON_EXISTENT_UUID, valid_body, _PROGRAM),
        ApiErrorId.ERR_MEAL_PROGRAM_NOT_FOUND,
    )

    nameless = create_employee_group_payload()
    nameless.pop("name")
    error = validate_error(
        api_client.create_employee_group(NON_EXISTENT_UUID, nameless, _PROGRAM),
        ApiErrorId.ERR_MEAL_PROGRAM_NOT_FOUND,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "the missing parent is reported even though the body is also invalid"
    )


def test_an_order_naming_another_programs_dock_is_a_program_scope_mismatch():
    """A cross-tenant reference is referential, not a not-found.

    PRD §2.11: "Because orders, group orders, benefit periods, and employees are
    all peer resources at the root, a request that mixes rows from two different
    meal programs is a referential error, not a not-found: it yields
    `ERR_PROGRAM_SCOPE_MISMATCH`."

    Design: Corner/entities/order_referencing_another_programs_delivery_location_is_program_scope_mismatch
    """
    ns = setup_program_base()
    ns.employee, ns.period = add_employee_with_period(ns)

    rival_program = create_program(
        employer_name="Globex Corp", billing_account_ref="ACCT-GLOBEX-1"
    )
    rival_dock = create_location(rival_program["id"], label="Rival Dock")

    payload = create_order_payload(
        ns.employee["id"],
        ns.period["id"],
        ns.restaurant["id"],
        rival_dock["id"],
    )
    error = validate_error(
        api_client.create_order(payload, make_employee_headers(ns.employee["id"])),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
    )
    assert error["error_id"] != ApiErrorId.ERR_DELIVERY_LOCATION_NOT_FOUND.value, (
        "the dock exists; it simply belongs to another program"
    )

    _rows, meta = validate_paginated(
        api_client.list_orders(_PROGRAM, params={"employee_id": ns.employee["id"]})
    )
    assert meta["total_count"] == 0
