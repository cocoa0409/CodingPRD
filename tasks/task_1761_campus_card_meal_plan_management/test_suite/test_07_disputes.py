"""Transaction disputes: filing rules, provisional credit, resolution outcomes,
and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_publish_plan,
    create_holder,
    create_term,
    file_dispute,
    get_success_data,
    grant_provisional_credit,
    make_cardholder_headers,
    make_fraud_analyst_headers,
    open_term,
    post_pos_transaction,
    resolve_dispute,
    set_clock,
    setup_disputed_purchase,
    setup_enrolled_holder_with_card,
    validate_error,
    validate_paginated,
    validate_success,
)

BURSAR = TEST_USERS["bursar_headers"]
DINING = TEST_USERS["dining_manager_headers"]


class TestDisputeFiling:
    def test_second_open_dispute_rejected(self, api):
        """PRD §3.6: "only while no non-terminal dispute already exists on the
        transaction (`ERR_DISPUTE_ALREADY_OPEN`)"

        Design: Corner/validations/second_open_dispute_rejected
        """
        (holder, card, account, tx, dispute) = setup_disputed_purchase(
            amount_cents=700, fund_cents=3000)
        resp = api.create_dispute(tx["id"], {"reason_code": "DUPLICATE_CHARGE"},
                                  make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)

    def test_dispute_after_thirty_day_window_rejected(self, api):
        """PRD §3.6: "Filing is allowed only within 30 days of the transaction's
        `created_at` (later filings are rejected with `ERR_DISPUTE_WINDOW_CLOSED`)"

        Design: Corner/validations/dispute_after_thirty_day_window_rejected
        """
        from test_helpers import setup_funded_campus_cash
        set_clock("2026-08-25T09:00:00Z")
        holder, card, account = setup_funded_campus_cash(
            amount_cents=3000, university_id="U92015", full_name="Yev Late",
            email="yev@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")
        tx = post_pos_transaction(card["id"], "CAMPUS_CASH", 700, key="yev-t")

        # Exactly 30 days later: admitted.
        set_clock("2026-09-24T09:00:00Z")
        ok = api.create_dispute(tx["id"], {"reason_code": "AMOUNT_MISMATCH"},
                                make_cardholder_headers(holder["id"]))
        dispute = validate_success(ok, 201)
        get_success_data(api.withdraw_dispute(
            dispute["id"], make_cardholder_headers(holder["id"])))

        # Past the window: rejected.
        set_clock("2026-09-25T09:00:01Z")
        late = api.create_dispute(tx["id"], {"reason_code": "AMOUNT_MISMATCH"},
                                  make_cardholder_headers(holder["id"]))
        validate_error(late, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)


class TestProvisionalCredit:
    def test_provisional_credit_not_applicable_to_swipe_dispute(self, api):
        """PRD §3.6: "A `FraudAnalyst` may grant **provisional credit** on an
        `OPENED` dispute — but only when the disputed transaction's tender is not
        `MEAL_SWIPE`; a swipe dispute is ineligible and is rejected with
        `ERR_CREDIT_NOT_APPLICABLE`."

        Design: Corner/validations/provisional_credit_not_applicable_to_swipe_dispute
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, plan, enrollment, card = setup_enrolled_holder_with_card(
            {"term_code": "T-PCS"},
            {"plan_code": "P-PCS",
             "eligible_holder_types": ["STUDENT_RESIDENT"]},
            {"university_id": "U92016", "full_name": "Zed Swipe",
             "email": "zed@x.edu", "holder_type": "STUDENT_RESIDENT",
             "housing_status": "ON_CAMPUS"})
        tx = post_pos_transaction(card["id"], "MEAL_SWIPE", 0, key="zed-sw")
        dispute = file_dispute(tx["id"], holder["id"], "UNAUTHORIZED_USE")

        resp = api.grant_provisional_credit(dispute["id"],
                                            make_fraud_analyst_headers("fraud-1"))
        validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_APPLICABLE)
        still = get_success_data(
            api.get_dispute(dispute["id"], make_fraud_analyst_headers("fraud-1")))
        assert still["status"] == "OPENED"


