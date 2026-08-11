"""Authentication and role-based access control (PRD §2.1, §2.9, §4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_production_payload, create_policy_payload,
    create_clearance_item_payload,
    set_logical_clock, create_production, get_production_version,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]


def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "A request that is missing either header, or whose header
    values are malformed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_returns_401
    """
    set_logical_clock()
    res = api.list_productions(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_production_manager_cannot_bind_policy(api):
    """PRD §2.1: "A request whose role is well-formed but not authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: binding a policy is listed under Authorized Role `BrokerAgent`.

    Design: Corner/rbac/production_manager_cannot_bind_policy
    """
    set_logical_clock()
    prod = create_production()
    policy = validate_success(
        api.create_policy(prod["id"], create_policy_payload(), BROKER), 201)
    version = get_production_version(prod["id"])
    res = api.bind_policy(prod["id"], policy["id"],
                          {"expected_production_version": version}, PM)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_claims_adjuster_cannot_create_clearance_item(api):
    """PRD §2.1: "A request whose role is well-formed but not authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: creating a clearance item is listed under Authorized Role
    `ClearanceCounsel`.

    Design: Corner/rbac/claims_adjuster_cannot_create_clearance_item
    """
    set_logical_clock()
    prod = create_production(production_type="FEATURE")
    res = api.create_clearance_item(prod["id"], create_clearance_item_payload(), ADJ)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
