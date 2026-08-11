"""Difficulty queue: combinatorial formulas (product cap, rounding order, frozen severity)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    approve_account,
    create_account,
    create_customer,
    create_rep,
    create_rule,
    escalate_alert,
    get_account,
    list_alerts_for_account,
    post_security_txn,
    post_wire,
    run_scan,
    set_clock,
    submit_and_verify_document,
    validate_success,
)


class TestRiskScoreProductCapAndTierBoundaries:
    def _setup_customers(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep C", crd_number="CRD-CF1")
        customers = [
            create_customer(
                rep,
                customer_type="INDIVIDUAL",
                full_name=name,
                tax_id=tax_id,
                country_risk_tier="LOW",
                is_pep=False,
            )
            for name, tax_id in (
                ("C One", "TIN-CF1a"),
                ("C Two", "TIN-CF1b"),
                ("C Three", "TIN-CF1c"),
            )
        ]
        return rep, customers

    def test_product_points_capped_at_25(self, api):
        """PRD §3.3: "Products add 15 points when `LOW_PRICED_SECURITIES` is present in
        `product_set`, 5 each for the `MARGIN` and `OPTIONS` products, and 10 for
        `CORRESPONDENT`, with the product contribution capped at 25 points in total."
        [LPS, MARGIN, OPTIONS, CORRESPONDENT] raw-sums to 35 but caps at 25;
        [LPS, CORRESPONDENT] hits exactly 25 uncapped.

        Design: Difficulty/combinatorial_formula/risk_score_product_cap_and_tier_boundaries
        """
        rep, customers = self._setup_customers()
        capped = create_account(
            customers[0]["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "MARGIN", "OPTIONS", "CORRESPONDENT"],
        )
        exact = create_account(
            customers[1]["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "CORRESPONDENT"],
        )
        assert capped["risk_score"] == 25, (
            f"raw product sum 35 must clamp to cap 25, got {capped['risk_score']}"
        )
        assert exact["risk_score"] == 25, (
            f"product sum exactly 25 must not be clamped, got {exact['risk_score']}"
        )

    def test_product_points_below_cap_and_low_tiers(self, api):
        """PRD §3.3: "5 each for the `MARGIN` and `OPTIONS` products" — [MARGIN,
        OPTIONS] yields 10.
        PRD §3.3: "a score of at least 70 yields `HIGH`, at least 40 (but below 70)
        yields `MEDIUM`, and anything lower yields `LOW`" — all three accounts score
        below 40 and are LOW tier.

        Design: Difficulty/combinatorial_formula/risk_score_product_cap_and_tier_boundaries
        """
        rep, customers = self._setup_customers()
        pair = create_account(
            customers[2]["id"], rep, product_set=["MARGIN", "OPTIONS"]
        )
        capped = create_account(
            customers[0]["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "MARGIN", "OPTIONS", "CORRESPONDENT"],
        )
        exact = create_account(
            customers[1]["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "CORRESPONDENT"],
        )
        assert pair["risk_score"] == 10, (
            f"MARGIN + OPTIONS must be 5 + 5 = 10, got {pair['risk_score']}"
        )
        for label, account in (("capped", capped), ("exact", exact), ("pair", pair)):
            assert account["risk_tier"] == "LOW", (
                f"{label} account score {account['risk_score']} must map to LOW tier"
            )


class TestLiquidationProceedsPerLineRoundingOrder:
    def _setup_account(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep D", crd_number="CRD-CF2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="D Low",
            tax_id="TIN-CF2",
            country_risk_tier="LOW",
            is_pep=False,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-CF2")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        return rep, account

    def test_per_line_rounding_on_posted_amount(self, api):
        """PRD §2.7: "Derived security-transaction amounts are computed per line:
        quantity multiplied by unit price, rounded half up to two decimal places,
        before any summation."
        PRD §3.5: "A transaction's `is_low_priced` flag is true exactly when the
        transaction is a security type and its `unit_price` is below 5.00".
        1 @ 2.345 rounds half up to 2.35; 2.345 < 5.00 is low-priced.

        Design: Difficulty/combinatorial_formula/liquidation_proceeds_per_line_rounding_order
        """
        rep, account = self._setup_account()
        txn = post_security_txn(account["id"], rep, "SELL", "PNYR", 1, 2.345)
        assert txn["amount"] == pytest.approx(2.35, abs=0.001), (
            f"round_half_up(2.345, 2) per line must be 2.35, got {txn['amount']}"
        )
        assert txn["is_low_priced"] is True

    def test_per_line_then_sum_fires_alert_at_4_70(self, api):
        """PRD §3.5: "each matching line's proceeds are computed as quantity times unit
        price rounded half up to two decimal places, and the alert's `aggregate_amount`
        is the exact sum of those rounded line amounts — the round-per-line-then-sum
        order is pinned, since the alternative (summing raw products and rounding once)
        can differ by cents."
        PRD §3.5: "A rule fires when its aggregate over matching transactions reaches
        or exceeds its `threshold_amount`".
        Two lines of 1 @ 2.345 give 2.35 + 2.35 = 4.70 >= threshold 4.70; the
        sum-then-round order would give 4.69 and would NOT fire.

        Design: Difficulty/combinatorial_formula/liquidation_proceeds_per_line_rounding_order
        """
        rep, account = self._setup_account()
        create_rule(rule_code="LPS_LIQUIDATION", threshold_amount=4.70, window_days=5,
                    min_transaction_count=1)
        post_security_txn(account["id"], rep, "SELL", "PNYR", 1, 2.345)
        post_security_txn(account["id"], rep, "SELL", "PNYR", 1, 2.345)
        scan = run_scan()
        assert scan["alerts_created"] == 1, (
            f"per-line sum 4.70 >= 4.70 must fire exactly one alert, got {scan['alerts_created']}"
        )
        alert = list_alerts_for_account(account["id"])[0]
        assert alert["aggregate_amount"] == pytest.approx(4.70, abs=0.001)


class TestAlertSeverityFrozenBeforeEscalationRecalc:
    def _setup_alert_under_review(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep E", crd_number="CRD-CF3")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="E Pep",
            tax_id="TIN-CF3",
            country_risk_tier="HIGH",
            is_pep=True,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-CF3")
        account = create_account(
            customer["id"], rep, product_set=["LOW_PRICED_SECURITIES", "MARGIN"]
        )
        approve_account(account["id"])
        create_rule(rule_code="WIRE_VELOCITY", threshold_amount=60000.00, window_days=30,
                    min_transaction_count=1)
        post_wire(account["id"], rep, 60000.00)
        post_wire(account["id"], rep, 12000.00)
        run_scan()
        alert = list_alerts_for_account(account["id"])[0]
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)
        return rep, account, alert

    def test_severity_frozen_at_creation_medium_multiplier(self, api):
        """PRD §3.5: "it is one hundred times the lesser of the aggregate-to-threshold
        ratio and 2.0, multiplied by a risk multiplier of 1.0 plus one quarter when the
        account's `risk_tier` is `HIGH` and plus one tenth when it is `MEDIUM`, and the
        result rounded half up to a whole number."
        PRD §3.5: "A rule fires when its aggregate over matching transactions reaches
        or exceeds its `threshold_amount`".
        Initial score 65 (25 country + 20 PEP + 15 LPS + 5 MARGIN) -> MEDIUM; aggregate
        72000 / threshold 60000 -> base 120; 120 * 1.10 = 132.0 -> severity 132.

        Design: Difficulty/combinatorial_formula/alert_severity_frozen_before_escalation_recalc
        """
        _rep, account, alert = self._setup_alert_under_review()
        assert account["risk_score"] == 65, (
            f"INITIAL score must be 65, got {account['risk_score']}"
        )
        assert alert["severity"] == 132, (
            f"severity must be round_half_up(120 * 1.10) = 132, got {alert['severity']}"
        )

    def test_case_priority_uses_frozen_severity_before_recalc(self, api):
        """PRD §3.5: "the case's `priority` is assigned from the alert's severity
        exactly as frozen at alert creation — at least 150 yields `CRITICAL`, at least
        100 yields `HIGH`, at least 50 yields `MEDIUM`, anything lower yields `LOW` —
        before any recalculation runs; third, the account's risk is recalculated with
        the `ONGOING` variant".
        Severity 132 -> priority HIGH; the wrong order (post-recalc HIGH-tier
        multiplier 1.25) would recompute severity to 120 * 1.25 = 150 -> CRITICAL.
        Only AFTER priority assignment does the ONGOING recalc raise the score to 75
        (65 + 5 alert + 5 velocity band at ratio 0.72) and the tier to HIGH.

        Design: Difficulty/combinatorial_formula/alert_severity_frozen_before_escalation_recalc
        """
        _rep, account, alert = self._setup_alert_under_review()
        escalation = escalate_alert(alert["id"])
        assert escalation["case_priority"] == "HIGH", (
            f"priority must come from frozen severity 132 -> HIGH, "
            f"got {escalation['case_priority']}"
        )

        after = get_account(account["id"])
        assert after["risk_score"] == 75, (
            f"post-escalation ONGOING recalc must give 65 + 5 + 5 = 75, "
            f"got {after['risk_score']}"
        )
        assert after["risk_tier"] == "HIGH", "score 75 >= 70 must lift the tier to HIGH"
        assert after["risk_variant_used"] == "ONGOING"
