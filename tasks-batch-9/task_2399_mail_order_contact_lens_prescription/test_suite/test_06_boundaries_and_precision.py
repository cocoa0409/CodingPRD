"""Boundary and precision behaviour on the four inclusive thresholds.

Each threshold in this file is decided by an inclusive comparison, so the value
sitting exactly on the boundary belongs to the lower band: the deviation index
of 0.50 auto-approves, a 5,000-cent subtotal ships free, a 5,000-cent pre-fee
subtotal pays no processing fee, and a response made at the passive deadline
instant is already too late.
"""

from test_helpers import (
    ApiErrorId,
    deliver_order,
    generate_reimbursement_claim,
    get_ledger,
    new_order,
    new_product,
    new_reimbursement_claim,
    read_order,
    set_clock,
    setup_delivered_order,
    setup_substitution_candidates,
    setup_verification_round,
    setup_verified_prescription,
    ship_order,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Product and prescription shapes that pin each boundary
# --------------------------------------------------------------------------

# The prescription and its ordered SKU both sit at base curve 8.60 / diameter
# 14.20, so every unit of deviation below comes from the substitute alone.
CEILING_SUBSTITUTE = {
    "brand": "NearFit",
    "name": "Daily 30 Near",
    "base_curve": 8.70,
    "diameter": 14.25,
}
"""4 * 10 hundredths of base curve plus 2 * 5 hundredths of diameter, with both
spheres landing exactly on the prescribed power: an index of exactly 0.50."""

ABOVE_CEILING_SUBSTITUTE = {
    "brand": "ClearSpan",
    "name": "Daily 30 Wide",
    "base_curve": 8.75,
    "diameter": 14.30,
}
"""4 * 15 hundredths plus 2 * 10 hundredths: an index of 0.80, in the consent
band rather than the auto-approve band."""

VALUE_PRODUCT = {
    "brand": "ValueVue",
    "name": "Monthly 6",
    "wear_schedule": "MONTHLY",
    "lenses_per_box": 6,
    "unit_price_cents": 2500,
    "material_family": "hydrogel",
}
"""Two boxes subtotal exactly 5,000 cents; one box subtotals 2,500 cents."""

PREMIUM_VALUE_PRODUCT = {
    "brand": "ValueVue",
    "name": "Monthly 6 Plus",
    "wear_schedule": "MONTHLY",
    "lenses_per_box": 6,
    "unit_price_cents": 5001,
    "material_family": "hydrogel",
}
"""One box subtotals 5,001 cents, one cent above the first fee tier ceiling."""

MONDAY_9AM = "2026-09-07T09:00:00Z"
MONDAY_BUSINESS_DAY_END = "2026-09-07T17:00:00Z"
EXPECTED_DEADLINE = "2026-09-07T17:00:00.000Z"


# --------------------------------------------------------------------------
# Composite setups
# --------------------------------------------------------------------------


def _setup_two_orders_with_clinical_substitutes() -> dict:
    """One PENDING two-box order per substitute candidate, both against the same
    prescription, plus ACTIVE CLINICAL mappings to the 0.50 and 0.80 SKUs."""
    scenario = setup_substitution_candidates(
        [CEILING_SUBSTITUTE, ABOVE_CEILING_SUBSTITUTE],
        boxes_od=1,
        boxes_os=1,
        equivalence_overrides={
            "equivalence_class": "CLINICAL",
            "requires_patient_consent": False,
        },
    )
    scenario["second_order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        1,
        1,
    )
    return scenario


def _setup_order_below_shipping_threshold() -> dict:
    """A verified prescription on the 2,500-cent SKU carrying one single-box
    order, whose subtotal sits below the free-shipping threshold."""
    scenario = setup_verified_prescription(product_overrides=VALUE_PRODUCT)
    scenario["below_order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        1,
        0,
    )
    return scenario


def _setup_two_delivered_orders_with_draft_claims() -> dict:
    """A plan-covered patient with two DELIVERED orders — one subtotalling 5,000
    cents and one subtotalling 5,001 cents — each carrying a DRAFT claim."""
    scenario = setup_delivered_order(
        boxes_od=1,
        boxes_os=1,
        with_plan=True,
        product_overrides=VALUE_PRODUCT,
    )
    scenario["order_at_ceiling"] = scenario["order"]

    scenario["premium_product"] = new_product(**PREMIUM_VALUE_PRODUCT)
    above = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["premium_product"]["id"],
        1,
        0,
    )
    ship_order(above["id"])
    scenario["order_above_ceiling"] = deliver_order(above["id"])

    scenario["claim_above_ceiling"] = new_reimbursement_claim(
        scenario["order_above_ceiling"]["id"],
        scenario["customer"]["id"],
        scenario["plan"]["id"],
    )
    scenario["claim_at_ceiling"] = new_reimbursement_claim(
        scenario["order_at_ceiling"]["id"],
        scenario["customer"]["id"],
        scenario["plan"]["id"],
    )
    return scenario


