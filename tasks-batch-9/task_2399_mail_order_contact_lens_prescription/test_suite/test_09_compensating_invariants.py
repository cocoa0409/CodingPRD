"""Compensating operations must release exactly what the forward operation
consumed: order cancellation against INV_MONEY and INV_BOXES, and claim voiding
against INV_ALLOWANCE."""

from test_helpers import (
    CO_ALPHA_HEADERS,
    ApiErrorId,
    create_order_payload,
    make_customer_headers,
    new_order,
    setup_generated_claim,
    setup_order_on_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)


def _six_box_pending_order() -> dict:
    """A verified prescription carrying one PENDING six-box order worth 19200
    cents: 3200 cents a box, three boxes per eye, free shipping."""
    return setup_order_on_verified_prescription(boxes_od=3, boxes_os=3)


def _prescription_with_two_orders() -> dict:
    """A 24-box prescription carrying a two-box order and a four-box order, so
    six boxes of authorisation are consumed in total."""
    scenario = setup_order_on_verified_prescription(boxes_od=1, boxes_os=1)
    scenario["keep_order"] = scenario["order"]
    scenario["drop_order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        2,
        2,
    )
    return scenario


class TestMoneyInvariantAcrossCancellation:
    """POST /orders is the forward operation, POST /orders/{id}/cancel the
    compensation, and the cash ledger must land back where it started."""

    def test_order_placement_charges_the_full_order_total(self, api):
        """PRD §3.5: "Placing an order also moves the ledgers forward: the
        prescription's `boxes_consumed` grows by the ordered boxes, and the
        customer's `lifetime_charged_cents` and `net_cash_position_cents` are
        reconciled."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`. This equality is the money invariant,
        **INV_MONEY**, and it must hold after every cancellation, settlement and
        cascade."

        Design: Difficulty/compensating_invariant/money_invariant_survives_order_cancellation
        """
        scenario = _six_box_pending_order()
        customer_id = scenario["customer"]["id"]

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )

        assert ledger["lifetime_charged_cents"] == 19200
        assert ledger["net_cash_position_cents"] == 19200

    def test_cancellation_returns_the_cash_ledger_to_zero(self, api):
        """PRD §3.7: "Cancellation is available while an order is still
        `PENDING` and is a full **compensating** operation, reversing every
        forward effect of placement."

        PRD §3.7: "The caller — the patient, a compliance officer or an
        administrator — supplies a `cancellation_reason` of `CUSTOMER_REQUEST`,
        `DISPUTE_UPHELD`, `PRESCRIBER_DENIED` or `RX_EXPIRED`, which is recorded
        on the order as `fulfillment_state` moves to the terminal `CANCELLED`."

        PRD §3.7: "The customer's `lifetime_charged_cents` and
        `net_cash_position_cents` are reconciled."

        PRD §2.7: "`lifetime_refunded_cents` is the sum of `settlement_cents`
        over that customer's return requests whose `status` is `SETTLED` and
        whose `settlement_channel` is `CASH_REFUND`."

        PRD §2.7: "`store_credit_cents` is the running store-credit balance,
        credited whenever a return settles through the `STORE_CREDIT` channel."

        Design: Difficulty/compensating_invariant/money_invariant_survives_order_cancellation
        """
        scenario = _six_box_pending_order()
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)

        before = validate_success(
            api.get_customer_ledger(customer_id, customer_headers)
        )
        assert before["lifetime_charged_cents"] == 19200
        assert before["net_cash_position_cents"] == 19200

        cancelled = validate_success(
            api.cancel_order(
                scenario["order"]["id"],
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                customer_headers,
            )
        )
        assert cancelled["fulfillment_state"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "CUSTOMER_REQUEST"

        after = validate_success(api.get_customer_ledger(customer_id, customer_headers))
        assert after["lifetime_charged_cents"] == 0
        assert after["lifetime_refunded_cents"] == 0
        assert after["net_cash_position_cents"] == 0
        assert after["store_credit_cents"] == 0

    def test_cancelled_order_row_is_preserved_rather_than_deleted(self, api):
        """PRD §3.7: "The caller — the patient, a compliance officer or an
        administrator — supplies a `cancellation_reason` of `CUSTOMER_REQUEST`,
        `DISPUTE_UPHELD`, `PRESCRIBER_DENIED` or `RX_EXPIRED`, which is recorded
        on the order as `fulfillment_state` moves to the terminal `CANCELLED`."

        PRD §3.5: "Order lists may be filtered by `customer_id`,
        `prescription_id`, `ordered_product_id`, `fulfilled_product_id` and,
        independently, by `verification_state` and `fulfillment_state`."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object, where `total_count` counts every
        row matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the returned page."

        Design: Difficulty/compensating_invariant/money_invariant_survives_order_cancellation
        """
        scenario = _six_box_pending_order()
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)

        validate_success(
            api.cancel_order(
                scenario["order"]["id"],
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                customer_headers,
            )
        )

        rows, meta = validate_paginated(
            api.list_orders(
                customer_headers,
                params={"customer_id": customer_id, "fulfillment_state": "CANCELLED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["order"]["id"]


class TestAllowanceInvariantAcrossClaimVoid:
    """Generation consumes plan-year allowance; the void releases exactly that
    much and no more, while the voided row keeps its historical figure."""

    def test_generation_consumes_the_applied_allowance(self, api):
        """PRD §3.9: "`applied_allowance_cents` is whichever is smaller,
        `base_eligible_cents` or that remaining allowance."

        PRD §3.9: "`processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that. `reimbursable_cents`, the final figure the plan will
        reimburse, is `pre_fee_subtotal_cents` less `processing_fee_cents`,
        floored at zero."

        PRD §3.9: "Generation also mints a `packet_reference`, the paperwork
        identifier, and increases the customer's `allowance_used_cents` by
        `applied_allowance_cents` — reconciled, as §2.7 requires, from the live
        claim rows rather than incremented blindly."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/compensating_invariant/allowance_invariant_releases_exactly_what_generation_consumed
        """
        scenario = setup_generated_claim(boxes_od=1, boxes_os=1)
        customer_id = scenario["customer"]["id"]

        claim = scenario["claim"]
        assert claim["status"] == "GENERATED"
        assert claim["applied_allowance_cents"] == 6400
        assert claim["processing_fee_cents"] == 250
        assert claim["reimbursable_cents"] == 6150

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert ledger["allowance_used_cents"] == 6400
        assert ledger["allowance_remaining_cents"] == 8600

    def test_void_releases_exactly_the_generated_allowance(self, api):
        """PRD §3.9: "Voiding a claim directly is declared only from
        `GENERATED`; the officer supplies a `voided_reason` of `DISPUTE_UPHELD`,
        `CUSTOMER_REQUEST` or `PLAN_RETIRED`, the customer's
        `allowance_used_cents` is decreased by the claim's
        `applied_allowance_cents` — releasing exactly what generation consumed —
        and a `CLAIM_VOIDED` compliance event is appended."

        PRD §2.7: "The value is recomputed after every claim generation and
        every claim void."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/compensating_invariant/allowance_invariant_releases_exactly_what_generation_consumed
        """
        scenario = setup_generated_claim(boxes_od=1, boxes_os=1)
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)

        before = validate_success(
            api.get_customer_ledger(customer_id, customer_headers)
        )
        assert before["allowance_used_cents"] == 6400
        assert before["allowance_remaining_cents"] == 8600

        voided = validate_success(
            api.void_reimbursement_claim(
                scenario["claim"]["id"],
                {"voided_reason": "CUSTOMER_REQUEST"},
                CO_ALPHA_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["voided_reason"] == "CUSTOMER_REQUEST"
        assert voided["applied_allowance_cents"] == 6400

        after = validate_success(api.get_customer_ledger(customer_id, customer_headers))
        assert after["allowance_used_cents"] == 0
        assert after["allowance_remaining_cents"] == 15000

    def test_voided_claim_no_longer_counts_as_generated(self, api):
        """PRD §2.7: "`allowance_used_cents` is then the sum of
        `applied_allowance_cents` over that customer's reimbursement claims whose
        `created_at` falls inside the window and whose `status` is `GENERATED` or
        `SUBMITTED`. Claims in `DRAFT` and claims in `VOIDED` contribute
        nothing."

        PRD §3.9: "A claim's `status` runs `DRAFT`, `GENERATED`, `SUBMITTED` and
        the terminal `VOIDED`; claims may be listed filtered by `order_id`,
        `customer_id`, `insurance_plan_id` and `status`."

        Design: Difficulty/compensating_invariant/allowance_invariant_releases_exactly_what_generation_consumed
        """
        scenario = setup_generated_claim(boxes_od=1, boxes_os=1)
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)

        validate_success(
            api.void_reimbursement_claim(
                scenario["claim"]["id"],
                {"voided_reason": "CUSTOMER_REQUEST"},
                CO_ALPHA_HEADERS,
            )
        )

        _, generated_meta = validate_paginated(
            api.list_reimbursement_claims(
                customer_headers,
                params={"customer_id": customer_id, "status": "GENERATED"},
            )
        )
        assert generated_meta["total_count"] == 0


class TestBoxAuthorizationReturnsAfterCancellation:
    """Cancellation frees the box authorisation the order had spent, so the
    freed boxes can be ordered again — and only up to the declared total."""

    def test_two_live_orders_consume_six_boxes(self, api):
        """PRD §2.7: "A prescription carries the parallel box ledger.
        `boxes_consumed` is the sum of `boxes_od` plus `boxes_os` over every
        order against that prescription whose `fulfillment_state` is not
        `CANCELLED`; this is the box invariant, **INV_BOXES**."

        Design: Difficulty/compensating_invariant/box_authorization_ledger_returns_after_cancellation
        """
        scenario = _prescription_with_two_orders()
        customer_id = scenario["customer"]["id"]

        prescription = validate_success(
            api.get_prescription(
                scenario["prescription"]["id"], make_customer_headers(customer_id)
            )
        )
        assert prescription["boxes_consumed"] == 6
        assert prescription["boxes_authorized_total"] == 24

    def test_cancellation_frees_the_boxes_for_reuse(self, api):
        """PRD §3.7: "The prescription's `boxes_consumed` is reduced by that
        order's `boxes_od` plus `boxes_os`, freeing the authorisation for reuse."

        PRD §2.7: "A prescription carries the parallel box ledger.
        `boxes_consumed` is the sum of `boxes_od` plus `boxes_os` over every
        order against that prescription whose `fulfillment_state` is not
        `CANCELLED`; this is the box invariant, **INV_BOXES**."

        PRD §3.5: "And the box ledger must have room: the prescription's
        `boxes_consumed` plus the requested `boxes_od` plus `boxes_os` must not
        exceed its `boxes_authorized_total`, or the order is refused with
        `ERR_BOX_AUTHORIZATION_EXCEEDED`."

        Design: Difficulty/compensating_invariant/box_authorization_ledger_returns_after_cancellation
        """
        scenario = _prescription_with_two_orders()
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)
        prescription_id = scenario["prescription"]["id"]

        before = validate_success(
            api.get_prescription(prescription_id, customer_headers)
        )
        assert before["boxes_consumed"] == 6

        validate_success(
            api.cancel_order(
                scenario["drop_order"]["id"],
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                customer_headers,
            )
        )

        after = validate_success(api.get_prescription(prescription_id, customer_headers))
        assert after["boxes_consumed"] == 2

        validate_success(
            api.create_order(
                create_order_payload(
                    customer_id, prescription_id, scenario["product"]["id"], 11, 11
                ),
                customer_headers,
            ),
            201,
        )

        exhausted = validate_success(
            api.get_prescription(prescription_id, customer_headers)
        )
        assert exhausted["boxes_consumed"] == 24

    def test_exhausted_authorization_refuses_one_more_box(self, api):
        """PRD §3.5: "And the box ledger must have room: the prescription's
        `boxes_consumed` plus the requested `boxes_od` plus `boxes_os` must not
        exceed its `boxes_authorized_total`, or the order is refused with
        `ERR_BOX_AUTHORIZATION_EXCEEDED`."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`. This equality is the money invariant,
        **INV_MONEY**, and it must hold after every cancellation, settlement and
        cascade."

        Design: Difficulty/compensating_invariant/box_authorization_ledger_returns_after_cancellation
        """
        scenario = _prescription_with_two_orders()
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)
        prescription_id = scenario["prescription"]["id"]
        product_id = scenario["product"]["id"]

        validate_success(
            api.cancel_order(
                scenario["drop_order"]["id"],
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                customer_headers,
            )
        )
        validate_success(
            api.create_order(
                create_order_payload(
                    customer_id, prescription_id, product_id, 11, 11
                ),
                customer_headers,
            ),
            201,
        )

        validate_error(
            api.create_order(
                create_order_payload(customer_id, prescription_id, product_id, 1, 0),
                customer_headers,
            ),
            ApiErrorId.ERR_BOX_AUTHORIZATION_EXCEEDED,
        )

        ledger = validate_success(
            api.get_customer_ledger(customer_id, customer_headers)
        )
        assert ledger["net_cash_position_cents"] == 76800
