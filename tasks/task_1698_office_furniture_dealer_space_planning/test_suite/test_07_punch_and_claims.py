"""Punch/deficiency workflow and manufacturer-claim negotiation."""
from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
    AE,
    CC,
    FINANCE,
    PM,
    REP,
)


class TestPunchVerification:
    def test_punch_verify_fail_reopens_to_open(self, api):
        """PRD section 3.7: "Verification belongs to the `ClaimsCoordinator`
        and carries a `passed` flag. A failed verification returns the item to
        `OPEN`."

        Design: Corner/state_machines/punch_verify_fail_reopens_to_open
        """
        ctx = fx.setup_submitted_order()
        fx.add_punch(ctx, {"order_line_id": ctx.line["id"]})
        get_success_data(api.ready_punch_for_verify(ctx.punch["id"], PM))
        resp = api.verify_punch(ctx.punch["id"], {"passed": False}, CC)
        assert validate_success(resp)["status"] == "OPEN"

    def test_claim_requires_punch_verified_open(self, api):
        """PRD section 3.7: "a `ClaimsCoordinator` may file a manual claim
        against a `VERIFIED` punch item — filing against a punch item in any
        other state is rejected with `ERR_PUNCH_NOT_VERIFIED`." An `OPEN` item
        has not been verified.

        Design: Difficulty/cross_entity_state_dependency/claim_requires_punch_verified
        """
        ctx = fx.setup_submitted_order()
        fx.add_punch(ctx, {"order_line_id": ctx.line["id"]})
        resp = api.create_manufacturer_claim(
            {
                "punch_item_id": ctx.punch["id"],
                "claim_type": "DEFECT",
                "remedy_requested": "REPAIR",
                "claimed_amount_cents": 5_000,
            },
            CC,
        )
        validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_VERIFIED)

    def test_claim_requires_punch_verified_ready_state(self, api):
        """PRD section 3.7: "a `ClaimsCoordinator` may file a manual claim
        against a `VERIFIED` punch item — filing against a punch item in any
        other state is rejected with `ERR_PUNCH_NOT_VERIFIED`." A
        `READY_FOR_VERIFY` item is marked ready but not yet verified.

        Design: Difficulty/cross_entity_state_dependency/claim_requires_punch_verified
        """
        ctx = fx.setup_submitted_order()
        fx.add_punch(ctx, {"order_line_id": ctx.line["id"]})
        get_success_data(api.ready_punch_for_verify(ctx.punch["id"], PM))
        resp = api.create_manufacturer_claim(
            {
                "punch_item_id": ctx.punch["id"],
                "claim_type": "DEFECT",
                "remedy_requested": "REPAIR",
                "claimed_amount_cents": 5_000,
            },
            CC,
        )
        validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_VERIFIED)


