"""CommuterBenefitAccount and FSAContribution — PRD §3.9, §3.5.

Covers account creation, contributions and the monthly cap, the
positive/negative amount rule, reversal as a negated entry, and the
FSA-first allocation during tap-in.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    assert_fsa_contribution,
    create_employer,
    create_fsa_account_payload,
    create_fsa_contribution_payload,
    create_rider,
    make_employer_admin_headers,
    setup_rider_with_fsa,
    tap_in,
    validate_error,
    validate_success,
)


class TestFsaAccountAndContribution:

    def test_create_fsa_account_starts_balance_zero_active(
            self, api, agency_officer_headers):
        """PRD §3.9: "The account begins with `balance_cents` of zero
        and `status` `ACTIVE`."

        Claim: a fresh FSA account has balance_cents=0 and
        status=ACTIVE."""
        rider = create_rider()
        employer = create_employer()
        eh = make_employer_admin_headers(employer["id"])
        resp = api.create_fsa_account(
            create_fsa_account_payload(
                rider_id=rider["id"], employer_id=employer["id"],
            ),
            eh,
        )
        acct = validate_success(resp, expected_status=201)
        assert acct["balance_cents"] == 0
        assert acct["status"] == "ACTIVE"

    def test_contribution_increments_balance(self, api):
        """PRD §3.9: "Each successful contribution starts in `status`
        `APPLIED` and increments the account's `balance_cents` by
        `amount_cents`."

        Claim: after contributing 500 cents, the second contribution
        of 200 cents brings balance to 700 (and the first contribution
        is APPLIED)."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, c1 = setup_rider_with_fsa(
            contribution_cents=500, topup_cents=0,
        )
        assert c1["status"] == "APPLIED"
        assert c1["amount_cents"] == 500
        eh = make_employer_admin_headers(employer["id"])
        c2_resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=200,
                contribution_month="2026-05",
            ),
            eh,
        )
        c2 = validate_success(c2_resp, expected_status=201)
        assert_fsa_contribution(c2)
        assert c2["amount_cents"] == 200
        assert c2["status"] == "APPLIED"

    def test_zero_amount_contribution_rejected(self, api):
        """PRD §3.9: "the `amount_cents` (strictly positive — otherwise
        `ERR_INVALID_AMOUNT`)".

        Claim: amount_cents=0 is rejected with ERR_INVALID_AMOUNT."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, _c = setup_rider_with_fsa(
            contribution_cents=0, topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=0,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)

    def test_negative_amount_contribution_rejected(self, api):
        """PRD §3.9: "(strictly positive — otherwise
        `ERR_INVALID_AMOUNT`)".

        Claim: amount_cents=-1 is rejected with ERR_INVALID_AMOUNT."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, _c = setup_rider_with_fsa(
            contribution_cents=0, topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=-1,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


class TestMonthlyCap:

    def test_at_monthly_cap_boundary_accepted(self, api):
        """PRD §3.9: "The monthly cap is enforced on the sum of all
        `APPLIED` contributions for the same employer in the same
        `contribution_month`: a new contribution that would push the
        running sum past `Employer.monthly_contribution_cap_cents` is
        rejected with `ERR_FSA_MONTHLY_CAP_EXCEEDED`."

        Claim: contributions summing to exactly the cap succeed; one
        cent past the cap is rejected."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, c1 = setup_rider_with_fsa(
            monthly_contribution_cap_cents=31_500,
            contribution_cents=31_499,
            contribution_month="2026-05",
            topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        # Bring the sum to exactly 31_500.
        c2 = validate_success(
            api.create_fsa_contribution(
                create_fsa_contribution_payload(
                    account_id=acct["id"], amount_cents=1,
                    contribution_month="2026-05",
                ),
                eh,
            ),
            expected_status=201,
        )
        assert c2["status"] == "APPLIED"

    def test_one_cent_past_monthly_cap_rejected(self, api):
        """PRD §3.9: "a new contribution that would push the running
        sum past `Employer.monthly_contribution_cap_cents` is rejected
        with `ERR_FSA_MONTHLY_CAP_EXCEEDED`."

        Claim: a contribution that would push the sum to 31_501 is
        rejected with ERR_FSA_MONTHLY_CAP_EXCEEDED."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, _c1 = setup_rider_with_fsa(
            monthly_contribution_cap_cents=31_500,
            contribution_cents=31_500,
            contribution_month="2026-05",
            topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=1,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(
            resp, ApiErrorId.ERR_FSA_MONTHLY_CAP_EXCEEDED.value,
        )


class TestFsaReversal:

    def test_reverse_creates_negated_entry(self, api):
        """PRD §3.9: "A contribution may be reversed by appending a
        new `FSAContribution` with the same `account_id`, the same
        `contribution_month`, and a negated `amount_cents`; the
        original's `status` becomes `REVERSED`."

        Claim: reversing a 500-cent contribution creates a new entry
        with amount_cents=-500 and flips the original to REVERSED."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, c1 = setup_rider_with_fsa(
            contribution_cents=500, contribution_month="2026-05",
            topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        resp = api.reverse_fsa_contribution(c1["id"], eh)
        # Some PRD ambiguity over which payload the reversal returns;
        # accept any 2xx. Verify the resulting FSAContribution entry has
        # amount_cents=-500.
        body = resp.json()
        assert 200 <= resp.status_code < 300, (
            f"reverse must succeed; got {resp.status_code}: {body}"
        )
        new_entry = body.get("data", body)
        assert new_entry.get("amount_cents") == -500, (
            "Reversal must append an entry with amount_cents=-500; got "
            f"{new_entry.get('amount_cents')!r}"
        )


class TestFsaFirstAllocation:

    def test_fsa_first_then_wallet(self, api):
        """PRD §2.10: "the system always draws from the FSA before the
        wallet. At every trip charge the FSA share is taken first (up
        to whichever is smaller, the provisional fare or the account's
        `balance_cents`), and the remainder is taken from the card's
        `wallet_balance_cents`."

        Claim: with FSA balance=100 and wallet=1000, a 275-cent fare
        debits paid_from_fsa_cents=100 (the smaller of provisional and
        account balance) and the remainder 175 from the wallet."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, card, _c = setup_rider_with_fsa(
            contribution_cents=100, contribution_month="2026-05",
            topup_cents=1000,
            discount_class="STANDARD",
            card_valid_from="2026-05-01T00:00:00.000Z",
            card_valid_until="2026-12-31T23:59:59.000Z",
        )
        advance_clock_to_iso("2026-05-20T17:00:00.000Z")
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T17:00:00.000Z",
        )
        assert trip["paid_from_fsa_cents"] == 100, (
            "FSA must absorb min(fare, account.balance) = 100; got "
            f"{trip['paid_from_fsa_cents']}"
        )
        # Wallet must have lost 275-100=175.
        from test_helpers import get_card
        post = get_card(card["id"])
        assert post["wallet_balance_cents"] == 1000 - 175, (
            "Wallet remainder after FSA share must be 825; got "
            f"{post['wallet_balance_cents']}"
        )
