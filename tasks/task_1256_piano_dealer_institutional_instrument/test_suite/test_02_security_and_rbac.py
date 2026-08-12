"""Authentication, role authorization, and segregation of duties (PRD §2.1, §2.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, build_user_headers,
    create_customer_payload, create_instrument_payload, bid_line,
    create_customer, create_instrument, create_bid, submit_bid,
    create_appraisal, evaluate_appraisal,
)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the capacity in which they act. A request missing
    either header, or presenting a role the system does not declare, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    ghost_headers = build_user_headers("ghost-1", "Ghost")
    res = api.create_customer(
        create_customer_payload(full_name="Ghost User", email="ghost@x.com",
                                customer_type="INDIVIDUAL"),
        ghost_headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_customer_cannot_intake_instrument(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: the intake endpoint `POST /piano-dealer/instruments` lists StoreManager as its
    only authorized role.

    Design: Corner/rbac/customer_cannot_intake_instrument
    """
    customer = create_customer(full_name="Nosy Nell", email="nell@x.com")
    headers = build_user_headers(customer["id"], "Customer")
    res = api.create_instrument(
        create_instrument_payload(serial_number="SN-NO-1", list_price_cents=300_000,
                                  floor_price_cents=200_000),
        headers)
    validate_error(res, "ERR_UNAUTHORIZED_ROLE")


def test_customer_cannot_counter_another_customers_appraisal(api, store_manager_headers):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `Customer`; ownership checks on any resource that references a `Customer` compare the
    resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with
    `ERR_UNAUTHORIZED_ROLE`."
    PRD §3.2: "Any of these self-service actions attempted under another user's identity is
    rejected with `ERR_UNAUTHORIZED_ROLE`, and any of them attempted while the appraisal is
    not `OFFERED` is rejected with `ERR_APPRAISAL_NOT_OFFERED`."

    Design: Corner/rbac/customer_cannot_counter_another_customers_appraisal
    """
    owner = create_customer(full_name="Owner Ann", email="oa@x.com")
    intruder = create_customer(full_name="Intruder Ian", email="ii@x.com")
    appraisal = create_appraisal(owner["id"], category="UPRIGHT", manufacturer="Kawai",
                                 model="K300", year_built=2016, condition_grade="EXCELLENT")
    evaluate_appraisal(appraisal["id"], 0, 0.0)

    res = api.counter_appraisal(appraisal["id"], {"counter_value_cents": 700_000},
                                build_user_headers(intruder["id"], "Customer"))
    validate_error(res, "ERR_UNAUTHORIZED_ROLE")

    after = validate_success(api.get_trade_in_appraisal(appraisal["id"],
                                                        build_user_headers(owner["id"], "Customer")), 200)
    assert after["status"] == "OFFERED", "rejected counter must not change appraisal state"


def test_bid_self_approval_rejected(api):
    """PRD §2.1: "Segregation of duties is enforced on bid approval: a `ComplianceOfficer`
    whose `X-User-ID` equals the bid's recorded `prepared_by_user_id` may not approve that
    bid, and the attempt is rejected with `ERR_SOD_SELF_APPROVAL` (HTTP 403)."
    PRD §3.3: "Approval carries the segregation-of-duties rule of §2.1: an officer whose
    identity matches the package's `prepared_by_user_id` is rejected with
    `ERR_SOD_SELF_APPROVAL`."

    Design: Corner/rbac/bid_self_approval_rejected
    """
    customer = create_customer(full_name="SOD County", email="buy@sod.gov",
                               customer_type="INSTITUTIONAL", institution_type="GOVERNMENT",
                               state_contract_ceiling_cents=900_000)
    instrument = create_instrument(serial_number="SN-SOD-1")
    bid = create_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                     officer_user_id="ibo-self")
    submit_bid(bid["id"], officer_user_id="ibo-self")

    res = api.compliance_approve_bid(bid["id"], build_user_headers("ibo-self", "ComplianceOfficer"))
    validate_error(res, "ERR_SOD_SELF_APPROVAL")
    after = validate_success(api.get_bid_package(
        bid["id"], build_user_headers("co-other", "ComplianceOfficer")), 200)
    assert after["status"] == "SUBMITTED", "self-approval rejection must not change bid state"

    approved = validate_success(api.compliance_approve_bid(
        bid["id"], build_user_headers("co-other", "ComplianceOfficer")), 200)
    assert approved["status"] == "APPROVED", "a different officer approves successfully"


def test_sales_associate_cannot_approve_bid(api, sales_associate_headers):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: `POST /piano-dealer/bid-packages/{id}/compliance-approve` lists ComplianceOfficer
    as its only authorized role.

    Design: Corner/rbac/sales_associate_cannot_approve_bid
    """
    customer = create_customer(full_name="Role Tech", email="rt@role.edu",
                               customer_type="INSTITUTIONAL", institution_type="EDUCATION")
    instrument = create_instrument(serial_number="SN-RB-1")
    bid = create_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                     officer_user_id="ibo-rb")
    submit_bid(bid["id"], officer_user_id="ibo-rb")

    res = api.compliance_approve_bid(bid["id"], sales_associate_headers)
    validate_error(res, "ERR_UNAUTHORIZED_ROLE")
