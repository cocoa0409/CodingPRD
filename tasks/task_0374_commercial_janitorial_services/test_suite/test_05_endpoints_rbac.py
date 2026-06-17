"""Action endpoints, supply-order lifecycle, error-envelope shape, RBAC, and
immediate-consistency claims.

Translates SCAFFOLD_CORNER_DESIGN.yaml §1.9 `endpoints`, `errors`, `rbac`,
and `consistency_model` non-stub instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures,
    create_account_payload, create_site_payload, create_supply_order_payload,
    create_visit_payload, create_complaint_payload,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
CC = TEST_USERS["client_contact_headers"]


# --- endpoints section ---

def test_suspend_account_then_create_site_blocked(api):
    """PRD §3.1: "An account may be moved to `SUSPENDED` status, which blocks the
    creation of new sites, visits, and contracts beneath it; a suspended (or
    `CLOSED`) account is no longer `ACTIVE`, and any operation that requires the
    owning account to be `ACTIVE` will be refused with `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Corner/endpoints/suspend_account_then_create_site_blocked
    """
    acct = fixtures.create_account()
    suspended = validate_success(api.suspend_account(acct["id"], AM), 200)
    assert suspended["status"] == "SUSPENDED"
    resp = api.create_site(create_site_payload(acct["id"]), AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_supply_order_fulfill_action_transitions_to_fulfilled(api):
    """PRD §3.10: "A `FieldSupervisor` may fulfill a requested order, advancing it
    `REQUESTED → FULFILLED`."

    Design: Corner/endpoints/supply_order_fulfill_action_transitions_to_fulfilled
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    order = validate_success(api.create_supply_order(
        create_supply_order_payload(site["id"], sku="PAPER_TOWEL", quantity=5), FS), 201)
    resp = api.fulfill_supply_order(order["id"], FS)
    data = validate_success(resp, 200)
    assert data["status"] == "FULFILLED"


def test_cancel_supply_order_from_fulfilled_returns_invalid_state(api):
    """PRD §3.10: "Each transition requires the order to be in `REQUESTED` status;
    otherwise it is refused with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/cancel_supply_order_from_fulfilled_returns_invalid_state
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    order = validate_success(api.create_supply_order(
        create_supply_order_payload(site["id"], sku="TRASH_LINER", quantity=10), FS), 201)
    validate_success(api.fulfill_supply_order(order["id"], FS), 200)
    resp = api.cancel_supply_order(order["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_supply_order(order["id"], AM), 200)
    assert after["status"] == "FULFILLED"


def test_cancel_periodic_job_from_requested_succeeds(api):
    """PRD §3.6: "A periodic job opens in `REQUESTED` status. From `REQUESTED`, an
    `AccountManager` may cancel it, transitioning it `REQUESTED → CANCELLED`."

    Design: Corner/endpoints/cancel_periodic_job_from_requested_succeeds
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"], floor_type="VCT")
    job = fixtures.create_periodic_job(site["id"], job_type="STRIP_WAX", quoted_hours=2)
    resp = api.cancel_periodic_job(job["id"], AM)
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"


def test_list_visits_filtered_by_billing_period(api):
    """PRD §3.5: "The completed visit's `billing_period_id` is set to that period."
    PRD §4 (GET /visits): "List visits with filters".

    Design: Corner/endpoints/list_visits_filtered_by_billing_period
    """
    bundle = fixtures.setup_billing_scenario()
    visit = fixtures.create_completed_routine_visit(
        bundle["site"]["id"], bundle["crew"]["id"], service_date="2026-06-10",
        planned_start_min=540, planned_end_min=600)
    resp = api.list_visits(AM, params={"billing_period_id": bundle["period"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["billing_period_id"] == bundle["period"]["id"]
    assert data[0]["id"] == visit["id"]


# --- errors section ---

def test_response_envelope_error_shape_on_validation_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with `response_type: "error"` and `data` carrying `error_id`
    and `message`, and `meta` carrying `api_request_id` and `api_request_timestamp`.

    Design: Corner/errors/response_envelope_error_shape_on_validation_failure
    """
    resp = api.create_account({"name": "Acme"}, AM)  # missing billing_email
    error_data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and len(error_data["message"]) > 0
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


# --- rbac section ---

def test_field_supervisor_cannot_create_account_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation under the matrix in §4, the request is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: POST `/accounts` is
    authorized for AccountManager only.

    Design: Corner/rbac/field_supervisor_cannot_create_account_returns_forbidden
    """
    resp = api.create_account(create_account_payload(), FS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_client_contact_cannot_create_visit_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation under the matrix in §4, the request is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: POST `/visits` is
    authorized for FieldSupervisor only.

    Design: Corner/rbac/client_contact_cannot_create_visit_returns_forbidden
    """
    _, site, crew = fixtures.setup_account_site_crew()
    resp = api.create_visit(create_visit_payload(site["id"], crew["id"]), CC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_client_contact_raise_complaint_wrong_site_returns_not_site_contact(api):
    """PRD §2.1: "When a `ClientContact` attempts to raise or reopen a complaint,
    or to read a site-scoped record, for a site whose `contact_user_id` does not
    match the caller's `X-User-ID`, the request is rejected with
    `ERR_NOT_SITE_CONTACT` (HTTP 403)."

    Design: Corner/rbac/client_contact_raise_complaint_wrong_site_returns_not_site_contact
    """
    from test_helpers.test_users import make_client_contact_headers
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"], contact_user_id="cc-1")
    headers = make_client_contact_headers("cc-999")
    resp = api.create_complaint(
        create_complaint_payload(site["id"], severity="MINOR", description="Not my site"), headers)
    validate_error(resp, ApiErrorId.ERR_NOT_SITE_CONTACT.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_accounts({})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --- consistency_model section ---

def test_immediate_consistency_periodic_capture_visible_same_request(api):
    """PRD §3.5: "Capturing the visit recomputes the period's running totals: for
    a `PERIODIC` visit the period's `periodic_cents` grows by the visit's periodic
    charge (see §3.6), and the period's `total_cents` is recomputed by the
    provisional total formula of §3.8."

    Design: Corner/consistency_model/immediate_consistency_periodic_capture_visible_same_request
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000})
    fixtures.setup_completed_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"], 480, 600,
        job_overrides={"quoted_hours": 2})
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period["periodic_cents"] == 12000
    assert period["total_cents"] == 312000  # 300000 + 12000 provisional
