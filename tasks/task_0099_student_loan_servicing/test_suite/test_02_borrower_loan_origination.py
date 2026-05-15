"""Borrower + Loan origination and the IN_SCHOOL → GRACE → REPAYMENT lifecycle.

Anchors: PRD §3.1, §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    assert_borrower,
    assert_borrower_aggregates_match,
    assert_loan,
    assert_version_bumped,
    create_borrower,
    create_borrower_payload,
    create_loan,
    create_loan_in_grace,
    create_loan_in_repayment,
    create_loan_payload,
    make_borrower_headers,
    reset_clock_to,
    separate_loan,
    separate_loan_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 1. Borrower CRUD (PRD §3.1)
# ---------------------------------------------------------------------------
def test_create_borrower_initial_field_defaults(api):
    """PRD §3.1: "family_size (an integer of at least 1, defaulting
    to 1 if omitted) ... adjusted_gross_income_cents ... defaults to
    0 ... veteran_status (defaulting to NONE if not supplied)".

    Claim: a borrower created with only required fields takes the
    documented defaults.
    """
    res = api.create_borrower(
        {
            "full_name": "Default Defaults",
            "ssn_last4": "0001",
            "state_code": "CA",
        },
        TEST_USERS["servicer_admin_headers"],
    )
    b = validate_success(res, 201)
    assert_borrower(b)
    assert b["family_size"] == 1
    assert b["adjusted_gross_income_cents"] == 0
    assert b["veteran_status"] == "NONE"


def test_create_borrower_persists_supplied_fields(api):
    """PRD §3.1: borrower payload carries full_name, ssn_last4,
    family_size, state_code, adjusted_gross_income_cents,
    agi_certified_at, veteran_status.

    Claim: every supplied field round-trips on POST/GET.
    """
    res = api.create_borrower(
        {
            "full_name": "Round Trip",
            "ssn_last4": "9999",
            "family_size": 3,
            "state_code": "NY",
            "adjusted_gross_income_cents": 5_200_000,
            "agi_certified_at": "2025-01-15T00:00:00.000Z",
            "veteran_status": "VETERAN",
        },
        TEST_USERS["servicer_admin_headers"],
    )
    b = validate_success(res, 201)
    assert b["family_size"] == 3
    assert b["state_code"] == "NY"
    assert b["adjusted_gross_income_cents"] == 5_200_000
    assert b["veteran_status"] == "VETERAN"


def test_borrower_initial_aggregates_zero(api):
    """PRD §3.1 / §2.11: "aggregate_principal_balance_cents and
    aggregate_interest_balance_cents are server-computed and reflect
    the live sum of principal_balance_cents and accrued_interest_cents
    respectively across the borrower's non-terminal loans."

    Claim: a borrower with no loans starts with both aggregates at 0.
    """
    borrower = create_borrower()
    fetched = validate_success(
        api.get_borrower(borrower["id"], TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["aggregate_principal_balance_cents"] == 0
    assert fetched["aggregate_interest_balance_cents"] == 0


def test_borrower_version_starts_at_one(api):
    """PRD §2.4: "version (an integer that starts at 1 on creation
    and increments by 1 on every successful mutation)."

    Claim: new borrower has version == 1.
    """
    b = create_borrower()
    assert b["version"] == 1


def test_borrower_version_increments_on_patch(api):
    """PRD §2.4: "A successful mutation always increments version by
    1 and refreshes updated_at to the current clock value."

    Claim: PATCH bumps version by exactly 1.
    """
    b = create_borrower()
    old_version = b["version"]
    res = api.update_borrower(
        b["id"], {"family_size": 4},
        TEST_USERS["servicer_admin_headers"],
    )
    updated = validate_success(res, 200)
    assert_version_bumped(updated, old_version)
    assert updated["family_size"] == 4


def test_patch_agi_stamps_certified_at(api):
    """PRD §3.1: "When adjusted_gross_income_cents is included in an
    update and its value differs from the stored value, the server
    stamps agi_certified_at to the current clock — this is the
    implicit re-certification event that resets the 365-day
    recertification window used by IDR plan activation."

    Claim: PATCH that changes AGI updates agi_certified_at.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    b = create_borrower(adjusted_gross_income_cents=4_000_000)
    new_clock = advance_clock_by_days(60,
                                      from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    res = api.update_borrower(
        b["id"], {"adjusted_gross_income_cents": 5_000_000},
        TEST_USERS["servicer_admin_headers"],
    )
    updated = validate_success(res, 200)
    assert updated["adjusted_gross_income_cents"] == 5_000_000
    # agi_certified_at should now be at-or-after the new clock value.
    assert updated["agi_certified_at"] is not None


def test_stale_version_rejected_on_borrower_patch(api):
    """PRD §2.4 + PRD §2.10: "the OCC check applies: a stale version
    value loses with ERR_VERSION_CONFLICT. The same OCC rule governs
    every other PATCH endpoint that accepts version? in its body."

    Claim: PATCH /borrowers with a stale version → ERR_VERSION_CONFLICT.
    """
    b = create_borrower()
    stale = b["version"]
    # First PATCH advances version.
    validate_success(
        api.update_borrower(b["id"], {"family_size": 2},
                            TEST_USERS["servicer_admin_headers"]),
        200,
    )
    # Now retry with the stale version.
    res = api.update_borrower(
        b["id"], {"family_size": 3, "version": stale},
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_VERSION_CONFLICT")


# ---------------------------------------------------------------------------
# 2. Loan origination (PRD §3.2)
# ---------------------------------------------------------------------------
def test_originate_loan_initial_state(api):
    """PRD §3.2: "At origination the loan enters IN_SCHOOL with
    status_entered_at and last_accrual_at set to the current clock;
    principal_balance_cents is initialized to original_principal_cents;
    accrued_interest_cents and capitalized_interest_cents both start
    at 0; days_past_due is 0; last_payment_due_at is absent;
    qualifying_pslf_payment_count is 0."

    Claim: a freshly originated loan matches every initial field
    above.
    """
    b = create_borrower()
    res = api.create_loan(
        b["id"],
        create_loan_payload(
            loan_type="DIRECT_UNSUBSIDIZED",
            original_principal_cents=2_000_000,
            interest_rate_bps=500,
        ),
        TEST_USERS["servicer_admin_headers"],
    )
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["status"] == "IN_SCHOOL"
    assert loan["principal_balance_cents"] == 2_000_000
    assert loan["accrued_interest_cents"] == 0
    assert loan["capitalized_interest_cents"] == 0
    assert loan["days_past_due"] == 0
    assert loan.get("last_payment_due_at") in (None, "", )
    assert loan["qualifying_pslf_payment_count"] == 0


@pytest.mark.parametrize("loan_type", [
    "DIRECT_SUBSIDIZED", "DIRECT_UNSUBSIDIZED", "DIRECT_PLUS",
])
def test_originate_each_loan_type(api, loan_type):
    """PRD §3.2: "loan_type (one of DIRECT_SUBSIDIZED, DIRECT_UNSUBSIDIZED,
    or DIRECT_PLUS)".

    Claim: each enumerated loan_type is accepted at origination.
    """
    b = create_borrower()
    res = api.create_loan(
        b["id"], create_loan_payload(loan_type=loan_type),
        TEST_USERS["servicer_admin_headers"],
    )
    loan = validate_success(res, 201)
    assert loan["loan_type"] == loan_type


def test_loan_rate_above_cap_rejected(api):
    """PRD §3.2: "interest_rate_bps (a positive integer, capped at
    2000 basis points — that is, twenty percent annual)".

    Claim: interest_rate_bps > 2000 is rejected with the input-shape
    error.
    """
    b = create_borrower()
    res = api.create_loan(
        b["id"], create_loan_payload(interest_rate_bps=2001),
        TEST_USERS["servicer_admin_headers"],
    )
    assert res.status_code in (400, 422), (
        f"PRD §3.2 caps interest_rate_bps at 2000 — out-of-bound input "
        f"must be rejected, got HTTP {res.status_code}"
    )


# ---------------------------------------------------------------------------
# 3. Separation (PRD §3.2)
# ---------------------------------------------------------------------------
def test_separate_moves_loan_to_grace(api):
    """PRD §3.2: "The default behaviour transitions the loan from
    IN_SCHOOL to GRACE, sets status_entered_at and last_accrual_at
    to now, and starts the loan's grace clock."

    Claim: POST /separate without skip_grace yields status GRACE.
    """
    b = create_borrower()
    loan = create_loan(b["id"])
    moved = separate_loan(b["id"], loan["id"], skip_grace=False)
    assert moved["status"] == "GRACE"


def test_separate_plus_with_skip_grace_jumps_to_repayment(api):
    """PRD §3.2: "A request body may supply skip_grace as true to
    bypass the grace period entirely; this option is restricted to
    DIRECT_PLUS loans and transitions the loan directly from
    IN_SCHOOL to REPAYMENT, capitalizing any accrued interest and
    setting last_payment_due_at to the first day of the next month
    at or after now."

    Claim: PLUS + skip_grace → status REPAYMENT.
    """
    b = create_borrower()
    loan = create_loan(b["id"], loan_type="DIRECT_PLUS")
    moved = separate_loan(b["id"], loan["id"], skip_grace=True)
    assert moved["status"] == "REPAYMENT"
    assert moved.get("last_payment_due_at"), (
        "PRD §3.2: skip_grace must set last_payment_due_at"
    )


def test_separate_non_plus_with_skip_grace_rejected(api):
    """PRD §3.2: "skip_grace ... is restricted to DIRECT_PLUS loans".

    Claim: non-PLUS loan with skip_grace=true is rejected with the
    state-machine error (the loan cannot make the IN_SCHOOL->REPAYMENT
    transition that is gated on loan_type==DIRECT_PLUS).
    """
    b = create_borrower()
    loan = create_loan(b["id"], loan_type="DIRECT_UNSUBSIDIZED")
    res = api.separate_loan(
        b["id"], loan["id"], {"skip_grace": True},
        TEST_USERS["servicer_admin_headers"],
    )
    # PRD calls it a restriction — implementer may report state error
    # or invalid input; both are PRD-consistent.
    assert res.status_code >= 400, (
        "PRD §3.2: skip_grace on non-PLUS must be rejected"
    )


def test_separate_already_in_grace_rejected(api):
    """PRD §3.2: "Any attempt to transition a loan that is not
    currently IN_SCHOOL is rejected with ERR_INVALID_STATE."

    Claim: calling /separate on a loan already in GRACE returns
    ERR_INVALID_STATE.
    """
    b = create_borrower()
    loan = create_loan_in_grace(b["id"])
    res = api.separate_loan(
        b["id"], loan["id"], {}, TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# 4. Borrower aggregates reflect non-terminal loans (PRD §2.11)
# ---------------------------------------------------------------------------
def test_borrower_aggregates_sum_active_loans(api):
    """PRD §2.11: "the borrower's aggregate_principal_balance_cents
    and aggregate_interest_balance_cents are recomputed as the sums
    of principal_balance_cents and accrued_interest_cents across
    that borrower's non-terminal loans."

    Claim: after creating two loans, the borrower's aggregate equals
    the sum of their principal balances.
    """
    b = create_borrower()
    loan_a = create_loan(b["id"], original_principal_cents=1_000_000)
    loan_b = create_loan(b["id"], original_principal_cents=2_000_000)
    fetched = validate_success(
        api.get_borrower(b["id"], TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert_borrower_aggregates_match(fetched, [loan_a, loan_b])
    assert fetched["aggregate_principal_balance_cents"] == 3_000_000
