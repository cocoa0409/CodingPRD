"""Configuration surface, identity gates and the not-found catalogue."""
from test_helpers import (
    ApiErrorId, NO_AUTH_HEADERS, UNKNOWN_UUID, UNKNOWN_UUID_2,
    ADMIN, CLERK, DISPATCHER,
    api_client, create_account, create_bench_day, create_chef_knife_spec,
    create_technician, create_van, item_class_spec_payload,
    make_account_owner_headers, make_technician_headers,
    validate_error, validate_success,
    assert_account, assert_bench_day, assert_same_instant,
)


def test_new_account_applies_the_declared_optional_field_defaults():
    """PRD 3.1: "Three further inputs are optional: `billing_mode`, defaulting to
    `PER_VISIT` and otherwise `MONTHLY_ROLLUP`; `tax_exempt`, defaulting to false; and
    `credit_limit_cents`, an integer of at least zero defaulting to 50000 cents."
    PRD 3.1: "A new account opens with `status` `ACTIVE` and `outstanding_balance_cents` of 0."
    PRD 2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1
    on every mutation of the row."

    Design: Corner/entities/create_account_applies_declared_defaults_and_system_fields
    """
    response = api_client.create_account(
        {"name": "Blue Fork Kitchen", "account_type": "RESTAURANT",
         "zone_code": "ZONE_N", "contact_email": "ops@bluefork.test"}, ADMIN)
    account = validate_success(response, 201)
    assert_account(account)
    assert account["billing_mode"] == "PER_VISIT"
    assert account["tax_exempt"] is False
    assert account["credit_limit_cents"] == 50000
    assert account["status"] == "ACTIVE"
    assert account["outstanding_balance_cents"] == 0
    assert account["version"] == 1


def test_unknown_route_run_id_answers_the_run_not_found_code():
    """PRD 2.6 rung 3: "Every id embedded in the URL path resolves to an existing row.
    Segments are checked left to right and the leftmost unresolved segment decides which
    error is returned: `ERR_ACCOUNT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
    `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_REQUEST_ITEM_NOT_FOUND`, `ERR_ROUTE_RUN_NOT_FOUND`,
    `ERR_ROUTE_STOP_NOT_FOUND`, `ERR_LOCKER_COMPARTMENT_NOT_FOUND`, `ERR_BENCH_DAY_NOT_FOUND`,
    `ERR_LOANER_UNIT_NOT_FOUND`, `ERR_LOANER_ISSUE_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND` or
    `ERR_ALLOWANCE_ENTRY_NOT_FOUND` as appropriate, each HTTP 404."

    Design: Corner/entities/get_route_run_with_unknown_id_returns_not_found
    """
    create_van()
    response = api_client.get_route_run(UNKNOWN_UUID_2, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_ROUTE_RUN_NOT_FOUND.value, 404)


def test_second_spec_for_an_existing_item_class_is_rejected():
    """PRD 3.1: "A second spec declaring a class that already has one is refused with
    `ERR_DUPLICATE_ITEM_CLASS_SPEC`."

    Design: Corner/entities/duplicate_item_class_spec_is_rejected
    """
    first = create_chef_knife_spec()
    response = api_client.create_item_class_spec(
        item_class_spec_payload(bevel_angle_degrees=22, base_service_minutes=7,
                                list_price_cents=1000, loaner_eligible=False), ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ITEM_CLASS_SPEC.value, 409)
    # The surviving spec is the first one, at its original list price.
    assert first["item_class"] == "CHEF_KNIFE"
    assert first["list_price_cents"] == 900


def test_second_bench_day_for_the_same_date_is_rejected():
    """PRD 3.1: "A second bench day for a date that already has one is refused with
    `ERR_DUPLICATE_BENCH_DAY`."

    Design: Corner/entities/duplicate_bench_day_date_is_rejected
    """
    bench = create_bench_day(bench_date="2026-05-01", bench_minute_budget=480)
    response = api_client.create_bench_day(
        {"bench_date": "2026-05-01", "bench_minute_budget": 240}, ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BENCH_DAY.value, 409)
    reread = validate_success(api_client.get_bench_day(bench["id"], ADMIN))
    assert_bench_day(reread)
    assert reread["bench_minute_budget"] == 480
    assert reread["booked_minutes"] == 0


