"""Credit reversal notice cooling, the reversal/reinstatement cycle, reversal
cascades, and cardholder withdrawal semantics."""
from test_helpers import (
    CLOCK,
    ApiErrorId,
    get_account,
    get_case,
    get_success_data,
    make_cardholder_headers,
    setup_account_with_dispute,
    setup_classified_case_with_credit,
    setup_representment_accepted_case,
    setup_resolved_merchant_favor_no_credit,
    setup_resolved_merchant_favor_via_reversal,
    setup_reversal_pending,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, resolve_payload, set_clock


class TestReversalNoticeCooling:
    def _notice_scenario(self, api):
        """Credit granted, case resolved NO_ERROR on Friday 2026-08-21 (the
        REVERSAL_NOTICE is sent then). Returns (account, case, credit)."""
        account, _txn, case, credit = setup_reversal_pending(
            balance=100000, amount=20000, claim=20000, claimed_delay=5,
            resolve_clock=CLOCK["RESOLVE_NO_ERROR"], after_clock=None,
        )
        return account, case, credit

    def test_reversal_at_two_business_days_rejected(self, api):
        """PRD §3.7: "A `FinanceOfficer` may reverse a Provisional Credit in
        `GRANTED` or `REINSTATED` only while its case sits in `REVERSAL_PENDING`,
        and only when a `REVERSAL_NOTICE` exists for the case whose `sent_at` is
        at least three full business days before the current logical clock time;
        reversing earlier is rejected with `ERR_REVERSAL_NOTICE_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/reversal_requires_sent_notice_cooling
        """
        _account, _case, credit = self._notice_scenario(api)
        # 2026-08-25 is Tuesday: only 2 business days after Friday 2026-08-21.
        set_clock(CLOCK["COOLING_2BD"])
        resp = api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_REVERSAL_NOTICE_PENDING)

    def test_reversal_at_exactly_three_business_days_succeeds(self, api):
        """PRD §3.7: "only when a `REVERSAL_NOTICE` exists for the case whose
        `sent_at` is at least three full business days before the current
        logical clock time; reversing earlier is rejected with
        `ERR_REVERSAL_NOTICE_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/reversal_requires_sent_notice_cooling
        """
        _account, _case, credit = self._notice_scenario(api)
        # 2026-08-26 is Wednesday: exactly 3 business days after Friday.
        set_clock(CLOCK["COOLING_3BD"])
        resp = api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "REVERSED"


