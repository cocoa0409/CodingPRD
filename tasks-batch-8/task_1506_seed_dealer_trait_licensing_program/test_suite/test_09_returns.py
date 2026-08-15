"""Returns pipeline: window and quantity rules, untreated-only policy,
provisional vs final credit variants, rejection, and fulfillment recompute."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    complete_ticket,
    confirm_order,
    create_draft_order,
    create_inventory_lot,
    create_return_payload,
    create_treatment_option,
    get_success_data,
    schedule_delivery,
    set_clock,
    setup_delivered_order,
    setup_market,
    setup_return_repricing_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


class TestReturnWindow:
    def test_return_at_exact_window_end_allowed_then_closed(self, api):
        """PRD §2.10: "`return_window_end` is the inclusive last instant at
        which a return may be requested — a request landing exactly at that
        instant is still admissible."
        PRD §3.7: "The request must land no later than the program's
        `return_window_end` — the boundary instant itself is admissible —
        otherwise `ERR_RETURN_WINDOW_CLOSED`."

        Design: Corner/validations/return_at_exact_window_end_allowed_then_closed
        """
        ctx = setup_delivered_order(units=10)

        set_clock("2027-06-30T23:59:59Z")
        seed_return = validate_success(
            api.create_return(
                create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=2),
                SALESREP,
            ),
            expected_status=201,
        )
        assert seed_return["status"] == "REQUESTED"

        set_clock("2027-07-01T00:00:00Z")
        resp = api.create_return(
            create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=1),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED)


class TestReturnQuantityRules:
    def test_return_quantity_exceeds_then_exact_then_nothing_left(self, api):
        """PRD §3.7: "Quantity rules compare against the line's returnable
        remainder — delivered units minus units already credited back minus
        units tied up in still-in-flight returns: when that remainder is zero
        the request fails with `ERR_NOTHING_TO_RETURN`, and when the requested
        units exceed it the request fails with `ERR_RETURN_QUANTITY_EXCEEDS`."

        Design: Corner/validations/return_quantity_exceeds_then_exact_then_nothing_left
        """
        ctx = setup_delivered_order(units=40)
        set_clock("2027-06-01T00:00:00Z")

        resp = api.create_return(
            create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=41),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS)

        seed_return = validate_success(
            api.create_return(
                create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=40),
                SALESREP,
            ),
            expected_status=201,
        )
        assert seed_return["status"] == "REQUESTED", (
            "returning exactly the delivered remainder is allowed"
        )

        resp = api.create_return(
            create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=1),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_RETURN)


class TestUntreatedOnlyPolicy:
    def test_return_of_treated_line_rejected_when_untreated_only(self, api):
        """PRD §3.7: "When the program sets `returns_untreated_only`, a line
        carrying a treatment option is not returnable at all
        (`ERR_RETURN_NOT_ALLOWED_TREATED`)."

        Design: Corner/validations/return_of_treated_line_rejected_when_untreated_only
        """
        treatment = create_treatment_option(code="INOC-S", crop="SOYBEAN",
                                            adder_cents_per_unit=300)
        ctx = setup_market()
        treated_lot = create_inventory_lot(
            ctx["variety"]["id"], treatment_option_id=treatment["id"]
        )
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        line = add_line(order, ctx["variety"]["id"], 10,
                        treatment_option_id=treatment["id"])
        order = confirm_order(order["id"])
        ticket = schedule_delivery(order, line, 10)
        complete_ticket(ticket["id"])

        set_clock("2027-06-01T00:00:00Z")
        resp = api.create_return(
            create_return_payload(order["id"], line["id"], units=1), SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_ALLOWED_TREATED)


class TestReturnCreditVariants:
    def test_provisional_credit_uses_locked_unit_price(self, api):
        """PRD §3.7: "the fee base is the returned units times the line's
        `discounted_unit_price_cents`; `restocking_fee_cents` is the program's
        `return_restocking_bps` applied to that base, rounded half-up to whole
        cents; and `credit_estimate_cents` is the fee base minus the restocking
        fee — a locked per-unit estimate that ignores any volume-rebate
        consequences."

        Design: Difficulty/dual_variant_calc/return_credit_provisional_locked_price_vs_final_repriced
        """
        ctx = setup_return_repricing_scenario(return_units=200)
        approved = validate_success(api.approve_return(ctx["return"]["id"], ADMIN))
        # fee base 200 x 18000 = 3600000; fee 1000bps -> 360000
        assert approved["restocking_fee_cents"] == 360000
        assert approved["credit_estimate_cents"] == 3240000

    def test_final_credit_repriced_after_losing_rebate_tier(self, api):
        """PRD §3.7: "The final `credit_cents` reprices the whole order as if
        the returned units had never been bought: the order's totals are
        recomputed with the line's units reduced by the returned units —
        re-selecting the volume rebate tier against the post-return
        `total_units` while the locked prepay discount stays fixed and excluded
        from both sides — and the credit equals the drop in the order's
        gross-minus-rebate, minus the same restocking fee computed at approval."
        PRD §3.7: "Crediting then adds the units to the line's
        `returned_units`, subtracts `credit_cents` from the grower's
        `outstanding_balance_cents` (which may push it negative — a refund
        owed), recomputes the order's `fulfillment_status`, and marks the
        program's commission statement stale so the next recompute reflects the
        credit."

        Design: Difficulty/dual_variant_calc/return_credit_provisional_locked_price_vs_final_repriced
        """
        ctx = setup_return_repricing_scenario(return_units=200)
        get_success_data(api.approve_return(ctx["return"]["id"], ADMIN))
        get_success_data(api.receive_return(ctx["return"]["id"], ADMIN))
        credited = validate_success(api.credit_return(ctx["return"]["id"], ADMIN))
        # old gross-minus-rebate: 10800000 - 540000 = 10260000 (500-unit tier)
        # new: 400 units < 500 -> tier lost -> 7200000; delta 3060000; minus fee
        assert credited["credit_cents"] == 2700000
        assert credited["credit_cents"] != credited["credit_estimate_cents"], (
            "the lost 500-unit rebate tier makes the final credit smaller"
        )

        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["outstanding_balance_cents"] == -2700000, (
            "the order was never invoiced, so the credit drives the balance "
            "negative — a refund owed"
        )


class TestReturnFulfillmentRecompute:
    def test_fulfillment_returned_full_after_complete_return(self, api):
        """PRD §3.7: "`RETURNED_FULL` when every line with any deliveries has
        its `returned_units` equal to its `delivered_units` and at least one
        return has occurred."
        PRD §3.7: "Crediting then adds the units to the line's
        `returned_units`, subtracts `credit_cents` from the grower's
        `outstanding_balance_cents` (which may push it negative — a refund
        owed), recomputes the order's `fulfillment_status`".

        Design: Corner/state_machines/fulfillment_returned_full_after_complete_return
        """
        ctx = setup_delivered_order(units=10)
        set_clock("2027-06-01T00:00:00Z")
        seed_return = get_success_data(
            api.create_return(
                create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=10),
                SALESREP,
            )
        )
        get_success_data(api.approve_return(seed_return["id"], ADMIN))
        get_success_data(api.receive_return(seed_return["id"], ADMIN))
        credited = validate_success(api.credit_return(seed_return["id"], ADMIN))
        assert credited["status"] == "CREDITED"

        line = validate_success(api.get_order_line(ctx["line"]["id"], SALESREP))
        assert line["returned_units"] == 10
        assert line["delivered_units"] == 10
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["fulfillment_status"] == "RETURNED_FULL"


class TestReturnRejection:
    def test_return_reject_then_approve_rejected(self, api):
        """PRD §3.7: "an administrator or sales rep may reject a `REQUESTED` or
        `APPROVED` return, moving it to `REJECTED` and recording the request's
        `note` into `reject_note`."
        PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".

        Design: Corner/state_machines/return_reject_then_approve_rejected
        """
        ctx = setup_delivered_order(units=10)
        set_clock("2027-06-01T00:00:00Z")
        seed_return = get_success_data(
            api.create_return(
                create_return_payload(ctx["order"]["id"], ctx["line"]["id"], units=2),
                SALESREP,
            )
        )
        rejected = validate_success(
            api.reject_return(seed_return["id"], ADMIN, note="bags opened")
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_note"] == "bags opened"

        resp = api.approve_return(seed_return["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAdjudicationOrder:
    def _two_orders_one_delivered(self, api):
        """Order A with line ln_a (delivered) and order B with line ln_b (never
        delivered), same grower, past the return window."""
        ctx = setup_market(lot_overrides={"received_units": 2000})
        set_clock("2027-01-10T00:00:00Z")
        order_a = create_draft_order(ctx["grower"], ctx["program"])
        line_a = add_line(order_a, ctx["variety"]["id"], 10)
        order_a = confirm_order(order_a["id"])
        order_b = create_draft_order(ctx["grower"], ctx["program"])
        line_b = add_line(order_b, ctx["variety"]["id"], 10)
        order_b = confirm_order(order_b["id"])
        ticket = schedule_delivery(order_a, line_a, 10)
        complete_ticket(ticket["id"])
        set_clock("2027-07-01T00:00:00Z")  # past the 2027-06-30 return window
        return {"order_a": order_a, "line_a": line_a,
                "order_b": order_b, "line_b": line_b}

    def test_referential_mismatch_beats_temporal_window(self, api):
        """PRD §2.8: "The server does not collect failures; it evaluates checks
        in a fixed priority order and reports the **first** failure only."
        PRD §2.8: "Body references must agree with each other: an
        `order_line_id` must belong to the referenced `order_id` (otherwise
        `ERR_ORDER_LINE_MISMATCH`, HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/return_line_mismatch_referential_beats_temporal_window
        """
        ctx = self._two_orders_one_delivered(api)
        resp = api.create_return(
            create_return_payload(ctx["order_b"]["id"], ctx["line_a"]["id"], units=1),
            SALESREP,
        )
        # The line belongs to a different order AND the return window has
        # closed; referential coherence (priority 6) is reported first.
        validate_error(resp, ApiErrorId.ERR_ORDER_LINE_MISMATCH)

    def test_rejected_return_creates_no_record(self, api):
        """PRD §2.8: "Body references must agree with each other: an
        `order_line_id` must belong to the referenced `order_id` (otherwise
        `ERR_ORDER_LINE_MISMATCH`, HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/return_line_mismatch_referential_beats_temporal_window
        """
        ctx = self._two_orders_one_delivered(api)
        validate_error(
            api.create_return(
                create_return_payload(ctx["order_b"]["id"], ctx["line_a"]["id"], units=1),
                SALESREP,
            ),
            ApiErrorId.ERR_ORDER_LINE_MISMATCH,
        )
        returns, meta = validate_paginated(
            api.list_returns(SALESREP, params={"order_line_id": ctx["line_a"]["id"]})
        )
        assert meta["total_count"] == 0
        assert returns == []
