"""Not-found codes, the failure envelope, role gates and the four-eyes controls."""

from test_helpers import (
    CONTROLLER_DRAFTER_ID,
    CONTROLLER_RESOLVER_ID,
    TEST_USERS,
    ApiErrorId,
    add_employee_with_period,
    api_client,
    create_benefit_period_payload,
    create_budget_rule_payload,
    create_employee_payload,
    create_group,
    create_meal_program_payload,
    create_program,
    create_restaurant_payload,
    draft_order,
    draft_rule,
    get_success_data,
    make_controller_headers,
    make_employee_headers,
    make_restaurant_headers,
    place_order,
    raise_claim,
    read_claim,
    read_claim_refund_entries,
    read_group,
    read_order,
    read_period,
    resolve_claim,
    settle_claim,
    setup_delivered_order,
    setup_placed_order,
    setup_program_base,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLATFORM = TEST_USERS["platform_admin_headers"]
_PROGRAM = TEST_USERS["program_admin_headers"]
_DRAFTER = TEST_USERS["controller_drafter_headers"]
_APPROVER = TEST_USERS["controller_approver_headers"]

_MISSING = {
    "group": "00000000-0000-4000-8000-000000000001",
    "rule": "00000000-0000-4000-8000-000000000002",
    "employee": "00000000-0000-4000-8000-000000000003",
    "period": "00000000-0000-4000-8000-000000000004",
    "restaurant": "00000000-0000-4000-8000-000000000005",
    "dock": "00000000-0000-4000-8000-000000000006",
    "group_order": "00000000-0000-4000-8000-000000000007",
    "claim": "00000000-0000-4000-8000-000000000008",
    "export": "00000000-0000-4000-8000-000000000009",
    "program": "00000000-0000-4000-8000-00000000000a",
}


def test_each_path_identifier_reports_its_own_entity_specific_not_found_code():
    """Ten unresolvable identifiers yield ten different 404 codes.

    PRD §2.10: "The entity addressed by an `{id}` path segment exists — otherwise
    the entity-specific 404: `ERR_MEAL_PROGRAM_NOT_FOUND`,
    `ERR_EMPLOYEE_GROUP_NOT_FOUND`, `ERR_BUDGET_RULE_NOT_FOUND`,
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_BENEFIT_PERIOD_NOT_FOUND`,
    `ERR_RESTAURANT_NOT_FOUND`, `ERR_DELIVERY_LOCATION_NOT_FOUND`,
    `ERR_GROUP_ORDER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_CREDIT_CLAIM_NOT_FOUND`, or `ERR_EXPENSE_EXPORT_NOT_FOUND`."

    PRD §3.4: "When nothing qualifies, the answer is a successful empty array with
    `total_count` of 0 — an empty result is not a not-found."

    Design: Corner/errors/every_path_id_not_found_error_is_triggerable_with_its_own_code
    """
    program = create_program()
    group = create_group(program["id"])

    validate_error(
        api_client.get_employee_group(_MISSING["group"], _PROGRAM),
        ApiErrorId.ERR_EMPLOYEE_GROUP_NOT_FOUND,
    )
    validate_error(
        api_client.activate_budget_rule(
            _MISSING["rule"], {"expected_employee_group_version": 1}, _APPROVER
        ),
        ApiErrorId.ERR_BUDGET_RULE_NOT_FOUND,
    )
    validate_error(
        api_client.get_employee(_MISSING["employee"], _PROGRAM),
        ApiErrorId.ERR_EMPLOYEE_NOT_FOUND,
    )
    validate_error(
        api_client.get_benefit_period(_MISSING["period"], _PROGRAM),
        ApiErrorId.ERR_BENEFIT_PERIOD_NOT_FOUND,
    )
    validate_error(
        api_client.get_restaurant(_MISSING["restaurant"], _PLATFORM),
        ApiErrorId.ERR_RESTAURANT_NOT_FOUND,
    )
    validate_error(
        api_client.list_eligible_restaurants(
            program["id"], _PROGRAM, params={"delivery_location_id": _MISSING["dock"]}
        ),
        ApiErrorId.ERR_DELIVERY_LOCATION_NOT_FOUND,
    )
    validate_error(
        api_client.get_group_order(_MISSING["group_order"], _PROGRAM),
        ApiErrorId.ERR_GROUP_ORDER_NOT_FOUND,
    )
    validate_error(
        api_client.get_credit_claim(_MISSING["claim"], _PROGRAM),
        ApiErrorId.ERR_CREDIT_CLAIM_NOT_FOUND,
    )
    validate_error(
        api_client.acknowledge_expense_export(_MISSING["export"], _DRAFTER),
        ApiErrorId.ERR_EXPENSE_EXPORT_NOT_FOUND,
    )
    validate_error(
        api_client.list_employee_groups(_MISSING["program"], _PROGRAM),
        ApiErrorId.ERR_MEAL_PROGRAM_NOT_FOUND,
    )

    refreshed = read_group(group["id"])
    assert refreshed["version"] == 1, "ten refusals mutated nothing"
    assert refreshed["active_rule_count"] == 0


def test_every_failure_carries_the_same_two_field_envelope_and_request_meta():
    """A 400 and a 404 are shaped identically, and the success is a 201 object.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    PRD §4: "Endpoints that create a new resource return HTTP 201; endpoints that
    read or modify an existing resource return HTTP 200."

    Design: Corner/errors/every_failure_uses_the_same_error_envelope_with_a_machine_readable_id
    """
    incomplete = create_meal_program_payload()
    incomplete.pop("billing_account_ref")
    bad_request = api_client.create_meal_program(incomplete, _PLATFORM)
    validate_error(bad_request, ApiErrorId.ERR_INVALID_REQUEST)

    not_found = api_client.get_meal_program(
        "00000000-0000-4000-8000-00000000000b", _PLATFORM
    )
    validate_error(not_found, ApiErrorId.ERR_MEAL_PROGRAM_NOT_FOUND)

    for response in (bad_request, not_found):
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}, (
            f"an error body carries nothing else, got {sorted(body['data'])}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    created = api_client.create_meal_program(create_meal_program_payload(), _PLATFORM)
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["response_type"] == "object"
    assert created_body["data"]["id"]


def test_a_role_outside_the_admitted_set_is_403_while_a_missing_identity_is_401():
    """Six cross-role writes are refused, and the anonymous call fails earlier.

    PRD §2.1: "Once identity is established, the declared role is checked against
    the set of roles the target endpoint admits; a caller whose role is not admitted
    receives `ERR_UNAUTHORIZED` (HTTP 403), and this happens even when the request
    body is malformed, so an unauthorised caller never learns whether their payload
    would have been accepted."

    PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of
    the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before the request body is even parsed."

    Design: Corner/rbac/another_roles_exclusive_operation_is_unauthorized_and_a_missing_identity_is_401
    """
    ns = setup_placed_order()
    employee_headers = make_employee_headers(ns.employee["id"])

    validate_error(
        api_client.create_restaurant(create_restaurant_payload(name="Rogue"), _PROGRAM),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_employee(
            create_employee_payload(
                ns.program["id"], ns.group["id"], email="rogue@acme.test"
            ),
            _PLATFORM,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_budget_rule(
            ns.group["id"], create_budget_rule_payload(), _PROGRAM
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_benefit_period(
            create_benefit_period_payload(ns.employee["id"], period_month="2026-09"),
            _DRAFTER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.close_benefit_period(
            ns.period["id"], {"mode": "FINAL"}, employee_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.confirm_order(ns.order["id"], _PROGRAM),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    validate_error(
        api_client.create_restaurant(create_restaurant_payload(name="Rogue"), {}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    _rows, employee_meta = validate_paginated(api_client.list_employees(_PROGRAM))
    assert employee_meta["total_count"] == 1, "no rogue enrolment landed"

    rules, rule_meta = validate_paginated(
        api_client.list_budget_rules(ns.group["id"], _DRAFTER)
    )
    assert rule_meta["total_count"] == 1
    assert rules[0]["status"] == "ACTIVE"

    assert read_period(ns.period["id"])["status"] == "OPEN"
    assert read_order(ns.order["id"])["fulfillment_status"] == "PLACED"


def test_a_shared_read_admits_four_roles_but_only_the_owning_employee():
    """Every declared role reads the order; the colleague gets a 403 instead.

    PRD §2.1: "A caller whose role is correct but whose target row belongs to
    somebody else is a different failure from an unauthorised role, and it carries a
    different code: `ERR_FORBIDDEN_RESOURCE` (HTTP 403). This ownership scoping
    guards twelve operations: drafting an order, placing an order, cancelling an
    order, confirming an order, delivering an order, locking a group order, reopening
    a group order, submitting a group order, cancelling a group order, creating a
    credit claim, reading a single order, and reading a single employee."

    PRD §2.1: "Once identity is established, the declared role is checked against
    the set of roles the target endpoint admits; a caller whose role is not admitted
    receives `ERR_UNAUTHORIZED` (HTTP 403), and this happens even when the request
    body is malformed, so an unauthorised caller never learns whether their payload
    would have been accepted."

    Design: Corner/rbac/shared_reads_serve_every_declared_role_but_stay_scoped_to_the_owning_employee
    """
    ns = setup_program_base()
    ada, ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ben, _ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    order = place_order(
        draft_order(ada, ada_period, ns.restaurant, ns.location), ada
    )

    for headers in (
        _PROGRAM,
        _DRAFTER,
        make_restaurant_headers(ns.restaurant["id"]),
        make_employee_headers(ada["id"]),
    ):
        seen = validate_success(api_client.get_order(order["id"], headers))
        assert seen["id"] == order["id"]
        assert seen["employer_covered_cents"] == 1787

    validate_error(
        api_client.get_order(order["id"], make_employee_headers(ben["id"])),
        ApiErrorId.ERR_FORBIDDEN_RESOURCE,
    )
    validate_error(
        api_client.get_employee(ada["id"], make_employee_headers(ben["id"])),
        ApiErrorId.ERR_FORBIDDEN_RESOURCE,
    )

    forbidden_role = validate_error(
        api_client.list_order_refund_entries(
            order["id"], make_restaurant_headers(ns.restaurant["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert forbidden_role["error_id"] != ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, (
        "the ledger listing does not admit the restaurant role at all"
    )

    _rows, meta = validate_paginated(
        api_client.list_orders(
            make_employee_headers(ben["id"]), params={"employee_id": ben["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_same_person_cannot_take_both_halves_of_a_money_decision():
    """The drafter cannot activate and the resolver cannot settle.

    PRD §2.9: "Drafting a budget rule records the drafter's `X-User-ID` as
    `drafted_by_user_id`; activating that rule requires a caller whose `X-User-ID`
    differs from the recorded drafter. Resolving a credit claim records the resolver's
    `X-User-ID` as `resolved_by_user_id`; settling that claim requires a caller whose
    `X-User-ID` differs from the recorded resolver. In both cases a same-user attempt
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409), and that check runs
    before the request body is validated so a four-eyes violation cannot be masked
    behind a payload error."

    PRD §3.8: "The order's settlement dimension advances according to how much of
    the order has now been refunded. When the cumulative refund after this settlement
    — `employer_refunded_cents` plus `employee_refunded_cents` plus the newly approved
    amount — remains strictly below `gross_total_cents`, the order moves `CAPTURED →
    PARTIALLY_REFUNDED`; a further such settlement keeps it at
    `PARTIALLY_REFUNDED`, with the ledger simply accumulating."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_from_both_halves_of_a_money_decision
    """
    ns = setup_delivered_order()
    assert ns.order["employer_covered_cents"] == 1787
    assert ns.order["employee_card_cents"] == 0
    assert ns.rule["drafted_by_user_id"] == CONTROLLER_DRAFTER_ID

    second_rule = draft_rule(ns.group["id"], monthly_allocation_cents=60000)
    group_version = read_group(ns.group["id"])["version"]

    validate_error(
        api_client.activate_budget_rule(
            second_rule["id"],
            {"expected_employee_group_version": group_version},
            _DRAFTER,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    still_draft, _meta = validate_paginated(
        api_client.list_budget_rules(ns.group["id"], _DRAFTER)
    )
    assert {row["id"]: row["status"] for row in still_draft}[second_rule["id"]] == "DRAFT"

    activated = get_success_data(
        api_client.activate_budget_rule(
            second_rule["id"],
            {"expected_employee_group_version": group_version},
            _APPROVER,
        )
    )
    assert activated["status"] == "ACTIVE", "the refusal was about identity, not state"
    rules, _meta = validate_paginated(
        api_client.list_budget_rules(ns.group["id"], _DRAFTER)
    )
    assert {row["id"]: row["status"] for row in rules}[ns.rule["id"]] == "SUPERSEDED"

    claim = raise_claim(
        ns.order,
        ns.employee,
        claim_type="MISSING_ITEM",
        line_index=0,
        claimed_cents=1088,
    )
    resolved = resolve_claim(claim, ns.order["id"], approved_cents=1088)
    assert resolved["status"] == "ROUTED_EMPLOYEE_FIRST"
    assert resolved["employee_refund_cents"] == 0
    assert resolved["employer_credit_cents"] == 1088
    assert resolved["resolved_by_user_id"] == CONTROLLER_RESOLVER_ID

    validate_error(
        api_client.settle_credit_claim(
            claim["id"], make_controller_headers(CONTROLLER_RESOLVER_ID)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    assert read_claim(claim["id"])["status"] == "ROUTED_EMPLOYEE_FIRST"
    assert read_claim_refund_entries(claim["id"]) == [], "no row was written"

    settled = settle_claim(claim)
    assert settled["status"] == "SETTLED"
    assert read_order(ns.order["id"])["settlement_status"] == "PARTIALLY_REFUNDED"

    entries = read_claim_refund_entries(claim["id"])
    assert len(entries) == 1
    assert entries[0]["direction"] == "EMPLOYER_CREDIT"
    assert entries[0]["amount_cents"] == 1088
    assert entries[0]["reason"] == "CLAIM_SETTLEMENT"
