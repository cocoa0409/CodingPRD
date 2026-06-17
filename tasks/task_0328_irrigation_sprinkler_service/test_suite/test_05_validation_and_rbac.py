"""Validation gates, existence ordering, RBAC denial / ownership, entity creation
defaults, and the list / read-only endpoint contracts.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_customer_property,
    setup_customer_property_system,
    setup_sent_quote,
    create_customer,
    create_property,
    create_system,
    create_zone,
    create_technician,
    create_work_order,
    create_route,
    create_route_stop,
    make_technician_headers,
    make_customer_headers,
    make_backflow_tester_headers,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Queue A — priority_pair_validation_conflict (backflow safety beats referential)
# ===========================================================================
def test_tester_not_certified_precedes_no_device(api):
    """PRD §2.5: "Then come the domain-specific business gates — the optimistic concurrency
    check, the backflow safety and device gates, the seasonal gates". PRD §3.5: "the system
    must actually have a backflow device, that is its `has_backflow_device` must be true
    (otherwise `ERR_NO_BACKFLOW_DEVICE`, HTTP 409); and the technician named in
    `tester_technician_id` must be one whose `backflow_certified` is true (otherwise
    `ERR_TESTER_NOT_CERTIFIED`, HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/backflow_safety_beats_referential
    """
    cust = create_customer(company_name="PP2 Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=60, has_backflow_device=False)
    tester = create_technician(full_name="Uncert Tech", backflow_certified=False)
    headers = make_backflow_tester_headers(tester["id"])
    resp = api.create_backflow_test(
        {"system_id": sys["id"], "tester_technician_id": tester["id"],
         "relief_open_psi": 5, "checkvalve_hold_psi": 3}, headers)
    validate_error(resp, ApiErrorId.ERR_TESTER_NOT_CERTIFIED.value)


# ===========================================================================
# Queue B — entities section
# ===========================================================================
def test_create_customer_defaults_active_version_one(api):
    """PRD §3.1: "A customer account is opened with a `company_name`, a `contact_email`, and
    a five-digit `billing_zip`; on creation its `status` is `ACTIVE`." PRD §2.4: "The
    `version` field is an integer that begins at 1 on creation".

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    data = validate_success(api.create_customer(
        {"company_name": "Fresh Co", "contact_email": "f@x.com", "billing_zip": "94016"},
        DISPATCHER), expected_status=201)
    assert data["status"] == "ACTIVE", f"status should default to ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"version should be 1, got {data['version']}"


def test_get_unknown_customer_returns_not_found(api):
    """PRD §2.5: "an unresolved Customer yields `ERR_CUSTOMER_NOT_FOUND`".

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    resp = api.get_customer(NONEXISTENT, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_create_property_missing_site_address_rejected(api):
    """PRD §2.5: "Generic request-shape problems — a missing required body field, a value
    of the wrong type, an enum value outside its allowed range, a negative quantity, or a
    time window whose end is at or before its start — are reported as `ERR_INVALID_REQUEST`
    (HTTP 422)". PRD §3.1: "A property is registered under a customer by supplying that
    account's `customer_id` together with the `site_address` and the geographic `lat` and
    `lng` coordinates".

    Design: Corner/entities/create_property_missing_required_field_returns_invalid_request
    """
    cust = create_customer(company_name="Req Co")
    resp = api.create_property(
        {"customer_id": cust["id"], "lat": 37.7, "lng": -122.4}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_technician_backflow_certified_defaults_false(api):
    """PRD §3.1: "The optional `backflow_certified` flag marks whether the technician is
    licensed to certify backflow tests and defaults to false when omitted."

    Design: Corner/entities/technician_backflow_certified_default_false
    """
    data = validate_success(api.create_technician(
        {"full_name": "Def Tech", "shift_start_sec": 28800, "shift_end_sec": 64800},
        DISPATCHER), expected_status=201)
    assert data["backflow_certified"] is False, (
        f"backflow_certified should default to false, got {data['backflow_certified']}")


def test_new_system_zone_count_and_committed_cost_zero(api):
    """PRD §3.2: "A new system starts with `season_state` of `DORMANT`, `backflow_status`
    of `UNTESTED`, and `lifecycle_state` of `OPERATIONAL`, with its `zone_count` and
    `committed_cost_cents` both at zero."

    Design: Corner/entities/system_computed_zone_count_and_costs_initialized
    """
    _cust, prop = setup_customer_property(company_name="Comp Co")
    data = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "Hunter", "static_psi": 60},
        DISPATCHER), expected_status=201)
    assert data["zone_count"] == 0, f"zone_count should be 0, got {data['zone_count']}"
    assert data["committed_cost_cents"] == 0, (
        f"committed_cost_cents should be 0, got {data['committed_cost_cents']}")


def test_duplicate_zone_number_rejected(api):
    """PRD §3.2: "The `zone_number` must be at least 1 and must be unique among the system's
    zones that are not archived; a collision is rejected with `ERR_DUPLICATE_ZONE_NUMBER`."

    Design: Corner/entities/duplicate_zone_number_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Dup Co")
    create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    resp = api.create_zone(
        {"system_id": sys["id"], "zone_number": 1, "plant_type": "SHRUB",
         "head_count": 4, "gpm_per_head": 12}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ZONE_NUMBER.value)


def test_invalid_plant_type_enum_rejected(api):
    """PRD §3.2: "a `plant_type` of `TURF`, `SHRUB`, `DRIP`, or `ROTOR`". PRD §2.5: "Generic
    request-shape problems — a missing required body field, a value of the wrong type, an
    enum value outside its allowed range, a negative quantity, or a time window whose end is
    at or before its start — are reported as `ERR_INVALID_REQUEST` (HTTP 422) and sit at the
    bottom of the priority order."

    Design: Corner/entities/invalid_enum_plant_type_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Enum Co")
    resp = api.create_zone(
        {"system_id": sys["id"], "zone_number": 1, "plant_type": "CACTUS",
         "head_count": 4, "gpm_per_head": 12}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — validations section
# ===========================================================================
def test_send_empty_line_items_quote_rejected(api):
    """PRD §3.3: "Sending requires that the quote currently be in `DRAFT` (otherwise
    `ERR_QUOTE_NOT_DRAFT`) and that its `line_items` be non-empty (otherwise
    `ERR_EMPTY_QUOTE`, HTTP 422)."

    Design: Corner/validations/empty_quote_send_rejected
    """
    _cust, prop = setup_customer_property(company_name="Eq Co")
    quote = validate_success(api.create_quote(
        {"property_id": prop["id"], "quote_type": "REPAIR", "line_items": []}, DISPATCHER),
        expected_status=201)
    resp = api.send_quote(quote["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_QUOTE.value)


def test_decommission_unknown_system_returns_not_found_before_state(api):
    """PRD §2.5: "Existence of every referenced identifier is checked third, yielding the
    appropriate not-found error... State preconditions for the requested transition are
    checked fifth". PRD §2.5: "an irrigation system `ERR_SYSTEM_NOT_FOUND`".

    Design: Corner/validations/existence_precedes_state_on_unknown_system_decommission
    """
    resp = api.decommission_system(NONEXISTENT, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_FOUND.value)


def test_create_work_order_unknown_system_returns_not_found(api):
    """PRD §2.5: "rejects the request at the first identifier that does not resolve to an
    existing row... an irrigation system `ERR_SYSTEM_NOT_FOUND`".

    Design: Corner/validations/workorder_fk_system_not_found_rejected
    """
    resp = api.create_work_order(
        {"system_id": NONEXISTENT, "job_type": "LEAK_REPAIR",
         "estimated_minutes": 30, "estimated_cost_cents": 4000}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_FOUND.value)


# ===========================================================================
# Queue B — errors section (work order terminal)
# ===========================================================================
def test_cancel_already_cancelled_work_order_rejected(api):
    """PRD §3.4: "cancellation is permitted only while the `completion_status` is not
    already one of `COMPLETED`, `FAILED`, or `CANCELLED` (otherwise `ERR_WORKORDER_TERMINAL`)."

    Design: Corner/errors/workorder_terminal_cancel_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Tc Co")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=3000)
    validate_success(api.cancel_work_order(wo["id"], DISPATCHER))
    resp = api.cancel_work_order(wo["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WORKORDER_TERMINAL.value)


# ===========================================================================
# Queue B — rbac section
# ===========================================================================
def test_technician_cannot_create_customer(api):
    """PRD §2.1: "When a syntactically valid user attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/technician_cannot_create_customer
    """
    tech = create_technician(full_name="Rb Tech")
    headers = make_technician_headers(tech["id"])
    resp = api.create_customer(
        {"company_name": "Sneaky Co", "contact_email": "s@x.com", "billing_zip": "94016"},
        headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_approve_other_customers_quote(api):
    """PRD §2.1: "a Customer may only act on a quote whose Property's `customer_id`
    resolves to a Property they own." PRD §2.1: "A failed ownership comparison on an
    entity-backed actor — a Customer acting on a property they do not own... — is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_approve_other_customers_quote
    """
    owner = create_customer(company_name="Owner A")
    intruder = create_customer(company_name="Intruder B")
    prop = create_property(owner["id"])
    quote = setup_sent_quote(prop["id"], quote_type="INSTALL")
    intruder_headers = make_customer_headers(intruder["id"])
    resp = api.approve_quote(quote["id"], intruder_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_technician_cannot_depart_unassigned_work_order(api):
    """PRD §3.4: "Departing for the job advances `SCHEDULED → EN_ROUTE`; this requires that
    `dispatch_status` be `SCHEDULED` (otherwise `ERR_WORKORDER_NOT_SCHEDULED`) and that the
    acting technician match the work order's `assigned_technician_id` (otherwise
    `ERR_NOT_RESOURCE_OWNER`)."

    Design: Corner/rbac/technician_cannot_act_on_unassigned_workorder
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Asg Co")
    tech_a = create_technician(full_name="Tech A")
    tech_b = create_technician(full_name="Tech B")
    wo = create_work_order(sys["id"], job_type="LEAK_REPAIR",
                           estimated_minutes=30, estimated_cost_cents=4000)
    route = create_route(tech_a["id"], route_date="2026-05-11")
    create_route_stop(route["id"], wo["id"], route["version"],
                      arrival_start_sec=28800, window_minutes=60)
    headers_b = make_technician_headers(tech_b["id"])
    resp = api.depart_work_order(wo["id"], headers_b)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ===========================================================================
# Queue B — endpoints section
# ===========================================================================
def test_list_properties_returns_paginated_envelope(api):
    """PRD §2.3: "List responses surface the pagination state inside the `meta` object of
    the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_properties_pagination_envelope
    """
    _cust, _prop = setup_customer_property(company_name="Pg Co")
    resp = api.list_properties(DISPATCHER, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta, "meta must contain total_count"
    assert "has_more" in meta, "meta must contain has_more"


def test_blowout_quote_read_only_does_not_mutate_system(api):
    """PRD §3.8: "The blowout price preview is a read-only pricing estimate for winterizing
    a system... its response carries the `system_id`, the system's current `zone_count`, and
    the computed `blowout_price_cents`." PRD §3.8: "The `blowout_price_cents` is the base
    fee of 4500 cents, plus the per-zone rate times the zone count, plus the pressure surcharge."

    Design: Corner/endpoints/blowout_quote_read_only_no_mutation
    """
    cust = create_customer(company_name="Ro Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=70)
    create_zone(sys["id"], 1, plant_type="TURF", head_count=4, gpm_per_head=18)
    create_zone(sys["id"], 2, plant_type="SHRUB", head_count=4, gpm_per_head=12)
    create_zone(sys["id"], 3, plant_type="DRIP", head_count=4, gpm_per_head=5)
    before = validate_success(api.get_system(sys["id"], DISPATCHER))
    version_before = before["version"]

    data = validate_success(api.get_blowout_quote(sys["id"], DISPATCHER))
    assert data["blowout_price_cents"] == 8100, (
        f"blowout_price_cents should be 8100, got {data['blowout_price_cents']}")

    after = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert after["version"] == version_before, (
        f"system version must be unchanged by a read, was {version_before} now {after['version']}")
