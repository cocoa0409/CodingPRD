"""Authentication / RBAC tests: missing-role rejection, peer-role denial of exclusive ops,
and entity-backed Account ownership scoping."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures as fx,
    make_account_headers,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


def test_missing_role_header_returns_unauthenticated(api):
    """PRD 2.1: "If X-User-Role is missing or does not name one of the four recognized roles,
    the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_role_header
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    resp = api.get_account(acct["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_customer_service_cannot_create_rate_schedule(api):
    """PRD 2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)." PRD 2.1: "A
    BillingAdmin owns rate and PGA configuration".

    Design: Corner/rbac/customer_service_cannot_create_rate_schedule_forbidden
    """
    resp = api.create_rate_schedule(
        {"code": "RES-RB1", "customer_class": "RESIDENTIAL", "fixed_customer_charge_cents": 1200,
         "distribution_rate_cents_per_therm": 15, "btu_factor": 1.025, "minimum_bill_cents": 0},
        headers=CS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_field_tech_cannot_issue_bill(api):
    """PRD 2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)." PRD 2.1: "A
    BillingAdmin owns ... bill creation/issuance/voiding".

    Design: Corner/rbac/field_tech_cannot_issue_bill_forbidden
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    resp = api.issue_bill(acct["id"], draft["id"],
                          {"expected_account_version": fx.account_version(acct["id"])}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_account_cannot_dispatch_service_order(api):
    """PRD 2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)." PRD 2.1: "A FieldTech
    owns field operations: meter removal, posting reads, service-order dispatch and
    completion".

    Design: Corner/rbac/account_cannot_dispatch_service_order_forbidden
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    resp = api.dispatch_service_order(order["id"], headers=make_account_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_account_cannot_read_another_accounts_data(api):
    """PRD 2.1: "Ownership checks on any resource that references an account compare that
    resource's account_id to X-User-ID; an Account principal acting on a resource whose
    account_id is not its own is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/account_cannot_read_another_accounts_data_forbidden
    """
    rs = fx.create_rate_schedule()
    acct_a = fx.create_account(rs["id"], holder_name="RB4-A")
    acct_b = fx.create_account(rs["id"], holder_name="RB4-B")
    # Acting as account A (X-User-ID = A.id), read account B.
    resp = api.get_account(acct_b["id"], headers=make_account_headers(acct_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_account_can_post_own_payment(api):
    """PRD 2.1: "An Account is the customer self-service role: it may read its own account and
    child collections, submit its own low-income application, post its own payment, and open
    an emergency ticket." PRD 3.12: "A payment is posted by a CustomerService operator or by
    the Account principal itself".

    Design: Corner/rbac/account_can_post_own_payment_shared_op
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    resp = api.create_payment(
        acct["id"], {"bill_id": issued["id"], "amount_cents": 6326,
                     "posted_date": "2026-03-01T00:00:00.000Z"},
        headers=make_account_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "POSTED", f"got {data['status']}"
    bill = fx.get_success_data(api.get_bill(issued["id"], headers=ADMIN))
    assert bill["status"] == "PAID", f"got {bill['status']}"
