"""Retained asset accounts: provisional vs final yield, the deposit/withdrawal
principal invariant, the withdrawal balance boundary, dormancy flips with
their strict-inequality boundary, and owner-activity reactivation."""
from test_helpers import (
    ApiErrorId,
    assert_raa_principal_invariant,
    get_account,
    list_escheatment_cases,
    set_clock,
    setup_dormant_raa,
    setup_paid_claim_with_raa,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalYield:
    def test_provisional_simple_yield_on_read(self, api,
                                              claims_approver_headers):
        """PRD §3.9: "The `provisional_interest_cents` field is a statement
        estimate recomputed on every read: simple interest on the current
        `balance_cents` at the statute's `raa_annual_interest_rate_bp` for the
        number of days the account has been open — the logical current date
        minus the creation date — over a 365-day year, rounded half-up to whole
        cents."

        Account funded 2026-04-01, read at 2026-07-01: 91 days open,
        10000000 x 3% x 91/365 = 74795 (half-up of 74794.52).

        Design: Difficulty/dual_variant_calc/raa_provisional_simple_vs_final_compound_yield
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z", state="TX",
            policy_overrides={"policy_number": "P-TX-1"})
        set_clock("2026-07-01T00:00:00Z")
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 10000000
        assert account["provisional_interest_cents"] == 74795
        assert account["interest_paid_cents"] == 0, (
            "The final figure stays zero until closure or escheatment")

    def test_final_compound_yield_at_closure(self, api,
                                             claims_approver_headers):
        """PRD §3.9: "The compounding period count is the number of complete
        calendar months between the account's creation date and its closing or
        escheat date, where a month completes on the same day of month as the
        creation day and any residual days earn nothing."
        PRD §3.9: "The posted interest is the closing balance multiplied by the
        growth factor — one plus the monthly rate, the monthly rate being the
        statute's `raa_annual_interest_rate_bp` divided by ten thousand and
        then by twelve, raised to the power of the complete-month count, with
        one subtracted — rounded half-up to whole cents."
        PRD §3.9: "Because the provisional figure is simple interest on the
        current balance while the final figure compounds over complete months,
        the two diverge for identical balances, and only the final figure is
        ever posted."

        Same balance at the same date: the provisional read shows 74795 while
        closure posts 75188 = 10000000 x ((1 + 0.03/12)^3 - 1) (half-up of
        75187.66) over the three complete months from 2026-04-01 to 2026-07-01.

        Design: Difficulty/dual_variant_calc/raa_provisional_simple_vs_final_compound_yield
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z", state="TX",
            policy_overrides={"policy_number": "P-TX-1"})
        set_clock("2026-07-01T00:00:00Z")
        provisional = get_account(ctx["account"]["id"])["provisional_interest_cents"]

        closed = validate_success(
            api.withdraw_from_account(ctx["account"]["id"],
                                      {"amount_cents": 10000000},
                                      claims_approver_headers))
        assert closed["status"] == "CLOSED"
        assert closed["balance_cents"] == 0
        assert closed["interest_paid_cents"] == 75188
        assert provisional == 74795
        assert provisional != closed["interest_paid_cents"], (
            "Provisional (simple) and final (compounded) yields must diverge "
            "for identical balances")


