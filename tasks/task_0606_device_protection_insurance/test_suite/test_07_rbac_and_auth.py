"""Authentication, role authorization, and resource ownership.

Covers corner-design rbac instances.
"""
from test_helpers import (
    validate_error, ApiErrorId, build_user_headers, create_plan_payload,
)
from test_helpers import fixtures as fx


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_enrollments({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_logistics_agent_cannot_create_plan(api, logistics_headers):
    """PRD 2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/logistics_agent_cannot_create_plan_forbidden
    """
    resp = api.create_plan(create_plan_payload(code="PLAN_X"), logistics_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_subscriber_cannot_approve_claim(api, admin_headers, adjuster_headers):
    """PRD 2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/subscriber_cannot_approve_claim_forbidden
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-20")
    enr = base["enrollment"]
    cust_id = base["customer"]["id"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z",
                         as_headers=fx.make_subscriber_headers(cust_id))
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    resp = api.approve_claim(cl["id"], {"expected_enrollment_version": enr_v},
                             fx.make_subscriber_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_subscriber_cannot_withdraw_other_customers_claim(api, admin_headers):
    """PRD 2.1: "A `Subscriber` acting on a `Claim` or `Enrollment` they do not own is
    rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.4: "A subscriber who is not the owner is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/subscriber_cannot_act_on_other_customers_claim
    """
    fx.set_clock()
    cust_a = fx.create_customer(carrier_account_number="CA-CN-21A", full_name="AnnA")
    cust_b = fx.create_customer(carrier_account_number="CA-CN-21B", full_name="AnnB")
    plan = fx.create_plan()
    sku = fx.create_sku()
    enr = fx.create_enrollment(cust_a["id"], plan["id"], sku["id"])
    # Activate at an early instant so enrolled_at precedes the 2026-05-10 incident, then
    # restore the clock to the default so the incident is at/before the current clock.
    fx.set_clock(fx.C.ENROLL_CLOCK)
    enr = fx.get_success_data(api.activate_enrollment(enr["id"], admin_headers))
    fx.set_clock(fx.C.CLOCK_DEFAULT)
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z",
                         as_headers=fx.make_subscriber_headers(cust_a["id"]))
    resp = api.withdraw_claim(cl["id"], fx.make_subscriber_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
