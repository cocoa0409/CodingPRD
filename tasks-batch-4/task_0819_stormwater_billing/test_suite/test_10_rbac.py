"""Role authorization and PropertyOwner resource-ownership enforcement."""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
    create_bill_payload,
    make_property_owner_headers,
    create_active_parcel, setup_appeal_under_review, setup_issued_bill,
)

ASSESSOR = TEST_USERS["assessor_headers"]


def test_propertyowner_cannot_issue_bill(api):
    """PRD §2.1: "When the headers are well formed but the named role is not
    permitted to perform the requested operation under the access matrix in
    Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/bills` | Issue a stormwater bill snapshotting current ERU
    and credit. | BillingClerk"

    Design: Corner/rbac/propertyowner_cannot_issue_bill
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    resp = api.create_bill(
        create_bill_payload(base["parcel"]["id"], base["account"]["id"]),
        make_property_owner_headers(base["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_assessor_cannot_decide_appeal(api):
    """PRD §2.1: "When the headers are well formed but the named role is not
    permitted to perform the requested operation under the access matrix in
    Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/appeals/{id}/decide` | Uphold or deny an appeal; UPHELD
    re-assesses the linked bill. | StormwaterAdmin"

    Design: Corner/rbac/assessor_cannot_decide_appeal
    """
    base = setup_appeal_under_review(api, grounds="MEASUREMENT_ERROR", measured_sqft=9000)
    resp = api.decide_appeal(base["appeal"]["id"], {"outcome": "DENIED"}, ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_owner_cannot_read_other_accounts_bill(api):
    """PRD §2.1: "When a `PropertyOwner` acts on a resource whose owning account
    is not their own, the request is rejected with `ERR_FORBIDDEN_OWNERSHIP`
    (HTTP 403)."

    Design: Corner/rbac/owner_cannot_read_other_accounts_bill
    """
    acct_a = api.create_account({"owner_name": "A", "contact_email": "a@x.com"}, ASSESSOR)
    acct_a_id = acct_a.json()["data"]["id"]
    # Account B owns the parcel and the bill.
    base_b = setup_issued_bill(api, measured_sqft=9000, land_use="COMMERCIAL")
    resp = api.get_bill(base_b["bill"]["id"], make_property_owner_headers(acct_a_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)
