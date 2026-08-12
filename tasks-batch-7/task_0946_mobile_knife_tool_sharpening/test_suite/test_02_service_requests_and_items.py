"""Opening a visit, pricing its blades and the two write gates that guard it."""
from test_helpers import (
    ApiErrorId, UNKNOWN_UUID_3, UNKNOWN_UUID_4, ADMIN, CLERK,
    api_client, add_item, create_account, create_chef_knife_spec, create_plan_tier,
    create_service_request, create_subscription, find_draft_invoice, issue_invoice,
    make_account_owner_headers, read_account, read_request,
    validate_error, validate_paginated, validate_success,
    assert_request_item, assert_service_request,
)


def test_fresh_service_request_reads_back_on_both_axes():
    """PRD 3.3: "The request is born in `status` `DRAFT` and `billing_status` `UNBILLED`,
    with `item_count` and both money totals at 0."
    PRD 3.3: "The `priority` is `STANDARD` unless the customer asks for `RUSH`, and the
    `requested_date` must not precede the logical clock's date — an earlier date is
    `ERR_DATE_IN_PAST`."

    Design: Corner/entities/get_service_request_returns_the_stored_row
    """
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    created = create_service_request(account["id"], requested_date="2026-05-04")

    request = validate_success(api_client.get_service_request(created["id"], owner))
    assert_service_request(request)
    assert request["status"] == "DRAFT"
    assert request["billing_status"] == "UNBILLED"
    assert request["item_count"] == 0
    assert request["quoted_total_cents"] == 0
    assert request["priority"] == "STANDARD"


def test_request_item_listing_paginates_with_total_count_and_has_more():
    """PRD 2.3: "All four pagination fields — `limit`, `offset`, `total_count` and `has_more`
    — appear in `meta` on every list response. `total_count` is the number of rows matching
    the filters before the limit and offset are applied, and `has_more` is true exactly when
    the sum of `offset` and the number of rows returned is less than `total_count`."

    Design: Corner/entities/list_request_items_paginates_with_total_count_and_has_more
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")
    for tier in ("ROUTINE_HONE", "CHIP_REPAIR", "RE_TIP"):
        add_item(request["id"], account["id"], spec["id"], "CHEF_KNIFE", tier)

    rows, meta = validate_paginated(api_client.list_request_items(
        owner, params={"service_request_id": request["id"], "limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    reread = read_request(request["id"])
    assert reread["item_count"] == 3
    assert reread["quoted_total_cents"] == 4365


def test_service_request_without_channel_is_a_validation_error():
    """PRD 2.6 rung 4: "Every field the endpoint marks required is present, and every
    supplied field carries the declared JSON type. Otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_service_request_missing_channel_returns_validation_error
    """
    account = create_account()
    response = api_client.create_service_request(
        {"account_id": account["id"], "requested_date": "2026-05-04"},
        make_account_owner_headers(account["id"]))
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_unknown_damage_tier_routes_to_the_enum_error():
    """PRD 2.6 rung 5: "Every enum-typed field carries a declared member of that enum.
    Otherwise `ERR_INVALID_ENUM` (422). The closed list of fields that route here is exactly:
    `account_type`, `zone_code`, `billing_mode`, `cadence`, the members of `allowed_cadences`,
    `item_class`, `declared_damage_tier`, `assessed_damage_tier`, `channel`, `priority`,
    `required_certification`, `price_tier`, `min_locker_size`, `size`, `grade`,
    `requested_grade`, `method`, `source`, `status`, `billing_status`, `custody_location`,
    `service_status` and `kind`."

    Design: Corner/entities/create_item_with_unknown_damage_tier_returns_invalid_enum
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")

    response = api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "POLISH"}, owner)
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)
    assert read_request(request["id"])["item_count"] == 0