def test_pagination_limit_above_one_hundred_is_refused():
    """PRD 2.3: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`,
    or either value supplied as something that is not an integer, is refused with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_above_one_hundred_is_refused
    """
    create_van()
    response = api_client.list_route_runs(DISPATCHER, params={"limit": 500, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_zero_service_minute_budget_is_out_of_range():
    """PRD 2.6 rung 6: "Numeric fields satisfy their declared ranges — budgets and caps are
    at least 1, payment amounts are at least 1, a stop `sequence` is at least 1, and
    cents-valued inputs are at least 0 — and every date or date-time field parses as ISO 8601.
    Otherwise `ERR_VALUE_OUT_OF_RANGE` (422)."

    Design: Corner/validations/zero_service_minute_budget_is_out_of_range
    """
    technician = create_technician()
    van = create_van()
    response = api_client.create_route_run(
        {"van_id": van["id"], "technician_id": technician["id"], "run_date": "2026-05-01",
         "zone_code": "ZONE_N", "service_minute_budget": 0, "stop_cap": 8}, DISPATCHER)
    error = validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_logical_clock_cannot_be_wound_backwards():
    """PRD 2.5: "The clock may only move forward: a `to_iso8601` earlier than the clock's
    current value is refused with `ERR_VALUE_OUT_OF_RANGE` (HTTP 422), and so is a value that
    does not parse as an ISO 8601 instant. Setting the clock to exactly its current value is
    permitted."

    Design: Corner/validations/logical_clock_cannot_be_wound_backwards
    """
    moved = validate_success(
        api_client.set_clock({"to_iso8601": "2026-05-05T00:00:00Z"}, ADMIN))
    assert_same_instant(moved["current_utc"], "2026-05-05T00:00:00Z", "current_utc")

    response = api_client.set_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, 422)

    # Setting the clock to exactly its current value is permitted and reports where it stands.
    still = validate_success(
        api_client.set_clock({"to_iso8601": "2026-05-05T00:00:00Z"}, ADMIN))
    assert_same_instant(still["current_utc"], "2026-05-05T00:00:00Z", "current_utc")


def test_technician_cannot_create_an_invoice():
    """PRD 2.6 rung 2: "The acting role appears in the endpoint's authorized-role list in
    §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to all endpoints; pre-empts rungs 3–57."

    Design: Corner/rbac/technician_cannot_create_an_invoice
    """
    account = create_account()
    technician = create_technician()
    response = api_client.create_invoice(
        {"account_id": account["id"], "billing_period": "2026-05"},
        make_technician_headers(technician["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_account_owner_cannot_submit_another_accounts_request():
    """PRD 2.6 rung 8: "For an entity-backed role, `X-User-ID` owns the resource, as
    described in §2.1. Otherwise `ERR_NOT_ACCOUNT_OWNER` (403)."
    PRD 2.1: "Ownership checks on any resource that references an `Account` compare the
    resource's account foreign key to `X-User-ID`; a mismatch is `ERR_NOT_ACCOUNT_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/account_owner_cannot_submit_another_accounts_request
    """
    spec = create_chef_knife_spec()
    account_a = create_account()
    account_b = create_account(name="Copper Pan", contact_email="ops@copperpan.test")
    request = validate_success(api_client.create_service_request(
        {"account_id": account_a["id"], "channel": "VAN_ROUTE", "requested_date": "2026-05-01"},
        make_account_owner_headers(account_a["id"])), 201)
    validate_success(api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": spec["id"], "item_class": "CHEF_KNIFE",
         "declared_damage_tier": "ROUTINE_HONE"},
        make_account_owner_headers(account_a["id"])), 201)

    response = api_client.submit_service_request(
        request["id"], make_account_owner_headers(account_b["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value, 403)

    reread = validate_success(api_client.get_service_request(
        request["id"], make_account_owner_headers(account_a["id"])))
    assert reread["status"] == "DRAFT"


def test_missing_user_headers_are_refused_before_anything_else():
    """PRD 2.1: "If either header is absent, or if `X-User-Role` carries any string other
    than those five, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before
    anything else is examined."

    Design: Corner/rbac/missing_user_headers_returns_unauthenticated
    """
    account = create_account()
    response = api_client.get_account(account["id"], NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_body_reference_not_found_errors_name_the_missing_entity():
    """PRD 2.6 rung 10: "Every foreign key supplied in the request body resolves to a row,
    checked in the order the fields are listed in that endpoint's input. The error is the
    not-found code for the entity the missing key names — `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_PLAN_TIER_NOT_FOUND`, `ERR_ITEM_CLASS_SPEC_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
    `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_REQUEST_ITEM_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
    `ERR_VAN_NOT_FOUND` or `ERR_BENCH_DAY_NOT_FOUND` — each HTTP 404."

    Design: Corner/errors/body_reference_not_found_errors_name_the_missing_entity
    """
    account = create_account()
    van = create_van()
    technician = create_technician()
    owner = make_account_owner_headers(account["id"])
    request = validate_success(api_client.create_service_request(
        {"account_id": account["id"], "channel": "VAN_ROUTE", "requested_date": "2026-05-01"},
        owner), 201)

    validate_error(api_client.create_subscription(
        {"account_id": account["id"], "plan_tier_id": "aaaaaaaa-1111-4222-8333-444444444444",
         "cadence": "MONTHLY", "anchor_date": "2026-06-01"}, owner),
        ApiErrorId.ERR_PLAN_TIER_NOT_FOUND.value, 404)

    validate_error(api_client.create_route_run(
        {"van_id": "bbbbbbbb-1111-4222-8333-444444444444", "technician_id": technician["id"],
         "run_date": "2026-05-01", "zone_code": "ZONE_N", "service_minute_budget": 420,
         "stop_cap": 8}, DISPATCHER),
        ApiErrorId.ERR_VAN_NOT_FOUND.value, 404)

    validate_error(api_client.create_route_run(
        {"van_id": van["id"], "technician_id": "cccccccc-1111-4222-8333-444444444444",
         "run_date": "2026-05-01", "zone_code": "ZONE_N", "service_minute_budget": 420,
         "stop_cap": 8}, DISPATCHER),
        ApiErrorId.ERR_TECHNICIAN_NOT_FOUND.value, 404)

    validate_error(api_client.add_request_item(
        request["id"],
        {"item_class_spec_id": "dddddddd-1111-4222-8333-444444444444",
         "item_class": "CHEF_KNIFE", "declared_damage_tier": "ROUTINE_HONE"}, owner),
        ApiErrorId.ERR_ITEM_CLASS_SPEC_NOT_FOUND.value, 404)


def test_path_not_found_errors_name_the_missing_entity():
    """PRD 2.6 rung 3: "Every id embedded in the URL path resolves to an existing row.
    Segments are checked left to right and the leftmost unresolved segment decides which
    error is returned: `ERR_ACCOUNT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
    `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_REQUEST_ITEM_NOT_FOUND`, `ERR_ROUTE_RUN_NOT_FOUND`,
    `ERR_ROUTE_STOP_NOT_FOUND`, `ERR_LOCKER_COMPARTMENT_NOT_FOUND`, `ERR_BENCH_DAY_NOT_FOUND`,
    `ERR_LOANER_UNIT_NOT_FOUND`, `ERR_LOANER_ISSUE_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND` or
    `ERR_ALLOWANCE_ENTRY_NOT_FOUND` as appropriate, each HTTP 404."

    Design: Corner/errors/path_not_found_errors_name_the_missing_entity
    """
    create_account()
    base = "eeeeeeee-1111-4222-8333-4444444444"
    probes = [
        (api_client.get_account(f"{base}01", ADMIN), ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        (api_client.get_subscription(f"{base}02", ADMIN), ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND),
        (api_client.get_service_request(f"{base}03", ADMIN), ApiErrorId.ERR_SERVICE_REQUEST_NOT_FOUND),
        (api_client.get_request_item(f"{base}04", ADMIN), ApiErrorId.ERR_REQUEST_ITEM_NOT_FOUND),
        (api_client.get_route_stop(f"{base}05", DISPATCHER), ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND),
        (api_client.get_locker_compartment(f"{base}06", ADMIN), ApiErrorId.ERR_LOCKER_COMPARTMENT_NOT_FOUND),
        (api_client.get_bench_day(f"{base}07", ADMIN), ApiErrorId.ERR_BENCH_DAY_NOT_FOUND),
        (api_client.get_loaner_unit(f"{base}08", ADMIN), ApiErrorId.ERR_LOANER_UNIT_NOT_FOUND),
        (api_client.get_loaner_issue(f"{base}09", ADMIN), ApiErrorId.ERR_LOANER_ISSUE_NOT_FOUND),
        (api_client.get_warranty_claim(f"{base}10", ADMIN), ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND),
        (api_client.get_invoice(f"{base}11", CLERK), ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api_client.get_invoice_line(f"{base}12", CLERK), ApiErrorId.ERR_INVOICE_LINE_NOT_FOUND),
        (api_client.get_payment(f"{base}13", CLERK), ApiErrorId.ERR_PAYMENT_NOT_FOUND),
        (api_client.get_allowance_entry(f"{base}14", ADMIN), ApiErrorId.ERR_ALLOWANCE_ENTRY_NOT_FOUND),
    ]
    for response, expected in probes:
        validate_error(response, expected.value, 404)


def test_role_gate_pre_empts_path_existence_on_dispatch():
    """PRD 2.6: "**Role authorization** occupies rung 2, on every endpoint, and pre-empts
    rungs 3 through 57."
    PRD 2.6 rung 2: "The acting role appears in the endpoint's authorized-role list in §4.
    Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to all endpoints; pre-empts rungs 3–57."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_by_account_owner_forbidden_role_beats_not_found
    """
    account = create_account()
    response = api_client.dispatch_route_run(
        UNKNOWN_UUID, make_account_owner_headers(account["id"]))
    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_ROUTE_RUN_NOT_FOUND.value


def test_authorized_dispatcher_reaches_the_path_existence_rung_on_the_same_id():
    """PRD 2.6: "**Path existence** occupies rung 3, on every endpoint that has path
    parameters, resolved left-to-right along the URL, and pre-empts rungs 4 through 57."
    PRD 2.6 rung 2: "The acting role appears in the endpoint's authorized-role list in §4.
    Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to all endpoints; pre-empts rungs 3–57."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_by_account_owner_forbidden_role_beats_not_found
    """
    create_account()
    response = api_client.dispatch_route_run(UNKNOWN_UUID, DISPATCHER)
    error = validate_error(response, ApiErrorId.ERR_ROUTE_RUN_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value
