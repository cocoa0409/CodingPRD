"""Borrower creation, hardship attestation, loan origination, and
scheduled-payment computation.

Coverage targets (PRD §3.1):
- Borrower create returns id + null hardship_attested_at; attest sets it.
- Loan create returns derived fields (scheduled_payment_cents,
  principal_balance_cents, escrow_balance_cents, next_due_date, posture,
  pmi_status) per PRD §3.1.
- Loan posture initialised CURRENT; pmi_status ACTIVE iff pmi_monthly > 0.
- ERR_LOAN_NOT_FOUND on bogus loan_id.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_borrower,
    assert_loan,
    attest_hardship,
    create_borrower,
    create_borrower_payload,
    create_loan,
    create_loan_payload,
    get_borrower,
    get_loan,
    setup_borrower_and_current_loan,
    validate_error,
    validate_success,
)


class TestBorrowerCreate:
    """PRD §3.1 borrower create + hardship."""

    def test_create_borrower_returns_id_and_null_hardship(
        self, api, servicer_headers,
    ):
        """PRD §3.1: "The borrower's hardship_attested_at field begins
        as null".

        Claim: a newly-created Borrower carries
        hardship_attested_at == null.
        """
        resp = api.create_borrower(create_borrower_payload(),
                                   servicer_headers)
        data = validate_success(resp, expected_status=201)
        assert_borrower(data)
        assert data.get("hardship_attested_at") is None

    def test_attest_hardship_sets_timestamp(self, api, servicer_headers):
        """PRD §3.1: "later, when a borrower formally attests to
        financial hardship — a precondition for both forbearance and
        pre-foreclosure mediation — the hardship-attestation capability
        stamps hardship_attested_at to the current server time."

        Claim: attest-hardship stamps a non-null ISO timestamp into
        hardship_attested_at.
        """
        b = create_borrower()
        assert b.get("hardship_attested_at") is None
        attest_hardship(b["id"])
        after = get_borrower(b["id"])
        assert isinstance(after.get("hardship_attested_at"), str), (
            f"hardship_attested_at must be set after attestation, "
            f"got {after.get('hardship_attested_at')!r}"
        )


class TestLoanCreate:
    """PRD §3.1 loan origination."""

    def test_create_loan_sets_posture_current(self, api, servicer_headers):
        """PRD §3.1: "Upon creation, the server computes ...
        initialises principal_balance_cents to original_principal_cents,
        initialises escrow_balance_cents to zero, sets next_due_date to
        the origination_date plus one month, sets posture to CURRENT".

        Claim: a freshly created loan has posture=CURRENT,
        principal_balance == original_principal, escrow_balance == 0.
        """
        b, loan = setup_borrower_and_current_loan()
        assert_loan(loan)
        assert loan["posture"] == "CURRENT"
        assert (
            loan["principal_balance_cents"]
            == loan["original_principal_cents"]
        )
        assert loan["escrow_balance_cents"] == 0

    def test_create_loan_pmi_active_when_pmi_monthly_positive(
        self, api, servicer_headers,
    ):
        """PRD §3.1: "sets pmi_status to ACTIVE when pmi_monthly_cents
        is greater than zero or to REMOVED otherwise."

        Claim: with pmi_monthly_cents > 0 -> pmi_status == ACTIVE.
        """
        b, loan = setup_borrower_and_current_loan(pmi_monthly_cents=8_000)
        assert loan["pmi_status"] == "ACTIVE"
        assert loan["pmi_monthly_cents"] == 8_000

    def test_create_loan_pmi_removed_when_pmi_monthly_zero(
        self, api, servicer_headers,
    ):
        """PRD §3.1: "sets pmi_status to ACTIVE when pmi_monthly_cents
        is greater than zero or to REMOVED otherwise."

        Claim: with pmi_monthly_cents == 0 (or omitted) -> pmi_status
        == REMOVED.
        """
        b, loan = setup_borrower_and_current_loan(pmi_monthly_cents=0)
        assert loan["pmi_status"] == "REMOVED"
        assert loan["pmi_monthly_cents"] == 0

    def test_scheduled_payment_amortization_formula(
        self, api, servicer_headers,
    ):
        """PRD §3.1: "the payment is P multiplied by the monthly rate,
        multiplied by one-plus-monthly-rate raised to the nth power,
        divided by the quantity one-plus-monthly-rate raised to the nth
        power minus one, with the final result rounded half-up to whole
        cents — a single rounding at the output".

        Claim: for P=20_000_000 cents, rate=625bps (6.25%/y), n=360 months,
        the standard amortization formula yields scheduled_payment_cents
        = ceil/half-up of P*r*(1+r)^n / ((1+r)^n - 1).
        """
        P = 20_000_000
        bps = 625
        n = 360
        r = bps / 10000.0 / 12.0
        pow_term = (1.0 + r) ** n
        expected_float = P * r * pow_term / (pow_term - 1.0)
        # PRD: "rounded half-up to whole cents".
        expected_half_up = int(math.floor(expected_float + 0.5))
        b, loan = setup_borrower_and_current_loan(
            original_principal_cents=P,
            interest_rate_bps=bps,
            term_months=n,
        )
        # Allow a 1-cent tolerance for floating-point comparison only.
        diff = abs(int(loan["scheduled_payment_cents"]) - expected_half_up)
        assert diff <= 1, (
            f"scheduled_payment_cents = {loan['scheduled_payment_cents']} "
            f"differs from expected {expected_half_up} by {diff} cents"
        )


class TestLoanNotFound:
    """PRD §2.6 / §2.7: existence checks return ERR_LOAN_NOT_FOUND."""

    def test_get_loan_nonexistent_returns_loan_not_found(
        self, api, servicer_headers,
    ):
        """PRD §2.6: "left-to-right resolution of the loan_id path
        parameter (ERR_LOAN_NOT_FOUND)".
        PRD §2.7: "the server first resolves loan_id and returns
        ERR_LOAN_NOT_FOUND if it does not exist".

        Claim: GET /loans/{bogus} -> ERR_LOAN_NOT_FOUND.
        """
        resp = api.get_loan(NON_EXISTENT_UUID, servicer_headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FOUND.value)

    def test_post_payment_on_nonexistent_loan_returns_loan_not_found(
        self, api, servicer_headers,
    ):
        """PRD §2.7: "the server first resolves loan_id and returns
        ERR_LOAN_NOT_FOUND if it does not exist".

        Claim: POST /loans/{bogus}/payments -> ERR_LOAN_NOT_FOUND
        (not a payload validation error — existence is checked first).
        """
        resp = api.create_payment(
            NON_EXISTENT_UUID,
            {"received_date": "2026-05-17T00:00:00.000Z",
             "amount_cents": 100_000},
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FOUND.value)


class TestLoanInputValidation:
    """PRD §3.1 input constraints."""

    @pytest.mark.parametrize("bad_principal", [0, 1, 99_999])
    def test_principal_below_floor_rejected(
        self, api, servicer_headers, bad_principal,
    ):
        """PRD §3.1: "original_principal_cents (at least 100,000, i.e.
        at least one thousand dollars)".

        Claim: original_principal_cents < 100_000 must not yield a
        2xx-created loan (the request must fail). The exact error_id
        for input validation is not pinned by PRD prose; the assertion
        is on the 4xx HTTP status (request rejected).
        """
        b = create_borrower()
        payload = create_loan_payload(
            borrower_id=b["id"],
            original_principal_cents=bad_principal,
        )
        resp = api.create_loan(payload, servicer_headers)
        assert resp.status_code >= 400, (
            f"original_principal_cents={bad_principal} must be rejected "
            f"(below the 100_000 floor); got HTTP {resp.status_code}"
        )

    def test_principal_at_floor_accepted(self, api, servicer_headers):
        """PRD §3.1: "original_principal_cents (at least 100,000, i.e.
        at least one thousand dollars)".

        Claim: original_principal_cents == 100_000 is at the inclusive
        floor and must be accepted.
        """
        b, loan = setup_borrower_and_current_loan(
            original_principal_cents=100_000,
        )
        assert loan["original_principal_cents"] == 100_000
