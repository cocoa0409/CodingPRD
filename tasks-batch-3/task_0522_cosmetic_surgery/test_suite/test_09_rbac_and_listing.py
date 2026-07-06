"""Role-based access control, ownership, authentication, and list pagination envelope."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, PROC_A, build_user_headers,
    create_procedure, create_accepted_quote, create_patient,
    make_surgeon_headers,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_frontdesk_cannot_approve_financing(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation (per the authorization column of the endpoint table
    in §4), the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/rbac_frontdesk_cannot_approve_financing
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    fin = get_success_data(api.submit_financing(
        {"quote_package_id": quote["id"], "lender": "CHERRY",
         "requested_amount_cents": 100000}, BILLING))
    # approve is a BillingSpecialist-exclusive op; FrontDeskCoordinator is forbidden.
    resp = api.approve_financing(fin["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_surgeon_not_owner_cannot_complete_consultation(api):
    """PRD §2.4: "Completing a consultation is permitted only to the surgeon whose
    X-User-ID equals the surgeon_user_id recorded on that Consultation; a mismatch is
    rejected with ERR_NOT_OWNER (HTTP 403)."

    Design: Corner/rbac/rbac_surgeon_not_owner_cannot_complete_consultation
    """
    patient = create_patient()
    cons = get_success_data(api.create_consultation(
        {"patient_id": patient["id"], "surgeon_user_id": "surgeon-1",
         "chief_complaint": "nose"}, FRONT))
    # a different surgeon (surgeon-2) attempts to complete surgeon-1's consultation
    resp = api.complete_consultation(cons["id"], make_surgeon_headers("surgeon-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER, 403)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the four
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/rbac_unauthenticated_missing_headers
    """
    bad_headers = build_user_headers("someone", "NoSuchRole")
    resp = api.list_procedures(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_list_procedures_pagination_envelope(api):
    """PRD §2.3: "For list responses, the meta object carries the pagination fields
    limit, offset, total_count (the total number of matching records ignoring
    pagination), and has_more (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_procedures_pagination_envelope
    """
    create_procedure(code="P1", name="One", surgical_fee_cents=100000,
                     facility_fee_cents=0, anesthesia_fee_cents=0)
    create_procedure(code="P2", name="Two", surgical_fee_cents=200000,
                     facility_fee_cents=0, anesthesia_fee_cents=0)
    resp = api.list_procedures(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
