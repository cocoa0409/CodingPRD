"""Authentication, role authorization, entity-backed ownership, and case withdrawal.

Translates queue-B corner instances from the validations and state_machines sections.
"""
from test_helpers import (
    validate_success, validate_error, make_counselor_headers, make_lab_headers,
    create_case_payload,
    create_family, create_counselor, create_lab, create_case, add_member,
    assess_risk, create_signed_testing_consent, create_order, submit_order, enter_result,
)
from test_helpers.test_users import TEST_USERS

BILLING = TEST_USERS["billing_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed value, is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/get_family_missing_header_unauthenticated
    """
    fam = create_family(name="Kindred S")
    res = api.get_family(fam["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_billing_role_cannot_create_case(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN." PRD
    2.1: "A GeneticCounselor is the clinical owner and drives cases, pedigrees, consent,
    sessions, orders, disclosure, cascade outreach, surveillance plans, and referrals."

    Design: Corner/validations/billing_role_cannot_create_case_forbidden
    """
    fam = create_family(name="Kindred T")
    gc = create_counselor()
    res = api.create_case(create_case_payload(fam["id"], gc["id"], covered_sessions=1), BILLING)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_lab_not_owner_cannot_release_result(api):
    """PRD 2.1: "releasing a result compares the parent test order's lab_id to
    X-User-ID, and a mismatch is likewise rejected with ERR_NOT_RESOURCE_OWNER." PRD
    3.5: "Releasing the pending result — permitted only while it is PENDING (else
    ERR_RESULT_INVALID_STATE) and only by the lab that owns the parent order (else
    ERR_NOT_RESOURCE_OWNER)".

    Design: Corner/validations/lab_wrong_owner_cannot_release_result
    """
    fam = create_family(name="Kindred U")
    gc = create_counselor()
    lab1 = create_lab(capacity=5, name="Lab1")
    lab2 = create_lab(capacity=5, name="Lab2")
    case = create_case(fam["id"], gc["id"], covered_sessions=1)
    add_member(case["id"], gc["id"], relationship="SIBLING", degree=1, affected=True,
               age_of_onset=60)
    assess_risk(case["id"], gc["id"])
    create_signed_testing_consent(case["id"], gc["id"])
    order = create_order(case["id"], lab1["id"], gc["id"])
    submit_order(order["id"], gc["id"])
    result = enter_result(order["id"], lab1["id"], classification="PATHOGENIC")
    # lab2 (not the owning lab) attempts to release
    res = api.release_result(result["id"], make_lab_headers(lab2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_withdraw_already_withdrawn_case_rejected(api):
    """PRD 3.9: "a case that has run its course clinically may be withdrawn from the
    workflow at any point before it is already terminal — from INTAKE, RISK_ASSESSED, or
    TESTING — moving clinical_status to WITHDRAWN and incrementing the case version;
    withdrawing an already-WITHDRAWN case is rejected with
    ERR_CASE_INVALID_CLINICAL_STATE."

    Design: Corner/state_machines/withdraw_already_withdrawn_case_rejected
    """
    fam = create_family(name="Kindred H")
    gc = create_counselor()
    case = create_case(fam["id"], gc["id"], covered_sessions=1)
    hdr = make_counselor_headers(gc["id"])
    validate_success(api.withdraw_case(case["id"], hdr), 200)
    res = api.withdraw_case(case["id"], hdr)
    validate_error(res, "ERR_CASE_INVALID_CLINICAL_STATE", expected_status=409)
