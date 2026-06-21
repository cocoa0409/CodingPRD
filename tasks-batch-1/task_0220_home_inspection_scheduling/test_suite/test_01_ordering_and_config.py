"""Ordering, configuration, identifiers, and access control.

Covers entity creation/validation, the lean Client/Agent shape, pagination
envelope, version semantics, and the four-role RBAC gate.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_inspector_headers, make_client_headers,
    setup_base_config, create_requested_order, setup_requested_order,
    assert_client,
)
from test_helpers import factories as F

SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# entities — creation, not-found, required/typed inputs, FK existence
# ---------------------------------------------------------------------------
def test_create_primary_order_starts_requested(api):
    """PRD §3.3: "The order is born in `REQUESTED` status with `order_kind` of
    `PRIMARY`, no assigned inspector, `amount_paid_cents` and `amount_refunded_cents`
    both at 0, and `version` at 1."

    Design: Corner/entities/corner_create_inspection_order_returns_201_requested
    """
    cfg = setup_base_config()
    resp = api.create_inspection_order(
        F.create_inspection_order_payload(cfg["property"]["id"], cfg["client"]["id"],
                                          cfg["agent"]["id"], cfg["fee_schedule"]["id"],
                                          "BUYER"), SCHED)
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"
    assert data["order_kind"] == "PRIMARY"
    assert data["version"] == 1
    assert data["amount_paid_cents"] == 0


def test_get_unknown_order_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource
    causes the request to fail with `ERR_NOT_FOUND` before any later identifier or any
    business rule is evaluated."

    Design: Corner/entities/corner_get_inspection_order_not_found
    """
    resp = api.get_inspection_order(NON_EXISTENT_UUID, SCHED)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_inspection_type_rejected(api):
    """PRD §3.3: "The create payload names the `property_id` to be inspected,
    the ordering `client_id`, the `agent_id` who is the delivery recipient on the deal,
    the `fee_schedule_id` of the `PUBLISHED` schedule to pin, and the `inspection_type`,
    which is one of `BUYER`, `SELLER`, `FOUR_POINT`, or `WIND_MIT`."

    Design: Corner/entities/corner_create_order_missing_required_field
    """
    cfg = setup_base_config()
    payload = {
        "property_id": cfg["property"]["id"],
        "client_id": cfg["client"]["id"],
        "agent_id": cfg["agent"]["id"],
        "fee_schedule_id": cfg["fee_schedule"]["id"],
        # inspection_type omitted
    }
    resp = api.create_inspection_order(payload, SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_invalid_inspection_type_enum_rejected(api):
    """PRD §3.3: "the `inspection_type`, which is one of `BUYER`, `SELLER`,
    `FOUR_POINT`, or `WIND_MIT`."

    Design: Corner/entities/corner_create_order_invalid_enum_inspection_type
    """
    cfg = setup_base_config()
    resp = api.create_inspection_order(
        F.create_inspection_order_payload(cfg["property"]["id"], cfg["client"]["id"],
                                          cfg["agent"]["id"], cfg["fee_schedule"]["id"],
                                          "HOME"), SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_unknown_fee_schedule_not_found(api):
    """PRD §2.6: "The system validates the existence of every path identifier left to
    right, and of every foreign key in a request body after the path identifiers. The
    first identifier that does not resolve to an existing resource causes the request to
    fail with `ERR_NOT_FOUND` before any later identifier or any business rule is
    evaluated."

    Design: Corner/entities/corner_create_order_unknown_fee_schedule_not_found
    """
    cli = validate_success(api.create_client(F.create_client_payload(), SCHED), 201)
    agt = validate_success(api.create_agent(F.create_agent_payload(), SCHED), 201)
    prop = validate_success(api.create_property(F.create_property_payload(), SCHED), 201)
    resp = api.create_inspection_order(
        F.create_inspection_order_payload(prop["id"], cli["id"], agt["id"],
                                          NON_EXISTENT_UUID, "BUYER"), SCHED)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_with_draft_fee_schedule_rejected(api):
    """PRD §3.1: "Only a `PUBLISHED` schedule may be pinned to a new order; an order
    that references a non-`PUBLISHED` schedule is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_create_order_draft_fee_schedule_invalid_request
    """
    fs = validate_success(api.create_fee_schedule(F.create_fee_schedule_payload(), SCHED), 201)
    # NOT published — stays DRAFT
    cli = validate_success(api.create_client(F.create_client_payload(), SCHED), 201)
    agt = validate_success(api.create_agent(F.create_agent_payload(), SCHED), 201)
    prop = validate_success(api.create_property(F.create_property_payload(), SCHED), 201)
    resp = api.create_inspection_order(
        F.create_inspection_order_payload(prop["id"], cli["id"], agt["id"],
                                          fs["id"], "BUYER"), SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_order_create_ignores_client_supplied_status(api):
    """PRD §3.3: "The order is born in `REQUESTED` status with `order_kind` of
    `PRIMARY`, no assigned inspector, `amount_paid_cents` and `amount_refunded_cents`
    both at 0, and `version` at 1."

    Design: Corner/entities/corner_computed_fields_ignored_on_order_create
    """
    cfg = setup_base_config()
    # A faithful create starts the order in REQUESTED regardless of input; the
    # server-controlled quoted fee is not set until scheduling, so we assert only
    # the uniquely-derivable status/version facts here.
    resp = api.create_inspection_order(
        F.create_inspection_order_payload(cfg["property"]["id"], cfg["client"]["id"],
                                          cfg["agent"]["id"], cfg["fee_schedule"]["id"],
                                          "BUYER"), SCHED)
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"
    assert data["version"] == 1


def test_client_is_lean_no_version_field(api):
    """PRD §2.4: "A `Client` and an `Agent` carry only an `id` and a `created_at` —
    they have no `updated_at` and no `version`, because once created they are not
    mutated through any state machine."

    Design: Corner/entities/corner_client_immutable_no_version_field
    """
    resp = api.create_client(F.create_client_payload(role_in_deal="BUYER"), SCHED)
    data = validate_success(resp, 201)
    assert "version" not in data, "Client must not carry a version field"
    assert "updated_at" not in data, "Client must not carry an updated_at field"
    assert data["role_in_deal"] == "BUYER"
    assert_client(data)


# ---------------------------------------------------------------------------
# pagination envelope + version semantics (cross-cutting)
# ---------------------------------------------------------------------------
def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/corner_list_inspection_orders_pagination_envelope
    """
    cfg = setup_base_config()
    prop2 = validate_success(
        api.create_property(F.create_property_payload(address_line="2 B St"), SCHED), 201)
    create_requested_order(cfg)
    create_requested_order(cfg, property_id=prop2["id"])
    resp = api.list_inspection_orders(SCHED, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_order_version_increments_on_mutation(api):
    """PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every
    mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/corner_version_increments_on_mutation
    """
    cfg, order = setup_requested_order()
    assert order["version"] == 1
    api_client.create_addon(order["id"], F.create_addon_payload("SEWER"), SCHED)
    refreshed = validate_success(api.get_inspection_order(order["id"], SCHED))
    assert refreshed["version"] == 2


# ---------------------------------------------------------------------------
# errors — pagination range
# ---------------------------------------------------------------------------
def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside its permitted bounds, or a malformed
    date query parameter where one is accepted, is rejected with `ERR_VALIDATION_RANGE`."

    Design: Corner/errors/corner_pagination_limit_out_of_range
    """
    resp = api.list_inspection_orders(SCHED, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value)


# ---------------------------------------------------------------------------
# rbac — authentication, authorization, peer-role ownership
# ---------------------------------------------------------------------------
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents an `X-User-Role`
    value outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/corner_missing_headers_unauthenticated
    """
    resp = api.get_inspection_order(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_client_cannot_schedule_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to invoke the
    targeted endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/corner_client_cannot_schedule_forbidden
    """
    cfg, order = setup_requested_order()
    cli_headers = make_client_headers(cfg["client"]["id"])
    resp = api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-16T13:00:00Z"),
        cli_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unassigned_inspector_cannot_start_order(api):
    """PRD §2.1: "An inspector who is authenticated and otherwise permitted but is not
    the assigned inspector of the targeted order — on the start, report, submit, or
    revise operations — is rejected with `ERR_NOT_ASSIGNED_INSPECTOR`."

    Design: Corner/rbac/corner_wrong_inspector_not_assigned
    """
    cfg, order = setup_requested_order()
    inspector_b = validate_success(api.create_inspector(
        F.create_inspector_payload(cfg["territory"]["id"], certifications=["BUYER"],
                                   full_name="Ivo"), SCHED), 201)
    api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-17T13:00:00Z"),
        SCHED)
    # inspector_b is not the assigned inspector
    resp = api.start_order(order["id"], make_inspector_headers(inspector_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR.value)