def _setup_round_at_its_deadline_instant() -> dict:
    """A directory-verified prescriber contacted at Monday 09:00 UTC, with the
    clock then moved to the computed deadline instant."""
    scenario = setup_verification_round(
        clock=MONDAY_9AM,
        directory_verified=True,
        contact_channel="PORTAL",
    )
    set_clock(MONDAY_BUSINESS_DAY_END)
    return scenario


# --------------------------------------------------------------------------
# The parameter deviation index at its auto-approve ceiling
# --------------------------------------------------------------------------


class TestDeviationIndexAtAutoApproveCeiling:
    def test_index_of_exactly_half_auto_approves_without_consent(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "An index of **at most 0.50** auto-approves: the swap
        proceeds without consent."

        PRD §3.6: "Once one is applied, it becomes `PARAMETER_ROUNDED` when the
        substitute product's `sphere_step` forced `fulfilled_od_sphere` or
        `fulfilled_os_sphere` away from the prescribed power, and
        `BRAND_EQUIVALENT` otherwise — that is, when both eyes are dispensed at
        exactly the prescribed powers and only the brand or material changed."

        Design: Difficulty/boundary_precision_check/deviation_index_exactly_at_auto_approve_ceiling_is_accepted
        """
        scenario = _setup_two_orders_with_clinical_substitutes()
        order = scenario["order"]
        substitute = scenario["substitutes"][0]

        data = validate_success(
            api.apply_substitution(
                order["id"],
                {
                    "substitute_product_id": substitute["id"],
                    "expected_order_version": order["version"],
                },
                fulfillment_headers,
            )
        )

        assert float(data["parameter_deviation_index"]) == 0.50, (
            "An index of exactly 0.50 must be computed in integer hundredths, "
            f"got {data['parameter_deviation_index']!r}"
        )
        assert data["substitution_type"] == "BRAND_EQUIVALENT"
        assert data["fulfilled_product_id"] == substitute["id"]

    def test_index_above_the_ceiling_still_demands_consent(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "An index **above 0.50 and at most 1.00** sits in the
        consent band: the swap proceeds only when the payload carries
        `patient_consent` set to true, and otherwise is refused with
        `ERR_CONSENT_REQUIRED` at HTTP 422."

        Design: Difficulty/boundary_precision_check/deviation_index_exactly_at_auto_approve_ceiling_is_accepted
        """
        scenario = _setup_two_orders_with_clinical_substitutes()
        second_order = scenario["second_order"]
        far_substitute = scenario["substitutes"][1]

        validate_error(
            api.apply_substitution(
                second_order["id"],
                {
                    "substitute_product_id": far_substitute["id"],
                    "expected_order_version": second_order["version"],
                },
                fulfillment_headers,
            ),
            ApiErrorId.ERR_CONSENT_REQUIRED,
        )

    def test_substitution_at_the_ceiling_leaves_both_orders_priced_as_placed(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "Substitution is deliberately **price-neutral**: it sets
        `fulfilled_product_id`, `substitution_type`, `parameter_deviation_index`,
        `fulfilled_od_sphere` and `fulfilled_os_sphere`, appends a
        `SUBSTITUTION_APPLIED` compliance event, and increments the order's
        `version`, while leaving `unit_price_cents`, `subtotal_cents`,
        `shipping_cents` and `total_cents` exactly as they were."

        Design: Difficulty/boundary_precision_check/deviation_index_exactly_at_auto_approve_ceiling_is_accepted
        """
        scenario = _setup_two_orders_with_clinical_substitutes()
        order = scenario["order"]
        second_order = scenario["second_order"]

        validate_success(
            api.apply_substitution(
                order["id"],
                {
                    "substitute_product_id": scenario["substitutes"][0]["id"],
                    "expected_order_version": order["version"],
                },
                fulfillment_headers,
            )
        )
        validate_error(
            api.apply_substitution(
                second_order["id"],
                {
                    "substitute_product_id": scenario["substitutes"][1]["id"],
                    "expected_order_version": second_order["version"],
                },
                fulfillment_headers,
            ),
            ApiErrorId.ERR_CONSENT_REQUIRED,
        )

        assert read_order(order["id"])["total_cents"] == 6400
        assert read_order(second_order["id"])["total_cents"] == 6400


# --------------------------------------------------------------------------
# The free-shipping threshold
# --------------------------------------------------------------------------


class TestFreeShippingSubtotalThreshold:
    def test_subtotal_exactly_at_the_threshold_ships_free(
        self, api, customer_headers_for
    ):
        """PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached
        the free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        Design: Difficulty/boundary_precision_check/free_shipping_at_exact_subtotal_threshold
        """
        scenario = _setup_order_below_shipping_threshold()
        customer_id = scenario["customer"]["id"]

        data = validate_success(
            api.create_order(
                {
                    "customer_id": customer_id,
                    "prescription_id": scenario["prescription"]["id"],
                    "ordered_product_id": scenario["product"]["id"],
                    "boxes_od": 1,
                    "boxes_os": 1,
                },
                customer_headers_for(customer_id),
            ),
            201,
        )

        assert data["subtotal_cents"] == 5000
        assert data["shipping_cents"] == 0
        assert data["total_cents"] == 5000

    def test_subtotal_one_tier_below_the_threshold_pays_flat_shipping(self, api):
        """PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached
        the free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        Design: Difficulty/boundary_precision_check/free_shipping_at_exact_subtotal_threshold
        """
        scenario = _setup_order_below_shipping_threshold()

        data = validate_success(
            api.get_order(
                scenario["below_order"]["id"],
                scenario["customer_headers"],
            )
        )

        assert data["subtotal_cents"] == 2500
        assert data["shipping_cents"] == 695
        assert data["total_cents"] == 3195

    def test_ledger_charges_both_the_free_and_the_charged_shipping_order(
        self, api, customer_headers_for
    ):
        """PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        Design: Difficulty/boundary_precision_check/free_shipping_at_exact_subtotal_threshold
        """
        scenario = _setup_order_below_shipping_threshold()
        customer_id = scenario["customer"]["id"]

        validate_success(
            api.create_order(
                {
                    "customer_id": customer_id,
                    "prescription_id": scenario["prescription"]["id"],
                    "ordered_product_id": scenario["product"]["id"],
                    "boxes_od": 1,
                    "boxes_os": 1,
                },
                customer_headers_for(customer_id),
            ),
            201,
        )

        ledger = get_ledger(customer_id)
        assert ledger["lifetime_charged_cents"] == 8195
        assert ledger["net_cash_position_cents"] == 8195


# --------------------------------------------------------------------------
# The first processing-fee tier ceiling
# --------------------------------------------------------------------------


class TestProcessingFeeFirstTierCeiling:
    def test_pre_fee_subtotal_exactly_at_the_ceiling_pays_no_fee(
        self, api, compliance_headers
    ):
        """PRD §3.9: "`processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        PRD §3.9: "`reimbursable_cents`, the final figure the plan will
        reimburse, is `pre_fee_subtotal_cents` less `processing_fee_cents`,
        floored at zero."

        Design: Difficulty/boundary_precision_check/processing_fee_first_tier_ceiling_is_inclusive
        """
        scenario = _setup_two_delivered_orders_with_draft_claims()

        data = validate_success(
            api.generate_reimbursement_claim(
                scenario["claim_at_ceiling"]["id"], compliance_headers
            )
        )

        assert data["pre_fee_subtotal_cents"] == 5000
        assert data["processing_fee_cents"] == 0
        assert data["reimbursable_cents"] == 5000

    def test_pre_fee_subtotal_one_cent_above_the_ceiling_pays_the_second_tier(
        self, api, compliance_headers
    ):
        """PRD §3.9: "`processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        PRD §3.9: "`reimbursable_cents`, the final figure the plan will
        reimburse, is `pre_fee_subtotal_cents` less `processing_fee_cents`,
        floored at zero."

        Design: Difficulty/boundary_precision_check/processing_fee_first_tier_ceiling_is_inclusive
        """
        scenario = _setup_two_delivered_orders_with_draft_claims()
        generate_reimbursement_claim(scenario["claim_at_ceiling"]["id"])

        data = validate_success(
            api.generate_reimbursement_claim(
                scenario["claim_above_ceiling"]["id"], compliance_headers
            )
        )

        assert data["pre_fee_subtotal_cents"] == 5001
        assert data["processing_fee_cents"] == 250
        assert data["reimbursable_cents"] == 4751

    def test_both_generations_consume_the_full_applied_allowance(self, api):
        """PRD §2.7: "`allowance_used_cents` is then the sum of
        `applied_allowance_cents` over that customer's reimbursement claims whose
        `created_at` falls inside the window and whose `status` is `GENERATED` or
        `SUBMITTED`."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/boundary_precision_check/processing_fee_first_tier_ceiling_is_inclusive
        """
        scenario = _setup_two_delivered_orders_with_draft_claims()
        generate_reimbursement_claim(scenario["claim_at_ceiling"]["id"])
        generate_reimbursement_claim(scenario["claim_above_ceiling"]["id"])

        ledger = get_ledger(scenario["customer"]["id"])
        assert ledger["allowance_used_cents"] == 10001
        assert ledger["allowance_remaining_cents"] == 4999


# --------------------------------------------------------------------------
# The passive deadline landing on the business-day boundary
# --------------------------------------------------------------------------


class TestPassiveDeadlineAtBusinessDayEnd:
    def test_eight_business_hours_from_nine_lands_on_the_day_end(
        self, api, compliance_headers
    ):
        """PRD §2.5: "A business day runs from 08:00 UTC to 17:00 UTC, which is
        nine business hours per day, and business days are Monday, Tuesday,
        Wednesday, Thursday and Friday."

        PRD §2.5: "While budget remains, consume from the cursor whichever is
        smaller: the whole remaining budget, or the number of hours between the
        cursor and 17:00 UTC on the cursor's day."

        PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing
        a business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        Design: Difficulty/boundary_precision_check/passive_deadline_lands_exactly_on_business_day_end
        """
        scenario = _setup_round_at_its_deadline_instant()

        assert scenario["verification_request"]["passive_deadline_at"] == (
            EXPECTED_DEADLINE
        ), "Eight business hours from Monday 09:00 UTC end the business day"

        data = validate_success(
            api.get_verification_request(
                scenario["verification_request"]["id"], compliance_headers
            )
        )
        assert data["passive_deadline_at"] == EXPECTED_DEADLINE

    def test_response_made_at_the_deadline_instant_is_refused(
        self, api, prescriber_headers_for
    ):
        """PRD §3.4: "The response is declared only for a request whose `status`
        is `SENT`, and the current logical time must be **strictly before**
        `passive_deadline_at`; a response at or after the deadline is refused
        with `ERR_VERIFICATION_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/passive_deadline_lands_exactly_on_business_day_end
        """
        scenario = _setup_round_at_its_deadline_instant()

        validate_error(
            api.respond_to_verification_request(
                scenario["verification_request"]["id"],
                {"response_type": "DENIED"},
                prescriber_headers_for(scenario["prescriber"]["id"]),
            ),
            ApiErrorId.ERR_VERIFICATION_WINDOW_CLOSED,
        )

    def test_sweep_at_the_deadline_instant_times_out_and_promotes(
        self, api, compliance_headers
    ):
        """PRD §3.4: "Every verification request still in `SENT` whose
        `passive_deadline_at` has been reached, meaning the current logical time
        is at or after it, moves to the terminal `PASSIVE_TIMEOUT` with
        `response_type` left null."

        PRD §3.4: "Its prescription is promoted from `PENDING_VERIFICATION` to
        `VERIFIED_ACTIVE`, a `PASSIVE_PROMOTED` compliance event is appended, and
        every order against that prescription whose `verification_state` is
        `RX_PENDING` moves to `RX_CLEARED` in `created_at` ascending order, each
        appending its own `PASSIVE_PROMOTED` compliance event with `subject_type`
        `Order`."

        Design: Difficulty/boundary_precision_check/passive_deadline_lands_exactly_on_business_day_end
        """
        scenario = _setup_round_at_its_deadline_instant()
        request_id = scenario["verification_request"]["id"]
        prescription_id = scenario["prescription"]["id"]

        sweep = validate_success(api.run_verification_sweep(compliance_headers))

        assert request_id in sweep["timed_out_request_ids"]
        assert prescription_id in sweep["promoted_prescription_ids"]

        prescription = validate_success(
            api.get_prescription(prescription_id, compliance_headers)
        )
        assert prescription["status"] == "VERIFIED_ACTIVE"
