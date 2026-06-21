"""Authentication, authorization / segregation of duties, and list pagination.

PRD §2.1 (auth/RBAC) and §2.3 (pagination) govern these assertions.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_case_payload, create_plan_payload,
    register_debtor, register_creditor, open_case, submit_means_test,
    add_income_and_expense_schedules, petition, setup_filed_case,
    create_plan, file_plan, current_case_version,
    make_debtor_headers, make_creditor_headers, build_user_headers, TEST_USERS,
)


def test_creditor_cannot_petition_case_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED." PRD §4: "POST /cases/{id}/petition ... Debtor".

    Design: Corner/rbac/creditor_cannot_petition_case_unauthorized
    """
    debtor = register_debtor(full_name="RbacD Debtor")
    creditor = register_creditor(name="Rbac Cr")
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    res = api.petition_case(case["id"], make_creditor_headers(creditor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_debtor_cannot_confirm_plan_segregation_of_duties(api):
    """PRD §2.1: "No single actor may both file a case and adjudicate it."
    PRD §4: "POST /plans/{id}/confirm-plan ... Trustee".

    Design: Corner/rbac/debtor_cannot_confirm_plan_segregation_of_duties
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    res = api.confirm_plan(plan["id"], make_debtor_headers(debtor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    debtor = register_debtor(full_name="Auth Debtor")
    res = api.create_case(create_case_payload(
        debtor["id"], filed_chapter="CHAPTER_7", state_code="CA", household_size=1),
        headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_list_cases_pagination_envelope(api):
    """PRD §2.3: "The limit parameter bounds the number of items returned ...
    Every list response carries the pagination bookkeeping in the meta object of
    the envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_cases_pagination_envelope
    """
    debtor = register_debtor(full_name="Page Debtor")
    open_case(debtor, filed_chapter="CHAPTER_7")
    open_case(debtor, filed_chapter="CHAPTER_13")

    # GET /cases is authorized for BankruptcyAdmin and Trustee; the admin role is
    # opaque so the shared constant is canonical here.
    res = api.list_cases(TEST_USERS["admin_headers"],
                         params={"debtor_id": debtor["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
