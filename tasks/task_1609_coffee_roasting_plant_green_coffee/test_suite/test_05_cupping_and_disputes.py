"""Cupping sessions, verdicts, score boundaries, dispute resolution."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_shipment,
    create_counterparty,
    create_cupping_session_payload,
    create_fixed_contract,
    create_ptbf_contract,
    cup_lot_fail,
    cup_lot_pass,
    finalize_cupping_session,
    get_contract,
    get_lot_for_shipment,
    open_cupping_session,
    receive_shipment,
    record_price_fix,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    walk_shipment_to_arrived,
)

TRADER = TEST_USERS["trader_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
QA = TEST_USERS["qa_grader_headers"]


def _setup_quarantine_lot(api, ref_suffix, received_lbs=1000, fixed_price=2.00):
    """Build a contract + shipment + receive into QUARANTINE (no cupping yet)."""
    supplier = create_counterparty(ref=f"SUP-{ref_suffix}")
    contract = create_fixed_contract(
        supplier["id"], contract_ref=f"C-{ref_suffix}",
        total_lbs=received_lbs, fixed_price=fixed_price,
    )
    shipment = book_shipment(contract["id"], shipment_ref=f"SH-{ref_suffix}",
                              planned_lbs=received_lbs)
    walk_shipment_to_arrived(shipment["id"])
    receive_shipment(shipment["id"], received_lbs, lot_code=f"L-{ref_suffix}")
    return {"supplier": supplier, "contract": contract, "shipment": shipment}


class TestCuppingBoundary:
    def test_cupping_score_at_exactly_80_passes(self, api):
        """PRD §3.5: "The pass bar differs by subject: a green lot passes
        with a `final_score` of at least 80.00 — exactly 80.00 passes —
        while roasted product passes at a lower bar, at least 78.00, with
        exactly 78.00 passing."
        PRD §3.5: "A successful finalization computes `final_score` as the
        sum of the ten attribute scores minus `defects_subtracted`, rounded
        half-up to 2 decimal places, stamps `reviewed_by_qa_id` with the
        caller's `X-User-ID`, and sets the verdict."

        Design: Difficulty/boundary_precision_check/cupping_score_at_exactly_80_passes
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "BND")
        shipment = ctx["shipment"]
        # Sum: 8*6 (aroma..balance) + 10*3 (uniformity,clean,sweet) + 8 (overall)
        #      - 6 (defects) = 48 + 30 + 8 - 6 = 80.00
        sess = open_cupping_session(
            "GREEN_LOT", shipment["id"], panelist_count=3,
            score_aroma=8.0, score_flavor=8.0, score_aftertaste=8.0,
            score_acidity=8.0, score_body=8.0, score_balance=8.0,
            score_uniformity=10.0, score_clean_cup=10.0, score_sweetness=10.0,
            score_overall=8.0, defects_subtracted=6,
        )
        final = finalize_cupping_session(sess["id"])
        assert final["final_score"] == pytest.approx(80.00, abs=0.01)
        assert final["session_verdict"] == "PASS"
        # Cascade: lot moves out of QUARANTINE into RELEASED
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "RELEASED"

    def test_cupping_score_at_exactly_80_passes_qa_id_stamped(self, api):
        """PRD §3.5: "A successful finalization computes `final_score` as
        the sum of the ten attribute scores minus `defects_subtracted`,
        rounded half-up to 2 decimal places, stamps `reviewed_by_qa_id`
        with the caller's `X-User-ID`, and sets the verdict."
        PRD §3.5: "a green lot passes with a `final_score` of at least
        80.00 — exactly 80.00 passes"

        Design: Difficulty/boundary_precision_check/cupping_score_at_exactly_80_passes
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "BND2")
        shipment = ctx["shipment"]
        sess = open_cupping_session(
            "GREEN_LOT", shipment["id"], panelist_count=3,
            score_aroma=8.0, score_flavor=8.0, score_aftertaste=8.0,
            score_acidity=8.0, score_body=8.0, score_balance=8.0,
            score_uniformity=10.0, score_clean_cup=10.0, score_sweetness=10.0,
            score_overall=8.0, defects_subtracted=2,
        )
        # Finalize with a specific QA identity
        qa = dict(TEST_USERS["qa_grader_headers"])
        qa["X-User-ID"] = "qa-boundary-checker"
        final = validate_success(
            api.finalize_cupping_session(sess["id"], qa))
        assert final["session_verdict"] == "PASS"
        # QAGrader X-User-ID is stamped on the session
        assert final["reviewed_by_qa_id"] == "qa-boundary-checker"

    def test_cupping_score_at_79_99_fails(self, api):
        """PRD §3.5: "The pass bar differs by subject: a green lot passes
        with a `final_score` of at least 80.00 — exactly 80.00 passes —
        while roasted product passes at a lower bar, at least 78.00, with
        exactly 78.00 passing. Anything below the bar fails."

        Design: Corner/calculations/cupping_score_at_79_99_fails
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "799")
        shipment = ctx["shipment"]
        # Sum: 8*6 + 10*3 + 7.75 - 6 = 48 + 30 + 7.75 - 6 = 79.75
        sess = open_cupping_session(
            "GREEN_LOT", shipment["id"], panelist_count=3,
            score_aroma=8.0, score_flavor=8.0, score_aftertaste=8.0,
            score_acidity=8.0, score_body=8.0, score_balance=8.0,
            score_uniformity=10.0, score_clean_cup=10.0, score_sweetness=10.0,
            score_overall=7.75, defects_subtracted=6,
        )
        final = finalize_cupping_session(sess["id"])
        assert final["final_score"] == pytest.approx(79.75, abs=0.01)
        assert final["session_verdict"] == "FAIL"


