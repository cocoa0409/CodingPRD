"""CRUD creation, field validation, RBAC, and listing (PRD §2.1, §2.3, §2.8, §3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_facility_payload, create_member_payload, create_vehicle_payload,
    create_unit_payload,
    make_member_headers,
)
from test_helpers import fixtures as fx

VM = TEST_USERS["vault_manager_headers"]
CT = TEST_USERS["concierge_tech_headers"]
BA = TEST_USERS["billing_admin_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_create_facility_returns_201_with_zero_counters(api):
    """PRD §3.1: "At creation the four occupancy counters (`units_available`,
    `units_reserved`, `units_occupied`, `units_out_of_service`) are all initialized
    to zero and grow as units are added."

    Design: Corner/entities/create_facility_returns_201_with_zero_counters
    """
    resp = api.create_facility(create_facility_payload(name="Vault Z", total_units=5), VM)
    data = validate_success(resp, 201)
    assert data["units_available"] == 0
    assert data["units_reserved"] == 0
    assert data["units_occupied"] == 0
    assert data["units_out_of_service"] == 0


def test_member_default_tier_is_bronze_zero_discount(api):
    """PRD §3.2: "an optional `membership_tier`; when the tier is omitted the member
    defaults to `BRONZE`."
    PRD §3.9: "`BRONZE` yields no discount (0.00)".

    Design: Corner/entities/member_default_tier_bronze_zero_discount
    """
    payload = create_member_payload(full_name="Def M")
    payload.pop("membership_tier", None)
    resp = api.create_member(payload, VM)
    data = validate_success(resp, 201)
    assert data["membership_tier"] == "BRONZE"
    assert data["tier_discount_pct"] == 0.00


def test_get_member_nonexistent_id_returns_not_found(api):
    """PRD §2.8: "A missing resource yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_member_nonexistent_id_returns_not_found
    """
    resp = api.get_member(NON_EXISTENT, VM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_vehicle_missing_required_vin_returns_invalid_request(api):
    """PRD §2.8: "Request validity — required body fields present and well-typed,
    and every enum value within its allowed set, else `ERR_INVALID_REQUEST` (422)."
    PRD §3.2: "`vin` (the vehicle identification number, unique across all vehicles
    — a duplicate raises `ERR_DUPLICATE`)".

    Design: Corner/entities/create_vehicle_missing_required_vin_returns_invalid_request
    """
    mem = fx.create_member(api)
    payload = create_vehicle_payload(mem["id"])
    payload.pop("vin")
    resp = api.create_vehicle(payload, VM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_unit_invalid_enum_class_returns_invalid_request(api):
    """PRD §3.1: "The `unit_class` is one of `STANDARD`, `CLIMATE`, or `SHOWCASE`".
    PRD §2.8: "required body fields present and well-typed, and every enum value
    within its allowed set, else `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_unit_invalid_enum_class_returns_invalid_request
    """
    fac = fx.create_facility(api, total_units=3)
    resp = api.create_unit(fac["id"], create_unit_payload(unit_class="PLATINUM",
                                                          monthly_rate_cents=1000), VM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_member_email_returns_duplicate(api):
    """PRD §3.2: "an `email` (unique across all members — a duplicate is rejected
    with `ERR_DUPLICATE`)".

    Design: Corner/entities/duplicate_member_email_returns_duplicate
    """
    validate_success(api.create_member(create_member_payload(full_name="Dup A",
                                                             email="dup@x.com"), VM), 201)
    resp = api.create_member(create_member_payload(full_name="Dup B", email="dup@x.com"), VM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_create_unit_beyond_total_units_returns_limit_error(api):
    """PRD §3.1: "Creating a unit is refused with `ERR_FACILITY_UNIT_LIMIT` (409)
    when the facility already holds `total_units` units — the count of a facility's
    units may never exceed its ceiling."

    Design: Corner/entities/create_unit_beyond_total_units_returns_limit_error
    """
    fac = fx.create_facility(api, total_units=1)
    fx.create_unit(api, fac["id"], unit_code="LU1")
    resp = api.create_unit(fac["id"], create_unit_payload(unit_code="LU2"), VM)
    validate_error(resp, ApiErrorId.ERR_FACILITY_UNIT_LIMIT.value)


def test_request_without_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_without_headers_returns_unauthenticated
    """
    resp = api.create_facility(create_facility_payload(name="NoAuth", total_units=1), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_cannot_approve_service_order_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §3.5: "A vault manager dispositions a requested order by approving or
    rejecting it."

    Design: Corner/rbac/member_cannot_approve_service_order_unauthorized
    """
    ctx = fx.setup_stored_agreement(api)
    so = validate_success(api.create_service_order(
        {"agreement_id": ctx["agreement_id"], "service_type": "DETAIL",
         "estimated_labor_hours": 1.0}, VM), 201)
    resp = api.approve_service_order(so["id"], {"scheduled_at": "2026-06-02T09:00:00Z"},
                                     make_member_headers(ctx["member_id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    unchanged = validate_success(api.get_service_order(so["id"], VM))
    assert unchanged["status"] == "REQUESTED"


def test_conciergetech_cannot_generate_invoice_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §3.9: "Generating an invoice for a member and agreement over a billing period
    gathers up to four kinds of line items into `line_items`".

    Design: Corner/rbac/conciergetech_cannot_generate_invoice_unauthorized
    """
    ctx = fx.setup_pending_agreement(api, document=False)
    resp = api.generate_invoice(
        {"member_id": ctx["member_id"], "agreement_id": ctx["agreement_id"],
         "period_start_at": "2026-06-01T00:00:00Z", "period_end_at": "2026-07-01T00:00:00Z"},
        CT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_agreements_filtered_by_member_paginated(api):
    """PRD §3.3: "Agreements are readable individually and listable with optional
    `member_id`, `vehicle_id`, `unit_id`, and `status` filters."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the total number of matching records before the page window is
    applied), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_agreements_filtered_by_member_paginated
    """
    ctx = fx.setup_pending_agreement(api, document=False)
    resp = api.list_agreements(VM, params={"member_id": ctx["member_id"]})
    data, meta = validate_paginated(resp)
    assert [a["id"] for a in data] == [ctx["agreement_id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
