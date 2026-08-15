"""Deep workflow tests: cyclic state machines (lot marketing cycle, claim
appeal loop), transitive cascades (death loss, close-out confirm), validation
priority pairs, cross-entity state gates, interval-overlap semantics, and
compensating invariants (void restoration)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_pen,
    assign_ration,
    choice_carcasses,
    confirm_close_out,
    create_draft_close_out,
    create_hedge,
    create_lot,
    create_owner,
    create_pen,
    create_ration,
    decide_claim,
    file_claim,
    get_lot,
    get_owner,
    get_pen,
    get_success_data,
    list_lot_assignments,
    list_lot_invoices,
    make_claims_adjuster_headers,
    market_lot,
    market_ship_and_draft_close_out,
    offset_hedge,
    pay_claim,
    record_death_loss,
    record_health_event,
    set_clock,
    setup_closed_out_lot,
    setup_full_cost_lifecycle,
    ship_lot,
    validate_error,
    validate_success,
)

FYM = TEST_USERS["feedyard_manager_headers"]
FM = TEST_USERS["feed_manager_headers"]
RM = TEST_USERS["risk_manager_headers"]
ANY = TEST_USERS["any_headers"]

NINE_HEAD_CARCASSES = (
    [{"hot_carcass_weight_lbs": 510, "quality_grade": "PRIME", "yield_grade": 2}] * 3
    + [{"hot_carcass_weight_lbs": 495, "quality_grade": "CHOICE", "yield_grade": 3}] * 4
    + [{"hot_carcass_weight_lbs": 477, "quality_grade": "SELECT", "yield_grade": 4}] * 2
)

TWO_HEAD_CARCASSES = [
    {"hot_carcass_weight_lbs": 763, "quality_grade": "CHOICE", "yield_grade": 2},
    {"hot_carcass_weight_lbs": 812, "quality_grade": "SELECT", "yield_grade": 4},
]


class TestLotMarketingCycleLoop:
    """OPEN -> MARKETED -> OPEN -> MARKETED with no drift."""

    def _build_lot(self):
        owner = create_owner(owner_name="O-600", billing_email="o600@x.com")
        return create_lot(owner["id"], lot_number="L-601", head_count_in=5,
                          in_weight_total_lbs=3500, purchase_cost_cents=700000)

    def test_lot_market_fail_sale_cycle_statuses(self, api):
        """PRD §3.6: "Success moves the lot `OPEN → MARKETED` and increments its
        `version`. If the sale falls through, the same role can fail the sale,
        returning the lot `MARKETED → OPEN` with another version increment"

        Design: Difficulty/non_linear_state_machine/lot_market_fail_sale_cycle
        """
        lot = self._build_lot()
        s1 = market_lot(lot["id"])["status"]
        assert s1 == "MARKETED"
        s2 = get_success_data(api.fail_sale_lot(lot["id"], FYM))["status"]
        assert s2 == "OPEN", "The sale fell through: the lot cycles back"
        s3 = market_lot(lot["id"])["status"]
        assert s3 == "MARKETED", "The lot can be marketed again after the loop"

    def test_lot_market_fail_sale_cycle_no_drift(self, api):
        """PRD §3.6: "hedges, assignments, and every cost accumulator are
        untouched by the round trip, so the cycle back to feeding is clean."

        Design: Difficulty/non_linear_state_machine/lot_market_fail_sale_cycle
        """
        lot = self._build_lot()
        market_lot(lot["id"])
        get_success_data(api.fail_sale_lot(lot["id"], FYM))
        market_lot(lot["id"])
        after = get_lot(lot["id"])
        assert after["head_count_current"] == 5, "The cycle touches no head counts"
        assert after["total_deaths"] == 0
        assert after["head_shipped"] == 0
        assert after["version"] == 4, (
            "One version increment per successful transition (create + 3 moves)"
        )
        for acc in ("total_feed_cost_cents", "total_health_cost_cents",
                    "total_death_loss_cents", "total_hedge_pnl_cents",
                    "insurance_credit_pending_cents"):
            assert after[acc] == 0, f"{acc} is untouched by the marketing cycle"


class TestClaimAppealCycleLoop:
    """UNDER_REVIEW -> DENIED -> UNDER_REVIEW -> APPROVED -> PAID."""

    def _build_claim(self):
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-602", billing_email="o602@x.com")
        lot = create_lot(owner["id"], lot_number="L-602", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-02",
                                       head_count=1, insured=True)
        assert death_loss["loss_value_cents"] == 140000, (
            "In-cost 700000 / 5 head, zero accrued costs at the loss date"
        )
        claim = file_claim(death_loss["id"], 100000)
        return lot, claim

    def test_claim_appeal_cycle_statuses(self, api):
        """PRD §3.5: "A `ClaimsAdjuster` may appeal a `DENIED` claim — appealing
        from any other state is an `ERR_CLAIM_INVALID_STATE` — provided
        `appeal_count` is still below one ... A successful appeal increments
        `appeal_count` and returns the claim to `UNDER_REVIEW` for a fresh
        decision cycle."
        PRD §3.5: "when omitted it defaults to the full `claimed_amount_cents`."

        Design: Difficulty/non_linear_state_machine/insurance_claim_appeal_cycle
        """
        _, claim = self._build_claim()
        assert claim["status"] == "UNDER_REVIEW", "Initial state at filing"
        denied = decide_claim(claim["id"], "DENY", decider_user_id="adj-1")
        assert denied["status"] == "DENIED"
        appealed = get_success_data(api.appeal_claim(
            claim["id"], make_claims_adjuster_headers("adj-1")))
        assert appealed["status"] == "UNDER_REVIEW", "The appeal loop re-enters review"
        assert appealed["appeal_count"] == 1
        approved = decide_claim(claim["id"], "APPROVE", decider_user_id="adj-2",
                                approved_amount_cents=90000)
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 90000, (
            "The approved amount may be set below the claimed amount"
        )
        paid = pay_claim(claim["id"], payer_user_id="tre-1")
        assert paid["status"] == "PAID"

    def test_claim_appeal_cycle_recovery_parked_on_lot(self, api):
        """PRD §3.5: "otherwise the approved amount is added to the lot's
        `insurance_credit_pending_cents`, to be consumed when the next invoice
        is generated"

        Design: Difficulty/non_linear_state_machine/insurance_claim_appeal_cycle
        """
        lot, claim = self._build_claim()
        decide_claim(claim["id"], "DENY", decider_user_id="adj-1")
        get_success_data(api.appeal_claim(
            claim["id"], make_claims_adjuster_headers("adj-1")))
        decide_claim(claim["id"], "APPROVE", decider_user_id="adj-2",
                     approved_amount_cents=90000)
        pay_claim(claim["id"], payer_user_id="tre-1")
        assert get_lot(lot["id"])["insurance_credit_pending_cents"] == 90000, (
            "No OPEN invoice exists at pay time, so the recovery parks on the lot"
        )


class TestDeathLossCascade:
    """Death loss -> lot counters (link 1) -> assignment waterfall reduction
    (link 2) -> pen occupancy collapse (link 3)."""

    def _build_split_lot(self):
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-700", billing_email="o700@x.com")
        pen_a = create_pen(pen_code="D-01", capacity_head=50)
        pen_b = create_pen(pen_code="D-02", capacity_head=50)
        lot = create_lot(owner["id"], lot_number="L-701", head_count_in=10,
                         in_weight_total_lbs=7000, purchase_cost_cents=1400000)
        assign_pen(pen_a["id"], lot["id"], 6)
        assign_pen(pen_b["id"], lot["id"], 4)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="DRAXXIN", withdrawal_days=0,
                            head_treated=2, treatment_cost_cents=5000)
        return {"owner": owner, "pen_a": pen_a, "pen_b": pen_b, "lot": lot}

    def test_death_loss_lot_counters_and_assignment_waterfall(self, api):
        """PRD §3.4: "The dead head are allocated to the lot's `ACTIVE` pen
        assignments oldest-created first — a waterfall over `created_at`
        ascending — and the loss's `allocations` field records each step as an
        entry naming the `assignment_id` and the `head_count` absorbed from it.
        Each allocated assignment's `head_count` is reduced accordingly"
        PRD §3.4: "On the lot, `head_count_current` decreases by the lost count,
        `total_deaths` increases by it, `total_death_loss_cents` increases by
        `loss_value_cents`"

        Design: Difficulty/transitive_cascade/death_loss_cascade_lot_assignment_pen
        """
        ws = self._build_split_lot()
        loss = record_death_loss(ws["lot"]["id"], loss_date="2026-08-02",
                                 head_count=7, insured=False)
        assert loss["loss_value_cents"] == 983815, (
            "7 x (140000 in-cost/head + 545 accrued/head = (0 feed + 450 yardage "
            "+ 5000 health) / 10)"
        )
        lot = get_lot(ws["lot"]["id"])
        assert lot["head_count_current"] == 3
        assert lot["total_deaths"] == 7
        assert lot["total_death_loss_cents"] == 983815

        assignments = list_lot_assignments(ws["lot"]["id"])
        assert assignments[0]["head_count"] == 0, (
            "The oldest-created assignment absorbs the first 6 dead head"
        )
        assert assignments[1]["head_count"] == 3, "The waterfall spills 1 head on"
        alloc_by_assignment = {a["assignment_id"]: a["head_count"]
                               for a in loss["allocations"]}
        assert alloc_by_assignment == {
            assignments[0]["id"]: 6, assignments[1]["id"]: 1,
        }, "allocations records the waterfall steps"

    def test_death_loss_pen_occupancy_collapse(self, api):
        """PRD §3.4: "each affected pen's `current_occupancy_head` is recomputed,
        and a pen that falls to zero flips `OCCUPIED → EMPTY`."

        Design: Difficulty/transitive_cascade/death_loss_cascade_lot_assignment_pen
        """
        ws = self._build_split_lot()
        record_death_loss(ws["lot"]["id"], loss_date="2026-08-02", head_count=7,
                          insured=False)
        pen_a = get_pen(ws["pen_a"]["id"])
        assert pen_a["current_occupancy_head"] == 0
        assert pen_a["status"] == "EMPTY", "Occupancy collapse flips the pen"
        pen_b = get_pen(ws["pen_b"]["id"])
        assert pen_b["current_occupancy_head"] == 3
        assert pen_b["status"] == "OCCUPIED"


class TestCloseOutConfirmCascade:
    """Confirm -> CloseOut CONFIRMED and lot CLOSED_OUT (link 1) -> new OPEN
    invoice from the cost pool (link 2) -> owner balance debited (link 3)."""

    def _confirm(self):
        ws = setup_full_cost_lifecycle(owner_name="O-800", pen_code="A-03",
                                       ration_name="R1-800", lot_number="L-800")
        market_ship_and_draft_close_out(ws, "2026-08-03", 7200,
                                        grid_base_price_cents_per_cwt=19000)
        close_out = confirm_close_out(ws["close_out"]["id"], NINE_HEAD_CARCASSES)
        return ws, close_out

    def test_confirm_flips_closeout_and_lot(self, api):
        """PRD §3.7: "Confirmation then cascades in four links. First, any prior
        `CONFIRMED` close-out for the same lot becomes `SUPERSEDED`, and its
        still-`OPEN` invoice becomes `VOID` with the owner's balance compensated
        by that invoice's unpaid remainder. Second, the lot transitions `SHIPPED
        → CLOSED_OUT`."

        Design: Difficulty/transitive_cascade/closeout_confirm_cascade_closeout_lot_invoice_owner
        """
        ws, close_out = self._confirm()
        assert close_out["status"] == "CONFIRMED"
        assert get_lot(ws["lot"]["id"])["status"] == "CLOSED_OUT", (
            "The confirm flips the shipped lot"
        )

    def test_confirm_generates_invoice_and_debits_owner(self, api):
        """PRD §3.7: "Third, a new `OPEN` invoice is generated with the lines
        above, its `lot_id` and `owner_id` copied from the lot, and an
        `amount_paid_cents` of zero, consuming the lot's pending insurance
        credit. Fourth, the owner's `outstanding_balance_cents` increases by the
        new invoice's `total_cents`."

        Design: Difficulty/transitive_cascade/closeout_confirm_cascade_closeout_lot_invoice_owner
        """
        ws, _ = self._confirm()
        invoices = list_lot_invoices(ws["lot"]["id"])
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice["status"] == "OPEN"
        assert invoice["total_cents"] == 7855, (
            "2000 feed + 855 yardage + 5000 health + 140745 death - 140745 credit"
        )
        assert invoice["amount_paid_cents"] == 0
        assert get_owner(ws["owner"]["id"])["outstanding_balance_cents"] == 7855, (
            "The owner is debited by the invoice creation"
        )


class TestValidationPriorityPairs:
    """PRD §2.8 pins a fixed cascade order; the first failing check wins."""

    def _build_open_lot_with_active_withdrawal(self):
        set_clock("2026-08-05T00:00:00Z")
        owner = create_owner(owner_name="O-901", billing_email="o901@x.com")
        lot = create_lot(owner["id"], lot_number="L-901", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="BAYTRIL", withdrawal_days=30,
                            head_treated=1, treatment_cost_cents=1000)
        return lot

    def test_ship_state_precondition_beats_withdrawal_safety(self, api):
        """PRD §2.8: "Every request is screened by a fixed validation cascade,
        evaluated in the following priority order; the first failing check
        produces the response and later checks are not consulted."
        PRD §2.8: "7. **State guards.** ... 8. **Withdrawal safety.** Shipping
        requires every health event's withdrawal to have cleared by the ship
        date (`ERR_WITHDRAWAL_NOT_CLEARED`)."
        PRD §3.6: "Shipping and failing a sale both require the lot to be
        `MARKETED`; attempting either from another state is an
        `ERR_LOT_NOT_MARKETED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/ship_state_precondition_beats_withdrawal_safety
        """
        lot = self._build_open_lot_with_active_withdrawal()
        resp = api.ship_lot(lot["id"], {"ship_date": "2026-08-05",
                                        "out_weight_total_lbs": 3700}, FYM)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_MARKETED)

    def test_ship_priority_rejection_leaves_lot_untouched(self, api):
        """PRD §2.8: "the first failing check produces the response and later
        checks are not consulted."
        PRD §3.6: "Shipping and failing a sale both require the lot to be
        `MARKETED`; attempting either from another state is an
        `ERR_LOT_NOT_MARKETED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/ship_state_precondition_beats_withdrawal_safety
        """
        lot = self._build_open_lot_with_active_withdrawal()
        before = get_lot(lot["id"])
        resp = api.ship_lot(lot["id"], {"ship_date": "2026-08-05",
                                        "out_weight_total_lbs": 3700}, FYM)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_MARKETED)
        after = get_lot(lot["id"])
        assert after["status"] == "OPEN", "The doubly-violating ship is rejected"
        assert after["version"] == before["version"], "No side effects on failure"

    def _build_full_pen_and_incompatible_lot(self):
        owner = create_owner(owner_name="O-902", billing_email="o902@x.com")
        pen = create_pen(pen_code="E-01", capacity_head=5)
        lot_a = create_lot(owner["id"], lot_number="L-902", head_count_in=5,
                           in_weight_total_lbs=3500, purchase_cost_cents=700000)
        lot_b = create_lot(owner["id"], lot_number="L-903", sex_class="HEIFER",
                           head_count_in=1, in_weight_total_lbs=700,
                           purchase_cost_cents=140000)
        assign_pen(pen["id"], lot_a["id"], 5)
        return pen, lot_a, lot_b

    def test_commingle_referential_beats_capacity_temporal(self, api):
        """PRD §2.8: "9. **Referential business rules.** Commingling
        compatibility, ration step-up progression, and claim-free death-loss
        voids ... 10. **Temporal interval rules.** Pen capacity over overlapping
        days ..."
        PRD §3.2: "the commingling rule demands three compatibilities at once:
        the new lot's `sex_class` must match that of the lots already present,
        `commingle_allowed` must be `true` on both the incoming lot and every lot
        sharing the pen, and all lots sharing the pen must be on an identical
        active ration; any breach is an `ERR_COMMINGLE_RULE_VIOLATION` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/commingle_referential_beats_capacity_temporal
        """
        pen, _, lot_b = self._build_full_pen_and_incompatible_lot()
        resp = api.create_assignment(
            {"pen_id": pen["id"], "lot_id": lot_b["id"], "head_count": 1,
             "start_date": "2026-08-01"},
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_COMMINGLE_RULE_VIOLATION)

    def test_commingle_priority_rejection_leaves_pen_untouched(self, api):
        """PRD §2.8: "Every request is screened by a fixed validation cascade,
        evaluated in the following priority order; the first failing check
        produces the response and later checks are not consulted."
        PRD §2.9: "A pen's `current_occupancy_head` is always the sum of
        `head_count` over that pen's `ACTIVE` pen assignments"

        Design: Difficulty/priority_pair_validation_conflict/commingle_referential_beats_capacity_temporal
        """
        pen, _, lot_b = self._build_full_pen_and_incompatible_lot()
        before = get_pen(pen["id"])
        resp = api.create_assignment(
            {"pen_id": pen["id"], "lot_id": lot_b["id"], "head_count": 1,
             "start_date": "2026-08-01"},
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_COMMINGLE_RULE_VIOLATION)
        after = get_pen(pen["id"])
        assert after["current_occupancy_head"] == 5
        assert after["version"] == before["version"]
        assert list_lot_assignments(lot_b["id"]) == [], (
            "The rejected assignment creates nothing"
        )


class TestCrossEntityStateGates:
    """Lot x HealthEvent ship gating; CloseOut x HedgePosition confirm gating."""

    def _build_withdrawal_gated_lot(self):
        set_clock("2026-08-08T00:00:00Z")
        owner = create_owner(owner_name="O-903", billing_email="o903@x.com")
        pen = create_pen(pen_code="G-01", capacity_head=50)
        lot = create_lot(owner["id"], lot_number="L-903B", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        assign_pen(pen["id"], lot["id"], 5)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="BAYTRIL", withdrawal_days=7,
                            head_treated=1, treatment_cost_cents=1000)
        market_lot(lot["id"])
        return lot

    def test_ship_one_day_before_clear_date_rejected(self, api):
        """PRD §3.6: "the withdrawal gate must pass: every health event of the
        lot must have a `withdrawal_end_date` on or before the `ship_date`. The
        hold is half-open — shipping exactly on the clear date is allowed — and
        a violation is an `ERR_WITHDRAWAL_NOT_CLEARED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/ship_gated_by_health_withdrawal
        """
        lot = self._build_withdrawal_gated_lot()
        assert get_lot(lot["id"])["withdrawal_clear_date"] == "2026-08-08"
        resp = api.ship_lot(lot["id"], {"ship_date": "2026-08-07",
                                        "out_weight_total_lbs": 3700}, FYM)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_CLEARED)

    def test_ship_exactly_on_clear_date_allowed(self, api):
        """PRD §3.6: "The hold is half-open — shipping exactly on the clear date
        is allowed"
        PRD §3.6: "A successful ship moves the lot `MARKETED → SHIPPED`, sets
        `head_shipped` to the lot's `head_count_current` at that moment"

        Design: Difficulty/cross_entity_state_dependency/ship_gated_by_health_withdrawal
        """
        lot = self._build_withdrawal_gated_lot()
        resp = api.ship_lot(lot["id"], {"ship_date": "2026-08-07",
                                        "out_weight_total_lbs": 3700}, FYM)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_CLEARED)
        shipped = validate_success(api.ship_lot(
            lot["id"], {"ship_date": "2026-08-08", "out_weight_total_lbs": 3700},
            FYM))
        assert shipped["status"] == "SHIPPED"
        assert shipped["head_shipped"] == 5

    def _build_hedged_shipped_lot(self):
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-904", billing_email="o904@x.com")
        pen = create_pen(pen_code="G-02", capacity_head=100)
        lot = create_lot(owner["id"], lot_number="L-904", head_count_in=27,
                         in_weight_total_lbs=27000, purchase_cost_cents=3780000)
        assign_pen(pen["id"], lot["id"], 27)
        hedge = create_hedge(lot["id"], lot["version"], quantity_contracts=1,
                             entry_price_cents_per_cwt=19000)
        lot = market_lot(lot["id"])
        lot = ship_lot(lot["id"], "2026-08-02", 22950)
        close_out = create_draft_close_out(lot["id"], lot["version"],
                                           grid_base_price_cents_per_cwt=19000)
        return {"lot": lot, "hedge": hedge, "close_out": close_out}

    def test_confirm_blocked_while_hedge_open(self, api):
        """PRD §3.7: "every hedge position of the lot must be `OFFSET` or
        `EXPIRED` — confirming while any hedge is `OPEN` is an
        `ERR_ACTIVE_HEDGES_EXIST` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/closeout_confirm_gated_by_hedge_positions
        """
        ws = self._build_hedged_shipped_lot()
        resp = api.confirm_close_out(
            ws["close_out"]["id"],
            {"carcass_records": choice_carcasses(27, 620)}, RM)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_HEDGES_EXIST)

    def test_confirm_succeeds_after_offset_and_snapshots_pnl(self, api):
        """PRD §3.6: "for a `SHORT` position it is the entry price minus the exit
        price, multiplied by the 400-hundredweight contract size and the number
        of contracts"
        PRD §3.7: "`hedge_pnl_cents` snapshots the lot's `total_hedge_pnl_cents`"

        Design: Difficulty/cross_entity_state_dependency/closeout_confirm_gated_by_hedge_positions
        """
        ws = self._build_hedged_shipped_lot()
        resp = api.confirm_close_out(
            ws["close_out"]["id"],
            {"carcass_records": choice_carcasses(27, 620)}, RM)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_HEDGES_EXIST)

        offset = offset_hedge(ws["hedge"]["id"], 18900, offset_date="2026-08-02")
        assert offset["realized_pnl_cents"] == 40000, (
            "SHORT: (19000 - 18900) x 400 cwt x 1 contract"
        )
        confirmed = validate_success(api.confirm_close_out(
            ws["close_out"]["id"],
            {"carcass_records": choice_carcasses(27, 620)}, RM))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["hedge_pnl_cents"] == 40000, (
            "The close-out snapshots the lot's realized hedge P&L at confirm"
        )


class TestIntervalOverlapSemantics:
    """Pen aggregate-capacity overlap vs lot ration-window exclusivity."""

    def _build_pen_overlap_setup(self):
        owner = create_owner(owner_name="O-1010", billing_email="o1010@x.com")
        pen = create_pen(pen_code="H-01", capacity_head=10)
        ration = create_ration(ration_name="R-H", step_level=1,
                               cost_per_ton_cents=20000)
        lot_a = create_lot(owner["id"], lot_number="L-1010", head_count_in=6,
                           in_weight_total_lbs=4200, purchase_cost_cents=840000,
                           commingle_allowed=True)
        lot_b = create_lot(owner["id"], lot_number="L-1011", head_count_in=4,
                           in_weight_total_lbs=2800, purchase_cost_cents=560000,
                           commingle_allowed=True)
        lot_c = create_lot(owner["id"], lot_number="L-1012", head_count_in=1,
                           in_weight_total_lbs=700, purchase_cost_cents=140000)
        lot_d = create_lot(owner["id"], lot_number="L-1013", head_count_in=6,
                           in_weight_total_lbs=4200, purchase_cost_cents=840000,
                           commingle_allowed=True)
        for lot in (lot_a, lot_b, lot_d):
            assign_ration(lot["id"], ration["id"], end_date="2026-09-01")
        return {"pen": pen, "lot_a": lot_a, "lot_b": lot_b,
                "lot_c": lot_c, "lot_d": lot_d}

    def test_compatible_overlap_allowed_incompatible_rejected(self, api):
        """PRD §3.2: "If the pen already holds other lots, the commingling rule
        demands three compatibilities at once ... any breach is an
        `ERR_COMMINGLE_RULE_VIOLATION` (HTTP 409). Capacity is enforced day by
        day: the summed head over overlapping compatible assignments must not
        exceed the pen's `capacity_head` on any day of the overlap"

        Design: Difficulty/resource_temporal_overlap/pen_assignment_aggregate_capacity_with_zero_gap_adjacency
        """
        ws = self._build_pen_overlap_setup()
        assign_pen(ws["pen"]["id"], ws["lot_a"]["id"], 6)
        assign_pen(ws["pen"]["id"], ws["lot_b"]["id"], 4)
        assert get_pen(ws["pen"]["id"])["current_occupancy_head"] == 10, (
            "Compatible lots overlap with summed head 6 + 4 == 10 <= capacity"
        )
        resp = api.create_assignment(
            {"pen_id": ws["pen"]["id"], "lot_id": ws["lot_c"]["id"],
             "head_count": 1, "start_date": "2026-08-01"},
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_COMMINGLE_RULE_VIOLATION)

    def test_zero_gap_adjacency_is_not_overlap(self, api):
        """PRD §2.6: "date windows throughout the system are half-open: a window
        written as start-inclusive, end-exclusive contains its start date and
        does not contain its end date."
        PRD §3.2: "A `FeedyardManager` ends an assignment by supplying an
        `end_date`, the last-day-exclusive end of occupation."
        PRD §2.9: "A pen's `current_occupancy_head` is always the sum of
        `head_count` over that pen's `ACTIVE` pen assignments"

        Design: Difficulty/resource_temporal_overlap/pen_assignment_aggregate_capacity_with_zero_gap_adjacency
        """
        ws = self._build_pen_overlap_setup()
        assign_a = assign_pen(ws["pen"]["id"], ws["lot_a"]["id"], 6)
        assign_pen(ws["pen"]["id"], ws["lot_b"]["id"], 4)
        get_success_data(api.end_assignment(
            assign_a["id"], {"end_date": "2026-08-10"}, FYM))
        assign_d = validate_success(api.create_assignment(
            {"pen_id": ws["pen"]["id"], "lot_id": ws["lot_d"]["id"],
             "head_count": 6, "start_date": "2026-08-10"},
            FYM,
        ), 201)
        assert assign_d["status"] == "ACTIVE", (
            "One assignment ending 2026-08-10 and another starting 2026-08-10 do "
            "not overlap; concurrent load is 4 + 6 == 10"
        )
        assert get_pen(ws["pen"]["id"])["current_occupancy_head"] == 10, (
            "Ended assignments contribute zero to the occupancy sum"
        )

    def _build_ration_step_lots(self):
        owner = create_owner(owner_name="O-1014", billing_email="o1014@x.com")
        ration1 = create_ration(ration_name="R-S1", step_level=1,
                                cost_per_ton_cents=20000)
        ration2 = create_ration(ration_name="R-S2", step_level=2,
                                cost_per_ton_cents=22000)
        lot = create_lot(owner["id"], lot_number="L-1014", head_count_in=10,
                         in_weight_total_lbs=7000, purchase_cost_cents=1400000)
        return lot, ration1, ration2

    def test_ration_window_overlap_rejected(self, api):
        """PRD §3.3: "The window rule requires a lot's ration windows to be
        pairwise disjoint, with zero-gap adjacency — one window's `end_date`
        equal to the next window's `start_date` — explicitly allowed; an overlap
        is an `ERR_RATION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ration_window_exclusive_disjoint
        """
        lot, ration1, ration2 = self._build_ration_step_lots()
        assign_ration(lot["id"], ration1["id"], start_date="2026-08-01",
                      end_date="2026-08-15")
        resp = api.create_ration_assignment(
            {"lot_id": lot["id"], "ration_id": ration2["id"],
             "start_date": "2026-08-10", "end_date": "2026-08-20"},
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_RATION_WINDOW_OVERLAP)

    def test_ration_window_zero_gap_adjacency_allowed(self, api):
        """PRD §3.3: "The window rule requires a lot's ration windows to be
        pairwise disjoint, with zero-gap adjacency — one window's `end_date`
        equal to the next window's `start_date` — explicitly allowed"
        PRD §3.3: "every subsequent assignment to be exactly one step above the
        lot's latest assignment's step level"

        Design: Difficulty/resource_temporal_overlap/ration_window_exclusive_disjoint
        """
        lot, ration1, ration2 = self._build_ration_step_lots()
        assign_ration(lot["id"], ration1["id"], start_date="2026-08-01",
                      end_date="2026-08-15")
        adjacent = validate_success(api.create_ration_assignment(
            {"lot_id": lot["id"], "ration_id": ration2["id"],
             "start_date": "2026-08-15", "end_date": "2026-08-25"},
            FM,
        ), 201)
        assert adjacent["status"] == "ACTIVE", (
            "[2026-08-15, 2026-08-25) starts exactly at the prior window's end; "
            "step 2 == 1 + 1 satisfies the step-up rule"
        )


class TestCompensatingInvariants:
    """Forward action + compensation restore the conserved quantity exactly."""

    def _build_split_lot(self):
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-1101", billing_email="o1101@x.com")
        pen_a = create_pen(pen_code="I-01", capacity_head=50)
        pen_b = create_pen(pen_code="I-02", capacity_head=50)
        lot = create_lot(owner["id"], lot_number="L-1101", head_count_in=10,
                         in_weight_total_lbs=7000, purchase_cost_cents=1400000)
        assign_pen(pen_a["id"], lot["id"], 6)
        assign_pen(pen_b["id"], lot["id"], 4)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="DRAXXIN", withdrawal_days=0,
                            head_treated=2, treatment_cost_cents=5000)
        return {"owner": owner, "pen_a": pen_a, "pen_b": pen_b, "lot": lot}

    def test_death_loss_void_restores_head_conservation(self, api):
        """PRD §3.4: "Voiding restores every `allocations` entry's head to its
        pen assignment, recomputes each affected pen's occupancy (a pen that
        regains head flips `EMPTY → OCCUPIED`), adds the head back to the lot's
        `head_count_current`, subtracts them from `total_deaths`, subtracts
        `loss_value_cents` from `total_death_loss_cents`, recomputes the
        provisional cost of gain, and increments both the death loss's and the
        lot's `version`."

        Design: Difficulty/compensating_invariant/death_loss_void_restores_head_conservation
        """
        ws = self._build_split_lot()
        loss = record_death_loss(ws["lot"]["id"], loss_date="2026-08-02",
                                 head_count=7, insured=False)
        forward = get_lot(ws["lot"]["id"])
        assert forward["head_count_in"] == (
            forward["head_count_current"] + forward["total_deaths"]
            + forward["head_shipped"]
        )
        assert (forward["head_count_current"], forward["total_deaths"],
                forward["head_shipped"]) == (3, 7, 0)

        voided = get_success_data(api.void_death_loss(
            loss["id"], TEST_USERS["cattle_health_tech_headers"]))
        assert voided["status"] == "VOIDED"

        restored = get_lot(ws["lot"]["id"])
        assert (restored["head_count_current"], restored["total_deaths"],
                restored["head_shipped"]) == (10, 0, 0), (
            "Compensation restores the head-conservation invariant with no drift"
        )
        assert restored["total_death_loss_cents"] == 0, (
            "The loss value is fully reversed out of the cost pool"
        )

    def test_death_loss_void_restores_assignments_and_pens(self, api):
        """PRD §3.4: "Voiding restores every `allocations` entry's head to its
        pen assignment, recomputes each affected pen's occupancy (a pen that
        regains head flips `EMPTY → OCCUPIED`)"

        Design: Difficulty/compensating_invariant/death_loss_void_restores_head_conservation
        """
        ws = self._build_split_lot()
        loss = record_death_loss(ws["lot"]["id"], loss_date="2026-08-02",
                                 head_count=7, insured=False)
        get_success_data(api.void_death_loss(
            loss["id"], TEST_USERS["cattle_health_tech_headers"]))
        assignments = list_lot_assignments(ws["lot"]["id"])
        assert assignments[0]["head_count"] == 6, (
            "Allocations are restored to the same assignments they were deducted "
            "from"
        )
        assert assignments[1]["head_count"] == 4
        pen_a = get_pen(ws["pen_a"]["id"])
        assert pen_a["status"] == "OCCUPIED", "The emptied pen flips back"
        assert pen_a["current_occupancy_head"] == 6

    def _build_closed_out_two_head_lot(self):
        return setup_closed_out_lot(
            owner_name="O-1102", pen_code="P-L-1102", lot_number="L-1102",
            head_count_in=2, sex_class="HEIFER", in_weight_total_lbs=1400,
            purchase_cost_cents=280000, head_assigned=2,
            clock_to="2026-08-02T00:00:00Z", ship_date="2026-08-02",
            out_weight_total_lbs=1500, grid_base_price_cents_per_cwt=18537,
            carcasses=TWO_HEAD_CARCASSES,
        )

    def test_invoice_void_restores_owner_balance(self, api):
        """PRD §3.7: "Voiding compensates the owner by the invoice's unpaid
        remainder — `total_cents` minus `amount_paid_cents`"
        PRD §3.7: "Fourth, the owner's `outstanding_balance_cents` increases by
        the new invoice's `total_cents`."

        Design: Difficulty/compensating_invariant/invoice_void_restores_owner_balance
        """
        ws = self._build_closed_out_two_head_lot()
        invoice = ws["invoice"]
        assert invoice["total_cents"] == 90, (
            "2 head x 1 head-day ([2026-08-01, 2026-08-02)) x 45 cents"
        )
        assert get_owner(ws["owner"]["id"])["outstanding_balance_cents"] == 90, (
            "Balance equals the open invoice total after confirm"
        )
        voided = get_success_data(api.void_invoice(
            invoice["id"], {"reason": "REBILL"},
            TEST_USERS["billing_clerk_headers"]))
        assert voided["status"] == "VOID"
        assert get_owner(ws["owner"]["id"])["outstanding_balance_cents"] == 0, (
            "Compensation restores the pre-confirm balance exactly"
        )

    def test_invoice_void_leaves_lot_closed_out(self, api):
        """PRD §3.7: "Voiding compensates the owner by the invoice's unpaid
        remainder — `total_cents` minus `amount_paid_cents` — and the lot
        remains `CLOSED_OUT`; it does not revert."
        PRD §3.7: "A `BillingClerk` may instead void an `OPEN` invoice,
        optionally recording a `reason` that is stored as `void_reason`"

        Design: Difficulty/compensating_invariant/invoice_void_restores_owner_balance
        """
        ws = self._build_closed_out_two_head_lot()
        invoice = ws["invoice"]
        voided = get_success_data(api.void_invoice(
            invoice["id"], {"reason": "REBILL"},
            TEST_USERS["billing_clerk_headers"]))
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "REBILL"
        assert get_lot(ws["lot"]["id"])["status"] == "CLOSED_OUT", (
            "The lot does not revert when its invoice is voided"
        )
