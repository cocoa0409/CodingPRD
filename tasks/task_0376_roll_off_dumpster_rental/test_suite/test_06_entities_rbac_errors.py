"""Entity CRUD surface (creation, defaults, system/computed fields, not-found,
required-field, type constraints, immutability, listing), action endpoints,
container/permit state-violation errors, and RBAC (role exclusivity, peer
isolation, missing auth).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_contractor_headers, NON_EXISTENT_UUID,
)
from test_helpers import fixtures
from test_helpers import factories
from test_helpers.assertions import assert_container_type, assert_weigh_ticket


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
PERMIT = TEST_USERS["permit_officer_headers"]
SCALE = TEST_USERS["scale_operator_headers"]


# ===========================================================================
# Queue B — entities
# ===========================================================================
def test_create_container_type_returns_201_with_fields(api):
    """PRD §3.1: "A new type is born with `active` set to true."
    PRD §2.4: "`version`, an integer that begins at 1 on creation and increments
    by exactly 1 on every mutation that changes the resource."

    Design: Corner/entities/create_container_type_returns_201_with_fields
    """
    resp = api.create_container_type(
        {"size_code": "YD40", "base_rate_cents": 60000, "included_days": 7,
         "overage_day_cents": 1800, "included_tonnage_lbs": 5000,
         "overage_rate_cents_per_lb": 10}, YARD_ADMIN)
    ct = validate_success(resp, expected_status=201)
    assert_container_type(ct)
    assert ct["size_code"] == "YD40"
    assert ct["active"] is True
    assert ct["version"] == 1


def test_get_order_not_found_returns_404(api):
    """PRD §2.8: "every path or body id is checked for existence and, when
    missing, yields the resource-specific not-found error at HTTP 404:
    ... ERR_ORDER_NOT_FOUND ...".

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_rental_order(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_create_order_missing_required_field_returns_422(api):
    """PRD §2.9: "General request well-formedness — required fields present, enum
    values legal, integers non-negative — is reported as ERR_INVALID_REQUEST
    (HTTP 422)".
    PRD §3.3: "creates a rental order by supplying account_id, container_type_id,
    site_address, requested_delivery_date".

    Omitting the required site_address is rejected.

    Design: Corner/entities/create_order_missing_required_field_returns_422
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Acme")
    resp = api.create_rental_order(
        {"account_id": account["id"], "container_type_id": ct["id"],
         "requested_delivery_date": "2026-06-01"},
        make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_default_requires_street_permit_false(api):
    """PRD §3.3: "optionally requires_street_permit (defaulting to false when
    omitted)".
    PRD §3.3: "The order is created with logistics_status of BOOKED and
    billing_status of UNBILLED".

    Design: Corner/entities/create_order_default_requires_street_permit_false
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Acme")
    resp = api.create_rental_order(
        factories.create_rental_order_payload(account["id"], ct["id"], site_address="1 Main"),
        make_contractor_headers(account["id"]))
    order = validate_success(resp, expected_status=201)
    assert order["requires_street_permit"] is False
    assert order["logistics_status"] == "BOOKED"
    assert order["billing_status"] == "UNBILLED"


def test_weigh_ticket_net_weight_clamped_to_zero(api):
    """PRD §3.9: "The ticket's net_weight_lbs is computed as the gross weight
    minus the tare weight, but never below zero — if tare meets or exceeds
    gross, net is 0."

    gross 9000 < tare 10000 -> net 0.

    Design: Corner/entities/weigh_ticket_net_weight_computed_clamped_to_zero
    """
    ctx = fixtures.setup_on_site_order(account_overrides={"business_name": "Net"},
                                       order_overrides={"site_address": "2 Main"},
                                       delivery_date="2026-06-01")
    pu_stop = get_success_data(
        api.create_pickup_stop(ctx["order"]["id"], {"estimated_weight_lbs": 0}, DISPATCHER))
    resp = api.create_weigh_ticket(
        {"order_id": ctx["order"]["id"], "service_stop_id": pu_stop["id"],
         "gross_weight_lbs": 9000, "tare_weight_lbs": 10000}, SCALE)
    ticket = validate_success(resp, expected_status=201)
    assert ticket["net_weight_lbs"] == 0