class TestReversalCascade:
    def test_credit_reversal_cascades_case_account_notice(self, api):
        """PRD §3.7: "The reversal debits the account's `balance_cents` by the
        credit's `amount_cents`, reduces `provisional_outstanding_cents` by the
        same, stamps `reversed_at` from the clock, and moves the credit to
        `REVERSED`. Completion of the reversal cascades the case
        `REVERSAL_PENDING` → `RESOLVED_MERCHANT_FAVOR`, issues the
        `RESOLUTION_LETTER`, settles the transaction, and restores the account
        to `ACTIVE` when no other fraud case remains open."

        Design: Difficulty/transitive_cascade/credit_reversal_cascades_case_account_notice
        """
        # Fraud dispute restricts the account; credit 15000 (tier-1 holdback).
        account, _txn, case, credit = setup_reversal_pending(
            balance=100000, amount=20000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=20000, claimed_delay=1,
            is_fraud=True, verified_delay=1,
        )
        assert get_account(account["id"])["status"] == "RESTRICTED"
        validate_success(api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"],
        ))
        resolved = get_case(case["id"])
        assert resolved["status"] == "RESOLVED_MERCHANT_FAVOR"
        after = get_account(account["id"])
        assert after["status"] == "ACTIVE", (
            "fraud restriction must lift once no open fraud case remains"
        )
        assert after["balance_cents"] == 100000
        assert after["provisional_outstanding_cents"] == 0
        notes = get_success_data(api.list_case_notifications(
            case["id"], TEST_USERS["finance_officer_headers"],
        ))
        types = {n["type"] for n in notes}
        assert {
            "PROVISIONAL_CREDIT_ADVICE", "REVERSAL_NOTICE", "RESOLUTION_LETTER",
        }.issubset(types), f"expected all three letter types, got {types}"

    def test_reversal_cascade_restores_account_and_settles_transaction(self, api):
        """PRD §3.7: "Completion of the reversal cascades the case
        `REVERSAL_PENDING` → `RESOLVED_MERCHANT_FAVOR`, issues the
        `RESOLUTION_LETTER`, settles the transaction, and restores the account
        to `ACTIVE` when no other fraud case remains open."

        Design: Difficulty/transitive_cascade/credit_reversal_cascades_case_account_notice
        """
        account, txn, case, credit = setup_reversal_pending(
            balance=100000, amount=20000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=20000, claimed_delay=1,
            is_fraud=True, verified_delay=1,
        )
        validate_success(api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"],
        ))
        txns = get_success_data(api.list_account_transactions(
            account["id"], TEST_USERS["finance_officer_headers"],
        ))
        assert txns[0]["status"] == "SETTLED", (
            f"reversal cascade must settle the transaction, got {txns[0]['status']}"
        )
        assert get_case(case["id"])["status"] == "RESOLVED_MERCHANT_FAVOR"
        assert get_account(account["id"])["status"] == "ACTIVE"

    def test_grant_reverse_balance_conservation(self, api):
        """PRD §3.4: "The grant credits the account's `balance_cents` by the
        granted amount, raises `provisional_outstanding_cents` by the same
        amount".
        PRD §3.7: "The reversal debits the account's `balance_cents` by the
        credit's `amount_cents`, reduces `provisional_outstanding_cents` by the
        same".

        Design: Difficulty/compensating_invariant/grant_reverse_balance_conservation
        """
        account, _txn, case, credit = setup_classified_case_with_credit(
            balance=100000, amount=20000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=20000, claimed_delay=1,
            is_fraud=True, verified_delay=1,
        )
        mid = get_account(account["id"])
        assert mid["balance_cents"] == 115000, (
            f"forward grant must add 15000, got {mid['balance_cents']}"
        )
        assert mid["provisional_outstanding_cents"] == 15000
        set_clock(CLOCK["RESOLVE_NO_ERROR"])
        validate_success(api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"),
            TEST_USERS["investigator_headers"],
        ))
        set_clock(CLOCK["COOLING_3BD"])
        validate_success(api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"],
        ))
        end = get_account(account["id"])
        assert end["balance_cents"] == 100000, (
            f"compensating reversal must restore 100000, got {end['balance_cents']}"
        )
        assert end["provisional_outstanding_cents"] == 0

    def test_grant_forward_action_applies_full_amount(self, api):
        """PRD §3.4: "The grant credits the account's `balance_cents` by the
        granted amount, raises `provisional_outstanding_cents` by the same
        amount".
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Difficulty/compensating_invariant/grant_reverse_balance_conservation
        """
        account, _txn, _case, credit = setup_classified_case_with_credit(
            balance=100000, amount=20000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=20000, claimed_delay=1,
            is_fraud=True, verified_delay=1,
        )
        assert credit["amount_cents"] == 15000, (
            f"credit must be claim 20000 - tier-1 holdback 5000, "
            f"got {credit['amount_cents']}"
        )
        mid = get_account(account["id"])
        assert mid["balance_cents"] == 115000
        assert mid["provisional_outstanding_cents"] == 15000


class TestReversalReinstatementCycle:
    def test_credit_reversal_then_reinstatement_flips_case(self, api):
        """PRD §3.7: "the account's `balance_cents` and
        `provisional_outstanding_cents` each increase by the credit's
        `amount_cents`, the credit moves to `REINSTATED`, and the case flips
        `RESOLVED_MERCHANT_FAVOR` → `RESOLVED_CARDHOLDER_FAVOR` — because the
        issuer now bears the principal, an automatic `LOSS_RECOGNIZED` entry
        equal to the reinstated `amount_cents` is booked, and a fresh
        `RESOLUTION_LETTER` is issued."

        Design: Difficulty/non_linear_state_machine/provisional_credit_reversal_reinstatement_cycle
        """
        account, _txn, case, credit = setup_resolved_merchant_favor_via_reversal(
            balance=100000, amount=20000, claimed_delay=5, verified_delay=5,
        )
        resp = api.reinstate_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "REINSTATED"
        flipped = get_case(case["id"])
        assert flipped["status"] == "RESOLVED_CARDHOLDER_FAVOR"
        assert flipped["outstanding_loss_cents"] == 20000, (
            f"auto LOSS_RECOGNIZED must equal the reinstated amount, "
            f"got {flipped['outstanding_loss_cents']}"
        )

    def test_reversed_credit_status_before_reinstate(self, api):
        """PRD §3.7: "The reversal debits the account's `balance_cents` by the
        credit's `amount_cents`, reduces `provisional_outstanding_cents` by the
        same, stamps `reversed_at` from the clock, and moves the credit to
        `REVERSED`."
        PRD §3.7: "When the case is `RESOLVED_MERCHANT_FAVOR` and the credit is
        `REVERSED`, a `FinanceOfficer` may reinstate it".

        Design: Difficulty/non_linear_state_machine/provisional_credit_reversal_reinstatement_cycle
        """
        account, _txn, case, credit = setup_reversal_pending(
            balance=100000, amount=20000, claim=20000, claimed_delay=5,
        )
        resp = api.reverse_provisional_credit(
            credit["id"], TEST_USERS["finance_officer_headers"]
        )
        reversed_credit = validate_success(resp)
        assert reversed_credit["status"] == "REVERSED"
        # The reinstatement path is only open from RESOLVED_MERCHANT_FAVOR.
        assert get_case(case["id"])["status"] == "RESOLVED_MERCHANT_FAVOR"