class TestDisputeResolution:
    def test_resolved_dispute_is_terminal(self, api):
        """PRD §2.10: "**State transition legality** — the target resource's state
        permits the requested transition, including terminal-state lockout,
        invalid-from rejection, and any state-machine precondition, else
        `ERR_INVALID_STATE_TRANSITION` (409)."
        PRD §3.6: resolution moves a dispute to `RESOLVED_FOR_CARDHOLDER` or
        `RESOLVED_FOR_MERCHANT`, and the dispute workflow defines no transitions
        out of those states.

        Design: Corner/state_machines/resolved_dispute_is_terminal
        """
        (holder, card, account, tx, dispute) = setup_disputed_purchase(
            amount_cents=700, fund_cents=3000)
        resolve_dispute(dispute["id"], "FOR_CARDHOLDER", "ok", analyst="fraud-1")

        again = api.resolve_dispute(
            dispute["id"], {"outcome": "FOR_MERCHANT", "resolution_note": "retry"},
            make_fraud_analyst_headers("fraud-2"))
        validate_error(again, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        withdraw = api.withdraw_dispute(dispute["id"],
                                        make_cardholder_headers(holder["id"]))
        validate_error(withdraw, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = get_success_data(
            api.get_dispute(dispute["id"], make_fraud_analyst_headers("fraud-1")))
        assert still["status"] == "RESOLVED_FOR_CARDHOLDER"

    def test_dispute_resolver_must_differ_from_granter(self, api):
        """PRD §3.6: "One segregation-of-duties rule applies: when provisional
        credit was granted, the resolving analyst must differ from the
        `granter_analyst_id` (`ERR_SOD_RESOLVER_IS_GRANTER`)."
        PRD §3.6: "if provisional credit was already posted, that credit simply
        becomes permanent and no reversal entry is written"

        Design: Corner/rbac/dispute_resolver_must_differ_from_granter
        """
        (holder, card, account, tx, dispute) = setup_disputed_purchase(
            amount_cents=1200, fund_cents=5000, reason_code="UNAUTHORIZED_USE")
        grant_provisional_credit(dispute["id"], analyst="fraud-1")

        self_resolve = api.resolve_dispute(
            dispute["id"],
            {"outcome": "FOR_CARDHOLDER", "resolution_note": "self-resolve attempt"},
            make_fraud_analyst_headers("fraud-1"))
        validate_error(self_resolve, ApiErrorId.ERR_SOD_RESOLVER_IS_GRANTER)

        resolved = resolve_dispute(dispute["id"], "FOR_CARDHOLDER",
                                   "second analyst confirms", analyst="fraud-2")
        assert resolved["status"] == "RESOLVED_FOR_CARDHOLDER"
        assert resolved["resolver_analyst_id"] == "fraud-2"

        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 5000
        entries, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": account["id"]}))
        entry_types = [e["entry_type"] for e in entries]
        assert "PROVISIONAL_CLAWBACK" not in entry_types
        assert "PURCHASE_REVERSAL" not in entry_types


class TestReversalBalanceInvariant:
    def test_purchase_reversal_restores_balance(self, api):
        """PRD §2.7: "a purchase of a given amount paired with its
        `PURCHASE_REVERSAL` of the same amount (posted directly, or made permanent
        through a provisional credit) leaves the balance identical to what it was
        before the purchase."
        PRD §3.6: "the transaction becomes `REVERSED`. If the dispute never
        received provisional credit, a `PURCHASE_REVERSAL` entry is posted to the
        account and the balance recomputed"

        Design: Difficulty/compensating_invariant/purchase_reversal_balance_conservation
        """
        (holder, card, account, tx, dispute) = setup_disputed_purchase(
            amount_cents=1200, fund_cents=5000, reason_code="DUPLICATE_CHARGE")
        resolve_dispute(dispute["id"], "FOR_CARDHOLDER", "duplicate confirmed",
                        analyst="fraud-1")

        tx_now = get_success_data(
            api.get_transaction(tx["id"], make_fraud_analyst_headers("fraud-1")))
        assert tx_now["status"] == "REVERSED"
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 5000

    def test_purchase_reversal_ledger_replay(self, api):
        """PRD §2.7: "Replaying the account's entries in ascending `created_at`
        order, with ties in `created_at` broken by ascending `entry_sequence`, the
        balance equals the sum of credit amounts minus the sum of debit amounts;
        each entry's `running_balance_cents` stores the balance immediately after
        that entry in that replay order."

        Design: Difficulty/compensating_invariant/purchase_reversal_balance_conservation
        """
        (holder, card, account, tx, dispute) = setup_disputed_purchase(
            amount_cents=1200, fund_cents=5000, reason_code="DUPLICATE_CHARGE")
        resolve_dispute(dispute["id"], "FOR_CARDHOLDER", "duplicate confirmed",
                        analyst="fraud-1")

        entries, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": account["id"]}))
        assert [e["entry_type"] for e in entries] == [
            "FUND", "PURCHASE", "PURCHASE_REVERSAL"]
        assert [e["amount_cents"] for e in entries] == [5000, 1200, 1200]
        assert [e["running_balance_cents"] for e in entries] == [5000, 3800, 5000]
