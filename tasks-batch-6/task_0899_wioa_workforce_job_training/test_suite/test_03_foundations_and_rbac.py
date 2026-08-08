"""Local-area creation, authentication, and role-based access control."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant, make_eligible, enroll, create_plan, activate_plan,
    create_local_area_payload, create_employer_payload, create_supportive_payload,
    get_success_data,
    ADMIN, CM,
)


def test_create_local_area_initializes_budget_ledger(api):
    """PRD §3.1: "At creation the area's available ITA budget equals its total, its
    obligated and expended balances are zero, and its `version` is 1."

    Design: Corner/entities/create_local_area_initializes_budget_ledger
    """
    resp = api.create_local_area(
        create_local_area_payload(ita_budget_total_cents=5000000), ADMIN)
    data = validate_success(resp, 201)
    assert data["ita_budget_available_cents"] == 5000000, data
    assert data["ita_budget_obligated_cents"] == 0, data
    assert data["ita_budget_expended_cents"] == 0, data
    assert data["version"] == 1, data


def test_create_local_area_without_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/create_local_area_missing_header_returns_unauthenticated
    """
    resp = api.create_local_area(create_local_area_payload(), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_case_manager_cannot_create_employer(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/case_manager_cannot_create_employer
    """
    area = create_area(api)
    resp = api.create_employer(area["id"], create_employer_payload(), CM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_case_manager_cannot_approve_supportive_payment(api):
    """PRD §2.1: "a `CaseManager` requests a supportive-service payment, but only a
    `FiscalOfficer` may approve or pay it."

    Design: Corner/rbac/case_manager_cannot_approve_supportive_payment
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])
    enroll(api, p["id"])
    cp = create_plan(api, p["id"], supportive_need_documented=True)
    activate_plan(api, cp["id"])
    ss = get_success_data(api.create_supportive(
        p["id"], create_supportive_payload(service_type="CHILDCARE", amount_cents=50000), CM))
    resp = api.approve_supportive(ss["id"], CM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
