"""Multi-input money and fitting formulas.

Two calculations in this API combine several independently weighted inputs in a
declared order, so that any reordering of the steps or any dropped term lands on
a different answer: the eight-step reimbursement chain of §3.9 and the
four-term parameter deviation index of §3.6.
"""

from test_helpers import (
    CO_ALPHA,
    CO_BRAVO,
    apply_substitution_payload,
    assert_generated_claim_money_chain,
    assert_ledger_values,
    assert_order_money,
    assert_reimbursement_claim,
    new_reimbursement_claim,
    settle_return_request,
    setup_approved_return,
    setup_delivered_order_with_draft_claim,
    setup_substitution_candidates,
    validate_success,
)

# ==========================================================================
# Scenario builders
# ==========================================================================


def _delivered_six_box_order_with_draft_claim() -> dict:
    """A six-box, 19200-cent order delivered under an out-of-network plan whose
    annual allowance is 15000 cents at a 0.20 coinsurance rate, carrying one
    DRAFT reimbursement claim and no returns."""
    return setup_delivered_order_with_draft_claim(boxes_od=3, boxes_os=3)


def _delivered_order_with_settled_refund_then_draft_claim() -> dict:
    """The same six-box delivered order, but three opened boxes with seven
    lenses used each come back as a PRESCRIPTION_CHANGE return that one officer
    approves and a second officer settles for cash. The DRAFT claim is opened
    only after the refund has settled."""
    scenario = setup_approved_return(
        reason="PRESCRIPTION_CHANGE",
        return_overrides={"unopened_boxes": 0, "opened_box_used_counts": [7, 7, 7]},
        approver=CO_ALPHA,
        with_plan=True,
        boxes_od=3,
        boxes_os=3,
    )
    scenario["return_request"] = settle_return_request(
        scenario["return_request"]["id"], actor=CO_BRAVO
    )
    scenario["claim"] = new_reimbursement_claim(
        scenario["order"]["id"], scenario["customer"]["id"], scenario["plan"]["id"]
    )
    return scenario


def _order_with_wider_clinical_equivalent() -> dict:
    """A two-box order for the 8.60 / 14.20 SKU, alongside a CLINICAL equivalent
    stocked at 8.75 / 14.30 that shares the prescribed sphere powers."""
    return setup_substitution_candidates(
        [
            {
                "brand": "ClearSpan",
                "name": "Daily 30 Wide",
                "base_curve": 8.75,
                "diameter": 14.30,
            }
        ],
        boxes_od=1,
        boxes_os=1,
        equivalence_overrides={
            "equivalence_class": "CLINICAL",
            "requires_patient_consent": False,
        },
    )


# ==========================================================================
# The eight-step reimbursement chain
# ==========================================================================


