"""Tests covering cross-entity state dependencies:
- ServiceTransaction creation requires an ACTIVE EligibilityDetermination
  covering the current clock for the student's household.
- ReimbursementClaim submission requires every transaction in the period to
  be in a final state (SETTLED, REJECTED, or REFUNDED).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    create_household,
    create_student,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    revoke_eligibility,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 7 / instance 1 — POST service-transactions requires ACTIVE
# eligibility covering server_clock_utc.
# ---------------------------------------------------------------------

def test_create_transaction_against_revoked_only_eligibility_returns_no_active_eligibility(api):
    """PRD §3.5: "The candidate pool is every `EligibilityDetermination` for
    the student's `household_id` whose `lifecycle_status` is `ACTIVE` and
    whose validity window contains the current server clock instant — that
    is, `valid_from_utc` is at or before now and `valid_to_utc` is strictly
    after now. If the candidate pool is empty, the creation is rejected with
    `ERR_NO_ACTIVE_ELIGIBILITY`."

    Design: Difficulty/cross_entity_state_dependency/service_transaction_create_requires_active_eligibility
    """
    set_clock("2026-04-12T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-04-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    revoke_eligibility(elig["id"], elig["version"])  # → lifecycle_status=REVOKED
    menu = create_menu_item(
        school_code="ELEM-101", name="Plain Bread",
        list_price_cents=100, allergens_present=[],
    )
    res = api.create_service_transaction(
        {"student_id": stu["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_NO_ACTIVE_ELIGIBILITY", expected_status=422)


def test_create_transaction_with_no_eligibility_record_returns_no_active_eligibility(api):
    """PRD §3.5: "If the candidate pool is empty, the creation is rejected
    with `ERR_NO_ACTIVE_ELIGIBILITY`."

    Design: Difficulty/cross_entity_state_dependency/service_transaction_create_requires_active_eligibility
    """
    set_clock("2026-04-12T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    # NO eligibility determination is created at all.
    menu = create_menu_item(
        school_code="ELEM-101", name="Plain Bread", list_price_cents=100,
    )
    res = api.create_service_transaction(
        {"student_id": stu["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_NO_ACTIVE_ELIGIBILITY", expected_status=422)


# ---------------------------------------------------------------------
# Difficulty rule 7 / instance 2 — claim submit requires period to be settled.
# ---------------------------------------------------------------------

def test_reimbursement_claim_submit_blocked_by_pending_transaction_in_period(api):
    """PRD §3.7: "Submission of a `DRAFT` claim by school staff is gated by a
    closure rule: every `ServiceTransaction` whose `served_at_utc` falls
    within the inclusive interval from `period_start_utc` to `period_end_utc`,
    for any student attending the claim's `school_code`, must be in a final
    status of `SETTLED`, `REJECTED`, or `REFUNDED`. If even one such
    transaction is still `PENDING` or `DISPUTED`, the submission is rejected
    with `ERR_PERIOD_NOT_SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/reimbursement_claim_submit_requires_all_transactions_settled
    """
    set_clock("2026-01-15T10:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="Free Lunch", list_price_cents=0,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
    )
    tx1 = create_service_transaction(stu["id"], menu["id"])
    settle_transaction(tx1["id"])
    tx2 = create_service_transaction(stu["id"], menu["id"])
    assert tx2["status"] == "PENDING"

    # Advance clock past period and create the claim.
    set_clock("2026-02-01T00:00:00.000Z")
    create_claim_res = api.create_reimbursement_claim(
        {
            "school_code": "ELEM-101",
            "period_start_utc": "2026-01-01T00:00:00.000Z",
            "period_end_utc": "2026-01-31T23:59:59.000Z",
            "accounting_basis": "CASH",
        },
        TEST_USERS["school_staff_headers"],
    )
    claim = validate_success(create_claim_res, 201)
    # Submit — tx2 PENDING blocks.
    submit_res = api.submit_reimbursement_claim(
        claim["id"], TEST_USERS["school_staff_headers"]
    )
    validate_error(submit_res, "ERR_PERIOD_NOT_SETTLED", expected_status=409)


def test_reimbursement_claim_submit_blocked_by_disputed_transaction_in_period(api):
    """PRD §3.7: "If even one such transaction is still `PENDING` or
    `DISPUTED`, the submission is rejected with `ERR_PERIOD_NOT_SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/reimbursement_claim_submit_requires_all_transactions_settled
    """
    set_clock("2026-01-15T10:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="Free Lunch", list_price_cents=0,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settle_transaction(tx["id"])
    # Parent disputes it → DISPUTED.
    dispute_res = api.dispute_service_transaction(
        tx["id"], make_parent_headers(hh["id"])
    )
    validate_success(dispute_res, 200)

    set_clock("2026-02-01T00:00:00.000Z")
    create_claim_res = api.create_reimbursement_claim(
        {
            "school_code": "ELEM-101",
            "period_start_utc": "2026-01-01T00:00:00.000Z",
            "period_end_utc": "2026-01-31T23:59:59.000Z",
            "accounting_basis": "CASH",
        },
        TEST_USERS["school_staff_headers"],
    )
    claim = validate_success(create_claim_res, 201)
    submit_res = api.submit_reimbursement_claim(
        claim["id"], TEST_USERS["school_staff_headers"]
    )
    validate_error(submit_res, "ERR_PERIOD_NOT_SETTLED", expected_status=409)
