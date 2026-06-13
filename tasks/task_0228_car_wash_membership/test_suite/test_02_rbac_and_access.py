"""Role-based access control and authentication gates (PRD §2.1, §2.11, §4).

Translates queue-B (Corner) instances from the rbac section.
"""
from test_helpers import (
    validate_error,
    create_plan_payload, create_vehicle_payload,
    TEST_USERS, make_account_holder_headers,
    create_account,
    ABSENT_UUID,
)

PA = TEST_USERS["platform_admin_headers"]
LO = TEST_USERS["location_operator_headers"]
BA = TEST_USERS["billing_admin_headers"]


def test_location_operator_cannot_create_plan_forbidden(api):
    """PRD §2.1: "Once a request is authenticated, the system checks whether the declared
    role is permitted to perform the requested operation; if it is not, the request is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/location_operator_cannot_create_plan_forbidden
    """
    res = api.create_plan(create_plan_payload(name="Sneaky"), LO)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_account_holder_cannot_run_billing_forbidden(api):
    """PRD §2.1: "Once a request is authenticated, the system checks whether the declared
    role is permitted to perform the requested operation; if it is not, the request is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/account_holder_cannot_run_billing_forbidden
    """
    acct = create_account(contact_email="bil@x.com")
    res = api.billing_run({}, make_account_holder_headers(acct["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_account_holder_cannot_act_on_other_account_forbidden(api):
    """PRD §2.1: "An `AccountHolder` who targets a resource owned by a different account
    is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/account_holder_cannot_act_on_other_account_forbidden
    """
    acct_a = create_account(contact_email="own_a@x.com")
    acct_b = create_account(contact_email="own_b@x.com")
    # Holder A (X-User-ID = acct_a.id) tries to register a vehicle under acct_b.
    res = api.create_vehicle(
        acct_b["id"], create_vehicle_payload("OWN001", "CA"),
        make_account_holder_headers(acct_a["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or supplies a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`. This authentication check is the very first gate
    on every protected endpoint".

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.cancel_membership(ABSENT_UUID, {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
