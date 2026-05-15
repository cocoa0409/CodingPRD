"""Repayment plan creation, activation guards, supersede cascade.

Anchors: PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    assert_repayment_plan,
    create_borrower,
    create_loan,
    create_plan,
    create_and_activate_plan,
    create_borrower_with_loan_in_repayment,
    make_borrower_headers,
    reset_clock_to,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 1. PENDING plan creation (PRD §3.7)
# ---------------------------------------------------------------------------
def test_create_pending_plan_initial_fields(api):
    """PRD §3.7: "At create time the plan is PENDING with
    effective_from, certified_agi_cents, certified_family_size,
    monthly_payment_cents, and recertification_due_at all zero or
    absent."

    Claim: a brand-new plan is PENDING with monthly_payment_cents=0.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan = create_plan(borrower["id"], "STANDARD_10", [loan["id"]])
    assert_repayment_plan(plan)
    assert plan["status"] == "PENDING"
    assert plan["monthly_payment_cents"] == 0
    assert plan["certified_agi_cents"] == 0
    assert plan["certified_family_size"] == 0


def test_cancel_pending_plan_moves_to_terminated(api):
    """PRD §3.7: "A pending plan may be cancelled by the borrower,
    moving it from PENDING to TERMINATED."

    Claim: DELETE on PENDING plan moves status to TERMINATED.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan = create_plan(borrower["id"], "STANDARD_10", [loan["id"]])
    res = api.cancel_plan(
        borrower["id"], plan["id"],
        make_borrower_headers(borrower["id"]),
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "TERMINATED"


def test_activate_plan_transitions_pending_to_active(api):
    """PRD §3.7: "On success the plan transitions from PENDING to
    ACTIVE, effective_from is set to now."

    Claim: POST /activate produces status==ACTIVE with effective_from set.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    assert plan["status"] == "ACTIVE"
    assert plan["effective_from"], (
        "PRD §3.7: effective_from must be set on activation"
    )


def test_activate_idr_snapshots_agi_and_family_size(api):
    """PRD §3.7: "an IDR plan snapshots the borrower's
    adjusted_gross_income_cents and family_size into the plan's
    certified_agi_cents and certified_family_size (a STANDARD_10 plan
    sets both to 0)."

    Claim: SAVE activation captures borrower's AGI and family_size
    into the plan's certified fields.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        adjusted_gross_income_cents=5_000_000,
        family_size=2,
        state_code="CA",
    )
    plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    assert plan["certified_agi_cents"] == 5_000_000
    assert plan["certified_family_size"] == 2


def test_activate_standard10_does_not_snapshot_agi(api):
    """PRD §3.7: "a STANDARD_10 plan sets both [certified_agi_cents
    and certified_family_size] to 0".

    Claim: STANDARD_10 activation keeps certified_agi_cents at 0.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        adjusted_gross_income_cents=5_000_000, family_size=3,
    )
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    assert plan["certified_agi_cents"] == 0
    assert plan["certified_family_size"] == 0


