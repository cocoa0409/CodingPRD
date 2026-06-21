"""Role-based access control: exclusive-operation enforcement, entity-backed ownership, and the
user-context header check.

Queue B: rbac-section corner instances.
"""
import pytest
from test_helpers import (
    validate_error,
    create_commissary, create_truck,
    api_client, TEST_USERS, build_user_headers,
    issue_health_permit_payload, create_menu_item_payload,
    create_commissary_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_dispatcher_cannot_issue_permit(api):
    """PRD §2.1: "When a role attempts an operation it is not authorized to perform under the
    authorization rules described throughout this document, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §3.2: "the regulatory dimension owned by the HealthInspector role (and, as superset,
    PlatformAdmin)."

    A Dispatcher attempting to issue a health permit is rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/dispatcher_cannot_issue_permit
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    res = api.issue_health_permit(issue_health_permit_payload(truck["id"]), DISPATCHER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_truck_cannot_act_on_other_trucks_menu(api):
    """PRD §2.1: "an OperatorTruck principal may only act on menu items, prep batches, staff
    shifts, utility logs, orders, order lines, and bookings whose owning truck is itself; a write
    against a resource owned by a different truck is rejected with ERR_FORBIDDEN_ROLE."

    OperatorTruck A (X-User-ID = truck A) adding a menu item with truck_id of truck B is rejected
    with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/truck_cannot_act_on_other_trucks_menu
    """
    commissary = create_commissary()
    truck_a = create_truck(commissary["id"], name="A")
    truck_b = create_truck(commissary["id"], name="B")
    headers_a = build_user_headers(truck_a["id"], "OperatorTruck")
    res = api.create_menu_item(create_menu_item_payload(truck_b["id"]), headers_a)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing, or if the value of X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT
    (HTTP 400)."

    A request with an unrecognized X-User-Role is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT before any business logic.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = build_user_headers("someone", "NotARealRole")
    res = api.create_commissary(create_commissary_payload(), bad_headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT")