class TestCriticalVerifyCascade:
    def test_punch_verify_critical_cascade_auto_claim(self, api):
        """PRD section 3.7: "A passed verification moves it to `VERIFIED` and —
        when the severity is `CRITICAL` and no manufacturer claim yet
        references the item — fires an automatic cascade: the system creates a
        `ManufacturerClaim` with `origin` `AUTO_CRITICAL_PUNCH`, `claim_type`
        `DEFECT`, `remedy_requested` `REPLACE`, a `claimed_amount_cents` equal
        to the order line's `unit_net_price_cents` times the punch item's
        `affected_units`, and status `DRAFT`".

        Design: Difficulty/transitive_cascade/punch_verify_critical_cascade
        """
        ctx = fx.setup_verified_punch(severity="CRITICAL")
        claim = fx.get_auto_claim_for_punch(ctx.punch["id"])
        line = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert claim["origin"] == "AUTO_CRITICAL_PUNCH"
        assert claim["claim_type"] == "DEFECT"
        assert claim["remedy_requested"] == "REPLACE"
        assert claim["status"] == "DRAFT"
        assert claim["claimed_amount_cents"] == line["unit_net_price_cents"] * 1

    def test_punch_verify_critical_cascade_quality_hold_gate(self, api):
        """PRD section 3.7: "that claim creation sets `quality_hold` true on
        the claim's series" and "which in turn blocks new order lines for that
        series with `ERR_SERIES_ON_QUALITY_HOLD` until a `DealerAdmin` clears
        the hold."

        Design: Difficulty/transitive_cascade/punch_verify_critical_cascade
        """
        ctx = fx.setup_verified_punch(severity="CRITICAL")
        series = validate_success(api.get_product_series(ctx.series["id"], fx.ADMIN))
        assert series["quality_hold"] is True
        order2 = fx.create_order(
            ctx.customer["id"], ctx.contract["id"], ctx.plan["id"]
        )
        resp = api.create_order_line(
            {
                "order_id": order2["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": [],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_SERIES_ON_QUALITY_HOLD)


class TestLineLinkageGates:
    def test_safety_beats_referential_on_line_create(self, api):
        """PRD section 2.8: "(5) segregation-of-duties and safety holds —
        within this group the sub-order is (5a) segregation of duties, (5b)
        series quality hold blocking new order lines, (5c) crew suspension
        blocking event create/confirm, (5d) a `BLOCKED` install posture
        blocking event start" comes before "(7) referenced-object freshness and
        linkage — within this group the sub-order is (7a) plan approval and
        plan-version freshness, (7b) typical-to-plan linkage" — a line that
        violates both the quality hold (5b) and typical-to-plan linkage (7b)
        surfaces `ERR_SERIES_ON_QUALITY_HOLD`.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_line_create
        """
        ctx = fx.setup_verified_punch(severity="CRITICAL")  # hold now set
        _plan_b, typical_b = fx.create_approved_plan(
            ctx.customer["id"], {"name": "Plan B"}, {"code": "WS-B"}
        )
        order2 = fx.create_order(
            ctx.customer["id"], ctx.contract["id"], ctx.plan["id"]
        )
        resp = api.create_order_line(
            {
                "order_id": order2["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": [],
                "typical_id": typical_b["id"],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_SERIES_ON_QUALITY_HOLD)

    def test_safety_pair_isolated_quality_hold(self, api):
        """PRD section 3.1: "while the flag is set, new order lines referencing
        the series are rejected with `ERR_SERIES_ON_QUALITY_HOLD`" — the hold
        alone, with no linkage violation, produces the same gate.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_line_create
        """
        ctx = fx.setup_verified_punch(severity="CRITICAL")
        order2 = fx.create_order(
            ctx.customer["id"], ctx.contract["id"], ctx.plan["id"]
        )
        resp = api.create_order_line(
            {
                "order_id": order2["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": [],
                "typical_id": ctx.typical["id"],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_SERIES_ON_QUALITY_HOLD)

    def test_typical_plan_mismatch_rejected(self, api):
        """PRD section 3.4: "a `typical_id` that does not belong to the order's
        space plan with `ERR_TYPICAL_PLAN_MISMATCH`".

        Design: Corner/validations/typical_plan_mismatch_rejected
        """
        ctx = fx.setup_draft_order()
        _plan_b, typical_b = fx.create_approved_plan(
            ctx.customer["id"], {"name": "Plan B"}, {"code": "WS-B"}
        )
        resp = api.create_order_line(
            {
                "order_id": ctx.order["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": [],
                "typical_id": typical_b["id"],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_TYPICAL_PLAN_MISMATCH)

    def test_series_discontinued_line_rejected(self, api):
        """PRD section 3.1: "A `DealerAdmin` may discontinue a series, moving
        it to `DISCONTINUED`, after which any attempt to add an order line
        referencing it is rejected with `ERR_SERIES_DISCONTINUED`."

        Design: Corner/validations/series_discontinued_line_rejected
        """
        ctx = fx.setup_draft_order()
        validate_success(api.discontinue_series(ctx.series["id"], fx.ADMIN))
        resp = api.create_order_line(
            {
                "order_id": ctx.order["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": [],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_SERIES_DISCONTINUED)


class TestClaimNegotiationCycle:
    def _setup_offered_claim(self, settlement=50_000):
        ctx = fx.setup_verified_punch(severity="STANDARD")
        fx.create_manual_claim(
            ctx, {"claim_type": "DEFECT", "remedy_requested": "CREDIT",
                  "claimed_amount_cents": 100_000}
        )
        fx.walk_claim_to_offered(ctx, settlement)
        return ctx

    def test_claim_negotiation_cycle_counter_clears_offer(self, api):
        """PRD section 3.7: "The `ClaimsCoordinator` may counter the offer,
        which clears the `settlement_amount_cents` and returns the claim to
        `SUBMITTED` for another round, or accept it."

        Design: Difficulty/non_linear_state_machine/claim_negotiation_cycle
        """
        ctx = self._setup_offered_claim(50_000)
        countered = validate_success(api.counter_claim(ctx.claim["id"], CC))
        assert countered["status"] == "SUBMITTED"
        assert countered.get("settlement_amount_cents") is None

    def test_claim_negotiation_cycle_second_round_settles(self, api):
        """PRD section 3.7: "Accepting a settlement moves the claim to
        `SETTLED`, records the offered amount as `settled_amount_cents`" and
        "When the remedy is `CREDIT`, the `settled_amount_cents` is added to
        the customer's `liquidation_credit_balance_cents`." The second round's
        offer (60000), not the countered first offer, is what settles.

        Design: Difficulty/non_linear_state_machine/claim_negotiation_cycle
        """
        ctx = self._setup_offered_claim(50_000)
        validate_success(api.counter_claim(ctx.claim["id"], CC))
        validate_success(api.acknowledge_claim(ctx.claim["id"], REP))
        validate_success(
            api.offer_settlement(ctx.claim["id"], {"settlement_amount_cents": 60_000}, REP)
        )
        settled = validate_success(api.accept_settlement(ctx.claim["id"], CC))
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 60_000
        customer = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert customer["liquidation_credit_balance_cents"] == 60_000


class TestSettleReplaceCascade:
    def _setup_settled_replace_claim(self, api):
        """CRITICAL verified punch -> auto REPLACE claim -> offered; settle it."""
        ctx = fx.setup_acknowledged_order()
        punch = fx.add_punch(
            ctx,
            {"order_line_id": ctx.line["id"], "severity": "CRITICAL",
             "description": "Armrest weld cracked", "affected_units": 1},
        )
        get_success_data(api.ready_punch_for_verify(punch["id"], PM))
        get_success_data(api.verify_punch(punch["id"], {"passed": True}, CC))
        ctx.punch = punch
        ctx.claim = fx.get_auto_claim_for_punch(punch["id"])
        get_success_data(api.submit_claim(ctx.claim["id"], CC))
        get_success_data(api.acknowledge_claim(ctx.claim["id"], REP))
        get_success_data(
            api.offer_settlement(ctx.claim["id"], {"settlement_amount_cents": 10_000}, REP)
        )
        return ctx

    def test_claim_settle_replace_cascade_creates_replacement_line(self, api):
        """PRD section 3.7: "Accepting a settlement moves the claim to
        `SETTLED`, records the offered amount as `settled_amount_cents`, and
        then branches on the requested remedy. When the remedy is `REPLACE`,
        the system creates a replacement `OrderLine` on the punch item's
        order" and "the claim's `replacement_order_line_id` records it."

        Design: Difficulty/transitive_cascade/claim_settle_replace_cascade
        """
        ctx = self._setup_settled_replace_claim(api)
        settled = validate_success(api.accept_settlement(ctx.claim["id"], CC))
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 10_000
        assert settled["replacement_order_line_id"]

    def test_claim_settle_replace_cascade_replacement_line_warranty_priced(self, api):
        """PRD section 3.7: "it carries the same series as the deficient line,
        a `quantity` equal to the punch item's `affected_units`,
        `is_replacement` true, warranty-zero pricing on `unit_list_price_cents`,
        `unit_net_price_cents`, and `line_total_cents`, and starts `OPEN`".

        Design: Difficulty/transitive_cascade/claim_settle_replace_cascade
        """
        ctx = self._setup_settled_replace_claim(api)
        settled = validate_success(api.accept_settlement(ctx.claim["id"], CC))
        line = validate_success(
            api.get_order_line(settled["replacement_order_line_id"], AE)
        )
        assert line["is_replacement"] is True
        assert line["series_id"] == ctx.series["id"]
        assert line["quantity"] == 1  # the punch item's affected_units
        assert line["unit_list_price_cents"] == 0
        assert line["unit_net_price_cents"] == 0
        assert line["line_total_cents"] == 0
        assert line["status"] == "OPEN"


class TestClaimTerminalAndPunchClose:
    def test_terminal_claim_denied_lockdown(self, api):
        """PRD section 3.7: "the `ManufacturerRep` may deny an `ACKNOWLEDGED`
        claim outright, moving it to `DENIED`" and "A claim may also be
        withdrawn by the `ClaimsCoordinator` from `DRAFT`, `SUBMITTED`, or
        `ACKNOWLEDGED`" — from terminal `DENIED` neither offer nor withdraw
        transitions exist (PRD section 2.8 rule 4), so both are rejected with
        ERR_INVALID_STATE (HTTP 409 per the section 5 catalogue).

        Design: Corner/state_machines/terminal_claim_denied_lockdown
        """
        ctx = fx.setup_verified_punch(severity="STANDARD")
        fx.create_manual_claim(ctx)
        get_success_data(api.submit_claim(ctx.claim["id"], CC))
        get_success_data(api.acknowledge_claim(ctx.claim["id"], REP))
        denied = validate_success(api.deny_claim(ctx.claim["id"], REP))
        assert denied["status"] == "DENIED"
        resp1 = api.offer_settlement(ctx.claim["id"], {"settlement_amount_cents": 1_000}, REP)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.withdraw_claim(ctx.claim["id"], CC)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    def test_punch_close_blocked_by_unsettled_claim(self, api):
        """PRD section 3.7: "A verified punch item is closed by a
        `ProjectManager` once every manufacturer claim referencing it has
        reached `SETTLED`, `DENIED`, or `WITHDRAWN`; a close attempted while
        any linked claim is non-terminal is rejected with
        `ERR_CLAIM_NOT_SETTLED`."

        Design: Corner/validations/punch_close_blocked_by_unsettled_claim
        """
        ctx = fx.setup_verified_punch(severity="CRITICAL")
        claim = fx.get_auto_claim_for_punch(ctx.punch["id"])
        resp = api.close_punch(ctx.punch["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLED)
        validate_success(api.withdraw_claim(claim["id"], CC))
        closed = validate_success(api.close_punch(ctx.punch["id"], PM))
        assert closed["status"] == "CLOSED"