class TestRepresentmentAcceptCascade:
    def test_representment_accept_cascades_loss_and_notice(self, api):
        """PRD §3.6: "An `ACCEPT` decision concedes: the Representment becomes
        `ACCEPTED`, the chargeback closes as `CLOSED_LOST` with `outcome` set to
        `LOST`, and the case forks on whether a credit is open."
        PRD §3.6: "with no open credit it moves straight to
        `RESOLVED_MERCHANT_FAVOR` with a `RESOLUTION_LETTER` and the transaction
        settles."
        PRD §3.6: "Either way, an automatic `LOSS_RECOGNIZED` ledger entry
        records the chargeback's `fees_total_cents` plus any finalized credit
        principal the issuer bears — zero when no credit has been finalized."

        Design: Difficulty/transitive_cascade/representment_accept_cascades_loss_and_notice
        """
        account, txn, case, chargeback = setup_representment_accepted_case(
            balance=50000, amount=12000,
        )
        cb = get_success_data(api.get_chargeback(
            chargeback["id"], TEST_USERS["chargeback_analyst_headers"],
        ))
        assert cb["status"] == "CLOSED_LOST"
        assert cb["outcome"] == "LOST"
        resolved = get_case(case["id"])
        assert resolved["status"] == "RESOLVED_MERCHANT_FAVOR"
        assert resolved["outstanding_loss_cents"] == 2500
        entries = get_success_data(api.list_loss_recoveries(
            case["id"], TEST_USERS["finance_officer_headers"],
        ))
        assert entries[0]["type"] == "LOSS_RECOGNIZED"
        assert entries[0]["amount_cents"] == 2500
        assert entries[0]["source"] == "AUTO"

    def test_representment_accept_issues_resolution_letter(self, api):
        """PRD §3.6: "with no open credit it moves straight to
        `RESOLVED_MERCHANT_FAVOR` with a `RESOLUTION_LETTER` and the transaction
        settles."

        Design: Difficulty/transitive_cascade/representment_accept_cascades_loss_and_notice
        """
        account, txn, case, chargeback = setup_representment_accepted_case(
            balance=50000, amount=12000,
        )
        notes = get_success_data(api.list_case_notifications(
            case["id"], TEST_USERS["finance_officer_headers"],
        ))
        types = {n["type"] for n in notes}
        assert "RESOLUTION_LETTER" in types, (
            f"accept with no open credit must issue a RESOLUTION_LETTER, got {types}"
        )
        txns = get_success_data(api.list_account_transactions(
            account["id"], TEST_USERS["chargeback_analyst_headers"],
        ))
        assert txns[0]["status"] == "SETTLED"


class TestCardholderWithdrawal:
    def test_withdraw_terminal_case_returns_invalid_state(self, api):
        """PRD §3.7: "A `Cardholder` (own cases only — withdrawing someone else's
        case fails ownership with `ERR_FORBIDDEN`) or an `IntakeAgent` may
        withdraw a case from `RECEIVED` or `CLASSIFIED`, landing it in
        `WITHDRAWN`" — a case in terminal `RESOLVED_MERCHANT_FAVOR` is in
        neither from-state.
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".

        Design: Corner/state_machines/withdraw_terminal_case_returns_invalid_state
        """
        account, _txn, case = setup_resolved_merchant_favor_no_credit(
            balance=50000, amount=5000,
        )
        resp = api.withdraw_dispute(
            case["id"], make_cardholder_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_auto_reverses_open_credit(self, api):
        """PRD §3.7: "Withdrawal from `CLASSIFIED` while a credit is open
        auto-reverses that credit immediately: the account's `balance_cents` and
        `provisional_outstanding_cents` drop by the credit amount and the credit
        becomes `REVERSED` — a cardholder-initiated withdrawal waives the
        three-business-day notice, so no cooling period applies."

        Design: Corner/state_machines/withdraw_auto_reverses_open_credit
        """
        account, _txn, case, credit = setup_classified_case_with_credit(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        resp = api.withdraw_dispute(
            case["id"], make_cardholder_headers(account["id"])
        )
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"
        after = get_account(account["id"])
        assert after["balance_cents"] == 50000, (
            f"immediate reversal must restore the balance, got {after['balance_cents']}"
        )
        assert after["provisional_outstanding_cents"] == 0
        credits = get_success_data(api.list_case_provisional_credits(
            case["id"], TEST_USERS["finance_officer_headers"],
        ))
        assert credits[0]["status"] == "REVERSED"
