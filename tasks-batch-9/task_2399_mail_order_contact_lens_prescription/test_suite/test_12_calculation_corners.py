"""Money, deviation and deadline arithmetic asserted at the exact figure.

Each test pins one computed value that the PRD specifies as a formula, so an
implementation that reorders a step, drops a constant or leaks binary floating
point residue into a boundary comparison is caught on the number itself rather
than on a status code.
"""

from decimal import Decimal

from test_helpers import (
    CO_ALPHA_HEADERS,
    DEFAULT_CLOCK_UTC,
    FO_HEADERS,
    assert_customer_ledger,
    assert_generated_claim_money_chain,
    assert_order_money,
    assert_return_request,
    assert_verification_request,
    make_customer_headers,
    new_customer,
    new_doctor_lookup_prescription,
    new_prescriber,
    new_product,
    order_version,
    set_clock,
    setup_allowance_partly_consumed,
    setup_delivered_order,
    setup_second_delivered_order,
    setup_substitution_candidates,
    setup_verified_prescription,
    submit_prescription,
    validate_paginated,
    validate_success,
)

FRIDAY_AFTERNOON = "2026-09-04T14:00:00Z"
"""A Friday inside business hours, three hours short of the 17:00 UTC close."""


def _two_prescriptions_awaiting_two_prescribers() -> dict:
    """Two non-overlapping DOCTOR_LOOKUP prescriptions for one patient, one
    naming a directory-verified provider and one naming a provider that is not,
    both sitting in PENDING_VERIFICATION with the clock on Friday afternoon."""
    set_clock(FRIDAY_AFTERNOON)
    product = new_product()
    directory_prescriber = new_prescriber(
        license_number="UT-40921", contact_channel="PORTAL", directory_verified=True
    )
    named_prescriber = new_prescriber(
        full_name="Dr. Ivo Renner",
        license_number="UT-50117",
        contact_channel="FAX",
        directory_verified=False,
    )
    customer = new_customer()
    first = new_doctor_lookup_prescription(
        customer["id"],
        product["id"],
        directory_prescriber["id"],
        issue_date="2026-07-01",
        expiry_date="2027-07-01",
        boxes_authorized_total=12,
    )
    submit_prescription(first["id"], customer["id"])
    second = new_doctor_lookup_prescription(
        customer["id"],
        product["id"],
        named_prescriber["id"],
        issue_date="2027-07-01",
        expiry_date="2028-07-01",
        boxes_authorized_total=12,
    )
    submit_prescription(second["id"], customer["id"])
    return {
        "customer": customer,
        "product": product,
        "directory_prescriber": directory_prescriber,
        "named_prescriber": named_prescriber,
        "directory_prescription": first,
        "named_prescription": second,
    }