class TestClaimEightStepMoneyChain:
    """The reimbursement figure is built in a declared order, and the
    processing-fee tier reads the seventh step rather than the order subtotal."""

    def test_generate_prices_eight_steps_in_the_declared_order(
        self, api, compliance_headers
    ):
        """PRD §3.9: "The money is then computed in a **fixed eight-step order**,
        and the order is load-bearing because the processing-fee tier is keyed on
        the seventh step's result rather than on the order subtotal or on the
        final figure."

        PRD §3.9: "1. Gross spend is the order's `subtotal_cents`, plus the
        order's `shipping_cents` when the plan's `covers_shipping` is true and
        plus nothing when it is false."

        PRD §3.9: "3. `base_eligible_cents` is gross spend less
        `refund_offset_cents`, floored at zero."

        PRD §3.9: "5. `applied_allowance_cents` is whichever is smaller,
        `base_eligible_cents` or that remaining allowance."

        PRD §3.9: "6. `coinsurance_cents` is `base_eligible_cents` less
        `applied_allowance_cents`, multiplied by the plan's `coinsurance_rate`,
        rounded half up to a whole cent."

        PRD §3.9: "7. `pre_fee_subtotal_cents` is `applied_allowance_cents` plus
        `coinsurance_cents`."

        PRD §3.9: "8. `processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        PRD §3.9: "`reimbursable_cents`, the final figure the plan will
        reimburse, is `pre_fee_subtotal_cents` less `processing_fee_cents`,
        floored at zero."

        PRD §3.9: "A claim's `status` runs `DRAFT`, `GENERATED`, `SUBMITTED` and
        the terminal `VOIDED`; claims may be listed filtered by `order_id`,
        `customer_id`, `insurance_plan_id` and `status`."

        Design: Difficulty/combinatorial_formula/claim_eight_step_order_with_allowance_cap_and_top_fee_tier
        """
        scenario = _delivered_six_box_order_with_draft_claim()

        response = api.generate_reimbursement_claim(
            scenario["claim"]["id"], compliance_headers
        )
        claim = validate_success(response)

        assert_reimbursement_claim(claim)
        assert_generated_claim_money_chain(claim)
        assert claim["status"] == "GENERATED"
        assert claim["base_eligible_cents"] == 19200
        assert claim["applied_allowance_cents"] == 15000
        assert claim["coinsurance_cents"] == 840
        assert claim["pre_fee_subtotal_cents"] == 15840
        assert claim["processing_fee_cents"] == 500
        assert claim["reimbursable_cents"] == 15340

    def test_generate_consumes_the_plan_year_allowance_in_full(
        self, api, compliance_headers
    ):
        """PRD §3.9: "2. `refund_offset_cents` is the sum of `settlement_cents`
        over the return requests on this order whose `status` is `SETTLED`."

        PRD §3.9: "Generation also mints a `packet_reference`, the paperwork
        identifier, and increases the customer's `allowance_used_cents` by
        `applied_allowance_cents` — reconciled, as §2.7 requires, from the live
        claim rows rather than incremented blindly."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/combinatorial_formula/claim_eight_step_order_with_allowance_cap_and_top_fee_tier
        """
        scenario = _delivered_six_box_order_with_draft_claim()

        response = api.generate_reimbursement_claim(
            scenario["claim"]["id"], compliance_headers
        )
        claim = validate_success(response)

        assert claim["refund_offset_cents"] == 0

        ledger = validate_success(
            api.get_customer_ledger(scenario["customer"]["id"], compliance_headers)
        )
        assert_ledger_values(
            ledger,
            allowance_used_cents=15000,
            allowance_remaining_cents=0,
        )


class TestClaimAfterSettledRefundOffset:
    """A settled cash refund is subtracted from gross spend before the allowance
    is applied, which moves the claim into the middle fee tier."""

    def test_generate_subtracts_the_settled_refund_before_the_allowance(
        self, api, compliance_headers
    ):
        """PRD §3.8: "Under `PER_BOX_ROUNDED`, each opened box is valued
        independently as the per-box value multiplied by the unused lenses in
        that box divided by the lenses per box, **rounded half up to a whole cent
        for that box**, and those per-box amounts are then added together."

        PRD §3.9: "2. `refund_offset_cents` is the sum of `settlement_cents` over
        the return requests on this order whose `status` is `SETTLED`."

        PRD §3.9: "3. `base_eligible_cents` is gross spend less
        `refund_offset_cents`, floored at zero."

        PRD §3.9: "5. `applied_allowance_cents` is whichever is smaller,
        `base_eligible_cents` or that remaining allowance."

        PRD §3.9: "6. `coinsurance_cents` is `base_eligible_cents` less
        `applied_allowance_cents`, multiplied by the plan's `coinsurance_rate`,
        rounded half up to a whole cent."

        PRD §3.9: "8. `processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        Design: Difficulty/combinatorial_formula/claim_recomputed_after_settled_refund_offset
        """
        scenario = _delivered_order_with_settled_refund_then_draft_claim()

        response = api.generate_reimbursement_claim(
            scenario["claim"]["id"], compliance_headers
        )
        claim = validate_success(response)

        assert_reimbursement_claim(claim)
        assert_generated_claim_money_chain(claim)
        assert claim["refund_offset_cents"] == 7359
        assert claim["base_eligible_cents"] == 11841
        assert claim["applied_allowance_cents"] == 11841
        assert claim["coinsurance_cents"] == 0
        assert claim["pre_fee_subtotal_cents"] == 11841
        assert claim["processing_fee_cents"] == 250
        assert claim["reimbursable_cents"] == 11591

    def test_ledger_reconciles_refund_charge_and_allowance_together(
        self, api, compliance_headers
    ):
        """PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`lifetime_refunded_cents` is the sum of `settlement_cents`
        over that customer's return requests whose `status` is `SETTLED` and
        whose `settlement_channel` is `CASH_REFUND`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        PRD §2.7: "`allowance_used_cents` is then the sum of
        `applied_allowance_cents` over that customer's reimbursement claims whose
        `created_at` falls inside the window and whose `status` is `GENERATED` or
        `SUBMITTED`."

        Design: Difficulty/combinatorial_formula/claim_recomputed_after_settled_refund_offset
        """
        scenario = _delivered_order_with_settled_refund_then_draft_claim()

        validate_success(
            api.generate_reimbursement_claim(
                scenario["claim"]["id"], compliance_headers
            )
        )

        ledger = validate_success(
            api.get_customer_ledger(scenario["customer"]["id"], compliance_headers)
        )
        assert_ledger_values(
            ledger,
            lifetime_charged_cents=19200,
            lifetime_refunded_cents=7359,
            net_cash_position_cents=11841,
            allowance_used_cents=11841,
        )