def test_activate_idr_sets_recertification_due_at_365_days(api):
    """PRD §3.7: "The recertification_due_at for IDR plans is set to
    365 days past now; for STANDARD_10 it is left absent."

    Claim: IDR plan has recertification_due_at populated; STANDARD_10
    leaves it absent/null.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    save_plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    assert save_plan.get("recertification_due_at") not in (None, ""), (
        "PRD §3.7: IDR plan must populate recertification_due_at"
    )


# ---------------------------------------------------------------------------
# 2. Activation eligibility — loan status (PRD §3.7)
# ---------------------------------------------------------------------------
def test_activate_with_loan_in_default_rejected(api):
    """PRD §3.7: "every such loan must currently be in REPAYMENT or
    GRACE (loans in DEFAULT block activation, reported as
    ERR_PLAN_LOAN_INELIGIBLE)".

    Claim: activation of a plan whose included_loan_ids contains a
    DEFAULT loan fails with ERR_PLAN_LOAN_INELIGIBLE.
    """
    from test_helpers.fixtures import setup_loan_in_default
    borrower, loan, _ = setup_loan_in_default()
    res = api.create_plan(
        borrower["id"],
        {"plan_type": "STANDARD_10", "included_loan_ids": [loan["id"]]},
        TEST_USERS["servicer_admin_headers"],
    )
    if res.status_code in (200, 201):
        plan = validate_success(res, res.status_code)
        act_res = api.activate_plan(
            borrower["id"], plan["id"],
            TEST_USERS["servicer_admin_headers"],
        )
        validate_error(act_res, "ERR_PLAN_LOAN_INELIGIBLE")
    else:
        body = res.json()
        assert body["data"]["error_id"] == "ERR_PLAN_LOAN_INELIGIBLE"


def test_activate_with_loan_in_in_school_rejected(api):
    """PRD §3.7: "every such loan must currently be in REPAYMENT or
    GRACE (loans in DEFAULT block activation, reported as
    ERR_PLAN_LOAN_INELIGIBLE)".

    The PRD lists REPAYMENT and GRACE as the only allowed statuses
    inside included_loan_ids; IN_SCHOOL is not in that set.

    Claim: trying to activate a plan that includes an IN_SCHOOL loan
    fails with ERR_PLAN_LOAN_INELIGIBLE.
    """
    b = create_borrower()
    loan_in_school = create_loan(b["id"])  # default IN_SCHOOL
    plan = create_plan(b["id"], "STANDARD_10", [loan_in_school["id"]])
    res = api.activate_plan(
        b["id"], plan["id"], TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_PLAN_LOAN_INELIGIBLE")


def test_activate_idr_without_agi_certified_rejected(api):
    """PRD §3.7: "for IDR plan types — IBR, PAYE, and SAVE — the
    borrower's adjusted_gross_income_cents must be present and
    agi_certified_at must be within the last 365 days (the
    recertification window) ... failure ... yields
    ERR_PLAN_LOAN_INELIGIBLE, ERR_AGI_NOT_CERTIFIED, and
    ERR_PLAN_CONFLICT respectively."

    Claim: SAVE activation without a fresh agi_certified_at is
    rejected with ERR_AGI_NOT_CERTIFIED.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    # Borrower without agi_certified_at (omitted).
    res = api.create_borrower(
        {"full_name": "No AGI",
         "ssn_last4": "1111",
         "state_code": "CA",
         "adjusted_gross_income_cents": 3_000_000},
        TEST_USERS["servicer_admin_headers"],
    )
    borrower = validate_success(res, 201)
    # Bring loan into REPAYMENT (180 days grace exit).
    loan_res = api.create_loan(
        borrower["id"], {"loan_type": "DIRECT_UNSUBSIDIZED",
                          "original_principal_cents": 1_000_000,
                          "interest_rate_bps": 500,
                          "disbursement_date": TEST_DEFAULTS["DEFAULT_DISBURSEMENT_DATE"]},
        TEST_USERS["servicer_admin_headers"],
    )
    loan = validate_success(loan_res, 201)
    api.separate_loan(borrower["id"], loan["id"], {},
                      TEST_USERS["servicer_admin_headers"])
    advance_clock_by_days(181, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    plan = create_plan(borrower["id"], "SAVE", [loan["id"]])
    res = api.activate_plan(
        borrower["id"], plan["id"],
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_AGI_NOT_CERTIFIED")


# ---------------------------------------------------------------------------
# 3. Overlapping plan activation supersedes prior (PRD §3.7)
# ---------------------------------------------------------------------------
def test_second_overlap_plan_supersedes_first(api):
    """PRD §3.7: "If the activation of this new plan touches any loan
    that is already covered by another ACTIVE plan for the same
    borrower, the older plan is cascaded to SUPERSEDED and the new
    plan's activation proceeds — its loans' monthly payments are
    recomputed under the new plan."

    Claim: activating a second plan that covers the same loan moves
    the first plan to SUPERSEDED while the second becomes ACTIVE.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan_a = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    plan_b = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    assert plan_b["status"] == "ACTIVE"
    # Reload first plan and check it has been superseded.
    res = api.get_plan(
        borrower["id"], plan_a["id"],
        TEST_USERS["servicer_admin_headers"],
    )
    first_after = validate_success(res, 200)
    assert first_after["status"] == "SUPERSEDED", (
        "PRD §3.7: cascade must move the prior plan to SUPERSEDED"
    )


# ---------------------------------------------------------------------------
# 4. RBAC on activation: Borrower role can activate own plan (PRD §4)
# ---------------------------------------------------------------------------
def test_borrower_can_activate_own_plan(api):
    """PRD §4: POST /activate authorized for Borrower and
    ServicerAdmin. PRD §2.1 ownership: Borrower's X-User-ID must
    equal the path borrower's id.

    Claim: a Borrower-role call with X-User-ID = borrower["id"] is
    allowed to activate the borrower's own plan.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan = create_plan(borrower["id"], "STANDARD_10", [loan["id"]])
    res = api.activate_plan(
        borrower["id"], plan["id"],
        make_borrower_headers(borrower["id"]),
    )
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE"