def test_container_ignores_client_status_fields(api):
    """PRD §3.1: "A freshly registered can starts IN_YARD with a null
    current_order_id."

    A registered container is IN_YARD with current_order_id null regardless of
    input.

    Design: Corner/entities/container_system_fields_ignore_client_status
    """
    ct = fixtures.create_container_type()
    resp = api.create_container(
        {"container_type_id": ct["id"], "asset_tag": "T-SYS-x", "yard_code": "Y1"}, YARD_ADMIN)
    cont = validate_success(resp, expected_status=201)
    assert cont["status"] == "IN_YARD"
    assert cont["current_order_id"] is None


def test_create_container_type_invalid_size_enum_returns_422(api):
    """PRD §3.1: "Its `size_code` is one of `YD10`, `YD20`, `YD30`, or `YD40`."
    PRD §2.9: "enum values legal ... is reported as ERR_INVALID_REQUEST (HTTP
    422)".

    Design: Corner/entities/create_container_type_invalid_size_enum_returns_422
    """
    resp = api.create_container_type(
        {"size_code": "YD99", "base_rate_cents": 50000, "included_days": 7,
         "overage_day_cents": 1500, "included_tonnage_lbs": 4000,
         "overage_rate_cents_per_lb": 9}, YARD_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_weigh_ticket_is_append_only_no_version(api):
    """PRD §2.4: "The WeighTicket is an append-only scale event: once recorded it
    is immutable, so it carries only id and created_at — it has neither
    updated_at nor version."

    GET returns the ticket with its computed net_weight (gross 11000 - tare
    10000 = 1000) and no version field.

    Design: Corner/entities/weigh_ticket_immutable_no_version_field
    """
    ctx = fixtures.setup_on_site_order(account_overrides={"business_name": "Imm"},
                                       order_overrides={"site_address": "3 Main"},
                                       delivery_date="2026-06-01")
    pu_stop = get_success_data(
        api.create_pickup_stop(ctx["order"]["id"], {"estimated_weight_lbs": 100}, DISPATCHER))
    ticket = fixtures.record_weigh_ticket(ctx["order"]["id"], pu_stop["id"],
                                          gross_weight_lbs=11000, tare_weight_lbs=10000)
    resp = api.get_weigh_ticket(ticket["id"], SCALE)
    data = validate_success(resp)
    assert_weigh_ticket(data)
    assert data["net_weight_lbs"] == 1000
    assert "version" not in data
    assert "updated_at" not in data


def test_create_container_bad_type_id_returns_404(api):
    """PRD §2.8: "every path or body id is checked for existence and, when
    missing, yields the resource-specific not-found error at HTTP 404:
    ERR_CONTAINER_TYPE_NOT_FOUND ...".

    Design: Corner/entities/create_container_bad_type_id_returns_404
    """
    resp = api.create_container(
        {"container_type_id": NON_EXISTENT_UUID, "asset_tag": "T-X-x", "yard_code": "Y1"}, YARD_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTAINER_TYPE_NOT_FOUND.value)


def test_list_container_types_paginated_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and
    has_more inside meta, where total_count is the count of all records matching
    the filter (ignoring pagination) and has_more is true when records remain
    beyond the current page."

    Two types exist; limit=1 returns one item with total_count 2 and has_more.

    Design: Corner/entities/list_container_types_paginated_envelope
    """
    fixtures.create_container_type(size_code="YD10", base_rate_cents=30000,
                                   overage_day_cents=1000, included_tonnage_lbs=2000,
                                   overage_rate_cents_per_lb=7)
    fixtures.create_container_type(size_code="YD20", base_rate_cents=40000,
                                   overage_day_cents=1200, included_tonnage_lbs=3000,
                                   overage_rate_cents_per_lb=8)
    resp = api.list_container_types(DISPATCHER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Queue B — endpoints
# ===========================================================================
def test_retire_container_type_sets_inactive(api):
    """PRD §3.1: "A type may later be retired, which sets active to false so no
    new order may select it".

    Design: Corner/endpoints/retire_container_type_sets_inactive
    """
    ct = fixtures.create_container_type(size_code="YD40", base_rate_cents=60000,
                                        overage_day_cents=1800, included_tonnage_lbs=5000,
                                        overage_rate_cents_per_lb=10)
    resp = api.retire_container_type(ct["id"], YARD_ADMIN)
    retired = validate_success(resp)
    assert retired["active"] is False


def test_swap_stop_created_unassigned(api):
    """PRD §3.7: "Creating a swap stop or a pickup stop both require the order to
    be ON_SITE, else ERR_ORDER_NOT_ON_SITE; each accepts an optional
    estimated_weight_lbs for the loaded can and creates a new SWAP or PICKUP
    service stop respectively in UNASSIGNED status".

    Design: Corner/endpoints/swap_stop_created_unassigned
    """
    ctx = fixtures.setup_on_site_order(account_overrides={"business_name": "Sw"},
                                       order_overrides={"site_address": "26 Main"},
                                       delivery_date="2026-06-01")
    resp = api.create_swap_stop(ctx["order"]["id"], {"estimated_weight_lbs": 2500}, DISPATCHER)
    stop = validate_success(resp, expected_status=201)
    assert stop["stop_type"] == "SWAP"
    assert stop["status"] == "UNASSIGNED"
    assert stop["order_id"] == ctx["order"]["id"]


# ===========================================================================
# Queue B — errors
# ===========================================================================
def test_return_to_yard_wrong_state_rejected(api):
    """PRD §3.7: "which requires the can to be AWAITING_DUMP
    (ERR_CONTAINER_NOT_AWAITING_DUMP)".

    return-to-yard on an IN_YARD container is rejected.

    Design: Corner/errors/return_to_yard_wrong_state_rejected
    """
    ct = fixtures.create_container_type()
    container = fixtures.create_container(ct["id"])
    resp = api.return_to_yard(container["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CONTAINER_NOT_AWAITING_DUMP.value)


def test_restore_non_out_of_service_rejected(api):
    """PRD §3.1: "restoring an out-of-service can moves it from OUT_OF_SERVICE
    back to IN_YARD (rejected with ERR_CONTAINER_NOT_OUT_OF_SERVICE if it is not
    currently out of service)".

    restore-asset on an IN_YARD container is rejected.

    Design: Corner/errors/restore_non_out_of_service_rejected
    """
    ct = fixtures.create_container_type()
    container = fixtures.create_container(ct["id"])
    resp = api.restore_asset(container["id"], YARD_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTAINER_NOT_OUT_OF_SERVICE.value)


def test_expire_check_not_yet_expired_rejected(api):
    """PRD §3.4: "Running an expiry check on an APPROVED permit moves it APPROVED
    -> EXPIRED, but only when the clock's current_date is strictly after the
    permit's valid_until; if the window has not yet passed the check is rejected
    with ERR_PERMIT_NOT_EXPIRED".

    current_date 2026-06-05 <= valid_until 2026-06-30.

    Design: Corner/errors/expire_check_not_yet_expired_rejected
    """
    fixtures.set_clock("2026-06-05")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Exp")
    order = fixtures.book_order(account["id"], ct["id"], site_address="27 Main",
                                requested_delivery_date="2026-06-10", requires_street_permit=True)
    permit = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                     valid_from="2026-06-01", valid_until="2026-06-30")
    fixtures.approve_permit(permit["id"])
    resp = api.expire_check_permit(permit["id"], PERMIT)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_EXPIRED.value)


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_contractor_cannot_dispatch_delivery(api):
    """PRD §4: the POST /rental-orders/{orderId}/dispatch-delivery endpoint is
    authorized for Dispatcher only.
    PRD §2.1: "If the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_dispatch_delivery
    """
    booked = fixtures.setup_booked_order_with_container(account_overrides={"business_name": "Rb1"})
    resp = api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(booked["container"]["id"], booked["container"]["version"]),
        make_contractor_headers(booked["account"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_scale_operator_cannot_create_account(api):
    """PRD §4: the POST /contractor-accounts endpoint is authorized for YardAdmin
    only.
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/scale_operator_cannot_create_account
    """
    resp = api.create_contractor_account(
        {"business_name": "Nope", "credit_limit_cents": 100000}, SCALE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_contractor_cannot_act_on_other_account_order(api):
    """PRD §2.1: "an attempt to act on a RentalOrder, ServiceStop, or Invoice the
    contractor does not own is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Contractor B cancelling Contractor A's order is rejected.

    Design: Corner/rbac/contractor_cannot_act_on_other_account_order
    """
    ct = fixtures.create_container_type()
    account_a = fixtures.create_account(business_name="A")
    account_b = fixtures.create_account(business_name="B")
    order = fixtures.book_order(account_a["id"], ct["id"], site_address="29 Main")
    resp = api.cancel_order(order["id"], make_contractor_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is
    rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401) before any other
    processing."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api.list_container_types({})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)