class TestOrderPricingAndLedgerRollForward:
    """Order money is priced from the snapshot and rolls into the ledgers."""

    def test_standard_shipping_applies_below_the_free_shipping_threshold(self, api):
        """PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached the
        free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        PRD §2.7: "`boxes_consumed` is the sum of `boxes_od` plus `boxes_os` over
        every order against that prescription whose `fulfillment_state` is not
        `CANCELLED`; this is the box invariant, **INV_BOXES**."

        Design: Corner/calculations/order_total_applies_standard_shipping_below_the_free_threshold
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        order = validate_success(
            api.create_order(
                {
                    "customer_id": customer_id,
                    "prescription_id": scenario["prescription"]["id"],
                    "ordered_product_id": scenario["product"]["id"],
                    "boxes_od": 1,
                    "boxes_os": 0,
                },
                make_customer_headers(customer_id),
            ),
            201,
        )

        assert order["subtotal_cents"] == 3200, "one 3200-cent box subtotals 3200"
        assert order["shipping_cents"] == 695, (
            "a 3200-cent subtotal is below the 5000-cent threshold, so the flat "
            "695-cent charge applies"
        )
        assert order["total_cents"] == 3895
        assert_order_money(order)

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert_customer_ledger(ledger)
        assert ledger["lifetime_charged_cents"] == 3895, (
            "the ledger records the 3895-cent total, not the 3200-cent subtotal"
        )
        assert ledger["net_cash_position_cents"] == 3895

        prescription = validate_success(
            api.get_prescription(
                scenario["prescription"]["id"], make_customer_headers(customer_id)
            )
        )
        assert prescription["boxes_consumed"] == 1


class TestAllowanceLedgerAggregation:
    """The plan-year allowance counts only the claim statuses the PRD names."""

    def test_allowance_used_counts_only_generated_and_submitted_claims(self, api):
        """PRD §2.7: "`allowance_used_cents` is then the sum of
        `applied_allowance_cents` over that customer's reimbursement claims
        whose `created_at` falls inside the window and whose `status` is
        `GENERATED` or `SUBMITTED`."

        PRD §2.7: "Claims in `DRAFT` and claims in `VOIDED` contribute nothing."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        PRD §3.9: "The claim is created in `DRAFT` with every money field null
        except `refund_offset_cents`, which is seeded from the settled returns
        already recorded against the order."

        PRD §3.9: "`processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        Design: Corner/calculations/allowance_used_counts_only_generated_and_submitted_claims
        """
        scenario = setup_allowance_partly_consumed(
            first_boxes=(1, 1), clock=DEFAULT_CLOCK_UTC
        )
        scenario = setup_second_delivered_order(scenario, boxes_od=1, boxes_os=1)
        customer_id = scenario["customer"]["id"]
        generated_claim_id = scenario["first_claim"]["id"]
        draft_claim_id = scenario["claim"]["id"]

        ledger = validate_success(api.get_customer_ledger(customer_id, CO_ALPHA_HEADERS))
        assert_customer_ledger(ledger)
        assert ledger["allowance_used_cents"] == 6400, (
            "only the GENERATED claim's applied allowance counts"
        )
        assert ledger["allowance_remaining_cents"] == 8600
        assert ledger["lifetime_charged_cents"] == 12800
        assert ledger["net_cash_position_cents"] == 12800

        generated = validate_success(
            api.get_reimbursement_claim(generated_claim_id, CO_ALPHA_HEADERS)
        )
        assert generated["status"] == "GENERATED"
        assert generated["applied_allowance_cents"] == 6400
        assert generated["processing_fee_cents"] == 250
        assert generated["reimbursable_cents"] == 6150
        assert_generated_claim_money_chain(generated)

        draft = validate_success(
            api.get_reimbursement_claim(draft_claim_id, CO_ALPHA_HEADERS)
        )
        assert draft["status"] == "DRAFT"
        assert draft["applied_allowance_cents"] is None, (
            "a DRAFT claim carries no money figures and consumes no allowance"
        )
        assert draft["reimbursable_cents"] is None


class TestParameterDeviationIndexPrecision:
    """The deviation index is integer-hundredths arithmetic, not float drift."""

    def test_base_curve_gap_yields_exactly_two_decimal_places(self, api):
        """PRD §3.6: "Sum four weighted absolute differences, each taken between
        the two values expressed in integer hundredths: the difference between
        the prescription's `base_curve` and the substitute product's
        `base_curve`, weighted by four; the difference between the
        prescription's `diameter` and the substitute product's `diameter`,
        weighted by two; the difference between the prescription's `od_sphere`
        and the dispensed `fulfilled_od_sphere`, weighted by one; and the
        difference between the prescription's `os_sphere` and the dispensed
        `fulfilled_os_sphere`, also weighted by one."

        PRD §3.6: "Divide that weighted sum by one hundred to obtain
        `parameter_deviation_index`, presented with two decimal places."

        PRD §3.6: "An index of **at most 0.50** auto-approves: the swap proceeds
        without consent."

        PRD §3.6: "Once one is applied, it becomes `PARAMETER_ROUNDED` when the
        substitute product's `sphere_step` forced `fulfilled_od_sphere` or
        `fulfilled_os_sphere` away from the prescribed power, and
        `BRAND_EQUIVALENT` otherwise — that is, when both eyes are dispensed at
        exactly the prescribed powers and only the brand or material changed."

        PRD §3.6: "Substitution is deliberately **price-neutral**: it sets
        `fulfilled_product_id`, `substitution_type`,
        `parameter_deviation_index`, `fulfilled_od_sphere` and
        `fulfilled_os_sphere`, appends a `SUBSTITUTION_APPLIED` compliance
        event, and increments the order's `version`, while leaving
        `unit_price_cents`, `subtotal_cents`, `shipping_cents` and `total_cents`
        exactly as they were."

        Design: Corner/calculations/deviation_index_is_computed_in_integer_hundredths_to_two_places
        """
        scenario = setup_substitution_candidates(
            [
                {
                    "brand": "OptiSoft",
                    "base_curve": 8.70,
                    "equivalence": {
                        "equivalence_class": "CLINICAL",
                        "requires_patient_consent": False,
                    },
                }
            ],
            clock=DEFAULT_CLOCK_UTC,
            boxes_od=1,
            boxes_os=1,
        )
        order_id = scenario["order"]["id"]
        substitute = scenario["substitutes"][0]

        substituted = validate_success(
            api.apply_substitution(
                order_id,
                {
                    "substitute_product_id": substitute["id"],
                    "expected_order_version": order_version(order_id),
                },
                FO_HEADERS,
            )
        )

        index = substituted["parameter_deviation_index"]
        assert Decimal(str(index)) == Decimal("0.40"), (
            "4 * abs(860 - 870) integer hundredths is exactly 0.40, so no float "
            "residue may leak into the presented value"
        )
        assert float(index) == 0.40

        assert substituted["substitution_type"] == "BRAND_EQUIVALENT"
        assert substituted["fulfilled_product_id"] == substitute["id"]
        assert float(substituted["fulfilled_od_sphere"]) == -2.25
        assert float(substituted["fulfilled_os_sphere"]) == -4.00

        assert substituted["unit_price_cents"] == 3200
        assert substituted["subtotal_cents"] == 6400
        assert substituted["total_cents"] == 6400
        assert_order_money(substituted)

        events, _meta = validate_paginated(
            api.list_compliance_events_for_prescription(
                scenario["prescription"]["id"], CO_ALPHA_HEADERS
            )
        )
        applied = [
            event
            for event in events
            if event["event_type"] == "SUBSTITUTION_APPLIED"
        ]
        assert len(applied) == 1, "the swap appends exactly one SUBSTITUTION_APPLIED"


class TestTornLensSettlementCap:
    """The torn-lens cap is a floor of twenty percent of the captured total."""

    def test_torn_lens_cap_binds_the_previewed_settlement(self, api):
        """PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all:
        the candidate figure is `torn_lens_count` multiplied by the per-box
        value, divided by the lenses per box and rounded half up to a whole
        cent, and `settlement_cents` is whichever is smaller — that candidate
        figure, or a cap equal to twenty percent of the order's `total_cents`
        with any fraction of a cent discarded downward."

        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS`
        and `CASH_REFUND` for the other two reasons — a torn lens is a
        replacement matter, not a refund matter."

        PRD §3.8: "Creating the return computes `settlement_mode` together with
        a **preview** of `settlement_cents` and `settlement_channel` without
        moving any money."

        PRD §3.8: "A return's `status` starts at `SUBMITTED` and ends in
        `REJECTED` or `SETTLED`."

        Design: Corner/calculations/torn_lens_cap_rate_constant_binds_the_preview_settlement
        """
        scenario = setup_delivered_order(
            boxes_od=1, boxes_os=1, clock=DEFAULT_CLOCK_UTC
        )
        customer_id = scenario["customer"]["id"]
        order_id = scenario["order"]["id"]

        return_request = validate_success(
            api.create_return_request(
                {
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "reason": "TORN_LENS",
                    "torn_lens_count": 13,
                },
                make_customer_headers(customer_id),
            ),
            201,
        )

        assert return_request["status"] == "SUBMITTED"
        assert return_request["settlement_mode"] == "NO_PRORATION"
        assert return_request["settlement_cents"] == 1280, (
            "the 1387-cent candidate loses to the 1280-cent twenty-percent cap"
        )
        assert return_request["settlement_channel"] == "STORE_CREDIT"
        assert_return_request(return_request)

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert ledger["store_credit_cents"] == 0, "creation only previews the figure"
        assert ledger["lifetime_refunded_cents"] == 0

        order = validate_success(
            api.get_order(order_id, make_customer_headers(customer_id))
        )
        assert order["total_cents"] == 6400


class TestPassiveDeadlineBusinessHourWalk:
    """The passive deadline walks business hours, so the weekend contributes
    nothing and the budget resumes on Monday morning."""

    def test_friday_afternoon_send_resumes_after_the_weekend(self, api):
        """PRD §2.5: "A business day runs from 08:00 UTC to 17:00 UTC, which is
        nine business hours per day, and business days are Monday, Tuesday,
        Wednesday, Thursday and Friday."

        PRD §2.5: "While budget remains, consume from the cursor whichever is
        smaller: the whole remaining budget, or the number of hours between the
        cursor and 17:00 UTC on the cursor's day. If budget still remains after
        reaching 17:00 UTC, move the cursor to 08:00 UTC on the next business
        day and continue."

        PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing
        a business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        PRD §3.3: "It records the `prescription_id` being verified and the
        `prescriber_id` receiving the contact, snapshots the provider's
        `contact_channel` into its own `channel`, and stamps `sent_at` from the
        logical clock."

        PRD §3.3: "Its `round_number` is a one-based index within the
        prescription, set to the prescription's `verification_rounds` plus one,
        and the prescription's `verification_rounds` is then incremented."

        PRD §3.3: "Verification requests may be listed filtered by
        `prescription_id`, `prescriber_id` and `status`."

        Design: Corner/calculations/passive_deadline_walk_skips_the_weekend_chronologically
        """
        scenario = _two_prescriptions_awaiting_two_prescribers()
        directory_prescriber_id = scenario["directory_prescriber"]["id"]

        request = validate_success(
            api.send_verification_request(
                scenario["directory_prescription"]["id"],
                {"prescriber_id": directory_prescriber_id},
                CO_ALPHA_HEADERS,
            ),
            201,
        )

        assert request["sent_at"] == "2026-09-04T14:00:00.000Z"
        assert request["passive_deadline_at"] == "2026-09-07T13:00:00.000Z", (
            "three hours run out on Friday and the remaining five resume at "
            "08:00 UTC on Monday, so the weekend contributes nothing"
        )
        assert request["channel"] == "PORTAL"
        assert request["round_number"] == 1
        assert_verification_request(request)

        named_request = validate_success(
            api.send_verification_request(
                scenario["named_prescription"]["id"],
                {"prescriber_id": scenario["named_prescriber"]["id"]},
                CO_ALPHA_HEADERS,
            ),
            201,
        )
        assert named_request["passive_deadline_at"] == "2026-09-07T17:00:00.000Z", (
            "a provider that is not directory-verified gets twelve business "
            "hours, which exhausts Monday's whole nine-hour day"
        )

        _rows, meta = validate_paginated(
            api.list_verification_requests(
                CO_ALPHA_HEADERS,
                params={"prescriber_id": directory_prescriber_id, "status": "SENT"},
            )
        )
        assert meta["total_count"] == 1


class TestSettlementVariantSelection:
    """The return reason, never the caller, picks the rounding variant."""

    def test_return_reason_selects_the_rounding_variant(self, api):
        """PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."

        PRD §3.8: "Under `PER_BOX_ROUNDED`, each opened box is valued
        independently as the per-box value multiplied by the unused lenses in
        that box divided by the lenses per box, **rounded half up to a whole
        cent for that box**, and those per-box amounts are then added together."

        PRD §3.8: "Under `POOLED_ROUNDED`, the unused lenses across all opened
        boxes are added together first, that total is multiplied by the per-box
        value and divided by the lenses per box **exactly**, and the single
        resulting amount is rounded half up to a whole cent once."

        PRD §3.8: "For both prorating variants, `settlement_cents` is the
        unopened component plus the opened component."

        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS`
        and `CASH_REFUND` for the other two reasons — a torn lens is a
        replacement matter, not a refund matter."

        Design: Corner/calculations/settlement_variant_is_selected_from_the_return_reason
        """
        scenario = setup_delivered_order(
            boxes_od=2, boxes_os=1, clock=DEFAULT_CLOCK_UTC
        )
        customer_id = scenario["customer"]["id"]
        order_id = scenario["order"]["id"]
        customer_headers = make_customer_headers(customer_id)

        pooled = validate_success(
            api.create_return_request(
                {
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "reason": "WRONG_PARAMETER",
                    "unopened_boxes": 0,
                    "opened_box_used_counts": [11, 11, 11],
                },
                customer_headers,
            ),
            201,
        )

        assert pooled["settlement_mode"] == "POOLED_ROUNDED"
        assert pooled["settlement_cents"] == 6080, (
            "57 unused lenses pooled once give exactly 6080 cents"
        )
        assert pooled["settlement_channel"] == "CASH_REFUND"
        assert_return_request(pooled)

        order = validate_success(api.get_order(order_id, customer_headers))
        assert order["subtotal_cents"] == 9600
        assert order["shipping_cents"] == 0
        assert order["total_cents"] == 9600

        per_box = validate_success(
            api.create_return_request(
                {
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "reason": "PRESCRIPTION_CHANGE",
                    "unopened_boxes": 0,
                    "opened_box_used_counts": [11, 11, 11],
                },
                customer_headers,
            ),
            201,
        )

        assert per_box["settlement_mode"] == "PER_BOX_ROUNDED"
        assert per_box["settlement_cents"] == 6081, (
            "rounding each box to 2027 cents first yields one cent more than "
            "pooling the same physical return"
        )
        assert per_box["settlement_channel"] == "CASH_REFUND"
        assert per_box["settlement_cents"] == pooled["settlement_cents"] + 1
