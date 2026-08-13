"""Dealer performance scorecard, suspension levers, and termination gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_sale,
    activate_agreement,
    assert_scorecard,
    create_agreement,
    create_and_verify_certification,
    create_assignment,
    create_dealer,
    create_lead,
    create_sales_target,
    make_stock_compliant,
    register_certification,
    report_sale,
    route_lead,
    setup_active_dealer,
    setup_claim_in_state,
    setup_dealer_with_closed_quarters,
    validate_error,
    validate_success,
)


class TestScorecardVariants:
    """STRICT and INCLUSIVE read the same dealer data differently."""

    def _setup(self, api, auditor_headers):
        """Dealer with mixed evidence: 1 ACTIVE + 1 PENDING cert (a second
        verified cert lapses via expiry), passing stock audit, a Q3 target
        at 2-of-4 with one REPORTED sale, and claims in PAID /
        CHARGED_BACK / AUDIT_FLAGGED."""
        dealer = create_dealer("DL-B1", name="Dealer B1", region="East",
                               min_stock_value_cents=1000)
        dealer_id = dealer["id"]
        # CA-1 expires 2026-07-01, which predates the 2026-08-01 startup
        # clock, so the auditor can expire it after activation; CA-3 is
        # registered but never verified (PENDING_VERIFICATION).
        lapsed = create_and_verify_certification(
            dealer_id, "CA-1", earned_on="2025-01-10",
            expires_on="2026-07-01")
        create_and_verify_certification(dealer_id, "CA-2")
        agreement = create_agreement(dealer_id, "AGR-B1")
        activate_agreement(agreement["id"], dealer["version"])
        register_certification(dealer_id, "CA-3", earned_on="2026-06-01",
                               expires_on="2028-06-01")
        validate_success(api.expire_certification(lapsed["id"],
                                                  auditor_headers), 200)
        make_stock_compliant(dealer_id, 1500)

        create_sales_target(dealer_id, period_year=2026,
                            period_quarter=3, target_units=4)
        accept_sale(report_sale(dealer_id, "SC-1", "2026-08-05")["id"])
        accept_sale(report_sale(dealer_id, "SC-2", "2026-08-06")["id"])
        report_sale(dealer_id, "SC-3", "2026-08-07")

        setup_claim_in_state(dealer_id, "CL-X", "PAID",
                             parts_cost_cents=10000)
        setup_claim_in_state(dealer_id, "CL-Y", "CHARGED_BACK",
                             parts_cost_cents=4000, finding="FULL")
        setup_claim_in_state(dealer_id, "CL-Z", "AUDIT_FLAGGED",
                             parts_cost_cents=5000)
        return dealer

    def test_scorecard_strict_variant_components(self, api, auditor_headers,
                                                 oem_admin_headers):
        """PRD section 3.8: "Under `STRICT`, the counted units are the target's `achieved_units` — `ACCEPTED` sales only; under `INCLUSIVE`, the count additionally includes the dealer's `REPORTED` (not yet decided) sales in the period."
        PRD section 3.8: "The **service** component reflects warranty discipline: settled value is the sum of `claim_amount_cents` over the dealer's claims in `PAID`, `AUDIT_FLAGGED`, `CHARGED_BACK`, or `DISPUTED`; the charged-back value is, under `STRICT`, the sum of `chargeback_amount_cents` over `CHARGED_BACK` claims, and under `INCLUSIVE` that same sum **plus** the full `claim_amount_cents` of claims currently `AUDIT_FLAGGED` or `DISPUTED`."
        PRD section 3.8: "The total score is the weighted sum — forty percent sales, twenty-five percent service, twenty percent training, fifteen percent parts."

        Design: Difficulty/dual_variant_calc/dealer_scorecard_strict_vs_inclusive
        """
        dealer = self._setup(api, auditor_headers)
        resp = api.get_scorecard(
            dealer["id"], oem_admin_headers,
            params={"period_year": 2026, "period_quarter": 3,
                    "variant": "STRICT"})
        card = validate_success(resp, 200)
        assert_scorecard(card)
        assert card["variant"] == "STRICT"
        # 2 ACCEPTED of 4 -> 0.5/1.5*100 = 33.33 (rounded before weighting).
        assert card["sales_score"] == pytest.approx(33.33, abs=0.001)
        # settled = 10000 + 4000 + 5000 = 19000; STRICT charged-back = 4000.
        assert card["service_score"] == pytest.approx(78.95, abs=0.001)
        # One ACTIVE certification -> 100 * 1 / 2.
        assert card["training_score"] == pytest.approx(50.00, abs=0.001)
        assert card["parts_score"] == pytest.approx(100, abs=0.001)
        # 0.40*33.33 + 0.25*78.95 + 0.20*50.00 + 0.15*100 = 58.0695.
        assert card["total_score"] == pytest.approx(58.07, abs=0.001)

    def test_scorecard_inclusive_variant_components(self, api,
                                                    auditor_headers,
                                                    oem_admin_headers):
        """PRD section 3.8: "The **training** component is 100 times the dealer's certification units divided by two, with certification units capped at two; under `STRICT`, certification units are the count of `ACTIVE` certifications, while under `INCLUSIVE` they are the `ACTIVE` count plus half the count of certifications still `PENDING_VERIFICATION`."
        PRD section 3.8: "The scorecard response reports `period_year`, `period_quarter`, the `variant` used, the four component scores `sales_score`, `service_score`, `training_score`, and `parts_score`, and the weighted `total_score`. All five scores are rounded half-up to two decimal places, and — critically for reproducibility — each component is rounded to two decimals **before** the weighting step, with the weighted total rounded to two decimals afterwards."

        Design: Difficulty/dual_variant_calc/dealer_scorecard_strict_vs_inclusive
        """
        dealer = self._setup(api, auditor_headers)
        strict = validate_success(
            api.get_scorecard(dealer["id"], oem_admin_headers,
                              params={"period_year": 2026,
                                      "period_quarter": 3,
                                      "variant": "STRICT"}), 200)
        inclusive = validate_success(
            api.get_scorecard(dealer["id"], oem_admin_headers,
                              params={"period_year": 2026,
                                      "period_quarter": 3,
                                      "variant": "INCLUSIVE"}), 200)
        assert_scorecard(inclusive)
        assert inclusive["variant"] == "INCLUSIVE"
        # 2 ACCEPTED + 1 REPORTED = 3 of 4 -> 0.75/1.5*100.
        assert inclusive["sales_score"] == pytest.approx(50.00, abs=0.001)
        # INCLUSIVE charged-back = 4000 + 5000 (flagged amount) = 9000.
        assert inclusive["service_score"] == pytest.approx(52.63, abs=0.001)
        # 1 ACTIVE + 0.5 * 1 PENDING = 1.5 units -> 75.00.
        assert inclusive["training_score"] == pytest.approx(75.00, abs=0.001)
        assert inclusive["parts_score"] == pytest.approx(100, abs=0.001)
        # 0.40*50.00 + 0.25*52.63 + 0.20*75.00 + 0.15*100 = 63.1575.
        assert inclusive["total_score"] == pytest.approx(63.16, abs=0.001)
        assert strict["total_score"] != inclusive["total_score"]

    def test_scorecard_empty_claims_service_score_is_100(
            self, api, oem_admin_headers):
        """PRD section 3.8: "The component is 100 minus 100 times the charged-back value divided by the settled value — and 100 outright when the settled value is zero."
        PRD section 3.8: "The **sales** component measures attainment against the period's target: the counted units divided by `target_units`, capped at one and a half, then divided by one and a half and multiplied by 100. If the dealer has no target for the period, the sales component is 0."

        Design: Corner/calculations/scorecard_empty_claims_service_score_is_100
        """
        dealer = create_dealer("DL-CC5", name="Dealer CC5",
                               credit_limit_cents=100000,
                               min_stock_value_cents=1000)
        card = validate_success(
            api.get_scorecard(dealer["id"], oem_admin_headers,
                              params={"period_year": 2026,
                                      "period_quarter": 1,
                                      "variant": "STRICT"}), 200)
        assert_scorecard(card)
        assert card["service_score"] == pytest.approx(100, abs=0.001)
        assert card["sales_score"] == pytest.approx(0, abs=0.001)
        assert card["training_score"] == pytest.approx(0, abs=0.001)
        assert card["parts_score"] == pytest.approx(0, abs=0.001)
        # 0.40*0 + 0.25*100 + 0.20*0 + 0.15*0 = 25.00.
        assert card["total_score"] == pytest.approx(25.0, abs=0.001)


class TestDealerTerminationCascade:
    """Termination under the scorecard gate, with the three-link cascade."""

    def _setup_terminable_dealer(self, api, sales_ops_headers):
        # Both 2026 Q1 and Q2 close CLOSED_MISSED with zero sales; with no
        # claims the service score is 100, training is 100, and with no
        # passing stock audit parts is 0 -> STRICT total 45 < 60 in both.
        ctx = setup_dealer_with_closed_quarters(
            "DL-G1", quarters=(1, 2), target_units=10,
            min_stock_value_cents=1000)
        ctx["assignment"] = create_assignment(
            ctx["dealer"]["id"], ctx["agreement"]["id"], "T-200",
            coverage_type="EXCLUSIVE")
        lead = create_lead("T-200", product_line="LOADER",
                           estimated_value_cents=300000, contact_name="Pat")
        ctx["lead"] = route_lead(lead["id"])
        assert ctx["lead"]["status"] == "ROUTED"
        return ctx

    def test_termination_moves_dealer_and_agreement_to_terminal(
            self, api, oem_admin_headers, sales_ops_headers):
        """PRD section 3.8: "A successful termination moves the dealer to the terminal `TERMINATED` state and executes the three-link cascade of §2.9: the dealer's `ACTIVE` agreement moves to `TERMINATED`, that agreement's `ACTIVE` territory assignments move to `RELEASED`, and every lead `ROUTED` through those assignments returns to `NEW` with its routing fields cleared — all in the same operation, with `Dealer.version` incrementing."

        Design: Difficulty/transitive_cascade/dealer_termination_cascade
        """
        ctx = self._setup_terminable_dealer(api, sales_ops_headers)

        terminated = validate_success(
            api.terminate_dealer(ctx["dealer"]["id"], oem_admin_headers), 200)
        assert terminated["status"] == "TERMINATED"

        agreement = validate_success(api.get_agreement(
            ctx["agreement"]["id"], oem_admin_headers), 200)
        assert agreement["status"] == "TERMINATED", (
            "link 1: the dealer's ACTIVE agreement must move to TERMINATED"
        )

    def test_termination_releases_assignments_and_requeues_leads(
            self, api, oem_admin_headers, sales_ops_headers):
        """PRD section 2.9: "Second, **the termination cascade**: terminating a dealer moves its `ACTIVE` agreement to `TERMINATED` (link 1), moves that agreement's `ACTIVE` territory assignments to `RELEASED` (link 2), and re-queues the leads routed through those assignments (link 3)."

        Design: Difficulty/transitive_cascade/dealer_termination_cascade
        """
        ctx = self._setup_terminable_dealer(api, sales_ops_headers)

        validate_success(api.terminate_dealer(ctx["dealer"]["id"],
                                              oem_admin_headers), 200)

        assignment = validate_success(api.get_assignment(
            ctx["assignment"]["id"], oem_admin_headers), 200)
        assert assignment["status"] == "RELEASED", (
            "link 2: the agreement's ACTIVE assignment must be RELEASED"
        )

        lead = validate_success(api.get_lead(ctx["lead"]["id"],
                                             oem_admin_headers), 200)
        assert lead["status"] == "NEW", (
            "link 3: the ROUTED lead must return to NEW"
        )
        assert lead["routed_dealer_id"] is None
        assert lead["routed_assignment_id"] is None
        assert lead["routed_at"] is None

    def test_terminate_without_low_scorecard_quarters_rejected(
            self, api, oem_admin_headers):
        """PRD section 3.8: "An `OemNetworkAdmin` may terminate a dealer in `ACTIVE` or `SUSPENDED` status, but only when the dealer's **STRICT** `total_score` is below 60 for **each of the two most recent closed quarters**, ordered by `period_year` and `period_quarter`. If the dealer has fewer than two closed quarters, or if either of the two scores is 60 or higher, the termination is rejected with `ERR_SCORECARD_THRESHOLD_NOT_MET`."

        Design: Corner/validations/terminate_without_low_scorecard_quarters_rejected
        """
        ctx = setup_active_dealer("DL-TM1", name="Dealer TM1")
        # No sales targets at all: fewer than two closed quarters.
        resp = api.terminate_dealer(ctx["dealer"]["id"], oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCORECARD_THRESHOLD_NOT_MET)

        unchanged = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                    oem_admin_headers), 200)
        assert unchanged["status"] == "ACTIVE"


class TestSuspensionLevers:

    def test_reinstate_active_dealer_rejected(self, api, oem_admin_headers):
        """PRD section 3.8: "Reinstatement requires the dealer to currently be `SUSPENDED` (`ERR_DEALER_NOT_SUSPENDED`) and requires the `chargeback_balance_cents` to be back below 50000 cents — a balance at or above that level blocks reinstatement with `ERR_REINSTATE_BLOCKED`."

        Design: Corner/validations/reinstate_active_dealer_rejected
        """
        ctx = setup_active_dealer("DL-RS1", name="Dealer RS1")

        resp = api.set_dealer_status(ctx["dealer"]["id"],
                                     {"target": "ACTIVE"}, oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_SUSPENDED)

        unchanged = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                    oem_admin_headers), 200)
        assert unchanged["status"] == "ACTIVE"

    def test_reinstate_with_high_chargeback_balance_blocked(
            self, api, auditor_headers, oem_admin_headers):
        """PRD section 3.8: "Reinstatement requires the dealer to currently be `SUSPENDED` (`ERR_DEALER_NOT_SUSPENDED`) and requires the `chargeback_balance_cents` to be back below 50000 cents — a balance at or above that level blocks reinstatement with `ERR_REINSTATE_BLOCKED`."

        Design: Corner/validations/reinstate_with_high_chargeback_balance_blocked
        """
        ctx = setup_active_dealer("DL-RB1", name="Dealer RB1")
        dealer_id = ctx["dealer"]["id"]
        claim = setup_claim_in_state(dealer_id, "RB-1", "AUDIT_FLAGGED",
                                     parts_cost_cents=55000)
        validate_success(
            api.chargeback_claim(claim["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        suspended = validate_success(api.get_dealer(dealer_id,
                                                    oem_admin_headers), 200)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["chargeback_balance_cents"] == 55000

        resp = api.set_dealer_status(dealer_id, {"target": "ACTIVE"},
                                     oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_BLOCKED)

        unchanged = validate_success(api.get_dealer(dealer_id,
                                                    oem_admin_headers), 200)
        assert unchanged["status"] == "SUSPENDED"