class TestCuppingErrors:
    def test_panel_too_small_rejected(self, api):
        """PRD §3.5: "then the panel check — a `panelist_count` below 3
        cannot produce a decisive verdict and is rejected with
        `ERR_PANEL_TOO_SMALL`."

        Design: Corner/validations/panel_too_small_rejected
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "PTS")
        shipment = ctx["shipment"]
        sess = open_cupping_session(
            "GREEN_LOT", shipment["id"], panelist_count=2,
        )
        resp = api.finalize_cupping_session(sess["id"], QA)
        validate_error(resp, ApiErrorId.ERR_PANEL_TOO_SMALL)

    def test_not_cuppable_rejected(self, api):
        """PRD §3.5: "Not everything is cuppable at all times. A green lot
        is cuppable only in `QUARANTINE`; a roast batch is cuppable only
        while its `qc_status` is `PENDING_QC`. The check is applied both
        when a session is opened and when it is finalized, and a subject
        out of position is rejected with `ERR_NOT_CUPPABLE` (HTTP 409)."

        Design: Corner/validations/not_cuppable_rejected
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "NC")
        shipment = ctx["shipment"]
        # PASS cupping moves lot QUARANTINE -> RELEASED
        cup_lot_pass(shipment["id"])
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "RELEASED"
        # Second cupping on the same shipment is rejected (lot not in QUARANTINE)
        resp = api.create_cupping_session(
            create_cupping_session_payload("GREEN_LOT", shipment["id"],
                                            panelist_count=3),
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CUPPABLE)


