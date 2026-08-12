"""Return recording, reason coding, the tiered return-item fee, balance
derivation variants, compensating ledger entries, and fee waivers."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_account,
    create_check_item,
    create_clearing_bank,
    setup_coded_return,
    setup_presented_item,
    setup_returned_item,
    sum_ledger_entries,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    PROCESSOR,
    SERVICE,
    get_account,
    get_fee_for_return_event,
    list_ledger_entries,
)


class TestReasonCoding:
    def test_code_already_coded_returns_invalid_state(self, api):
        """PRD §3.4: "moving the return event from `PENDING_CODING` to `CODED`
        with `coded_at` recorded" — coding is defined only from
        PENDING_CODING.
        PRD §2.11: "sixth, state-machine preconditions for the requested
        transition (`ERR_INVALID_STATE`, `ERR_ACCOUNT_FROZEN`,
        `ERR_CLEARING_BANK_SUSPENDED`, `ERR_MAX_PRESENTMENTS_EXCEEDED`,
        `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`)"

        Design: Corner/state_machines/code_already_coded_returns_invalid_state
        """
        ctx = setup_coded_return(
            reason_code="NSF", amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB CC", "routing_number": "222000013"},
            item_reference="ITM-CC",
        )
        res = api.code_return_event(
            ctx["return_event"]["id"], {"reason_code": "STOP_PAYMENT"}, PROCESSOR
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_invalid_reason_code_rejected(self, api):
        """PRD §3.4: "An `ItemProcessor` supplies a `reason_code` — one of
        `NSF`, `STOP_PAYMENT`, `CLOSED_ACCOUNT`, `MISSING_ENDORSEMENT`,
        `ALTERED_OR_FICTITIOUS`, `IMAGE_NONCONFORMING`,
        `DUPLICATE_PRESENTMENT`, or `REFER_TO_MAKER`"
        PRD §2.11: "and eleventh, amount sanity and request shape
        (`ERR_INVALID_AMOUNT`, `ERR_INVALID_REQUEST`)."

        Design: Corner/errors/invalid_enum_rejected
        """
        ctx = setup_returned_item(
            amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB IE", "routing_number": "222000039"},
            item_reference="ITM-IE",
        )
        res = api.code_return_event(
            ctx["return_event"]["id"], {"reason_code": "NOT_A_REASON"}, PROCESSOR
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestReturnItemFee:
    def _two_nsf_returns_high_risk(self, api):
        """HIGH_RISK account with two presented+returned items, both coded NSF
        at the same logical clock, so the second coding sees one prior return."""
        ctx = setup_coded_return(
            reason_code="NSF", amount_cents=100000, opening_balance_cents=1000000,
            risk_tier="HIGH_RISK",
            bank_overrides={"name": "CB Fee", "routing_number": "111000027"},
            item_reference="ITM-F1",
        )
        account, bank = ctx["account"], ctx["bank"]
        item2 = create_check_item(account["id"], bank["id"], item_reference="ITM-F2",
                                  amount_cents=50000, capture_channel="ATM")
        validate_success(api.present_check_item(item2["id"], PROCESSOR), 200)
        re2 = validate_success(api.create_return_event(item2["id"], PROCESSOR), 201)
        validate_success(
            api.code_return_event(re2["id"], {"reason_code": "NSF"}, PROCESSOR), 200
        )
        return ctx["fee"], get_fee_for_return_event(re2["id"])

    def test_first_nsf_return_fee_uses_base_times_risk_multiplier(self, api):
        """PRD §3.4: "The base fee depends on the reason: 2500 cents for
        `NSF`, 3000 cents for `CLOSED_ACCOUNT`, 1500 cents for
        `REFER_TO_MAKER`, and zero for `STOP_PAYMENT`, `MISSING_ENDORSEMENT`,
        `ALTERED_OR_FICTITIOUS`, `IMAGE_NONCONFORMING`, and
        `DUPLICATE_PRESENTMENT`."
        PRD §3.4: "The base is multiplied by the account's risk multiplier —
        1.0 for `STANDARD`, 1.5 for `HIGH_RISK` — and that product is rounded
        half-up to whole cents first. A surcharge is then added: zero when
        there are no prior returns, 500 cents when there is one or two, and
        1500 cents when there are three or more."
        (2500 x 1.5 = 3750, zero surcharge on the first coded return.)

        Design: Difficulty/combinatorial_formula/return_fee_tiered_multiplier
        """
        fee1, _fee2 = self._two_nsf_returns_high_risk(api)
        assert fee1["amount_cents"] == 3750
        assert fee1["fee_type"] == "RETURN_ITEM_FEE"
        assert fee1["status"] == "POSTED"

    def test_second_nsf_return_fee_adds_first_surcharge_tier(self, api):
        """PRD §3.4: "Let the account's prior returns be its
        `returned_item_count_30d` minus one — the count is evaluated after the
        current event flips to `CODED`, so subtracting one removes the event
        being coded and leaves only the earlier ones." and "A surcharge is
        then added: zero when there are no prior returns, 500 cents when
        there is one or two, and 1500 cents when there are three or more."
        (Second coded NSF return on HIGH_RISK: 3750 + 500 = 4250.)

        Design: Difficulty/combinatorial_formula/return_fee_tiered_multiplier
        """
        fee1, fee2 = self._two_nsf_returns_high_risk(api)
        assert fee2["amount_cents"] == 4250
        assert fee2["amount_cents"] - fee1["amount_cents"] == 500


class TestCodingCascadeFreezesAccount:
    def _setup_zeroed_account_return(self):
        """STANDARD account, opening 0: deposit +100000 then return -100000
        leaves available_balance_cents == 0 with the account still ACTIVE."""
        ctx = setup_returned_item(
            amount_cents=100000, opening_balance_cents=0,
            bank_overrides={"name": "CB Frz", "routing_number": "111000031"},
            item_reference="ITM-FRZ",
        )
        account = get_account(ctx["account"]["id"])
        assert account["status"] == "ACTIVE"
        assert account["available_balance_cents"] == 0
        return ctx

    def test_return_coding_posts_fee_assessment(self, api):
        """PRD §3.4: "Coding also assesses the return-item fee immediately: a
        `FeeAssessment` of `fee_type` `RETURN_ITEM_FEE` is created in `POSTED`
        status, linked to the account, the `RETURN_ITEM` case, and the coded
        return event, and a `FEE_DEBIT` ledger entry for the negative of the
        fee's `amount_cents` (non-provisional) posts at once"
        (STANDARD first NSF return: 2500 x 1.0 + 0 = 2500.)

        Design: Difficulty/transitive_cascade/return_coding_fee_freezes_account
        """
        ctx = self._setup_zeroed_account_return()
        coded = validate_success(
            api.code_return_event(ctx["return_event"]["id"], {"reason_code": "NSF"}, PROCESSOR),
            200,
        )
        assert coded["status"] == "CODED"

        fee = get_fee_for_return_event(ctx["return_event"]["id"])
        assert fee["amount_cents"] == 2500
        assert fee["status"] == "POSTED"
        assert fee["fee_type"] == "RETURN_ITEM_FEE"

    def test_fee_debit_tips_account_into_frozen(self, api):
        """PRD §3.4: "a `FEE_DEBIT` ledger entry for the negative of the fee's
        `amount_cents` (non-provisional) posts at once — which may itself tip
        the account into `FROZEN`."
        PRD §2.7: "After any ledger write that leaves
        `available_balance_cents` below zero, the account's `status`
        transitions from `ACTIVE` to `FROZEN`"

        Design: Difficulty/transitive_cascade/return_coding_fee_freezes_account
        """
        ctx = self._setup_zeroed_account_return()
        validate_success(
            api.code_return_event(ctx["return_event"]["id"], {"reason_code": "NSF"}, PROCESSOR),
            200,
        )
        account = get_account(ctx["account"]["id"])
        assert account["available_balance_cents"] == -2500
        assert account["status"] == "FROZEN"


class TestCompensatingReturnDebit:
    def _setup_returned_no_coding(self):
        return setup_returned_item(
            amount_cents=100000, opening_balance_cents=7000,
            bank_overrides={"name": "CB Inv", "routing_number": "111000040"},
            item_reference="ITM-INV",
        )

    def test_return_debit_nets_item_ledger_zero(self, api):
        """PRD §3.4: "posts an `ITEM_RETURN_DEBIT` ledger entry for the
        negative of `amount_cents` (provisional)" — paired with the
        `DEPOSIT_CREDIT` posted at intake ("the system immediately posts a
        `DEPOSIT_CREDIT` ledger entry for the full `amount_cents`, marked
        provisional", §3.2), the item's ledger footprint nets to zero.

        Design: Difficulty/compensating_invariant/return_debit_nets_item_ledger_zero
        """
        ctx = self._setup_returned_no_coding()
        entries = list_ledger_entries(check_item_id=ctx["item"]["id"])
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type.get("DEPOSIT_CREDIT") == 100000
        assert by_type.get("ITEM_RETURN_DEBIT") == -100000
        assert sum(e["amount_cents"] for e in entries) == 0

    def test_account_balance_restored_to_opening_after_return(self, api):
        """PRD §2.7: "The `available_balance_cents` of a `DepositorAccount`
        is the sum of `amount_cents` over all of the account's ledger
        entries, provisional and non-provisional alike." (7000 opening +
        100000 deposit - 100000 return debit = 7000.)

        Design: Difficulty/compensating_invariant/return_debit_nets_item_ledger_zero
        """
        ctx = self._setup_returned_no_coding()
        account = get_account(ctx["account"]["id"])
        assert account["available_balance_cents"] == 7000


class TestBalanceVariants:
    def _setup_deposit_then_pay(self, api):
        ctx = setup_presented_item(
            amount_cents=100000, opening_balance_cents=0,
            bank_overrides={"name": "CB One", "routing_number": "111000025"},
            item_reference="ITM-1",
        )
        pre = get_account(ctx["account"]["id"])
        validate_success(api.pay_check_item(ctx["item"]["id"], PROCESSOR), 200)
        post = get_account(ctx["account"]["id"])
        return pre, post

    def test_available_includes_provisional_but_settled_excludes_it(self, api):
        """PRD §2.7: "The `available_balance_cents` of a `DepositorAccount`
        is the sum of `amount_cents` over all of the account's ledger
        entries, provisional and non-provisional alike. The
        `settled_balance_cents` is the sum of `amount_cents` over only those
        entries whose `provisional` flag is false."
        PRD §2.7: "A freshly deposited item therefore raises the available
        balance immediately but does not touch the settled balance until
        payment posts a `SETTLEMENT_CREDIT`."

        Design: Difficulty/dual_variant_calc/account_balance_provisional_vs_settled
        """
        pre, _post = self._setup_deposit_then_pay(api)
        assert pre["available_balance_cents"] == 100000
        assert pre["settled_balance_cents"] == 0
        assert pre["available_balance_cents"] != pre["settled_balance_cents"]

    def test_balances_converge_after_payment(self, api):
        """PRD §2.7: "A freshly deposited item therefore raises the available
        balance immediately but does not touch the settled balance until
        payment posts a `SETTLEMENT_CREDIT`."
        PRD §3.4: "two ledger entries land together — a
        `PROVISIONAL_REVERSAL` for the negative of `amount_cents`
        (provisional) that withdraws the provisional deposit credit, and a
        `SETTLEMENT_CREDIT` for the positive `amount_cents` (non-provisional)
        that finally settles the funds."

        Design: Difficulty/dual_variant_calc/account_balance_provisional_vs_settled
        """
        _pre, post = self._setup_deposit_then_pay(api)
        assert post["available_balance_cents"] == 100000
        assert post["settled_balance_cents"] == 100000


class TestFeeWaiver:
    def test_fee_waive_posts_compensating_credit(self, api):
        """PRD §3.7: "Waiving records `waived_by_user_id`, `waive_reason`, and
        `waived_at`, and posts a compensating `FEE_WAIVER_CREDIT` ledger entry
        for the positive `amount_cents`, non-provisional and linked to the fee
        via `fee_assessment_id`"
        (STANDARD first NSF return on an account opened with 100000:
        fee 2500, available 97500 before the waive, 100000 after.)

        Design: Corner/calculations/fee_waive_posts_compensating_credit
        """
        ctx = setup_coded_return(
            reason_code="NSF", amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB FW", "routing_number": "222000023"},
            item_reference="ITM-FW",
        )
        fee = ctx["fee"]
        assert fee["amount_cents"] == 2500

        waived = validate_success(
            api.waive_fee(fee["id"], {"waive_reason": "goodwill"}, SERVICE), 200
        )
        assert waived["status"] == "WAIVED"

        # FEE_DEBIT -2500 + FEE_WAIVER_CREDIT +2500 nets the fee to zero.
        fee_entries = list_ledger_entries(fee_assessment_id=fee["id"])
        by_type = {e["entry_type"]: e["amount_cents"] for e in fee_entries}
        assert by_type.get("FEE_DEBIT") == -2500
        assert by_type.get("FEE_WAIVER_CREDIT") == 2500
        assert sum(e["amount_cents"] for e in fee_entries) == 0

        assert get_account(ctx["account"]["id"])["available_balance_cents"] == 100000

    def test_fee_waive_cap_by_role(self, api):
        """PRD §3.7: "A `CustomerService` agent may waive only fees whose
        `amount_cents` is at most 2500 cents; anything larger is rejected with
        `ERR_FEE_WAIVE_LIMIT_EXCEEDED`. A `ComplianceOfficer` may waive any
        amount."
        (STANDARD first NSF return -> 2500, exactly at the inclusive cap;
        HIGH_RISK second NSF return -> 4250, over the cap.)

        Design: Corner/cross_cutting_layers/fee_waive_cap_by_role
        """
        # Standard account: first NSF return -> fee 2500 (at the cap).
        ctx_s = setup_coded_return(
            reason_code="NSF", amount_cents=5000, opening_balance_cents=100000,
            risk_tier="STANDARD",
            bank_overrides={"name": "CB WC", "routing_number": "222000045"},
            item_reference="ITM-WS",
        )
        fee_s = ctx_s["fee"]
        assert fee_s["amount_cents"] == 2500

        # High-risk account: two NSF returns -> second fee 3750 + 500 = 4250.
        ctx_h = setup_coded_return(
            reason_code="NSF", amount_cents=5000, opening_balance_cents=100000,
            risk_tier="HIGH_RISK",
            bank_overrides={"name": "CB WC2", "routing_number": "222000046"},
            item_reference="ITM-WH1",
        )
        item2 = create_check_item(
            ctx_h["account"]["id"], ctx_h["bank"]["id"], item_reference="ITM-WH2",
            amount_cents=5000, capture_channel="ATM",
        )
        validate_success(api.present_check_item(item2["id"], PROCESSOR), 200)
        re2 = validate_success(api.create_return_event(item2["id"], PROCESSOR), 201)
        validate_success(
            api.code_return_event(re2["id"], {"reason_code": "NSF"}, PROCESSOR), 200
        )
        fee_h = get_fee_for_return_event(re2["id"])
        assert fee_h["amount_cents"] == 4250

        waived_s = validate_success(
            api.waive_fee(fee_s["id"], {"waive_reason": "service goodwill at cap"}, SERVICE),
            200,
        )
        assert waived_s["status"] == "WAIVED"

        over_cap = api.waive_fee(
            fee_h["id"], {"waive_reason": "service over cap"}, SERVICE
        )
        validate_error(over_cap, ApiErrorId.ERR_FEE_WAIVE_LIMIT_EXCEEDED)

        waived_h = validate_success(
            api.waive_fee(fee_h["id"], {"waive_reason": "officer override"}, OFFICER),
            200,
        )
        assert waived_h["status"] == "WAIVED"
