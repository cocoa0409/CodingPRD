"""Attic stock ledgers (adjust, OCC, disposition valuation variants) and the
two-step program closeout."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_attic_stock_ledger,
    complete_wave,
    create_claim,
    make_program_manager_headers,
    make_warehouse_lead_headers,
    setup_closeout_pending_scenario,
    setup_fulfilled_scenario,
    validate_error,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-7")
WL = make_warehouse_lead_headers("wl-suite-7")

GONDOLA_BOM = [{"part_number": "PN-300", "quantity": 5,
                "list_unit_cost_cents": 9000}]
HUNDRED_AT_3000 = [{"part_number": "PN-300", "quantity": 100,
                    "unit_cost_cents": 3000}]
ROUNDING_LINES = [
    {"part_number": "PN-500", "quantity": 1, "unit_cost_cents": 1025},
    {"part_number": "PN-501", "quantity": 1, "unit_cost_cents": 2075},
]
CASH_WRAP_BOM = [{"part_number": "PN-500", "quantity": 1,
                  "list_unit_cost_cents": 1025}]


def _fulfilled_ctx(name, store_code="STORE-B3", **overrides):
    """Full chain through signoff approval; returns ctx incl. the auto-created
    attic ledger (quantity_on_hand 5, unit_cost_cents 3180, ACTIVE)."""
    kwargs = dict(
        budget_total_cents=2_000_000,
        fixture_code="GONDOLA-8FT",
        bom_lines=GONDOLA_BOM,
        store_code=store_code,
        config_lines=HUNDRED_AT_3000,
        wave_capacity=200,
        estimated_install_hours=5,
    )
    kwargs.update(overrides)
    return setup_fulfilled_scenario(program_name=name, **kwargs)


class TestAtticLedgerSeeding:

    def test_attic_quantity_ceiling_on_small_kit(self):
        """PRD §3.7: "Finally, an attic stock ledger is automatically created
        for the fulfilled kit — exactly one per kit — with its `store_code`
        copied from the kit, its `quantity_on_hand` initialized to five percent
        of the kit's `total_components` rounded up to a whole unit, its
        `unit_cost_cents` set to the kit's `kit_total_cost_cents` divided by
        its `total_components` and rounded half up to a whole cent, its
        `reorder_point` defaulted to 2, its `reorder_required` evaluated
        immediately per §3.8, and its status `ACTIVE`."

        Design: Corner/calculations/attic_quantity_ceiling_on_small_kit
        """
        ctx = setup_fulfilled_scenario(
            program_name="P-CALC2",
            budget_total_cents=1_000_000,
            fixture_code="CASH-WRAP",
            bom_lines=CASH_WRAP_BOM,
            store_code="STORE-C2",
            config_lines=ROUNDING_LINES,
            wave_capacity=100,
            estimated_install_hours=2,
        )
        ledger = ctx["ledger"]
        assert_attic_stock_ledger(ledger)
        # total_components 2, kit total 3287: ceil(2 * 0.05) == 1;
        # round_half_up(3287 / 2) == 1644.
        assert ledger["quantity_on_hand"] == 1
        assert ledger["unit_cost_cents"] == 1_644
        assert ledger["kit_id"] == ctx["kit"]["id"]
        assert ledger["store_code"] == "STORE-C2"


class TestAtticAdjust:

    def test_attic_reorder_point_equality_triggers(self):
        """PRD §3.8: "The reorder flag `reorder_required` becomes true whenever
        `quantity_on_hand` falls to the `reorder_point` or below — the boundary
        is inclusive, so a quantity exactly equal to the reorder point demands
        replenishment."

        Design: Difficulty/boundary_precision_check/attic_reorder_point_equality_triggers
        """
        ctx = _fulfilled_ctx("P-BND2")
        ledger = ctx["ledger"]
        assert ledger["quantity_on_hand"] == 5
        assert ledger["reorder_point"] == 2
        assert ledger["reorder_required"] is False

        stepped = validate_success(api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -3, "reorder_point": 2,
             "expected_ledger_version": ledger["version"]},
            WL,
        ))
        assert stepped["quantity_on_hand"] == 2
        assert stepped["reorder_point"] == 2
        assert stepped["reorder_required"] is True, \
            "quantity exactly at the reorder point must demand replenishment"

        raised = validate_success(api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": 1, "expected_ledger_version": stepped["version"]},
            WL,
        ))
        assert raised["quantity_on_hand"] == 3
        assert raised["reorder_required"] is False

    def test_attic_reorder_flag_walks_down_through_boundary(self):
        """PRD §3.8: "The reorder flag `reorder_required` becomes true whenever
        `quantity_on_hand` falls to the `reorder_point` or below — the boundary
        is inclusive, so a quantity exactly equal to the reorder point demands
        replenishment."

        Design: Difficulty/boundary_precision_check/attic_reorder_point_equality_triggers
        """
        ctx = _fulfilled_ctx("P-BND2B", store_code="STORE-B4")
        ledger = ctx["ledger"]
        one_above = validate_success(api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -2, "expected_ledger_version": ledger["version"]},
            WL,
        ))
        assert one_above["quantity_on_hand"] == 3
        assert one_above["reorder_required"] is False, \
            "one unit above the reorder point stays false"
        at_point = validate_success(api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -1, "expected_ledger_version": one_above["version"]},
            WL,
        ))
        assert at_point["quantity_on_hand"] == 2
        assert at_point["reorder_required"] is True
        assert at_point["status"] == "ACTIVE"

    def test_adjust_underflow_rejected(self):
        """PRD §3.8: "The `delta` is added to `quantity_on_hand`, and the
        result may never drop below zero — an adjustment that would drive stock
        negative is rejected with `ERR_STOCK_UNDERFLOW` (HTTP 422)."

        Design: Corner/validations/adjust_underflow_rejected
        """
        ctx = _fulfilled_ctx("P-VAL9", store_code="STORE-V9")
        ledger = ctx["ledger"]
        resp = api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -99, "expected_ledger_version": ledger["version"]},
            WL,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_UNDERFLOW)
        after = validate_success(
            api_client.get_attic_stock_ledger(ledger["id"], PM))
        assert after["quantity_on_hand"] == 5, "rejected writes leave stock unchanged"
        assert after["version"] == ledger["version"], \
            "a rejected write must not bump the version"

    def test_attic_adjust_stale_version_returns_412(self):
        """PRD §2.6: "The second protected operation is `POST
        /attic-stock-ledgers/{id}/adjust`. Its request body must include
        `expected_ledger_version`, likewise non-optional, so that every
        quantity or reorder-point change builds on the latest observed ledger
        state. A mismatch with the ledger's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/attic_adjust_stale_version_returns_412
        """
        ctx = _fulfilled_ctx("P-OCC2", store_code="STORE-OCC2")
        ledger = ctx["ledger"]
        stale_version = ledger["version"]
        first = validate_success(api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -1, "expected_ledger_version": stale_version},
            WL,
        ))
        assert first["quantity_on_hand"] == 4
        assert first["version"] == stale_version + 1
        resp = api_client.adjust_attic_stock_ledger(
            ledger["id"],
            {"delta": -1, "expected_ledger_version": stale_version},
            WL,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(
            api_client.get_attic_stock_ledger(ledger["id"], PM))
        assert after["quantity_on_hand"] == 4, \
            "the stale write must not be applied"


class TestDispositionGateAndValuation:

    def test_ledger_dispose_requires_closeout_pending(self):
        """PRD §3.8: "A ledger may be disposed from either `ACTIVE` or
        `DEPLETED` (`ERR_LEDGER_INVALID_STATE` otherwise), and only while the
        program of the ledger's kit sits in `CLOSEOUT_PENDING`
        (`ERR_PROGRAM_NOT_CLOSEOUT_PENDING` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/ledger_dispose_requires_closeout_pending
        """
        ctx = _fulfilled_ctx("P-XDEP2", store_code="STORE-X2")
        resp = api_client.dispose_attic_stock_ledger(
            ctx["ledger"]["id"], {"disposition_type": "RETURN_VENDOR"}, PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_CLOSEOUT_PENDING)
        ledger_after = validate_success(
            api_client.get_attic_stock_ledger(ctx["ledger"]["id"], PM))
        assert ledger_after["status"] == "ACTIVE"
        assert ledger_after["recovery_value_cents"] is None
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["closeout_recovery_cents"] == 0

    def test_ledger_dispose_succeeds_in_closeout_pending(self):
        """PRD §3.8: "Disposition adds the computed recovery to the program's
        `closeout_recovery_cents`, stamps the ledger's `disposition_type`, and
        moves the ledger to `DISPOSED`, its terminal state."
        PRD §3.8: "under the default `PROGRAM_AVERAGE` variant the stock is
        valued at the ledger's own `unit_cost_cents` — the source kit's average
        unit cost — so the recovery is `quantity_on_hand` multiplied by
        `unit_cost_cents` multiplied by the recovery rate, rounded half up to a
        whole cent".

        Design: Difficulty/cross_entity_state_dependency/ledger_dispose_requires_closeout_pending
        """
        ctx = setup_closeout_pending_scenario(
            program_name="P-XDEP2B",
            budget_total_cents=2_000_000,
            fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM,
            store_code="STORE-X2B",
            config_lines=HUNDRED_AT_3000,
            wave_capacity=200,
            estimated_install_hours=5,
        )
        assert ctx["program"]["status"] == "CLOSEOUT_PENDING"
        disposed = validate_success(api_client.dispose_attic_stock_ledger(
            ctx["ledger"]["id"], {"disposition_type": "RETURN_VENDOR"}, PM))
        assert disposed["status"] == "DISPOSED"
        assert disposed["disposition_type"] == "RETURN_VENDOR"
        # round_half_up(5 * 3180 * 0.80) = 12720
        assert disposed["recovery_value_cents"] == 12_720
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["closeout_recovery_cents"] == 12_720

    def test_attic_valuation_program_average_vs_liquidation(self):
        """PRD §3.8: "The unit value depends on the program's
        `attic_valuation_method`: under the default `PROGRAM_AVERAGE` variant
        the stock is valued at the ledger's own `unit_cost_cents` — the source
        kit's average unit cost — so the recovery is `quantity_on_hand`
        multiplied by `unit_cost_cents` multiplied by the recovery rate,
        rounded half up to a whole cent; under the `LIQUIDATION` variant the
        stock is valued at a flat market rate of 2,500 cents per unit
        regardless of kit cost, so the recovery is `quantity_on_hand`
        multiplied by 2,500 and by the recovery rate, again rounded half up to
        a whole cent."
        PRD §3.8: "The recovery rate is eighty percent of unit value for
        `RETURN_VENDOR`, five percent for `SCRAP`, and zero for `DONATE`."

        Design: Difficulty/dual_variant_calc/attic_valuation_program_average_vs_liquidation
        """
        ctx_a = setup_closeout_pending_scenario(
            program_name="P-AVG", attic_valuation_method="PROGRAM_AVERAGE",
            budget_total_cents=2_000_000, fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM, store_code="STORE-A",
            config_lines=HUNDRED_AT_3000, wave_capacity=200,
            estimated_install_hours=4, crew_code="CREW-A",
        )
        ctx_b = setup_closeout_pending_scenario(
            program_name="P-LIQ", attic_valuation_method="LIQUIDATION",
            budget_total_cents=2_000_000, fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM, store_code="STORE-B",
            config_lines=HUNDRED_AT_3000, wave_capacity=200,
            estimated_install_hours=4, crew_code="CREW-B",
        )
        disposed_a = validate_success(api_client.dispose_attic_stock_ledger(
            ctx_a["ledger"]["id"], {"disposition_type": "RETURN_VENDOR"}, PM))
        disposed_b = validate_success(api_client.dispose_attic_stock_ledger(
            ctx_b["ledger"]["id"], {"disposition_type": "RETURN_VENDOR"}, PM))

        # Identical ledgers: 5 units at the kit-derived average of 3180.
        assert disposed_a["quantity_on_hand"] == 5
        assert disposed_a["unit_cost_cents"] == 3_180
        assert disposed_b["quantity_on_hand"] == 5
        # PROGRAM_AVERAGE: 5 * 3180 * 0.80 = 12720; LIQUIDATION: 5 * 2500 *
        # 0.80 = 10000.
        assert disposed_a["recovery_value_cents"] == 12_720
        assert disposed_b["recovery_value_cents"] == 10_000
        assert disposed_a["recovery_value_cents"] \
            != disposed_b["recovery_value_cents"]

        program_a = validate_success(
            api_client.get_rollout_program(ctx_a["program"]["id"], PM))
        program_b = validate_success(
            api_client.get_rollout_program(ctx_b["program"]["id"], PM))
        assert program_a["closeout_recovery_cents"] == 12_720
        assert program_b["closeout_recovery_cents"] == 10_000

    def test_liquidation_values_at_flat_rate_regardless_of_kit_cost(self):
        """PRD §3.8: "under the `LIQUIDATION` variant the stock is valued at a
        flat market rate of 2,500 cents per unit regardless of kit cost, so the
        recovery is `quantity_on_hand` multiplied by 2,500 and by the recovery
        rate, again rounded half up to a whole cent. The two variants diverge
        whenever the kit's average unit cost differs from 2,500 cents."

        Design: Difficulty/dual_variant_calc/attic_valuation_program_average_vs_liquidation
        """
        ctx = setup_closeout_pending_scenario(
            program_name="P-LIQ2", attic_valuation_method="LIQUIDATION",
            budget_total_cents=2_000_000, fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM, store_code="STORE-B2",
            config_lines=HUNDRED_AT_3000, wave_capacity=200,
            estimated_install_hours=4, crew_code="CREW-B2",
        )
        assert ctx["ledger"]["unit_cost_cents"] == 3_180, \
            "the kit-derived average unit cost differs from 2500"
        disposed = validate_success(api_client.dispose_attic_stock_ledger(
            ctx["ledger"]["id"], {"disposition_type": "RETURN_VENDOR"}, PM))
        # Flat 2500 market rate, not the 3180 kit average: 5*2500*0.80.
        assert disposed["recovery_value_cents"] == 10_000


class TestCloseout:

    def test_initiate_closeout_blocked_by_open_claim(self):
        """PRD §3.8: "Initiating closeout moves an `ACTIVE` program `ACTIVE →
        CLOSEOUT_PENDING` — attempting it from any other state fails with
        `ERR_PROGRAM_NOT_ACTIVE` — and is permitted only when the program's
        operational work is fully resolved: no kit of the program may remain in
        `DRAFT`, `FROZEN`, or `RELEASED`, no damage claim belonging to the
        program (reached through the claim's delivery, that delivery's kit, and
        the kit's program) may still be `OPEN`, and every production wave of
        the program must be `COMPLETE` or `CANCELLED`. Any violation blocks the
        transition with `ERR_CLOSEOUT_BLOCKED`."

        Design: Corner/validations/initiate_closeout_blocked_by_open_claim
        """
        ctx = _fulfilled_ctx("P-VAL11", store_code="STORE-V11")
        # Delivery is COMPLETE after the signoff cascade; claims may still be
        # filed against it, and this one stays OPEN.
        create_claim(ctx["delivery"]["id"], "PN-300", "DAMAGED", 1, 500)
        complete_wave(ctx["wave"]["id"])
        resp = api_client.initiate_closeout(ctx["program"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CLOSEOUT_BLOCKED)
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["status"] == "ACTIVE"

    def test_finalize_blocked_by_undisposed_stock(self):
        """PRD §3.8: "Finalization requires the program to actually be in
        `CLOSEOUT_PENDING` (`ERR_PROGRAM_NOT_CLOSEOUT_PENDING` otherwise) and
        requires every attic stock ledger of the program's kits to have reached
        `DEPLETED` or `DISPOSED`; any ledger still `ACTIVE` blocks finalization
        with `ERR_UNDISPOSED_STOCK_REMAINS`."

        Design: Corner/validations/finalize_blocked_by_undisposed_stock
        """
        ctx = setup_closeout_pending_scenario(
            program_name="P-VAL12",
            budget_total_cents=2_000_000,
            fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM,
            store_code="STORE-V12",
            config_lines=HUNDRED_AT_3000,
            wave_capacity=200,
            estimated_install_hours=5,
        )
        assert ctx["ledger"]["status"] == "ACTIVE"
        resp = api_client.finalize_closeout(ctx["program"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_UNDISPOSED_STOCK_REMAINS)
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["status"] == "CLOSEOUT_PENDING"
        assert program_after["final_reconciliation_cents"] is None

    def test_closed_program_terminal_lockdown(self):
        """PRD §3.8: "Initiating closeout moves an `ACTIVE` program `ACTIVE →
        CLOSEOUT_PENDING` — attempting it from any other state fails with
        `ERR_PROGRAM_NOT_ACTIVE` — and is permitted only when the program's
        operational work is fully resolved: no kit of the program may remain in
        `DRAFT`, `FROZEN`, or `RELEASED`, no damage claim belonging to the
        program (reached through the claim's delivery, that delivery's kit, and
        the kit's program) may still be `OPEN`, and every production wave of
        the program must be `COMPLETE` or `CANCELLED`."
        PRD §3.8: "On success the server computes the program's
        `final_reconciliation_cents` — null until this moment — as the
        program's `remaining_budget_cents` minus its `contingency_spent_cents`
        plus its `closeout_recovery_cents`."

        Design: Corner/state_machines/closed_program_terminal_lockdown
        """
        ctx = setup_closeout_pending_scenario(
            program_name="P-SM2",
            budget_total_cents=2_000_000,
            fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM,
            store_code="STORE-S2",
            config_lines=HUNDRED_AT_3000,
            wave_capacity=200,
            estimated_install_hours=5,
        )
        # Dispose as SCRAP: round_half_up(5 * 3180 * 0.05) = 795.
        disposed = validate_success(api_client.dispose_attic_stock_ledger(
            ctx["ledger"]["id"], {"disposition_type": "SCRAP"}, PM))
        assert disposed["recovery_value_cents"] == 795

        closed = validate_success(
            api_client.finalize_closeout(ctx["program"]["id"], PM))
        assert closed["status"] == "CLOSED"
        # remaining = 2000000 - 318000 (kit) - 15000 (release charge at 50%
        # utilization, tier 1.0) = 1667000; final = 1667000 - 0 + 795.
        assert closed["final_reconciliation_cents"] == 1_667_795

        resp = api_client.initiate_closeout(ctx["program"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert after["status"] == "CLOSED"