def test_item_price_and_minutes_are_derived_from_the_spec_and_the_declared_tier():
    """PRD 3.3: "The item's **declared minutes**, stored in `service_minutes_declared`, are
    the spec's `base_service_minutes` plus the minutes supplement of the
    `declared_damage_tier`."
    PRD 3.3: "The item's **quoted gross**, stored in `quoted_gross_cents`, is the spec's
    `list_price_cents` multiplied by the price multiplier of the `declared_damage_tier`,
    rounded half up to whole cents."
    PRD 3.3: "Every item opens with `service_status` `INTAKE_PENDING`, `custody_location`
    `CUSTOMER`, `authorization_status` `NOT_REQUIRED`, `allowance_applied` false,
    `requires_reauthorization` false, and null values for `bench_day_id`,
    `rework_of_request_item_id`, `assessed_by_technician_id`, `assessed_damage_tier`,
    `service_minutes_assessed` and `delivered_at`."

    Design: Corner/entities/item_quoted_price_and_minutes_are_computed_not_supplied
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")

    item = validate_success(api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "HANDLE_WORK"}, owner), 201)
    assert_request_item(item)
    assert item["quoted_gross_cents"] == 2700
    assert item["final_gross_cents"] == 2700
    assert item["service_minutes_declared"] == 26
    assert item["service_minutes_assessed"] is None
    assert item["custody_location"] == "CUSTOMER"
    assert item["service_status"] == "INTAKE_PENDING"
    assert item["allowance_applied"] is False


def test_unknown_parent_request_is_reported_before_the_body_reference():
    """PRD 2.11: "Where a path names a parent and then a child — the lines of one invoice,
    the stops added to one run — the parent must resolve first, and a request naming a
    non-existent parent is answered with the parent's not-found code even if the child id is
    also unknown."
    PRD 2.6: "**Path existence** occupies rung 3, on every endpoint that has path parameters,
    resolved left-to-right along the URL, and pre-empts rungs 4 through 57."

    Design: Corner/entities/add_item_to_unknown_service_request_returns_not_found
    """
    account = create_account()
    response = api_client.add_request_item(
        UNKNOWN_UUID_3,
        {"item_class_spec_id": UNKNOWN_UUID_4, "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"},
        make_account_owner_headers(account["id"]))
    error = validate_error(response, ApiErrorId.ERR_SERVICE_REQUEST_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_ITEM_CLASS_SPEC_NOT_FOUND.value


def test_second_submit_of_the_same_request_is_an_invalid_state():
    """PRD 2.6 rung 14: "The target entity's current state is a declared from-state of the
    requested transition, and every precondition declared on that transition in §3 that no
    more specific rung below already covers also holds. Otherwise `ERR_INVALID_STATE` (409)."
    PRD 3.3: "Submitting the draft moves the request `DRAFT → SUBMITTED`. It requires the
    request to currently be `DRAFT`, to hold at least one item, to belong to an `ACTIVE`
    account, and to pass the credit gate."

    Design: Corner/state_machines/submitting_an_already_submitted_request_returns_invalid_state
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")
    add_item(request["id"], account["id"], spec["id"])
    validate_success(api_client.submit_service_request(request["id"], owner))

    response = api_client.submit_service_request(request["id"], owner)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_request(request["id"])["status"] == "SUBMITTED"


def test_second_cancel_of_a_cancelled_request_is_already_terminal():
    """PRD 2.6 rung 13: "The target entity is not already sitting in one of the terminal
    states of the axis the requested transition acts on. Otherwise `ERR_ALREADY_TERMINAL`
    (409). Applies to every state-transition endpoint; pre-empts rungs 14–57."
    PRD 2.9: "On the request fulfilment axis, `COMPLETED` and `CANCELLED` are terminal; on
    its billing axis, `CREDITED` is terminal."

    Design: Corner/state_machines/cancelling_an_already_cancelled_request_returns_already_terminal
    """
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")
    validate_success(api_client.cancel_service_request(request["id"], owner))

    response = api_client.cancel_service_request(request["id"], owner)
    error = validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value
    assert read_request(request["id"])["status"] == "CANCELLED"


