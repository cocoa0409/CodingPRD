"""Provisional credit grant: amounts, one-open-credit rule, tier boundaries,
dual-variant holdback, and the granted_late compliance flag."""
from test_helpers import (
    ApiErrorId,
    assert_claim_conservation,
    create_card_account_payload,
    create_card_transaction_payload,
    create_dispute_payload,
    file_dispute,
    get_account,
    grant_credit,
    make_cardholder_headers,
    make_investigator_headers,
    reclassify_payload,
    resolve_payload,
    set_clock,
    setup_account_with_dispute,
    setup_classified_case_with_credit,
    validate_error,
    validate_success,
)
from test_helpers import CLOCK, TEST_USERS


class TestProvisionalCreditGrant:
    def test_grant_second_credit_rejected(
        self, api, intake_agent_headers, finance_officer_headers
    ):
        """PRD §3.4: "A case carries at most one open credit: if a Provisional
        Credit in `GRANTED` or `REINSTATED` already exists for the case, the
        grant is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/grant_second_credit_rejected
        """
        account, _txn, case, credit = setup_classified_case_with_credit(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        resp = api.grant_provisional_credit(case["id"], intake_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_account(account["id"])
        assert after["balance_cents"] == 58000, (
            f"rejected second grant must not move the balance, "
            f"got {after['balance_cents']}"
        )

    def test_non_fraud_zero_holdback(self, api, bank_admin_headers):
        """PRD §3.2: "Until an investigator classifies the case, the fraud
        question is provisionally answered by the `error_type`: `UNAUTHORIZED`
        is treated as fraud, everything else as non-fraud (holdback zero)."
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Corner/calculations/non_fraud_zero_holdback
        """
        account, txn, case = setup_account_with_dispute(
            balance=50000, amount=8000, error_type="INCORRECT_AMOUNT",
            claim=8000, claimed_delay=40, classify=True,
            is_fraud=False, verified_delay=40,
        )
        # intake captured holdback is on the case read back after classify
        from test_helpers import get_case
        held = get_case(case["id"])["provisional_holdback_cents"]
        credit = grant_credit(case["id"])
        assert held == 0, f"non-fraud holdback must be 0, got {held}"
        assert credit["amount_cents"] == 8000, (
            f"full claim must be credited for non-fraud, got {credit['amount_cents']}"
        )

    def test_tier2_liability_cap_applied(self, api, bank_admin_headers):
        """PRD §3.2: "for a claim treated as fraud, a reported delay of at most
        two days caps the cardholder's exposure at 5,000 cents, a delay of at
        most sixty days caps it at 50,000 cents, and a delay beyond sixty days
        leaves the cardholder exposed to the full claim; the holdback is then
        the smaller of that cap and the `claim_amount_cents`."
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Corner/calculations/tier2_liability_cap_applied
        """
        account, txn, case = setup_account_with_dispute(
            balance=200000, amount=80000, txn_type="POS_SIGNATURE",
            error_type="UNAUTHORIZED", claim=80000, claimed_delay=30,
            classify=False,
        )
        intake_holdback = case["provisional_holdback_cents"]
        assert intake_holdback == 50000, (
            f"tier-2 holdback must be min(50000, 80000) = 50000, got {intake_holdback}"
        )
        from test_helpers import classify_case
        classify_case(case["id"], is_fraud=True, verified_delay=30)
        credit = grant_credit(case["id"])
        assert credit["amount_cents"] == 30000, (
            f"credit must be 80000 - 50000 = 30000, got {credit['amount_cents']}"
        )


class TestLiabilityTierBoundary:
    def _fraud_credit_for_delay(self, api, delay_days):
        """Claim 100000 on an old account; returns granted credit amount."""
        account, txn, case = setup_account_with_dispute(
            balance=300000, amount=100000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=100000, claimed_delay=delay_days,
            classify=True, is_fraud=True, verified_delay=delay_days,
        )
        return grant_credit(case["id"])["amount_cents"]

    def test_delay_exactly_two_days_stays_tier_one(self, api):
        """PRD §3.2: "for a claim treated as fraud, a reported delay of at most
        two days caps the cardholder's exposure at 5,000 cents, a delay of at
        most sixty days caps it at 50,000 cents, and a delay beyond sixty days
        leaves the cardholder exposed to the full claim; the holdback is then
        the smaller of that cap and the `claim_amount_cents`."
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Corner/cross_cutting_layers/liability_tier_boundary_day_2_vs_3
        """
        amount = self._fraud_credit_for_delay(api, 2)
        assert amount == 95000, (
            f"delay == 2 is still tier 1: credit must be 100000 - 5000, got {amount}"
        )

    def test_delay_three_days_crosses_to_tier_two(self, api):
        """PRD §3.2: "for a claim treated as fraud, a reported delay of at most
        two days caps the cardholder's exposure at 5,000 cents, a delay of at
        most sixty days caps it at 50,000 cents, and a delay beyond sixty days
        leaves the cardholder exposed to the full claim; the holdback is then
        the smaller of that cap and the `claim_amount_cents`."
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Corner/cross_cutting_layers/liability_tier_boundary_day_2_vs_3
        """
        amount = self._fraud_credit_for_delay(api, 3)
        assert amount == 50000, (
            f"delay == 3 crosses to tier 2: credit must be 100000 - 50000, "
            f"got {amount}"
        )


class TestProvisionalVsFinalLiabilityHoldback:
    def _setup_tier_shift_case(self, api):
        """Fraud dispute, claim 20000, claimed delay 1 (tier 1), credit granted;
        then reclassified to verified delay 5 (tier 2). Returns (account, case,
        credit, case_version_after_classify)."""
        account, txn, case = setup_account_with_dispute(
            balance=100000, amount=20000, txn_type="ECOMMERCE",
            error_type="UNAUTHORIZED", claim=20000, claimed_delay=1,
            classify=False,
        )
        from test_helpers import classify_case
        classified = classify_case(case["id"], is_fraud=True, verified_delay=1)
        credit = grant_credit(case["id"])
        return account, classified, credit

    def test_provisional_credit_uses_claimed_delay_tier(self, api):
        """PRD §3.3: "recomputes the `provisional_holdback_cents` under that flag
        (still from the claimed delay, since the provisional tier is what funds
        any credit)".
        PRD §3.4: "The granted `amount_cents` is the `claim_amount_cents` minus
        the `provisional_holdback_cents`, floored at zero."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_liability_holdback
        """
        account, classified, credit = self._setup_tier_shift_case(api)
        assert credit["amount_cents"] == 15000, (
            f"provisional variant: claim 20000 - tier-1 holdback min(5000, 20000) "
            f"must grant 15000, got {credit['amount_cents']}"
        )

    def test_final_credit_true_up_after_verified_tier_shift(self, api):
        """PRD §3.4: "the account `balance_cents` is adjusted by the difference
        between F and the credit's current `amount_cents`, the credit moves to
        `FINALIZED` with `final_amount_cents` set to F".
        PRD §3.4: "the system enforces claim conservation: `cardholder_keeps_cents`
        plus `final_liability_cents` always equals `claim_amount_cents`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_liability_holdback
        """
        account, classified, credit = self._setup_tier_shift_case(api)
        # Verified delay moves to 5 days -> tier 2: holdback min(50000, 20000).
        reclassified = validate_success(api.reclassify_dispute(
            classified["id"],
            reclassify_payload(
                classified["version"],
                is_fraud_claim=True, verified_report_delay_days=5,
            ),
            make_investigator_headers("ops-inv-1"),
        ))
        resolved = validate_success(api.resolve_dispute(
            classified["id"], resolve_payload(outcome="ERROR_CONFIRMED"),
            make_investigator_headers("ops-inv-1"),
        ))
        assert_claim_conservation(resolved)
        assert resolved["final_liability_cents"] == 20000, (
            f"final variant: tier-2 holdback min(50000, 20000) must be 20000, "
            f"got {resolved['final_liability_cents']}"
        )
        assert resolved["cardholder_keeps_cents"] == 0
        from test_helpers import get_success_data
        credits = get_success_data(api.list_case_provisional_credits(
            classified["id"], TEST_USERS["finance_officer_headers"],
        ))
        assert credits[0]["status"] == "FINALIZED"
        assert credits[0]["final_amount_cents"] == 0, (
            f"final credit F must be 0, got {credits[0]['final_amount_cents']}"
        )
        after = get_account(account["id"])
        assert after["balance_cents"] == 100000, (
            f"true-up must reverse the full 15000 grant, got {after['balance_cents']}"
        )