class TestPrincipalConservation:
    def test_partial_withdrawal_conserves_principal(
        self, api, claims_approver_headers
    ):
        """PRD §3.9: "A successful withdrawal reduces `balance_cents` by the
        amount, adds it to `withdrawn_total_cents`, and stamps
        `last_activity_at` from the logical clock."
        PRD §3.9: "its `deposited_cents` preserve the initial deposit — the
        beneficiary claim's allocated amount at funding — and are immutable,
        while `balance_cents` tracks the current principal."

        After the forward deposit (10000000) and a compensating partial
        withdrawal (4000000): balance 6000000 + withdrawn 4000000 ==
        deposited 10000000, and the account stays OPEN.

        Design: Difficulty/compensating_invariant/raa_deposit_withdrawal_cycle_conserves_balance
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z", state="TX",
            policy_overrides={"policy_number": "P-INV-1"})
        account = ctx["account"]
        assert account["deposited_cents"] == 10000000
        assert_raa_principal_invariant(account)

        set_clock("2026-05-01T00:00:00Z")
        after = validate_success(
            api.withdraw_from_account(account["id"], {"amount_cents": 4000000},
                                      claims_approver_headers))
        assert after["status"] == "OPEN"
        assert after["balance_cents"] == 6000000
        assert after["withdrawn_total_cents"] == 4000000
        assert after["deposited_cents"] == 10000000
        assert_raa_principal_invariant(after)

    def test_full_withdrawal_closes_with_final_yield(
        self, api, claims_approver_headers
    ):
        """PRD §3.9: "A withdrawal that reduces the balance to exactly zero
        closes the account: the final compound yield is posted as
        `interest_paid_cents` and paid out together with the final withdrawal,
        and the account moves to the terminal `CLOSED` state."

        The closing balance is 6000000 (after the 4000000 partial), and three
        complete months elapsed from 2026-04-01 to 2026-07-01, so the final
        yield is 6000000 x ((1 + 0.03/12)^3 - 1) = 45113 (half-up of
        45112.59); the principal invariant still holds at closure.

        Design: Difficulty/compensating_invariant/raa_deposit_withdrawal_cycle_conserves_balance
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z", state="TX",
            policy_overrides={"policy_number": "P-INV-1"})
        account_id = ctx["account"]["id"]
        set_clock("2026-05-01T00:00:00Z")
        validate_success(api.withdraw_from_account(account_id,
                                                   {"amount_cents": 4000000},
                                                   claims_approver_headers))

        set_clock("2026-07-01T00:00:00Z")
        closed = validate_success(
            api.withdraw_from_account(account_id, {"amount_cents": 6000000},
                                      claims_approver_headers))
        assert closed["status"] == "CLOSED"
        assert closed["balance_cents"] == 0
        assert closed["withdrawn_total_cents"] == 10000000
        assert_raa_principal_invariant(closed)
        assert closed["interest_paid_cents"] == 45113, (
            "Final compound yield posts on the closing balance without "
            "perturbing the principal invariant")


class TestWithdrawalBalanceBoundary:
    def test_withdrawal_balance_boundary(self, api, claims_approver_headers):
        """PRD §3.9: "The account must be `OPEN` or `DORMANT` — a closed or
        escheated account rejects the withdrawal with
        `ERR_ACCOUNT_NOT_WITHDRAWABLE` — the `amount_cents` must be greater
        than zero (`ERR_INVALID_REQUEST`), and it must not exceed the current
        `balance_cents`, else `ERR_INSUFFICIENT_ACCOUNT_BALANCE`."
        PRD §3.9: "A withdrawal that reduces the balance to exactly zero closes
        the account: the final compound yield is posted as `interest_paid_cents`
        and paid out together with the final withdrawal, and the account moves
        to the terminal `CLOSED` state."

        Boundary precision: balance + 1 is rejected; exactly balance closes the
        account; a further draft against the CLOSED account is rejected.

        Design: Corner/state_machines/c_raa_withdrawal_balance_boundary
        """
        ctx = setup_paid_claim_with_raa(state="TX", policy_overrides={
            "policy_number": "P-SM-15"})
        account_id = ctx["account"]["id"]

        over = api.withdraw_from_account(account_id, {"amount_cents": 10000001},
                                         claims_approver_headers)
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_ACCOUNT_BALANCE)
        assert get_account(account_id)["balance_cents"] == 10000000, (
            "A rejected withdrawal must not move the balance")

        closed = validate_success(
            api.withdraw_from_account(account_id, {"amount_cents": 10000000},
                                      claims_approver_headers))
        assert closed["status"] == "CLOSED"
        assert closed["balance_cents"] == 0

        after_close = api.withdraw_from_account(account_id, {"amount_cents": 1},
                                                claims_approver_headers)
        validate_error(after_close, ApiErrorId.ERR_ACCOUNT_NOT_WITHDRAWABLE)


