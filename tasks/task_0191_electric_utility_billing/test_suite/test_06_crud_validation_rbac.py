"""CRUD, input-validation, listing, RBAC, and error-catalogue compliance:
resource creation defaults, required-field and enum validation, tariff-shape and
interval checks, the single-active-plan and payment-range rules, paginated
filtered listing, and the role matrix.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_tariff,
    NONEXISTENT_UUID,
)
from test_helpers.fixtures import (
    OPERATOR,
    CASEWORKER,
    create_active_tariff,
    open_account,
    add_meter,
    import_reads,
    create_draft_bill,
    issue_bill_with_occ_data,
    enroll_budget_plan,
    pay_account_data,
    setup_issued_bill,
    reads_for_2636,
)
from test_helpers.test_users import make_customer_headers, make_role_headers



# ===========================================================================
# Queue B — entities (CRUD)
# ===========================================================================
def test_create_tariff_returns_201_draft(api):
    """PRD §3.1: "A tariff begins life in `DRAFT` status."
    PRD §2.4: "a `version`, an integer that starts at its initial value and
    increments by one on each mutation of the resource."

    POST /tariffs with all required fields returns 201, status DRAFT, version 1.

    Design: Corner/entities/create_tariff_returns_201_with_all_fields
    """
    res = api.create_tariff({
        "code": "RES-CREATE-1", "name": "Corner Tariff",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, OPERATOR)
    tariff = validate_success(res, 201)
    assert_tariff(tariff)
    assert tariff["status"] == "DRAFT", tariff["status"]
    assert tariff["version"] == 1, tariff["version"]


def test_get_account_not_found(api):
    """PRD §2.5: "When a request does carry a path identifier, the server
    validates every path-referenced resource left-to-right and rejects the first
    one that does not exist with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account(NONEXISTENT_UUID, OPERATOR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_account_missing_holder_name_rejected(api):
    """PRD §3.10: "Structural validation of the request body follows: a missing
    required field, a wrong type, or an invalid enum member yields
    `ERR_INVALID_REQUEST`."

    POST /accounts omitting holder_name is rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
    """
    tariff = create_active_tariff()
    res = api.create_account({"tariff_id": tariff["id"]}, OPERATOR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_meter_type_defaults_to_bidirectional(api):
    """PRD §3.2: "an optional `meter_type` that is either `CONSUMPTION_ONLY` or
    `BIDIRECTIONAL`, defaulting to `BIDIRECTIONAL`."

    Design: Corner/entities/meter_type_default_applied_when_omitted
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.create_meter(
        {"account_id": account["id"], "serial": "MTR-DEFAULT-1"}, OPERATOR)
    meter = validate_success(res, 201)
    assert meter["meter_type"] == "BIDIRECTIONAL", meter["meter_type"]


def test_create_meter_invalid_meter_type_rejected(api):
    """PRD §3.10: "a missing required field, a wrong type, or an invalid enum
    member yields `ERR_INVALID_REQUEST`."

    POST /meters with meter_type not in {CONSUMPTION_ONLY, BIDIRECTIONAL} is
    rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_meter_invalid_meter_type_enum_returns_invalid_request
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.create_meter(
        {"account_id": account["id"], "serial": "MTR-BAD-ENUM",
         "meter_type": "SOLAR_ONLY"}, OPERATOR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ===========================================================================
# Queue B — validations
# ===========================================================================
def test_tariff_shape_rate_length_mismatch_rejected(api):
    """PRD §3.1: "The rate array must be exactly one longer than the breakpoint
    array ... A tariff whose shape violates any of these is rejected with
    `ERR_INVALID_TARIFF_SHAPE`."

    breakpoints [500,1000] with rates [12,18] (length 2, needs 3) is rejected.

    Design: Corner/validations/invalid_tariff_shape_rates_length_mismatch
    """
    res = api.create_tariff({
        "code": "RES-BAD-LEN", "name": "Bad Length",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500, 1000],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, OPERATOR)
    validate_error(res, "ERR_INVALID_TARIFF_SHAPE", expected_status=422)


def test_tariff_shape_tou_order_violation_rejected(api):
    """PRD §3.1: "the three TOU multipliers must satisfy `ON_PEAK` at least
    `MID_PEAK` and `MID_PEAK` at least `OFF_PEAK`, with every multiplier greater
    than zero. A tariff whose shape violates any of these is rejected with
    `ERR_INVALID_TARIFF_SHAPE`."

    OFF_PEAK 1.5 > ON_PEAK 0.8 violates the ordering and is rejected.

    Design: Corner/validations/invalid_tariff_shape_tou_order_violation
    """
    res = api.create_tariff({
        "code": "RES-BAD-TOU", "name": "Bad TOU",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 0.8, "MID_PEAK": 1.0, "OFF_PEAK": 1.5},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, OPERATOR)
    validate_error(res, "ERR_INVALID_TARIFF_SHAPE", expected_status=422)


def test_meter_read_interval_not_one_hour_rejected(api):
    """PRD §3.2: "Each interval must be exactly one hour long: `interval_end`
    must equal `interval_start` plus sixty minutes, and a read whose interval is
    not exactly sixty minutes is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/invalid_interval_not_one_hour
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    res = api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T16:00:00Z",
        "interval_end": "2026-01-05T18:00:00Z",
        "import_kwh": 2.0, "export_kwh": 0.0,
    }, OPERATOR)
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_meter_read_export_on_consumption_only_rejected(api):
    """PRD §3.2: "The same error rejects any read carrying a positive
    `export_kwh` on a meter whose `meter_type` is `CONSUMPTION_ONLY`, since a
    consumption-only meter cannot export."

    Design: Corner/validations/invalid_interval_export_on_consumption_only_meter
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"], meter_type="CONSUMPTION_ONLY")
    res = api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T16:00:00Z",
        "interval_end": "2026-01-05T17:00:00Z",
        "import_kwh": 2.0, "export_kwh": 5.0,
    }, OPERATOR)
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_second_active_budget_plan_rejected(api):
    """PRD §3.7: "An account may hold at most one `ACTIVE` plan at a time;
    enrolling a second while one is already active is rejected with
    `ERR_BUDGET_PLAN_EXISTS`."

    Design: Corner/validations/second_active_budget_plan_rejected
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    enroll_budget_plan(account["id"], 1500)
    res = api.create_budget_plan(
        {"account_id": account["id"], "levelized_amount_cents": 2000}, OPERATOR)
    validate_error(res, "ERR_BUDGET_PLAN_EXISTS", expected_status=409)


def test_payment_zero_amount_rejected(api):
    """PRD §3.5: "The amount must be strictly greater than zero; a non-positive
    amount is rejected with `ERR_INVALID_PAYMENT`."

    The §5 error catalogue likewise binds ERR_INVALID_PAYMENT to "Payment
    amount_cents <= 0". The design index grounds this on the generic range rule,
    but the operation-specific PRD prose (§3.5) uniquely names ERR_INVALID_PAYMENT
    for a zero payment, so the test asserts the PRD-stated error.

    Design: Corner/validations/invalid_payment_zero_amount_rejected
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.create_payment(
        {"account_id": account["id"], "amount_cents": 0, "method": "ACH"},
        make_customer_headers(account["id"]))
    validate_error(res, "ERR_INVALID_PAYMENT", expected_status=409)


# ===========================================================================
# Queue B — errors
# ===========================================================================
def test_fk_not_found_on_meter_create(api):
    """PRD §2.5: "When a creation request's body carries a foreign key — such as
    `account_id`, `meter_id`, or `tariff_id` — that references a resource which
    does not exist, the request is rejected with `ERR_FK_NOT_FOUND`."

    POST /meters referencing a non-existent account_id is rejected
    ERR_FK_NOT_FOUND.

    Design: Corner/errors/fk_not_found_on_meter_create
    """
    res = api.create_meter(
        {"account_id": NONEXISTENT_UUID, "serial": "MTR-NO-ACCT",
         "meter_type": "BIDIRECTIONAL"}, OPERATOR)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_reverse_already_reversed_payment_rejected(api):
    """PRD §3.5: "A `BillingOperator` may reverse a payment, which must currently
    be `POSTED`; reversing a payment that is not `POSTED` (already `REVERSED`) is
    rejected with `ERR_INVALID_PAYMENT`."

    Design: Corner/errors/invalid_payment_reverse_already_reversed
    """
    scene = setup_issued_bill(read_tuples=reads_for_2636())
    payment = pay_account_data(scene["account"]["id"], 1000)
    validate_success(api.reverse_payment(payment["id"], OPERATOR), 200)
    res = api.reverse_payment(payment["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_PAYMENT", expected_status=409)


# ===========================================================================
# Queue B — endpoints (listing)
# ===========================================================================
def test_list_bills_filtered_by_account(api):
    """PRD §4: "List bills, filterable by account_id, tariff_id, and status"
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    GET /bills?account_id= returns only that account's bills as a paginated
    array with total_count and has_more.

    Design: Corner/endpoints/list_bills_filtered_by_account_id
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    create_draft_bill(
        account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
        "2026-03-20T00:00:00Z")
    data, meta = validate_paginated(
        api.list_bills(OPERATOR, params={"account_id": account["id"]}))
    assert len(data) == 2, len(data)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    for b in data:
        assert b["account_id"] == account["id"]


def test_list_meters_by_account_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum
    of 100. The `offset` parameter sets the number of items to skip and defaults
    to 0."

    GET /meters?account_id= applies default limit 10 / offset 0 and returns the
    paginated Meter array.

    Design: Corner/endpoints/list_meters_by_account_pagination_defaults
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    add_meter(account["id"])
    data, meta = validate_paginated(
        api.list_meters(OPERATOR, params={"account_id": account["id"]}))
    assert len(data) == 1, len(data)
    assert meta["total_count"] == 1, meta["total_count"]
    assert meta["limit"] == 10, meta["limit"]
    assert meta["offset"] == 0, meta["offset"]


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_customer_cannot_create_tariff(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation under the role matrix in
    Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /tariffs is a BillingOperator-only op; a Customer is forbidden.

    Design: Corner/rbac/customer_cannot_create_tariff_forbidden
    """
    res = api.create_tariff({
        "code": "RES-RBAC-FORBID", "name": "Forbidden",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, make_customer_headers(NONEXISTENT_UUID))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_field_dispatcher_cannot_issue_bill(api):
    """PRD §4: the issue endpoint is authorized for BillingOperator only.
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A FieldDispatcher calling POST /bills/{id}/issue is forbidden.

    Design: Corner/rbac/field_dispatcher_cannot_issue_bill_forbidden
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    from test_helpers.fixtures import DISPATCHER
    res = api.issue_bill(
        bill["id"], {"expected_account_version": acct["version"]}, DISPATCHER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` names a role
    the system does not recognize, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    A request with an unrecognized role returns ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.get_account(NONEXISTENT_UUID, make_role_headers("nobody-1", "Nobody"))
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_caseworker_can_pledge_grant(api):
    """PRD §3.8: "An **AssistanceGrant** is pledged to an account by an
    `AssistanceCaseworker`, created with the `account_id`, a `pledged_cents`
    total ... A new grant is `PLEDGED` and its `remaining_cents` starts equal to
    `pledged_cents`"

    The AssistanceCaseworker successfully pledges a grant -> 201, PLEDGED,
    remaining == pledged.

    Design: Corner/rbac/assistance_caseworker_can_pledge_grant
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.create_assistance_grant(
        {"account_id": account["id"], "pledged_cents": 1000, "program": "LIHEAP"},
        CASEWORKER)
    grant = validate_success(res, 201)
    assert grant["status"] == "PLEDGED", grant["status"]
    assert grant["remaining_cents"] == 1000, grant["remaining_cents"]
