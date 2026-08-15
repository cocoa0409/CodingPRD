"""State-machine transitions, preconditions, terminal-state lockdown, and the
compensating actions (death-loss void, invoice void) across the lot lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_pen,
    assign_ration,
    confirm_close_out,
    create_assignment_payload,
    create_draft_close_out,
    create_feed_call_payload,
    create_health_event_payload,
    create_hedge,
    create_lot,
    create_lot_payload,
    create_owner,
    create_pen,
    create_ration,
    create_ration_assignment_payload,
    decide_claim,
    file_claim,
    get_lot,
    get_owner,
    get_pen,
    get_success_data,
    list_lot_close_outs,
    make_claims_adjuster_headers,
    make_claims_treasurer_headers,
    market_lot,
    offset_hedge,
    post_first_feed_call,
    record_death_loss,
    set_clock,
    setup_closed_out_lot,
    setup_lot_with_assignment,
    ship_lot,
    suspend_owner,
    validate_error,
    validate_success,
)

FYM = TEST_USERS["feedyard_manager_headers"]
FM = TEST_USERS["feed_manager_headers"]
CHT = TEST_USERS["cattle_health_tech_headers"]
RM = TEST_USERS["risk_manager_headers"]
BC = TEST_USERS["billing_clerk_headers"]
ANY = TEST_USERS["any_headers"]

STANDARD_CARCASSES_2 = [
    {"hot_carcass_weight_lbs": 763, "quality_grade": "CHOICE", "yield_grade": 2},
    {"hot_carcass_weight_lbs": 812, "quality_grade": "SELECT", "yield_grade": 4},
]


def _settled_two_heifer_lot(lot_number, owner_name):
    """Two-heifer lot fully settled: clock 2026-08-02, assigned 2 head from
    arrival, shipped 2026-08-02, close-out confirmed (invoice = 2 head-days
    x 45c = 90c). Returns the workspace dict."""
    return setup_closed_out_lot(
        owner_name=owner_name, pen_code=f"P-{lot_number}", lot_number=lot_number,
        head_count_in=2, sex_class="HEIFER", in_weight_total_lbs=1400,
        purchase_cost_cents=280000, head_assigned=2,
        clock_to="2026-08-02T00:00:00Z", ship_date="2026-08-02",
        out_weight_total_lbs=1500, grid_base_price_cents_per_cwt=18537,
        carcasses=STANDARD_CARCASSES_2,
    )


class TestLotMarketingCycle:
    def test_fail_sale_from_open_lot_rejected(self, api):
        """PRD §3.6: "Shipping and failing a sale both require the lot to be
        `MARKETED`; attempting either from another state is an
        `ERR_LOT_NOT_MARKETED` (HTTP 409)."

        Design: Corner/state_machines/fail_sale_from_open_lot_rejected
        """
        owner = create_owner(owner_name="O-SM1", billing_email="sm1@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.fail_sale_lot(lot["id"], FYM)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_MARKETED)
        assert get_lot(lot["id"])["status"] == "OPEN", "The lot is untouched"

    def test_settled_lot_terminal_lockdown_market_rejected(self, api):
        """PRD §3.7: "exact equality is allowed and pays the invoice: the invoice
        transitions `OPEN → PAID`, and the billed lot bubbles up from
        `CLOSED_OUT` to `SETTLED`, its terminal state."
        PRD §3.6: "Marketing requires the lot to be `OPEN` (`ERR_LOT_NOT_OPEN`)"

        Design: Corner/state_machines/settled_lot_terminal_lockdown_market_rejected
        """
        ws = _settled_two_heifer_lot("L-SM2", "O-SM2")
        invoice = ws["invoice"]
        assert invoice["total_cents"] == 90, (
            "2 head x 1 head-day (2026-08-01 up to but not including ship day "
            "2026-08-02) x 45 cents"
        )
        paid = get_success_data(api.pay_invoice(
            invoice["id"], {"amount_cents": 90, "payment_date": "2026-08-02"}, BC))
        assert paid["status"] == "PAID"
        assert get_lot(ws["lot"]["id"])["status"] == "SETTLED"

        resp = api.market_lot(ws["lot"]["id"], FYM)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_OPEN)


class TestPenMaintenance:
    def test_pen_maintenance_blocks_new_assignment(self, api):
        """PRD §3.2: "The pen must not be in `MAINTENANCE`
        (`ERR_PEN_IN_MAINTENANCE`)."

        Design: Corner/state_machines/pen_maintenance_blocks_new_assignment
        """
        owner = create_owner(owner_name="O-SM3", billing_email="sm3@x.com")
        pen = create_pen(pen_code="M-01", capacity_head=50)
        get_success_data(api.patch_pen(pen["id"], {"status": "MAINTENANCE"}, FYM))
        lot = create_lot(owner["id"], lot_number="L-SM3", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.create_assignment(
            create_assignment_payload(pen["id"], lot["id"], head_count=5,
                                      start_date="2026-08-01"),
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_PEN_IN_MAINTENANCE)

    def test_occupied_pen_cannot_enter_maintenance(self, api):
        """PRD §3.1: "attempting to start maintenance on an `OCCUPIED` pen is
        rejected with `ERR_PEN_OCCUPIED` (HTTP 409)"

        Design: Corner/state_machines/occupied_pen_cannot_enter_maintenance
        """
        ws = setup_lot_with_assignment(owner_name="O-SM4", pen_code="M-02",
                                       lot_number="L-SM4", head_count_in=5)
        resp = api.patch_pen(ws["pen"]["id"], {"status": "MAINTENANCE"}, FYM)
        validate_error(resp, ApiErrorId.ERR_PEN_OCCUPIED)
        assert get_pen(ws["pen"]["id"])["status"] == "OCCUPIED"


class TestOwnerAndAssignmentTransitions:
    def test_owner_patch_same_state_rejected(self, api):
        """PRD §2.9: "a status-update request that names the status the resource
        already holds, or that attempts a transition the state machine does not
        define, is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/owner_patch_same_state_rejected
        """
        owner = create_owner(owner_name="O-SM5", billing_email="sm5@x.com")
        resp = api.patch_owner(owner["id"], {"status": "ACTIVE"}, FYM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_assignment_end_twice_rejected(self, api):
        """PRD §3.2: "Ending an assignment that is no longer `ACTIVE` is rejected
        with `ERR_ASSIGNMENT_ALREADY_ENDED` (HTTP 409)."

        Design: Corner/state_machines/assignment_end_twice_rejected
        """
        ws = setup_lot_with_assignment(owner_name="O-SM6", pen_code="M-03",
                                       lot_number="L-SM6", head_count_in=5)
        assignment_id = ws["assignment"]["id"]
        get_success_data(api.end_assignment(
            assignment_id, {"end_date": "2026-08-05"}, FYM))
        resp = api.end_assignment(assignment_id, {"end_date": "2026-08-06"}, FYM)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_ALREADY_ENDED)


class TestClaimStateGuards:
    def _lot_with_filed_claim(self, lot_number, owner_name, claim_amount=100000):
        owner = create_owner(owner_name=owner_name,
                             billing_email=f"{lot_number.lower()}@x.com")
        lot = create_lot(owner["id"], lot_number=lot_number, head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        claim = file_claim(death_loss["id"], claim_amount)
        return owner, lot, death_loss, claim

    def test_claim_pay_before_decide_rejected(self, api):
        """PRD §3.5: "The claim must be `APPROVED` (`ERR_CLAIM_INVALID_STATE`
        otherwise), and `PAID` is terminal."

        Design: Corner/state_machines/claim_pay_before_decide_rejected
        """
        _, _, _, claim = self._lot_with_filed_claim("L-SM7", "O-SM7")
        assert claim["status"] == "UNDER_REVIEW"
        resp = api.pay_claim(claim["id"], make_claims_treasurer_headers("tre-1"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)

    def test_claim_second_appeal_rejected(self, api):
        """PRD §3.5: "a claim may be appealed at most once, and a second appeal
        is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/state_machines/claim_second_appeal_rejected
        """
        _, _, _, claim = self._lot_with_filed_claim("L-SM8", "O-SM8")
        cid = claim["id"]
        decide_claim(cid, "DENY", decider_user_id="adj-1")
        appealed = get_success_data(
            api.appeal_claim(cid, make_claims_adjuster_headers("adj-1")))
        assert appealed["appeal_count"] == 1
        decide_claim(cid, "DENY", decider_user_id="adj-2")
        resp = api.appeal_claim(cid, make_claims_adjuster_headers("adj-1"))
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)


class TestHedgeStateGuards:
    def test_hedge_offset_twice_rejected(self, api):
        """PRD §3.6: "A `RiskManager` offsets an `OPEN` position — offsetting
        from any other state is an `ERR_HEDGE_NOT_OPEN` (HTTP 409)"

        Design: Corner/state_machines/hedge_offset_twice_rejected
        """
        owner = create_owner(owner_name="O-SM9", billing_email="sm9@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM9", head_count_in=80,
                         in_weight_total_lbs=80000, purchase_cost_cents=9600000)
        hedge = create_hedge(lot["id"], lot["version"], quantity_contracts=1,
                             entry_price_cents_per_cwt=19000)
        offset_hedge(hedge["id"], 18900, offset_date="2026-08-01")
        resp = api.offset_hedge(
            hedge["id"], {"exit_price_cents_per_cwt": 18900,
                          "offset_date": "2026-08-01"}, RM)
        validate_error(resp, ApiErrorId.ERR_HEDGE_NOT_OPEN)


class TestRationWindowAndFeedCallGuards:
    def test_ration_window_end_not_after_start_rejected(self, api):
        """PRD §3.3: "an explicit half-open window with a `start_date`
        (inclusive) and an `end_date` (exclusive); the end must be strictly after
        the start, or the request fails with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/state_machines/ration_window_end_not_after_start_rejected
        """
        owner = create_owner(owner_name="O-SM10", billing_email="sm10@x.com")
        ration = create_ration(ration_name="R-SM10", step_level=1,
                               cost_per_ton_cents=20000)
        lot = create_lot(owner["id"], lot_number="L-SM10", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp1 = api.create_ration_assignment(
            create_ration_assignment_payload(lot["id"], ration["id"],
                                             start_date="2026-08-10",
                                             end_date="2026-08-05"),
            FM,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_DATE_RANGE)
        resp2 = api.create_ration_assignment(
            create_ration_assignment_payload(lot["id"], ration["id"],
                                             start_date="2026-08-05",
                                             end_date="2026-08-05"),
            FM,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def _pen_on_feed(self, pen_code, lot_number, owner_name):
        owner = create_owner(owner_name=owner_name,
                             billing_email=f"{lot_number.lower()}@x.com")
        pen = create_pen(pen_code=pen_code, capacity_head=50)
        ration = create_ration(ration_name=f"R-{lot_number}", step_level=1,
                               cost_per_ton_cents=20000)
        lot = create_lot(owner["id"], lot_number=lot_number, head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        assign_pen(pen["id"], lot["id"], 5)
        assign_ration(lot["id"], ration["id"], end_date="2026-08-10")
        return owner, pen, ration, lot

    def test_feed_call_same_date_rejected(self, api):
        """PRD §3.3: "the `call_date` must be strictly after the pen's latest
        existing feed call date, or the request fails with
        `ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS` (HTTP 409)."

        Design: Corner/state_machines/feed_call_same_date_rejected
        """
        _, pen, _, _ = self._pen_on_feed("F-20", "L-SM11", "O-SM11")
        post_first_feed_call(pen["id"], "2026-08-01", 20.0)
        resp = api.create_feed_call(
            {"pen_id": pen["id"], "call_date": "2026-08-01", "bunk_score": 2}, FM)
        validate_error(resp, ApiErrorId.ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS)

    def test_feed_call_base_qty_rules_enforced(self, api):
        """PRD §3.3: "If the pen has no prior feed call, `base_qty_lbs_per_head`
        is required and becomes the starting per-head quantity, and `bunk_score`
        must not be supplied. If the pen has at least one prior feed call,
        `bunk_score` — the previous-day bunk reading, one of 0, 1, 2, or 3 — is
        required and `base_qty_lbs_per_head` is forbidden. Supplying the wrong
        member of the pair for the pen's situation is an `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/feed_call_base_qty_rules_enforced
        """
        _, pen, _, _ = self._pen_on_feed("F-21", "L-SM12", "O-SM12")
        resp1 = api.create_feed_call(
            {"pen_id": pen["id"], "call_date": "2026-08-01", "bunk_score": 2}, FM)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

        first = validate_success(api.create_feed_call(
            create_feed_call_payload(pen["id"], call_date="2026-08-01",
                                     base_qty_lbs_per_head=20.0),
            FM,
        ), 201)
        assert first["qty_lbs_per_head"] == 20.0

        resp2 = api.create_feed_call(
            {"pen_id": pen["id"], "call_date": "2026-08-02", "bunk_score": 1,
             "base_qty_lbs_per_head": 20.0},
            FM,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)


class TestCloseOutGuards:
    def test_confirm_with_wrong_carcass_count_rejected(self, api):
        """PRD §3.7: "The record count must equal the lot's `head_shipped`
        exactly (`ERR_CARCASS_COUNT_MISMATCH`, HTTP 409)"

        Design: Corner/state_machines/confirm_with_wrong_carcass_count_rejected
        """
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-SM13", billing_email="sm13@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM13", sex_class="HEIFER",
                         head_count_in=2, in_weight_total_lbs=1400,
                         purchase_cost_cents=280000)
        lot = market_lot(lot["id"])
        lot = ship_lot(lot["id"], "2026-08-02", 1500)
        close_out = create_draft_close_out(lot["id"], lot["version"],
                                           grid_base_price_cents_per_cwt=18537)
        resp = api.confirm_close_out(
            close_out["id"], {"carcass_records": STANDARD_CARCASSES_2[:1]}, RM)
        validate_error(resp, ApiErrorId.ERR_CARCASS_COUNT_MISMATCH)

    def test_closeout_create_on_open_lot_rejected(self, api):
        """PRD §3.7: "The lot must be `SHIPPED` or `CLOSED_OUT`
        (`ERR_LOT_NOT_CLOSABLE`, HTTP 409)"

        Design: Corner/state_machines/closeout_create_on_open_lot_rejected
        """
        owner = create_owner(owner_name="O-SM14", billing_email="sm14@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM14", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.create_close_out(
            {"lot_id": lot["id"], "pricing_basis": "PER_CARCASS",
             "grid_base_price_cents_per_cwt": 18537,
             "expected_lot_version": lot["version"]},
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_CLOSABLE)

    def test_confirm_on_superseded_closeout_rejected(self, api):
        """PRD §3.7: "A `RiskManager` confirms a `DRAFT` close-out — any other
        state is an `ERR_CLOSE_OUT_NOT_DRAFT` (HTTP 409)"
        PRD §3.7: "any prior `CONFIRMED` close-out for the same lot becomes
        `SUPERSEDED`"

        Design: Corner/state_machines/confirm_on_superseded_closeout_rejected
        """
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-SM15", billing_email="sm15@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM15", sex_class="HEIFER",
                         head_count_in=2, in_weight_total_lbs=1400,
                         purchase_cost_cents=280000)
        lot = market_lot(lot["id"])
        lot = ship_lot(lot["id"], "2026-08-02", 1500)
        co1 = create_draft_close_out(lot["id"], lot["version"],
                                     grid_base_price_cents_per_cwt=18537)
        confirm_close_out(co1["id"], STANDARD_CARCASSES_2)
        lot_now = get_lot(lot["id"])
        co2 = create_draft_close_out(lot["id"], lot_now["version"],
                                     grid_base_price_cents_per_cwt=18537)
        confirm_close_out(co2["id"], STANDARD_CARCASSES_2)

        resp = api.confirm_close_out(
            co1["id"], {"carcass_records": STANDARD_CARCASSES_2}, RM)
        validate_error(resp, ApiErrorId.ERR_CLOSE_OUT_NOT_DRAFT)
        statuses = {co["id"]: co["status"] for co in list_lot_close_outs(lot["id"])}
        assert statuses[co1["id"]] == "SUPERSEDED"
        assert statuses[co2["id"]] == "CONFIRMED"


class TestInvoicePaymentsAndVoid:
    def test_invoice_exact_payment_settles_lot_and_overpay_rejected(self, api):
        """PRD §3.7: "Cumulative payments may never exceed the invoice's
        `total_cents` — an excess is an `ERR_OVERPAYMENT` (HTTP 422) — but exact
        equality is allowed and pays the invoice: the invoice transitions
        `OPEN → PAID`, and the billed lot bubbles up from `CLOSED_OUT` to
        `SETTLED`, its terminal state."

        Design: Corner/state_machines/invoice_exact_payment_settles_lot_and_overpay_rejected
        """
        ws = _settled_two_heifer_lot("L-SM16", "O-SM16")
        invoice = ws["invoice"]
        assert invoice["total_cents"] == 90

        resp = api.pay_invoice(
            invoice["id"], {"amount_cents": 91, "payment_date": "2026-08-02"}, BC)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        paid = validate_success(api.pay_invoice(
            invoice["id"], {"amount_cents": 90, "payment_date": "2026-08-02"}, BC))
        assert paid["status"] == "PAID", "Exact payment of the full total pays the invoice"
        assert get_lot(ws["lot"]["id"])["status"] == "SETTLED"
        assert get_owner(ws["owner"]["id"])["outstanding_balance_cents"] == 0

    def test_payment_on_void_invoice_rejected(self, api):
        """PRD §3.7: "A `BillingClerk` applies payments to an `OPEN` invoice —
        anything else is an `ERR_INVOICE_NOT_OPEN` (HTTP 409)"

        Design: Corner/state_machines/payment_on_void_invoice_rejected
        """
        ws = _settled_two_heifer_lot("L-SM17", "O-SM17")
        invoice = ws["invoice"]
        voided = get_success_data(api.void_invoice(
            invoice["id"], {"reason": "REBILL"}, BC))
        assert voided["status"] == "VOID"
        resp = api.pay_invoice(
            invoice["id"], {"amount_cents": 90, "payment_date": "2026-08-02"}, BC)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_OPEN)


class TestCrossEntityStateGates:
    def test_suspended_owner_lot_create_rejected(self, api):
        """PRD §3.1: "while an owner is `SUSPENDED`, receiving a new lot for that
        owner is rejected with `ERR_OWNER_SUSPENDED` (HTTP 409)."

        Design: Corner/state_machines/suspended_owner_lot_create_rejected
        """
        owner = create_owner(owner_name="O-SM18", billing_email="sm18@x.com")
        suspend_owner(owner["id"])
        resp = api.create_lot(
            create_lot_payload(owner["id"], lot_number="L-SM18"), FYM)
        validate_error(resp, ApiErrorId.ERR_OWNER_SUSPENDED)

    def test_market_empty_lot_rejected(self, api):
        """PRD §3.6: "Marketing requires the lot to be `OPEN` (`ERR_LOT_NOT_OPEN`)
        and to have at least one head on feed — a lot whose `head_count_current`
        is zero is rejected with `ERR_LOT_HAS_NO_HEAD` (HTTP 409)."

        Design: Corner/state_machines/market_empty_lot_rejected
        """
        owner = create_owner(owner_name="O-SM19", billing_email="sm19@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM19", head_count_in=1,
                         in_weight_total_lbs=700, purchase_cost_cents=140000)
        record_death_loss(lot["id"], loss_date="2026-08-01", head_count=1,
                          insured=False)
        assert get_lot(lot["id"])["head_count_current"] == 0
        resp = api.market_lot(lot["id"], FYM)
        validate_error(resp, ApiErrorId.ERR_LOT_HAS_NO_HEAD)

    def test_health_event_on_marketed_lot_rejected(self, api):
        """PRD §3.4: "The `CattleHealthTech` crew records a **health event**
        against a lot with the `lot_id`, a `treatment_date` that must fall within
        the lot's arrival date and the current logical date inclusive"
        PRD §3.4: "The lot must be `OPEN` (`ERR_LOT_NOT_OPEN`)."

        Design: Corner/validations/health_event_on_marketed_lot_rejected
        """
        owner = create_owner(owner_name="O-V7", billing_email="v7@x.com")
        lot = create_lot(owner["id"], lot_number="L-V7", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        market_lot(lot["id"])
        resp = api.create_health_event(
            create_health_event_payload(lot["id"], treatment_date="2026-08-01",
                                        withdrawal_days=0, head_treated=1,
                                        treatment_cost_cents=500),
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_OPEN)


class TestShipCascade:
    def test_ship_cascade_ends_assignments_and_empties_pen(self, api):
        """PRD §3.6: "A successful ship moves the lot `MARKETED → SHIPPED`, sets
        `head_shipped` to the lot's `head_count_current` at that moment, stores
        the `out_weight_total_lbs`, ends every `ACTIVE` pen assignment of the lot
        with `end_date` set to the ship date (recomputing pen occupancies, so
        pens may flip to `EMPTY`)"

        Design: Corner/state_machines/ship_cascade_ends_assignments_and_empties_pen
        """
        set_clock("2026-08-04T00:00:00Z")
        ws = setup_lot_with_assignment(owner_name="O-SM20", pen_code="S-20",
                                       lot_number="L-SM20", head_count_in=5)
        market_lot(ws["lot"]["id"])
        shipped = validate_success(api.ship_lot(
            ws["lot"]["id"], {"ship_date": "2026-08-04",
                              "out_weight_total_lbs": 3800}, FYM))
        assert shipped["status"] == "SHIPPED"
        assert shipped["head_shipped"] == 5

        assignments = validate_success(
            api.list_lot_assignments(ws["lot"]["id"], ANY))
        assert assignments[0]["status"] == "ENDED"
        assert assignments[0]["end_date"] == "2026-08-04", (
            "System end at the ship date"
        )
        pen = get_pen(ws["pen"]["id"])
        assert pen["status"] == "EMPTY"
        assert pen["current_occupancy_head"] == 0


class TestClaimPaymentRouting:
    def test_claim_pay_after_invoice_credits_owner_balance(self, api):
        """PRD §3.5: "if the lot has an `OPEN` invoice at pay time, the owner's
        `outstanding_balance_cents` is reduced directly by the approved amount,
        or by the full balance if the approved amount exceeds it; otherwise the
        approved amount is added to the lot's `insurance_credit_pending_cents`"

        Design: Corner/state_machines/claim_pay_after_invoice_credits_owner_balance
        """
        set_clock("2026-08-10T00:00:00Z")
        owner = create_owner(owner_name="O-SM21", billing_email="sm21@x.com")
        lot = create_lot(owner["id"], lot_number="L-SM21", sex_class="HEIFER",
                         head_count_in=2, in_weight_total_lbs=1400,
                         purchase_cost_cents=280000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-02",
                                       head_count=1, insured=True)
        assert death_loss["loss_value_cents"] == 140000, (
            "In-cost per head 140000 with zero accrued costs"
        )
        claim = file_claim(death_loss["id"], 50000)
        decide_claim(claim["id"], "APPROVE", decider_user_id="adj-1")

        lot = market_lot(lot["id"])
        lot = ship_lot(lot["id"], "2026-08-03", 700)
        close_out = create_draft_close_out(lot["id"], lot["version"],
                                           grid_base_price_cents_per_cwt=19000)
        confirm_close_out(close_out["id"], [
            {"hot_carcass_weight_lbs": 450, "quality_grade": "CHOICE",
             "yield_grade": 3},
        ])
        assert get_owner(owner["id"])["outstanding_balance_cents"] == 140000, (
            "The generated invoice carries the death charge only; the claim was "
            "not PAID at confirm so no credit is netted"
        )

        paid = validate_success(api.pay_claim(
            claim["id"], make_claims_treasurer_headers("tre-1")))
        assert paid["status"] == "PAID"
        assert get_owner(owner["id"])["outstanding_balance_cents"] == 90000, (
            "Direct owner-balance credit: 140000 - min(50000, 140000)"
        )


class TestDeathLossVoidGuards:
    def test_death_loss_void_with_open_claim_rejected(self, api):
        """PRD §3.4: "only while no insurance claim references it
        (`ERR_VOID_BLOCKED_BY_CLAIMS`, HTTP 409)."

        Design: Corner/state_machines/death_loss_void_with_open_claim_rejected
        """
        owner = create_owner(owner_name="O-VD1", billing_email="vd1@x.com")
        lot = create_lot(owner["id"], lot_number="L-VD1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        file_claim(death_loss["id"], 100000)
        resp = api.void_death_loss(death_loss["id"], CHT)
        validate_error(resp, ApiErrorId.ERR_VOID_BLOCKED_BY_CLAIMS)


class TestFeedCallOccupancyGate:
    def test_feed_call_on_empty_pen_rejected(self, api):
        """PRD §3.3: "The pen must currently be `OCCUPIED` — a call against a pen
        with no active assignments is rejected with `ERR_PEN_NOT_OCCUPIED`
        (HTTP 409)"

        Design: Corner/state_machines/feed_call_on_empty_pen_rejected
        """
        pen = create_pen(pen_code="E-99", capacity_head=50)
        resp = api.create_feed_call(
            create_feed_call_payload(pen["id"], call_date="2026-08-01",
                                     base_qty_lbs_per_head=20.0),
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_PEN_NOT_OCCUPIED)
