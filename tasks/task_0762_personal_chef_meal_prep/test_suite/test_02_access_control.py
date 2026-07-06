"""Role, ownership, and auth-header access control.

Queue B (Corner) translations from section `rbac`.
"""
from test_helpers import (
    validate_error,
    create_client, make_client_headers, make_chef_headers,
    setup_proposed_single_meal,
)


def test_chef_cannot_approve_menu_forbidden_role(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.4: "The client reviewing a `PROPOSED` menu has two moves."

    Design: Corner/rbac/chef_cannot_approve_menu_forbidden_role
    """
    ctx = setup_proposed_single_meal()
    # Approve is a Client-only action; the authoring Chef attempts it.
    res = api.approve_menu(ctx["menu"]["id"], make_chef_headers(ctx["chef"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_client_cannot_approve_another_clients_menu(api):
    """PRD §2.1: "For operations that mutate an ownership-scoped resource, if the
    entity-backed caller is not the owner of the target resource, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.1: "A `Client` owns its own dietary plans, its weekly menus (and, through
    them, those menus' meals), and its invoices."

    Design: Corner/rbac/client_cannot_approve_others_menu_ownership
    """
    ctx = setup_proposed_single_meal()
    other_client = create_client()
    # A different, valid Client role tries to approve client1's proposed menu.
    res = api.approve_menu(ctx["menu"]["id"], make_client_headers(other_client["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_request_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is
    rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/request_with_missing_required_auth_header_rejected
    """
    res = api.list_weekly_menus(headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")