def test_suspension_blocks_an_item_add_and_reinstatement_restores_it():
    """PRD 2.6 rung 9: "The `Account` the operation resolves to has `status` `ACTIVE`.
    Otherwise `ERR_ACCOUNT_SUSPENDED` (409)."
    PRD 3.1: "Reinstatement moves `SUSPENDED → ACTIVE`, requires the account to currently be
    `SUSPENDED`, and likewise increments `version`."

    Design: Corner/state_machines/suspended_account_blocks_item_add_and_reinstatement_restores_it
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-04")
    validate_success(api_client.suspend_account(account["id"], ADMIN))

    blocked = api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"}, owner)
    validate_error(blocked, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 409)

    reinstated = validate_success(api_client.reinstate_account(account["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"

    item = validate_success(api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"}, owner), 201)
    assert item["quoted_gross_cents"] == 900
    assert read_request(request["id"])["item_count"] == 1


def test_credit_limit_blocks_new_work_on_an_active_account():
    """PRD 2.6 rung 11: "The account's `outstanding_balance_cents` is not greater than its
    `credit_limit_cents`. Otherwise `ERR_CREDIT_LIMIT_BLOCKED` (402). Applies to exactly five
    new-work endpoints: service-request submission, item addition, stop addition, locker
    assignment and loaner issue."
    PRD 3.1: "All five refuse with `ERR_CREDIT_LIMIT_BLOCKED`, and the refusal carries HTTP
    402 rather than 403, because it is a payment problem and not a permission problem."

    Design: Corner/validations/credit_limit_blocks_new_work_while_the_account_stays_active
    """
    spec = create_chef_knife_spec()
    tier = create_plan_tier()
    account = create_account(credit_limit_cents=0)
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-01")
    subscription = create_subscription(account["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    validate_success(api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "WEEKLY", "expected_subscription_version": subscription["version"]}, owner))
    issue_invoice(find_draft_invoice(account["id"])["id"])

    response = api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"}, owner)
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_BLOCKED.value, 402)

    reread = read_account(account["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["outstanding_balance_cents"] == 19627
    assert read_request(request["id"])["item_count"] == 0


def test_declared_class_must_match_the_referenced_spec():
    """PRD 3.3: "The declared class must equal the `item_class` of the referenced spec, or
    the addition is `ERR_ITEM_CLASS_MISMATCH`."
    PRD 2.6 rung 26: "The supplied `item_class` equals the `item_class` of the referenced
    `ItemClassSpec`. Otherwise `ERR_ITEM_CLASS_MISMATCH` (422)."

    Design: Corner/validations/item_class_must_match_the_referenced_spec
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-01")

    response = api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "SALON_SHEAR",
         "declared_damage_tier": "ROUTINE_HONE"}, owner)
    error = validate_error(response, ApiErrorId.ERR_ITEM_CLASS_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_ENUM.value
    assert read_request(request["id"])["item_count"] == 0


def test_ninth_item_exceeds_the_per_request_limit():
    """PRD 3.3: "A request may hold at most 8 items; a ninth is `ERR_ITEM_LIMIT_EXCEEDED`."
    PRD 2.6 rung 40: "The request's `item_count` plus one is at most 8. Otherwise
    `ERR_ITEM_LIMIT_EXCEEDED` (422). Applies to item addition; pre-empts rungs 41–57."

    Design: Corner/validations/adding_a_ninth_item_exceeds_the_per_request_limit
    """
    spec = create_chef_knife_spec()
    account = create_account()
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-01")
    for _ in range(8):
        add_item(request["id"], account["id"], spec["id"])

    response = api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"}, owner)
    validate_error(response, ApiErrorId.ERR_ITEM_LIMIT_EXCEEDED.value, 422)

    reread = read_request(request["id"])
    assert reread["item_count"] == 8
    assert reread["quoted_total_cents"] == 7200


def _suspended_and_over_limit_account():
    """An account that is simultaneously SUSPENDED and far over a zero credit limit."""
    spec = create_chef_knife_spec()
    tier = create_plan_tier()
    account = create_account(credit_limit_cents=0)
    owner = make_account_owner_headers(account["id"])
    request = create_service_request(account["id"], requested_date="2026-05-01")
    add_item(request["id"], account["id"], spec["id"])
    subscription = create_subscription(account["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    validate_success(api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "WEEKLY", "expected_subscription_version": subscription["version"]}, owner))
    invoice = find_draft_invoice(account["id"])
    issue_invoice(invoice["id"])
    validate_success(api_client.suspend_account(account["id"], ADMIN))
    return account, owner, request, invoice


def test_suspended_account_gate_pre_empts_the_credit_gate_on_submit():
    """PRD 2.6: "**Account status** occupies rung 9 — deliberately after ownership and
    *before* body-reference existence — on every mutating endpoint whose target resolves to an
    `Account`, and pre-empts rungs 10 through 57."
    PRD 2.6 rung 11: "The account's `outstanding_balance_cents` is not greater than its
    `credit_limit_cents`. Otherwise `ERR_CREDIT_LIMIT_BLOCKED` (402). Applies to exactly five
    new-work endpoints: service-request submission, item addition, stop addition, locker
    assignment and loaner issue."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_beats_credit_limit_on_submit
    """
    account, owner, request, _invoice = _suspended_and_over_limit_account()

    response = api_client.submit_service_request(request["id"], owner)
    error = validate_error(response, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_BLOCKED.value


def test_refused_submit_leaves_the_draft_and_the_issued_balance_untouched():
    """PRD 2.6 rung 9: "The `Account` the operation resolves to has `status` `ACTIVE`.
    Otherwise `ERR_ACCOUNT_SUSPENDED` (409)."
    PRD 3.1: "An account's `outstanding_balance_cents` is not a stored balance that drifts;
    it is always exactly the sum of `amount_due_cents` over that account's invoices whose
    status is `ISSUED` or `PARTIALLY_PAID`, recomputed whenever an invoice is issued, paid or
    voided."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_beats_credit_limit_on_submit
    """
    account, owner, request, invoice = _suspended_and_over_limit_account()
    api_client.submit_service_request(request["id"], owner)

    reread_invoice = validate_success(api_client.get_invoice(invoice["id"], CLERK))
    assert reread_invoice["taxable_subtotal_cents"] == 18300
    assert reread_invoice["tax_cents"] == 1327
    assert reread_invoice["total_cents"] == 19627
    assert read_account(account["id"])["outstanding_balance_cents"] == 19627
    assert read_request(request["id"])["status"] == "DRAFT"