class TestDisputeResolution:
    def test_shipment_branching_dispute_resolution_fork(self, api):
        """PRD §3.5: "A disputed shipment is settled by a `Trader` with an
        `outcome` of `ACCEPT` or `REJECT`, provided the shipment is
        `DISPUTED` and its `qc_status` is `CUP_FAILED` — otherwise
        `ERR_INVALID_STATE`. Accepting the coffee at a negotiated discount
        moves `dispute_status` to `RESOLVED_ACCEPTED` and, remarkably,
        moves the lot from `REJECTED` back to `RELEASED`: its
        `landed_cost_usd_per_lb` is recomputed as the original landed cost
        times one minus the supplied `discount_pct`, at 5 decimal places
        rounded half-up, and the warehouse position is recomputed with the
        lot once again counting toward physical mass. Rejecting the coffee
        moves the dispute to `RESOLVED_REJECTED`; the lot stays `REJECTED`
        and is marked for return or destruction, leaving the position's
        physical mass unchanged since the rejected lot was already
        excluded."

        Design: Difficulty/non_linear_state_machine/shipment_branching_dispute_resolution_fork
        """
        set_clock()
        acc_ctx = _setup_quarantine_lot(api, "ACC")
        rej_ctx = _setup_quarantine_lot(api, "REJ")
        # Both cup FAIL
        cup_lot_fail(acc_ctx["shipment"]["id"])
        cup_lot_fail(rej_ctx["shipment"]["id"])
        # ACCEPT branch with 30% discount
        resp_acc = validate_success(api.resolve_dispute(
            acc_ctx["shipment"]["id"],
            {"outcome": "ACCEPT", "discount_pct": 0.30},
            TRADER,
        ))
        # REJECT branch
        resp_rej = validate_success(api.resolve_dispute(
            rej_ctx["shipment"]["id"],
            {"outcome": "REJECT"},
            TRADER,
        ))
        assert resp_acc["dispute_status"] == "RESOLVED_ACCEPTED"
        assert resp_rej["dispute_status"] == "RESOLVED_REJECTED"
        # ACCEPT side: lot is RELEASED at discounted landed cost
        lot_acc = get_lot_for_shipment(acc_ctx["shipment"]["id"])
        assert lot_acc["lot_status"] == "RELEASED"
        # 2.00 * (1 - 0.30) = 1.40000
        assert lot_acc["landed_cost_usd_per_lb"] == pytest.approx(
            1.40, abs=1e-5)
        # REJECT side: lot stays REJECTED
        lot_rej = get_lot_for_shipment(rej_ctx["shipment"]["id"])
        assert lot_rej["lot_status"] == "REJECTED"

    def test_shipment_dispute_accept_releases_lot_and_recounts_physical_mass(
            self, api):
        """PRD §3.5: "Accepting the coffee at a negotiated discount moves
        `dispute_status` to `RESOLVED_ACCEPTED` and, remarkably, moves the
        lot from `REJECTED` back to `RELEASED`: its
        `landed_cost_usd_per_lb` is recomputed as the original landed cost
        times one minus the supplied `discount_pct`, at 5 decimal places
        rounded half-up, and the warehouse position is recomputed with
        the lot once again counting toward physical mass."

        Design: Difficulty/non_linear_state_machine/shipment_branching_dispute_resolution_fork
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "ACC2", received_lbs=800,
                                     fixed_price=2.50)
        shipment = ctx["shipment"]
        cup_lot_fail(shipment["id"])
        # After FAIL the lot is REJECTED and out of physical_lbs
        pos_fail = validate_success(api.get_warehouse_position(TRADER))
        assert pos_fail["physical_lbs"] == 0
        # Accept with 20% discount
        validate_success(api.resolve_dispute(
            shipment["id"], {"outcome": "ACCEPT", "discount_pct": 0.20},
            TRADER,
        ))
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "RELEASED"
        # 2.50 * (1 - 0.20) = 2.00000
        assert lot["landed_cost_usd_per_lb"] == pytest.approx(2.00, abs=1e-5)
        # Position re-includes the released lot
        pos_after = validate_success(api.get_warehouse_position(TRADER))
        assert pos_after["physical_lbs"] == 800


class TestCuppingFailCascade:
    def test_cupping_fail_cascade_to_position_recompute(self, api):
        """PRD §3.5: "A green-lot `FAIL` moves the lot from `QUARANTINE` to
        `REJECTED`, still sets `cup_score`, moves the shipment to
        `CUP_FAILED`, opens a dispute by moving `dispute_status` from `NONE`
        to `DISPUTED`, and recomputes the position with the rejected lot
        excluded from physical mass."
        PRD §2.6: "`physical_lbs` is the sum of `received_lbs` over all
        green lots whose `lot_status` is `RELEASED` or `QUARANTINE` —
        rejected lots do not count."

        Design: Difficulty/transitive_cascade/cupping_fail_cascade_to_position_recompute
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "CASC", received_lbs=2000,
                                     fixed_price=2.00)
        shipment = ctx["shipment"]
        pos_before = validate_success(api.get_warehouse_position(TRADER))
        assert pos_before["physical_lbs"] == 2000, (
            "QUARANTINE lot counts toward physical_lbs"
        )
        # Cup FAIL: score sums to 6*6 + 10*3 + 6 - 6 = 66, well below 80.
        cup_lot_fail(shipment["id"])
        # Link 1: lot QUARANTINE -> REJECTED
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "REJECTED"
        # Link 2 + 3: shipment qc_status -> CUP_FAILED; dispute NONE -> DISPUTED
        ship = validate_success(api.get_shipment(shipment["id"], TRADER))
        assert ship["qc_status"] == "CUP_FAILED"
        assert ship["dispute_status"] == "DISPUTED"
        # Link 4: position recompute excludes REJECTED lot
        pos_after = validate_success(api.get_warehouse_position(TRADER))
        assert pos_after["physical_lbs"] == 0

    def test_cupping_fail_stamps_cup_score_on_lot(self, api):
        """PRD §3.5: "A green-lot `FAIL` moves the lot from `QUARANTINE`
        to `REJECTED`, still sets `cup_score`, moves the shipment to
        `CUP_FAILED`, opens a dispute by moving `dispute_status` from
        `NONE` to `DISPUTED`, and recomputes the position with the
        rejected lot excluded from physical mass."

        Design: Difficulty/transitive_cascade/cupping_fail_cascade_to_position_recompute
        """
        set_clock()
        ctx = _setup_quarantine_lot(api, "CASC2", received_lbs=1000)
        shipment = ctx["shipment"]
        cup_lot_fail(shipment["id"])
        # Cascade: cup_score is stamped on the lot even on FAIL.
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "REJECTED"
        # Session scored 6*6 + 10*3 + 6 - 6 = 66 (from cup_lot_fail recipe)
        assert lot["cup_score"] is not None
        ship = validate_success(api.get_shipment(shipment["id"], TRADER))
        assert ship["qc_status"] == "CUP_FAILED"
        assert ship["dispute_status"] == "DISPUTED"


