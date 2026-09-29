"""Requests that violate two guards at once, where the lower priority number wins.

Each rule also proves the losing check is genuinely violated, so an
implementation that evaluates the guards in the wrong order is caught rather
than accidentally passing.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    ApiErrorId,
    adjudicate_claim,
    api_client,
    book_appointment,
    complete_appointment,
    confirm_assignment_intake,
    create_bundle,
    create_disposition_partner_row,
    create_model,
    comfort_exchange_payload,
    disposition_return,
    file_quality_claim,
    inspect_return,
    make_customer_headers,
    make_finance_controller_headers,
    open_return_case,
    preload_abuse_signals,
    read_customer,
    read_order,
    read_quality_claim,
    read_return_case,
    refund_authorization_payload,
    set_clock,
    setup_delivered_order,
    setup_published_route,
    validate_error,
    validate_paginated,
)

AUTHORIZER_2 = make_finance_controller_headers("fin-authorizer-2")


class TestAbuseBlockOutranksTheBreakInWindowOnAnExchangeRequest:
    """A blocked customer and a clean customer both ask for an exchange on night nine."""

    def _two_households(self):
        medium = create_model(
            sku="MDL-Q-MED-P", firmness="MEDIUM", size="QUEEN", list_price_cents=120000
        )
        firm = create_model(
            sku="MDL-Q-FIRM-P", firmness="FIRM", size="QUEEN", list_price_cents=139000
        )
        blocked = setup_delivered_order(
            model=medium,
            customer_overrides={
                "email": "pp1a@example.com",
                "full_name": "Blocked Bella",
                "household_hash": "HH-PP1A",
            },
        )
        clean = setup_delivered_order(
            model=medium,
            customer_overrides={
                "email": "pp1b@example.com",
                "full_name": "Clean Cleo",
                "household_hash": "HH-PP1B",
            },
        )
        preload_abuse_signals(
            blocked["customer"]["id"],
            [
                ("HOUSEHOLD_MATCH", "2026-08-01T00:00:00Z"),
                ("REPEAT_RETURN", "2026-08-01T00:00:00Z"),
                ("MULTI_CHANNEL", "2026-08-01T00:00:00Z"),
                ("SHORT_TRIAL", "2026-08-01T00:00:00Z"),
            ],
        )
        set_clock("2026-08-10T00:00:00Z")
        return medium, firm, blocked, clean

    def test_the_fraud_posture_gate_answers_before_the_break_in_clock(self):
        """PRD §2.8: "15. The fraud posture gate — `ERR_TRIAL_ABUSE_BLOCK`."

        Both guards are violated by the same request — the customer's rolling
        score is exactly 80 and the clock is twelve days short of
        `break_in_ends_at` — and priority 15 must beat priority 17.

        Design: Difficulty/priority_pair_validation_conflict/abuse_block_p15_outranks_break_in_not_elapsed_p17_on_exchange_request
        """
        _medium, firm, blocked, _clean = self._two_households()

        response = api_client.create_comfort_exchange(
            comfort_exchange_payload(blocked["order"]["id"], firm["id"]),
            make_customer_headers(blocked["customer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TRIAL_ABUSE_BLOCK)

        customer = read_customer(blocked["customer"]["id"])
        assert customer["abuse_score_rolling"] == 80
        assert customer["status"] == "BLOCKED"

    def test_a_clean_household_at_the_same_clock_proves_the_break_in_gate_bites(self):
        """PRD §3.5: "And the trial clock applies exactly as it does to returns — the break-in window must have elapsed and the trial window must not yet have closed, answering `ERR_BREAK_IN_NOT_ELAPSED` or `ERR_TRIAL_WINDOW_EXPIRED` respectively, with a blocked customer refused earlier still by `ERR_TRIAL_ABUSE_BLOCK`."

        The control customer carries no signals at all, so the only guard left
        standing is the break-in window, and the very same clock and payload
        shape now answer 422.

        Design: Difficulty/priority_pair_validation_conflict/abuse_block_p15_outranks_break_in_not_elapsed_p17_on_exchange_request
        """
        _medium, firm, _blocked, clean = self._two_households()

        response = api_client.create_comfort_exchange(
            comfort_exchange_payload(clean["order"]["id"], firm["id"]),
            make_customer_headers(clean["customer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BREAK_IN_NOT_ELAPSED)

    def test_a_rejected_exchange_request_persists_nothing(self):
        """PRD §2.8: "Because most operations in this domain are guarded by many checks at once, the order in which those checks run is part of the contract: validations are evaluated strictly in ascending priority, and the first failing check alone decides the response."

        Neither refusal may leave a `ComfortExchange` row behind or disturb the
        blocked customer's order, which is still DELIVERED and inside BREAK_IN.

        Design: Difficulty/priority_pair_validation_conflict/abuse_block_p15_outranks_break_in_not_elapsed_p17_on_exchange_request
        """
        _medium, firm, blocked, clean = self._two_households()

        api_client.create_comfort_exchange(
            comfort_exchange_payload(blocked["order"]["id"], firm["id"]),
            make_customer_headers(blocked["customer"]["id"]),
        )
        api_client.create_comfort_exchange(
            comfort_exchange_payload(clean["order"]["id"], firm["id"]),
            make_customer_headers(clean["customer"]["id"]),
        )

        for order_id in (blocked["order"]["id"], clean["order"]["id"]):
            _rows, meta = validate_paginated(
                api_client.list_comfort_exchanges(AGENT, params={"original_order_id": order_id})
            )
            assert meta["total_count"] == 0, (
                f"a refused request must not create an exchange row for {order_id}"
            )

        order = read_order(blocked["order"]["id"])
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["trial_status"] == "BREAK_IN"


class TestOpenQualityClaimOutranksTheUnpayableBalance:
    """A return whose FINAL settlement is negative and which still carries an open complaint."""

    def _case_ready_for_refund(self):
        model = create_model(
            sku="MDL-Q-SOFT-P",
            name="Comfort Q Soft",
            firmness="SOFT",
            size="QUEEN",
            list_price_cents=120000,
            donation_eligible=False,
        )
        bundle = create_bundle(
            code="BUNDLE-PP2",
            unwind_policy="DEDUCT_RETAIL",
            accessory_retail_cents=60000,
            gift_card_cents=40000,
            percent_off_bps=0,
            requires_accessory_return=True,
        )
        create_disposition_partner_row(
            name="Foam Cycle CA",
            partner_type="RECYCLER",
            region_code="CA",
            daily_intake_capacity_units=10,
            accepts_condition_grades=["A", "B", "C", "D"],
            soil_policy="ACCEPT_SOILED",
            priority_rank=1,
            recycle_fee_cents_per_unit=5000,
        )
        scenario = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "pp2@example.com",
                "full_name": "Percy Priority",
                "household_hash": "HH-PP2",
            },
            order_overrides={"bundle_id": bundle["id"]},
        )
        set_clock("2026-08-05T00:00:00Z")
        scenario["claim"] = file_quality_claim(
            scenario["order"]["id"],
            "COMPRESSION_RECOVERY",
            2,
            headers=scenario["customer_headers"],
        )
        case = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-09-10T00:00:00Z",
        )
        route = setup_published_route()
        appointment = book_appointment(route["id"], case["id"])
        complete_appointment(appointment["id"], "COMPLETED", at="2026-09-15T00:00:00Z")
        inspect_return(case["id"], "D", True, False)
        assignment = disposition_return(case["id"], "RECYCLE", "2026-09-16")
        confirm_assignment_intake(assignment["id"])
        scenario["return_case"] = read_return_case(case["id"])
        return scenario

    def test_the_unresolved_complaint_answers_before_the_settlement_is_priced(self):
        """PRD §3.9: "No quality claim on the case's trial order may still be `SUBMITTED` or `EVIDENCE_REQUESTED` — an unresolved complaint blocks the ledger, and an attempt is refused with `ERR_OPEN_QUALITY_CLAIM`."

        The FINAL settlement on this case is 120000 - 6000 - 100000 - 48000 =
        -34000 cents, so priority 40 is violated too, but the referential guard
        at priority 36 must decide the response.

        Design: Difficulty/priority_pair_validation_conflict/open_quality_claim_p36_outranks_no_refundable_balance_p40_on_refund_creation
        """
        scenario = self._case_ready_for_refund()
        case = scenario["return_case"]

        response = api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_2
        )
        validate_error(response, ApiErrorId.ERR_OPEN_QUALITY_CLAIM)

    def test_clearing_the_complaint_exposes_the_unpayable_balance_refusal(self):
        """PRD §3.9: "That net figure must be strictly greater than zero: a refund that computes to exactly zero, or to a negative number because deductions and offsets have consumed the whole balance, is refused with `ERR_NO_REFUNDABLE_BALANCE`."

        Denying the complaint in place removes the priority-36 guard without
        touching the case, and a byte-identical retry carrying the same expected
        version now answers 422 — proving the balance was unpayable all along.
        The order stays CLOSED, because the revert edge leaves a closed order be.

        Design: Difficulty/priority_pair_validation_conflict/open_quality_claim_p36_outranks_no_refundable_balance_p40_on_refund_creation
        """
        scenario = self._case_ready_for_refund()
        case = scenario["return_case"]

        api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_2
        )
        adjudicate_claim(scenario["claim"]["id"], "DENIED")

        assert read_quality_claim(scenario["claim"]["id"])["status"] == "DENIED"
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "CLOSED"

        retry = api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_2
        )
        validate_error(retry, ApiErrorId.ERR_NO_REFUNDABLE_BALANCE)

    def test_both_refusals_leave_the_case_and_its_stamped_deductions_untouched(self):
        """PRD §3.8: "`damage_offset_cents` is the order's `paid_amount_cents` multiplied by whichever is smaller of the combined rate and the 4000-basis-point cap, divided by 10000, and rounded to the nearest whole cent with ties away from zero."

        Grade D retains 3000 basis points and the soiling finding adds 1000, so
        the offset is capped at 4000 basis points of 120000 = 48000 cents, while
        the DEDUCT_RETAIL bundle claws back 60000 + 40000 = 100000; both figures
        were stamped at inspection and neither failed authorization may alter
        them, the money axis, or the case's version.

        Design: Difficulty/priority_pair_validation_conflict/open_quality_claim_p36_outranks_no_refundable_balance_p40_on_refund_creation
        """
        scenario = self._case_ready_for_refund()
        case = scenario["return_case"]

        api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_2
        )
        adjudicate_claim(scenario["claim"]["id"], "DENIED")
        api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_2
        )

        _rows, meta = validate_paginated(
            api_client.list_refund_authorizations(
                ADMIN, params={"return_case_id": case["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "neither refused authorization may leave a ledger row behind"
        )

        reloaded = read_return_case(case["id"])
        assert reloaded["financial_status"] == "PENDING"
        assert reloaded["version"] == case["version"]
        assert reloaded["bundle_unwind_cents"] == 100000
        assert reloaded["damage_offset_cents"] == 48000