# ==========================================================================
# The four-term parameter deviation index
# ==========================================================================


class TestParameterDeviationIndexWeightedSum:
    """Base curve, diameter and each eye's sphere carry their own weight, and the
    four terms are summed rather than averaged."""

    def test_weighted_sum_of_four_terms_lands_in_the_consent_band(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "3. Sum four weighted absolute differences, each taken
        between the two values expressed in integer hundredths: the difference
        between the prescription's `base_curve` and the substitute product's
        `base_curve`, weighted by four; the difference between the prescription's
        `diameter` and the substitute product's `diameter`, weighted by two; the
        difference between the prescription's `od_sphere` and the dispensed
        `fulfilled_od_sphere`, weighted by one; and the difference between the
        prescription's `os_sphere` and the dispensed `fulfilled_os_sphere`, also
        weighted by one."

        PRD §3.6: "Base curve therefore matters twice as much as diameter and
        four times as much as either sphere."

        PRD §3.6: "4. Divide that weighted sum by one hundred to obtain
        `parameter_deviation_index`, presented with two decimal places."

        PRD §3.6: "An index **above 0.50 and at most 1.00** sits in the consent
        band: the swap proceeds only when the payload carries `patient_consent`
        set to true, and otherwise is refused with `ERR_CONSENT_REQUIRED` at HTTP
        422."

        PRD §3.6: "Once one is applied, it becomes `PARAMETER_ROUNDED` when the
        substitute product's `sphere_step` forced `fulfilled_od_sphere` or
        `fulfilled_os_sphere` away from the prescribed power, and
        `BRAND_EQUIVALENT` otherwise — that is, when both eyes are dispensed at
        exactly the prescribed powers and only the brand or material changed."

        Design: Difficulty/combinatorial_formula/parameter_deviation_index_four_weighted_terms
        """
        scenario = _order_with_wider_clinical_equivalent()
        substitute = scenario["substitutes"][0]

        response = api.apply_substitution(
            scenario["order"]["id"],
            apply_substitution_payload(
                substitute["id"],
                scenario["order"]["version"],
                patient_consent=True,
            ),
            fulfillment_headers,
        )
        order = validate_success(response)

        # 4 * 15 + 2 * 10 + 1 * 0 + 1 * 0 = 80 integer hundredths.
        assert float(order["parameter_deviation_index"]) == 0.80
        assert order["substitution_type"] == "BRAND_EQUIVALENT"
        assert order["fulfilled_product_id"] == substitute["id"]

    def test_substitution_stays_price_neutral_and_advances_the_version(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "Substitution is deliberately **price-neutral**: it sets
        `fulfilled_product_id`, `substitution_type`, `parameter_deviation_index`,
        `fulfilled_od_sphere` and `fulfilled_os_sphere`, appends a
        `SUBSTITUTION_APPLIED` compliance event, and increments the order's
        `version`, while leaving `unit_price_cents`, `subtotal_cents`,
        `shipping_cents` and `total_cents` exactly as they were."

        PRD §2.9: "A successful substitution increments the order's `version`, so
        the next substitution attempt must present the new value."

        Design: Difficulty/combinatorial_formula/parameter_deviation_index_four_weighted_terms
        """
        scenario = _order_with_wider_clinical_equivalent()
        substitute = scenario["substitutes"][0]
        version_before = scenario["order"]["version"]

        response = api.apply_substitution(
            scenario["order"]["id"],
            apply_substitution_payload(
                substitute["id"],
                version_before,
                patient_consent=True,
            ),
            fulfillment_headers,
        )
        order = validate_success(response)

        assert order["total_cents"] == 6400
        assert order["subtotal_cents"] == 6400
        assert order["shipping_cents"] == 0
        assert order["unit_price_cents"] == 3200
        assert_order_money(order)
        assert order["version"] > version_before
