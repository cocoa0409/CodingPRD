"""Accounts settlement ledger, review holds, and unauthorized-item liability
claims with their cascading enrollment effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_account_ledger_invariants,
    create_active_enrollment,
    decide,
    get_account,
    get_enrollment,
    get_exception,
    make_bank_ops_headers,
    make_bank_treasury_manager_headers,
    make_check_row,
    present_item,
    set_clock,
    setup_case_under_review,
    setup_liability_case,
    setup_open_exception,
    setup_paid_item,
    upload_checks,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


# ----------------------------------------------------------------------
# Settlement ledger pay/reverse invariant
# ----------------------------------------------------------------------

class TestPayReverseInvariant:
    def test_pay_event_moves_gross_and_net(self, api):
        """PRD §3.2: "On every item pay event — a clean auto-match, an exception
        decided to pay, or an exception defaulted to pay — the item's
        `amount_cents` is added to `cumulative_paid_cents`."
        PRD §3.2: "Both gross counters only ever increase; `net_settled_cents`
        is recomputed on every mutation as the paid total minus the reversed
        total."

        Design: Difficulty/compensating_invariant/pay_reverse_pair_preserves_net_settled
        """
        b = setup_paid_item(7000, payee="THETA CO", business_name="NetCo",
                            account_number="990007", check_number="901",
                            user_roles=("ADMIN",))
        account = get_account(b["account"]["id"])
        assert account["cumulative_paid_cents"] == 7000
        assert account["cumulative_reversed_cents"] == 0
        assert account["net_settled_cents"] == 7000
        assert_account_ledger_invariants(account)

    def test_reversal_restores_net_while_gross_counters_grow(self, api):
        """PRD §3.2: "The invariant is that a pay event followed by its own
        reversal leaves `net_settled_cents` exactly where it was before the
        payment, while both gross counters have moved."
        PRD §3.4: "The reversal adds the item's `amount_cents` to the account's
        `cumulative_reversed_cents` and recomputes `net_settled_cents`,
        returning the net figure to its pre-payment value."

        Design: Difficulty/compensating_invariant/pay_reverse_pair_preserves_net_settled
        """
        b = setup_paid_item(7000, payee="THETA CO", business_name="NetCo2",
                            account_number="990017", check_number="901",
                            user_roles=("ADMIN",))
        reversed_item = validate_success(api.reverse_presented_item(
            b["item"]["id"], "posting error", BANK_MGR))
        assert reversed_item["status"] == "REVERSED"
        account = get_account(b["account"]["id"])
        assert account["cumulative_paid_cents"] == 7000
        assert account["cumulative_reversed_cents"] == 7000
        assert account["net_settled_cents"] == 0, (
            "pay +X then reverse -X nets to zero")


# ----------------------------------------------------------------------
# Review-hold cascade
# ----------------------------------------------------------------------

class TestReviewHoldCascade:
    def _setup(self):
        b = create_active_enrollment("HoldCo", "PAYEE_POSITIVE_PAY", "RETURN",
                                     account_number="970001",
                                     user_roles=("ADMIN", "DECISION_MAKER"),
                                     payment_review_threshold_cents=30001)
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-HOLD",
                      [make_check_row("301", 30000, "GAMMA INC"),
                       make_check_row("302", 5000, "DELTA CO"),
                       make_check_row("303", 6000, "EPSILON LTD")],
                      b["headers"]["ADMIN"])
        item1 = present_item(b["account"]["id"], "301", 30001, "GAMMA INC",
                             presented_at="2026-08-03T10:00:00Z")
        assert item1["match_result"] == "AMOUNT_MISMATCH"
        return b, item1

    def test_decision_pay_crossing_threshold_holds_account(self, api):
        """PRD §3.2: "if `payment_review_threshold_cents` is non-null, the
        account is still `ACTIVE`, and `cumulative_paid_cents` has reached or
        exceeded the threshold — equality triggers — the account automatically
        transitions to `REVIEW_HOLD`."

        Design: Difficulty/transitive_cascade/decision_pay_cascade_account_review_hold
        """
        b, item1 = self._setup()
        decided = decide(item1["exception_id"], "PAY",
                         b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_PAY"
        account = get_account(b["account"]["id"])
        assert account["cumulative_paid_cents"] == 30001, (
            "the item pays at the presented amount")
        assert account["status"] == "REVIEW_HOLD", (
            "cumulative_paid_cents == threshold triggers the hold (>= boundary)")

    def test_held_account_exceptions_then_clean_after_clear(self, api):
        """PRD §3.2: "While an account is in `REVIEW_HOLD`, auto-matching is
        suspended: every item ingested against it becomes an exception with
        reason `ACCOUNT_HOLD_REVIEW` (see §3.4)."
        PRD §3.2: "clearing the hold does not retro-process items already held —
        it only restores clean auto-matching for future items".

        Design: Difficulty/transitive_cascade/decision_pay_cascade_account_review_hold
        """
        b, item1 = self._setup()
        decide(item1["exception_id"], "PAY", b["headers"]["DECISION_MAKER"])
        item2 = present_item(b["account"]["id"], "302", 5000, "DELTA CO",
                             presented_at="2026-08-03T11:00:00Z")
        assert item2["status"] == "EXCEPTION_HELD"
        assert item2["match_result"] == "ACCOUNT_HOLD_REVIEW"
        cleared = validate_success(
            api.clear_review_hold(b["account"]["id"], BANK_OPS))
        assert cleared["status"] == "ACTIVE"
        item3 = present_item(b["account"]["id"], "303", 6000, "EPSILON LTD",
                             presented_at="2026-08-03T11:30:00Z")
        assert item3["status"] == "PAID"
        assert get_account(b["account"]["id"])["cumulative_paid_cents"] == 36001


# ----------------------------------------------------------------------
# Reverse / close state gates
# ----------------------------------------------------------------------

class TestItemAndAccountStateGates:
    def test_reverse_of_returned_item_rejected(self, api):
        """PRD §3.4: "any attempt to reverse an item not in `PAID` is rejected
        with `ERR_ITEM_NOT_REVERSIBLE`."

        Design: Corner/state_machines/reverse_returned_item_rejected
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="RevCo",
                                 account_number="810004")
        decided = decide(b["exception_id"], "RETURN",
                         b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_RETURN"
        resp = api.reverse_presented_item(b["item"]["id"], "try", BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_REVERSIBLE)

    def test_account_close_blocked_until_exception_resolved(self, api):
        """PRD §3.2: "The close is blocked while any exception with this
        `account_id` is `OPEN` (`ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS`)."

        Design: Corner/state_machines/account_close_blocked_by_open_exception
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="BlkCo",
                                 account_number="810007")
        resp = api.close_account(b["account"]["id"], BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS)
        decide(b["exception_id"], "PAY", b["headers"]["DECISION_MAKER"])
        closed = validate_success(api.close_account(b["account"]["id"],
                                                    BANK_MGR))
        assert closed["status"] == "CLOSED"


# ----------------------------------------------------------------------
# Liability cases
# ----------------------------------------------------------------------

class TestLiabilityCases:
    def test_claim_on_returned_item_rejected(self, api):
        """PRD §3.8: "Filing requires the item be in `PAID` status (otherwise
        `ERR_ITEM_NOT_CLAIMABLE`)".

        Design: Corner/rbac/claim_on_returned_item_rejected
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="RETURN", business_name="ClmCo",
                                 account_number="850009")
        decide(b["exception_id"], "RETURN", b["headers"]["DECISION_MAKER"])
        resp = api.file_liability_case(
            {"presented_item_id": b["item"]["id"], "claim_reason": "COUNTERFEIT"},
            b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_CLAIMABLE)

    def test_resolve_before_review_rejected(self, api):
        """PRD §3.8: "Resolution is manager-only, taking a `resolution` of
        `BANK_LIABLE`, `CUSTOMER_LIABLE`, or `SHARED`, and requires the case be
        `UNDER_REVIEW` (`ERR_CASE_NOT_OPEN`)."

        Design: Corner/state_machines/case_resolve_before_review_rejected
        """
        b = setup_liability_case(9000, claim_reason="COUNTERFEIT",
                                 business_name="SkipCo", account_number="810009")
        resp = api.resolve_case(b["case"]["id"], "BANK_LIABLE", BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN)

    def test_shared_split_odd_cent_lands_on_customer(self, api):
        """PRD §3.8: "`RESOLVED_SHARED` gives the bank the claim amount divided
        by two rounded down to a whole cent and the customer the remainder, so
        an odd cent always lands on the customer — a 10001-cent claim splits
        5000 to the bank and 5001 to the customer."

        Design: Corner/calculations/shared_split_odd_cent_to_customer
        """
        b = setup_case_under_review(10001, claim_reason="ALTERED_AMOUNT",
                                    bank_ops_user_id="bank-ops-7",
                                    business_name="OddCo",
                                    account_number="820009")
        assert b["case"]["claim_amount_cents"] == 10001
        resolved = validate_success(api.resolve_case(
            b["case"]["id"], "SHARED",
            make_bank_treasury_manager_headers("bank-mgr-1")))
        assert resolved["status"] == "RESOLVED_SHARED"
        assert resolved["bank_liability_cents"] == 5000
        assert resolved["customer_liability_cents"] == 5001

    def test_provisional_credit_cap_boundary(self, api):
        """PRD §3.8: "if `claim_amount_cents` is at most 25000 cents,
        `provisional_credit_cents` is set to the full claim amount and the same
        amount is added to the enrollment's
        `provisional_credit_outstanding_cents`; above 25000 cents no provisional
        credit posts and `provisional_credit_cents` stays zero."

        Design: Corner/calculations/provisional_credit_cap_boundary
        """
        b = create_active_enrollment("CapCo", "POSITIVE_PAY", "PAY",
                                     account_number="820010",
                                     user_roles=("ADMIN", "DECISION_MAKER"))
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-CAP",
                      [make_check_row("1", 25000, "A CO"),
                       make_check_row("2", 25001, "B CO")],
                      b["headers"]["ADMIN"])
        it1 = present_item(b["account"]["id"], "1", 25000, "A CO",
                           presented_at="2026-08-03T10:00:00Z")
        it2 = present_item(b["account"]["id"], "2", 25001, "B CO",
                           presented_at="2026-08-03T10:01:00Z")
        cs1 = validate_success(api.file_liability_case(
            {"presented_item_id": it1["id"],
             "claim_reason": "FORGED_SIGNATURE"},
            b["headers"]["DECISION_MAKER"]), 201)
        cs2 = validate_success(api.file_liability_case(
            {"presented_item_id": it2["id"],
             "claim_reason": "FORGED_SIGNATURE"},
            b["headers"]["DECISION_MAKER"]), 201)
        r1 = validate_success(api.start_case_review(cs1["id"], BANK_OPS))
        r2 = validate_success(api.start_case_review(cs2["id"], BANK_OPS))
        assert r1["provisional_credit_cents"] == 25000, "claim at cap posts in full"
        assert r2["provisional_credit_cents"] == 0, "claim at cap + 1 posts nothing"

    def test_claim_window_thirty_day_boundary(self, api):
        """PRD §3.8: "the logical clock must be no later than thirty days after
        the item's `paid_at`, with a filing exactly thirty days after still
        accepted and anything later rejected with `ERR_CLAIM_WINDOW_CLOSED`."

        Design: Corner/calculations/claim_window_thirty_day_boundary
        """
        b = create_active_enrollment("WinCo2", "POSITIVE_PAY", "PAY",
                                     account_number="820011",
                                     user_roles=("ADMIN", "DECISION_MAKER"),
                                     trainer_id="tr-1",
                                     training_start="2026-07-01T09:00:00Z",
                                     training_end="2026-07-01T10:00:00Z")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-WIN",
                      [make_check_row("1", 100, "A"),
                       make_check_row("2", 100, "B")],
                      b["headers"]["ADMIN"])
        set_clock("2026-08-01T10:00:00Z")
        it1 = present_item(b["account"]["id"], "1", 100, "A")
        it2 = present_item(b["account"]["id"], "2", 100, "B")
        set_clock("2026-08-31T10:00:00Z")
        ok = validate_success(api.file_liability_case(
            {"presented_item_id": it1["id"], "claim_reason": "COUNTERFEIT"},
            b["headers"]["DECISION_MAKER"]), 201)
        assert ok["status"] == "FILED", "filing at exactly paid_at + 30d is accepted"
        set_clock("2026-08-31T10:00:01Z")
        resp = api.file_liability_case(
            {"presented_item_id": it2["id"], "claim_reason": "COUNTERFEIT"},
            b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED)

    def test_large_claim_resolver_must_differ_from_assignee(self, api):
        """PRD §2.8: "When resolving a liability case whose `claim_amount_cents`
        is strictly greater than 25000 cents, the resolving
        `BankTreasuryManager`'s `X-User-ID` must differ from the case's
        `assigned_bank_user_id`. A violation is rejected with
        `ERR_SOD_CASE_RESOLUTION_CONFLICT`."

        Design: Corner/rbac/sod_case_resolution_conflict
        """
        b = setup_case_under_review(30000, bank_ops_user_id="bank-ops-1",
                                    business_name="SodCaseCo",
                                    account_number="850007")
        resp = api.resolve_case(
            b["case"]["id"], "BANK_LIABLE",
            make_bank_treasury_manager_headers("bank-ops-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_CASE_RESOLUTION_CONFLICT)
        resolved = validate_success(api.resolve_case(
            b["case"]["id"], "BANK_LIABLE",
            make_bank_treasury_manager_headers("bank-mgr-2")))
        assert resolved["status"] == "RESOLVED_BANK_LIABLE"
        assert resolved["bank_liability_cents"] == 30000

    def test_withdraw_reverses_outstanding_provisional_credit(self, api):
        """PRD §3.8: "Withdrawing from `UNDER_REVIEW` reverses any outstanding
        provisional credit by subtracting `provisional_credit_cents` from the
        enrollment's `provisional_credit_outstanding_cents`".

        Design: Corner/rbac/case_withdraw_reverses_provisional
        """
        b = setup_case_under_review(12000, claim_reason="UNAUTHORIZED_PAYEE",
                                    bank_ops_user_id="bank-ops-1",
                                    business_name="WdrCo",
                                    account_number="850008")
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["provisional_credit_outstanding_cents"] == 12000
        withdrawn = validate_success(api.withdraw_case(
            b["case"]["id"], b["headers"]["DECISION_MAKER"]))
        assert withdrawn["status"] == "WITHDRAWN"
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["provisional_credit_outstanding_cents"] == 0


# ----------------------------------------------------------------------
# Bank-liable resolution cascade into enrollment auto-suspension
# ----------------------------------------------------------------------

def _loss_setup():
    b = create_active_enrollment("LossCo", "POSITIVE_PAY", "RETURN",
                                 account_number="970002",
                                 user_roles=("ADMIN", "DECISION_MAKER"),
                                 loss_suspension_threshold_cents=30000)
    upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-LOSS",
                  [make_check_row("401", 20000, "ZETA CORP"),
                   make_check_row("402", 15000, "ETA LLC")],
                  b["headers"]["ADMIN"])
    it1 = present_item(b["account"]["id"], "401", 20000, "ZETA CORP",
                       presented_at="2026-08-03T09:00:00Z")
    it2 = present_item(b["account"]["id"], "402", 15000, "ETA LLC",
                       presented_at="2026-08-03T09:05:00Z")
    ex3 = present_item(b["account"]["id"], "999", 500, "GHOST",
                       presented_at="2026-08-03T09:10:00Z")["exception_id"]
    cases = []
    for item, reason in ((it1, "FORGED_SIGNATURE"), (it2, "COUNTERFEIT")):
        case = validate_success(api_client.file_liability_case(
            {"presented_item_id": item["id"], "claim_reason": reason},
            b["headers"]["DECISION_MAKER"]), 201)
        case = validate_success(api_client.start_case_review(
            case["id"], make_bank_ops_headers("bank-ops-1")))
        cases.append(case)
    return b, cases, ex3


class TestLossSuspensionCascade:
    def test_first_resolution_below_threshold_keeps_active(self, api):
        """PRD §3.8: "Whenever the bank bears any share, that share is added to
        the enrollment's `ytd_bank_loss_cents`, which accumulates the
        bank-liability amounts of cases resolved within the calendar year of
        their resolution."
        PRD §3.8: "after a resolution that adds to it, if
        `loss_suspension_threshold_cents` is non-null and `ytd_bank_loss_cents`
        has reached or exceeded it, an `ACTIVE` enrollment transitions to
        `SUSPENDED` without any operator action."

        Design: Difficulty/transitive_cascade/bank_liable_resolution_cascade_enrollment_suspension
        """
        b, cases, _ = _loss_setup()
        resolved = validate_success(api.resolve_case(
            cases[0]["id"], "BANK_LIABLE",
            make_bank_treasury_manager_headers("bank-mgr-9")))
        assert resolved["bank_liability_cents"] == 20000
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["ytd_bank_loss_cents"] == 20000
        assert enr["status"] == "ACTIVE", "20000 < 30000: no premature suspension"

    def test_second_resolution_crossing_threshold_suspends_enrollment(
            self, api):
        """PRD §3.8: "after a resolution that adds to it, if
        `loss_suspension_threshold_cents` is non-null and `ytd_bank_loss_cents`
        has reached or exceeded it, an `ACTIVE` enrollment transitions to
        `SUSPENDED` without any operator action."
        PRD §3.8: "Every resolution first unwinds the provisional credit,
        subtracting `provisional_credit_cents` from the enrollment's
        `provisional_credit_outstanding_cents`".

        Design: Difficulty/transitive_cascade/bank_liable_resolution_cascade_enrollment_suspension
        """
        b, cases, ex3 = _loss_setup()
        for case in cases:
            validate_success(api.resolve_case(
                case["id"], "BANK_LIABLE",
                make_bank_treasury_manager_headers("bank-mgr-9")))
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["ytd_bank_loss_cents"] == 35000
        assert enr["status"] == "SUSPENDED", "35000 >= 30000 triggers auto-suspension"
        assert enr["provisional_credit_outstanding_cents"] == 0
        resp = api.decide_exception(ex3, "RETURN",
                                    b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
