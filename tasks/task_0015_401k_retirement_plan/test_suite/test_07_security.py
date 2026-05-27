"""Role-based access control and authentication: 401 on missing headers,
403 on role-not-permitted, distinguished read/write permissions per role.

Corner queue B — Section: rbac.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_plan_payload,
    create_and_activate_plan,
    create_plan,
    build_user_headers,
)
from test_helpers.test_users import missing_headers

_ADMIN = TEST_USERS["plan_admin_headers"]
_CUSTODIAN = TEST_USERS["custodian_headers"]


def test_participant_cannot_create_plan(api):
    """PRD §2.1: "A request that authenticates successfully but whose declared role
    is not permitted to perform the requested operation per the authorization
    rules of §4 is rejected with `ERR_FORBIDDEN`."
    PRD §4: per the endpoint table, `POST /plans` is authorized for `PlanAdmin`
    only — Participant is not in the authorized role list.

    Design: Corner/rbac/participant_cannot_create_plan
    """
    participant_role_headers = build_user_headers(
        "00000000-0000-0000-0000-000000000001", "Participant",
    )
    res = api.create_plan(
        create_plan_payload(name="X", match_formula="TIERED", vesting_schedule="CLIFF_3"),
        participant_role_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_custodian_can_read_plan_but_cannot_activate(api):
    """PRD §2.1: "A request that authenticates successfully but whose declared role
    is not permitted to perform the requested operation per the authorization
    rules of §4 is rejected with `ERR_FORBIDDEN`."
    PRD §4: per the endpoint table, `GET /plans/{id}` lists Custodian as
    authorized; `POST /plans/{id}/activate` lists only PlanAdmin.

    Design: Corner/rbac/custodian_can_read_plans_but_not_activate
    """
    plan = create_plan(name="Cust", match_formula="TIERED",
                       vesting_schedule="CLIFF_3")
    # Custodian read succeeds
    read_res = api.get_plan(plan["id"], _CUSTODIAN)
    data = validate_success(read_res)
    assert data["id"] == plan["id"]
    # Custodian activate is forbidden
    res = api.activate_plan(plan["id"], _CUSTODIAN)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    # Plan remains DRAFT.
    refreshed = validate_success(api.get_plan(plan["id"], _ADMIN))
    assert refreshed["status"] == "DRAFT"


def test_missing_auth_headers_return_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, which
    identifies the acting user, and `X-User-Role`, which declares the operational
    capacity under which the request is made... A request that omits either
    header — or carries a header value the server cannot parse — is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_plans(headers=missing_headers())
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