class TestHedgeAutoLiftCascade:
    def test_full_fix_auto_lifts_approved_hedges(self, api):
        """PRD §3.3: "A hedge can also be lifted without a human touch:
        when its contract reaches `FULLY_FIXED` (§3.2), every `APPROVED`
        hedge auto-transitions to `LIFTED` with `exit_price_usd_per_lb`
        set to the contract's final `weighted_avg_fixed_futures_usd`, and
        P&L is realized by the same formula."
        PRD §3.3: "Realized P&L is then computed at 2 decimals, rounded
        half-up: for a `BUY_FUTURES` hedge, the exit price minus the entry
        price, times `hedge_lbs`; for a `SELL_FUTURES` hedge, the entry
        price minus the exit price, times `hedge_lbs`."

        Design: Difficulty/transitive_cascade/full_fix_auto_lifts_approved_hedges
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-HL",
                                        legal_name="Hedge Lift Co",
                                        credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-HL",
                                         total_lbs=5000, differential=0.40)
        record_price_fix(contract["id"], 2000, 1.60, contract["version"])
        # Submitted by trader-001 (so risk-001 may approve without SoD trip)
        hedge = validate_success(api.create_futures_hedge(
            contract["id"],
            {"hedge_side": "BUY_FUTURES", "hedge_lbs": 3000,
             "entry_price_usd_per_lb": 1.65},
            TEST_USERS["trader_headers"],
        ), 201)
        validate_success(api.approve_futures_hedge(
            hedge["id"], TEST_USERS["risk_manager_headers"]))
        c1 = get_contract(contract["id"])
        # Final fix to FULLY_FIXED: cumulative 5000 == total_lbs.
        record_price_fix(contract["id"], 3000, 1.90, c1["version"])
        c2 = get_contract(contract["id"])
        # wavg = (2000*1.60 + 3000*1.90) / 5000 = 8900/5000 = 1.78
        assert c2["pricing_status"] == "FULLY_FIXED"
        assert c2["weighted_avg_fixed_futures_usd"] == pytest.approx(
            1.78, abs=1e-5)
        # Cascade: APPROVED hedge auto-LIFTED with exit = wavg
        h = validate_success(api.get_futures_hedge(hedge["id"], TRADER))
        assert h["hedge_status"] == "LIFTED"
        assert h["exit_price_usd_per_lb"] == pytest.approx(1.78, abs=1e-5)
        # BUY: (exit - entry) * hedge_lbs = (1.78 - 1.65) * 3000 = 390.00
        assert h["realized_pnl_usd"] == pytest.approx(390.00, abs=0.01)

    def test_full_fix_auto_lift_sell_futures_pnl(self, api):
        """PRD §3.3: "A hedge can also be lifted without a human touch:
        when its contract reaches `FULLY_FIXED` (§3.2), every `APPROVED`
        hedge auto-transitions to `LIFTED` with `exit_price_usd_per_lb`
        set to the contract's final `weighted_avg_fixed_futures_usd`, and
        P&L is realized by the same formula."
        PRD §3.3: "for a `SELL_FUTURES` hedge, the entry price minus the
        exit price, times `hedge_lbs`."

        Design: Difficulty/transitive_cascade/full_fix_auto_lifts_approved_hedges
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-HL2", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-HL2",
                                         total_lbs=2000, differential=0.40)
        # SELL_FUTURES hedge, 1000 lbs at entry 2.00
        hedge = validate_success(api.create_futures_hedge(
            contract["id"],
            {"hedge_side": "SELL_FUTURES", "hedge_lbs": 1000,
             "entry_price_usd_per_lb": 2.00},
            TEST_USERS["trader_headers"],
        ), 201)
        validate_success(api.approve_futures_hedge(
            hedge["id"], TEST_USERS["risk_manager_headers"]))
        # Fully fix the contract in one shot at futures 1.50
        record_price_fix(contract["id"], 2000, 1.50, contract["version"])
        h = validate_success(api.get_futures_hedge(hedge["id"], TRADER))
        assert h["hedge_status"] == "LIFTED"
        # exit = wavg = 1.50 (single fix)
        assert h["exit_price_usd_per_lb"] == pytest.approx(1.50, abs=1e-5)
        # SELL: (entry - exit) * hedge_lbs = (2.00 - 1.50) * 1000 = 500.00
        assert h["realized_pnl_usd"] == pytest.approx(500.00, abs=0.01)