class TestDormancyAndReactivation:
    def test_dormancy_boundary_and_case_creation(
        self, api, compliance_officer_headers
    ):
        """PRD §3.9: "When the logical current date passes the account's
        `last_activity_at` by strictly more than the statute's `dormancy_years`
        calendar years — a date exactly equal to the anniversary leaves the
        account `OPEN` — the account flips from `OPEN` to `DORMANT`, and the
        system opens an escheatment case over it with `subject_type`
        `RETAINED_ASSET_ACCOUNT`, status `MONITORING`, and `trigger_date` set
        to the date of the account's last activity."
        PRD §2.4: "First, retained-asset dormancy is evaluated: accounts whose
        last activity lies strictly more than the governing statute's dormancy
        period in the past flip from `OPEN` to `DORMANT`, each spawning an
        escheatment case. Second, escheatment-case progression is evaluated:
        cases in `MONITORING` whose due-diligence start has been reached
        advance to `DUE_DILIGENCE`."

        Funded 2026-04-01 under a 3-year dormancy statute: at the exact
        anniversary 2029-04-01 the account stays OPEN with no case; one day
        later the sweep flips it DORMANT and the new case — whose
        due-diligence start (2028-12-11) already lies in the past — advances
        to DUE_DILIGENCE in the same sweep.

        Design: Corner/state_machines/c_raa_dormancy_boundary_and_case_creation
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z", state="TX",
            policy_overrides={"policy_number": "P-SM-12"})
        account_id = ctx["account"]["id"]

        set_clock("2029-04-01T00:00:00Z")
        assert get_account(account_id)["status"] == "OPEN", (
            "Exactly at the anniversary the account stays OPEN (strict >)")
        assert list_escheatment_cases({"account_id": account_id}) == []

        set_clock("2029-04-02T00:00:00Z")
        assert get_account(account_id)["status"] == "DORMANT"
        cases = list_escheatment_cases({"account_id": account_id})
        assert len(cases) == 1
        case = cases[0]
        assert case["subject_type"] == "RETAINED_ASSET_ACCOUNT"
        assert case["status"] == "DUE_DILIGENCE"
        assert case["trigger_date"] == "2026-04-01"
        assert case["escheat_due_date"] == "2029-04-01"

    def test_escheatment_resolve_reactivates_dormant_account(
        self, api, compliance_officer_headers
    ):
        """PRD §3.9: "Resolving a case requires it to be in `MONITORING` or
        `DUE_DILIGENCE` — otherwise `ERR_CASE_NOT_ACTIONABLE` — stores an
        optional `resolution_note`, and moves the case to the terminal
        `RESOLVED` state; when the subject is a retained asset account, the
        account also reactivates from `DORMANT` to `OPEN` with
        `last_activity_at` refreshed."

        Design: Corner/state_machines/c_escheatment_resolve_reactivates_dormant_raa
        """
        ctx = setup_dormant_raa(3, state="TX", policy_overrides={
            "policy_number": "P-SM-14"})
        case = ctx["case"]
        assert case["status"] == "DUE_DILIGENCE"

        resolved = validate_success(
            api.resolve_escheatment_case(case["id"],
                                         {"resolution_note": "OWNER_LOCATED"},
                                         compliance_officer_headers))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "OWNER_LOCATED"

        account = get_account(ctx["account"]["id"])
        assert account["status"] == "OPEN"
        assert account["last_activity_at"].startswith("2029-04-02"), (
            "Reactivation refreshes the dormancy clock anchor")
        assert account["balance_cents"] == 10000000
