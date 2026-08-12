"""Response envelopes, authentication, role authorization, and resident
ownership checks."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_household,
    create_household_payload,
    create_inspection_payload,
    create_route_payload,
    create_service_zone_payload,
    create_subscription_payload,
    create_subscription,
    create_zone,
    get_subscription,
    is_iso8601_timestamp,
    make_inspector_headers,
    make_resident_headers,
    validate_error,
    validate_success,
)


def test_response_envelope_object_shape(api, admin_headers, anonymous_headers):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`." and "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources." and "The `data` field contains the resource object or
    an array of resource objects."

    Design: Corner/endpoints/response_envelope_object_shape
    """
    zone = create_zone()
    res = api.create_household(create_household_payload(zone["id"], address_line="1 Oak St"),
                               anonymous_headers)
    assert res.status_code == 201
    body = res.json()

    assert "meta" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", ""))
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)
    household_id = body["data"]["id"]
    assert household_id

    get_res = api.get_household(household_id, admin_headers)
    assert get_res.json()["data"]["id"] == household_id


def test_error_envelope_shape_on_failure(api, admin_headers):
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error." and
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    res = api.get_household(NON_EXISTENT_UUID, admin_headers)
    assert res.status_code == 404
    body = res.json()

    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_HOUSEHOLD_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"]
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_household_get_missing_headers_unauthenticated(api):
    """PRD section 2.1: "A request with a missing or unrecognized role header,
    or a missing user identifier, is rejected with `ERR_UNAUTHENTICATED`."
    PRD section 2.8: authentication is step 1, before path existence (step 4).

    Design: Corner/validations/household_get_missing_headers_unauthenticated
    """
    res = api.get_household(NON_EXISTENT_UUID, headers={})
    assert res.status_code == 401
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_resident_cannot_pay_others_subscription(api, admin_headers):
    """PRD section 2.1: "ownership checks on any resource that references a
    household compare the resource's `household_id` (or the household reached
    through its subscription or ticket) to `X-User-ID`, and a mismatch is
    rejected with `ERR_RESIDENT_NOT_OWNER`."

    Design: Corner/validations/resident_cannot_pay_others_subscription
    """
    zone = create_zone()
    hh_a = create_household(zone["id"], "1 Oak St")
    hh_b = create_household(zone["id"], "9 Birch Ave")
    sub_a = create_subscription(hh_a, season_year=2026)
    assert sub_a["status"] == "PENDING_PAYMENT"

    res = api.pay_subscription(sub_a["id"], {"use_credit_balance": False},
                               make_resident_headers(hh_b["id"]))
    validate_error(res, ApiErrorId.ERR_RESIDENT_NOT_OWNER)
    assert get_subscription(sub_a["id"])["status"] == "PENDING_PAYMENT"


def test_resident_cannot_create_zone(api, resident_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 4:
    POST /service-zones is authorized for ProgramAdmin only.

    Design: Corner/rbac/resident_cannot_create_zone
    """
    res = api.create_service_zone(
        create_service_zone_payload(name="Rogue"), resident_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_inspector_cannot_validate_missed(api, inspector_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 4:
    POST /pickup-tickets/{id}/validate-missed is authorized for RouteSupervisor
    only — a FieldInspector is denied before any ticket existence check.

    Design: Corner/rbac/inspector_cannot_validate_missed
    """
    res = api.validate_missed_pickup_ticket(NON_EXISTENT_UUID, {"validated": True},
                                            inspector_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_clerk_cannot_create_inspection(api, clerk_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 4:
    POST /contamination-inspections is authorized for FieldInspector only.

    Design: Corner/rbac/clerk_cannot_create_inspection
    """
    res = api.create_contamination_inspection(
        create_inspection_payload(NON_EXISTENT_UUID, result="PASSED", violation_codes=[]),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_anonymous_cannot_create_subscription(api, admin_headers, anonymous_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 4:
    POST /subscriptions is authorized for Resident only; `Anonymous` is a
    declared role, so the request is authenticated yet role-denied.

    Design: Corner/rbac/anonymous_cannot_create_subscription
    """
    zone = create_zone()
    household = create_household(zone["id"], "1 Oak St")
    res = api.create_subscription(
        create_subscription_payload(household["id"], household["version"], season_year=2026),
        anonymous_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_program_admin_cannot_launch_campaign(api, admin_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 3.9:
    "Education and outreach are run by an `OutreachCoordinator`, segregated
    from program administration." PRD section 4: POST
    /outreach-campaigns/{id}/launch is authorized for OutreachCoordinator only.

    Design: Corner/rbac/program_admin_cannot_launch_campaign
    """
    res = api.launch_outreach_campaign(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_coordinator_cannot_create_route(api, coordinator_headers):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD section 4:
    POST /routes is authorized for ProgramAdmin only.

    Design: Corner/rbac/coordinator_cannot_create_route
    """
    res = api.create_route(
        create_route_payload(NON_EXISTENT_UUID), coordinator_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
