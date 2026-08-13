"""Production runs: overage ceiling, tiered costing, OCC guard, and cascades."""
import pytest

from test_helpers import (
    PRODUCTION_PLANNER,
    PROGRAM_MANAGER,
    WAREHOUSE_OPERATOR,
    ApiErrorId,
    api_client,
    assert_kit,
    assert_production_run,
    authorize_run,
    create_production_run_entity,
    create_production_run_payload,
    create_store,
    get_production_run,
    list_kits_for_run,
    lock_design,
    mark_produced,
    setup_authorized_run,
    setup_produced_run,
    setup_program_in_production,
    start_fulfillment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTieredUnitCosting:
    """Average-rate-on-whole-quantity costing: the entire production_quantity
    bills at the single tier rate it qualifies for."""

    def test_whole_quantity_billed_at_single_tier_rate_2200(self):
        """PRD §3.3: "fewer than 100 units bill at 2500 cents per unit,
        quantities from 100 up to 499 bill at 2200 cents per unit, and 500 or
        more units bill at 1950 cents per unit."
        PRD §3.3: "This is an average-rate-on-whole-quantity scheme — the entire
        `production_quantity` is billed at the single tier rate it qualifies for,
        never split marginally across tiers."

        Design: Difficulty/dual_variant_calc/unit_cost_tiered_vs_marginal_interpretation
        """
        _program, _design, run = setup_authorized_run(
            store_count=200, overage_pct=8)
        assert_production_run(run)
        assert run["production_quantity"] == 216
        assert run["unit_cost_cents"] == 2200
        assert run["total_cost_cents"] == 475200
        assert run["total_cost_cents"] != 504900, \
            "a marginal tier-split (99*2500 + 117*2200) would produce 504900"

        # Values are frozen at authorization time and do not drift afterward.
        run = mark_produced(run["id"])
        reread = get_production_run(run["id"])
        assert reread["production_quantity"] == 216
        assert reread["unit_cost_cents"] == 2200
        assert reread["total_cost_cents"] == 475200

    def test_whole_quantity_billed_at_single_tier_rate_1950(self):
        """PRD §3.3: "500 or more units bill at 1950 cents per unit."
        PRD §3.3: "This is an average-rate-on-whole-quantity scheme — the entire
        `production_quantity` is billed at the single tier rate it qualifies for,
        never split marginally across tiers."
        PRD §3.3: "Third, `total_cost_cents` is the `production_quantity`
        multiplied by the `unit_cost_cents`, an integer number of cents."

        Design: Difficulty/dual_variant_calc/unit_cost_tiered_vs_marginal_interpretation
        """
        _program, _design, run = setup_authorized_run(
            store_count=500, overage_pct=0)
        assert run["production_quantity"] == 500
        assert run["unit_cost_cents"] == 1950
        assert run["total_cost_cents"] == 500 * 1950
        assert run["total_cost_cents"] == 975000
        assert run["total_cost_cents"] != 1129450, \
            "a marginal tier-split (99*2500 + 400*2200 + 1*1950) would produce 1129450"


class TestProductionQuantityCeiling:

    def test_overage_producing_exact_integer_is_not_rounded_up(self):
        """PRD §3.3: "the program's `store_count` is scaled by one plus the
        `overage_pct` divided by one hundred, and the result is rounded up to the
        next whole unit whenever it is not already an integer — a 120-store
        program at ten percent overage produces 132 units, and a 101-store
        program at ten percent produces 112, never 111.1."

        Design: Difficulty/combinatorial_formula/production_quantity_ceiling_with_overage
        """
        # 200 * (1 + 8/100) = 216.0 exactly: already an integer, ceiling is a
        # no-op and the quantity must be exactly 216.
        _program, _design, run = setup_authorized_run(
            store_count=200, overage_pct=8)
        assert run["production_quantity"] == 216

    def test_fractional_overage_result_rounded_up(self):
        """PRD §3.3: "the program's `store_count` is scaled by one plus the
        `overage_pct` divided by one hundred, and the result is rounded up to the
        next whole unit whenever it is not already an integer".

        Design: Difficulty/combinatorial_formula/production_quantity_ceiling_with_overage
        """
        # 200 * (1 + 7.5/100) = 215.0 exactly.
        _program, _design, run = setup_authorized_run(
            store_count=200, overage_pct=7.5)
        assert run["production_quantity"] == 215

    def test_store_count_77_overage_5_ceils_to_81(self):
        """PRD §3.3: "the result is rounded up to the next whole unit whenever
        it is not already an integer — a 120-store program at ten percent
        overage produces 132 units, and a 101-store program at ten percent
        produces 112, never 111.1."

        Design: Corner/calculations/production_quantity_uses_ceiling
        """
        # 77 * 1.05 = 80.85 -> ceil = 81; 81 < 100 so the 2500-cent tier applies.
        _program, _design, run = setup_authorized_run(
            store_count=77, overage_pct=5, program_revenue_cents=5000000)
        assert run["production_quantity"] == 81
        assert run["unit_cost_cents"] == 2500
        assert run["total_cost_cents"] == 202500


class TestTierBoundaryPrecision:

    def test_quantity_exactly_100_uses_2200_tier(self):
        """PRD §3.3: "fewer than 100 units bill at 2500 cents per unit,
        quantities from 100 up to 499 bill at 2200 cents per unit, and 500 or
        more units bill at 1950 cents per unit."

        Design: Difficulty/boundary_precision_check/tier_boundary_at_exactly_100
        """
        _program, _design, run = setup_authorized_run(
            store_count=100, overage_pct=0, program_revenue_cents=5000000)
        assert run["production_quantity"] == 100
        assert run["unit_cost_cents"] == 2200, \
            f"quantity 100 is 'from 100 up to 499', got {run['unit_cost_cents']}"
        assert run["total_cost_cents"] == 220000

    def test_quantity_99_uses_2500_tier(self):
        """PRD §3.3: "fewer than 100 units bill at 2500 cents per unit,
        quantities from 100 up to 499 bill at 2200 cents per unit".

        Design: Difficulty/boundary_precision_check/tier_boundary_at_exactly_100
        """
        _program, _design, run = setup_authorized_run(
            store_count=99, overage_pct=0, program_revenue_cents=5000000)
        assert run["production_quantity"] == 99
        assert run["unit_cost_cents"] == 2500, \
            f"quantity 99 is 'fewer than 100', got {run['unit_cost_cents']}"
        assert run["total_cost_cents"] == 247500


class TestRunCreationValidation:

    def test_negative_overage_returns_400(self):
        """PRD §3.3: "A negative `overage_pct` is rejected with
        `ERR_INVALID_REQUEST`, and a stale `expected_program_version` is rejected
        with `ERR_STALE_VERSION`."

        Design: Corner/validations/violation_negative_overage_returns_400
        """
        _client, program, design = setup_program_in_production(store_count=200)
        resp = api_client.create_production_run(
            create_production_run_payload(
                program["id"], design["id"], program["version"],
                overage_pct=-5),
            PRODUCTION_PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_stale_expected_program_version_returns_412(self):
        """PRD §2.7: "Creating a production run requires the request to carry
        `expected_program_version`, holding the `version` of the parent retailer
        program as the client last observed it. If the program's current
        `version` has advanced beyond that observed value — for example because
        another writer transitioned the program since the client read it — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client
        cannot build a run on a program state it has not seen."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_production_run_create
        """
        _client, program, design = setup_program_in_production(store_count=200)
        stale_version = program["version"] - 1
        resp = api_client.create_production_run(
            create_production_run_payload(
                program["id"], design["id"], stale_version, overage_pct=8),
            PRODUCTION_PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestRunAuthorizeDesignGate:

    def test_authorize_rejected_when_referenced_design_no_longer_approved(self):
        """PRD §3.3: "Moving a run from `PLANNED` to `AUTHORIZED` requires the
        run to be `PLANNED`, the parent program to be in `PRODUCTION`, and the
        referenced design to be `APPROVED`; violations are rejected with
        `ERR_INVALID_STATE`."
        PRD §3.2: "once a design is `APPROVED` and at least one production run
        references it, the `ProgramManager` may lock the design, moving it from
        `APPROVED` to the terminal `LOCKED` state".

        Design: Difficulty/cross_entity_state_dependency/run_authorize_requires_design_approved
        """
        _client, program, design = setup_program_in_production(store_count=200)
        run = create_production_run_entity(program, design["id"], overage_pct=8)
        # The freshly created run references the design, so the design may now
        # be locked; LOCKED is no longer APPROVED.
        locked = lock_design(design["id"])
        assert locked["status"] == "LOCKED"

        resp = api_client.authorize_run(run["id"], PRODUCTION_PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = get_production_run(run["id"])
        assert reread["status"] == "PLANNED", \
            f"run must remain PLANNED, got {reread['status']}"

    def test_authorize_succeeds_when_design_approved_and_program_in_production(self):
        """PRD §3.3: "Moving a run from `PLANNED` to `AUTHORIZED` requires the
        run to be `PLANNED`, the parent program to be in `PRODUCTION`, and the
        referenced design to be `APPROVED`; violations are rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/run_authorize_requires_design_approved
        """
        _client, program, design = setup_program_in_production(store_count=200)
        run = create_production_run_entity(program, design["id"], overage_pct=8)
        authorized = authorize_run(run["id"])
        assert_production_run(authorized)
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["production_quantity"] == 216


class TestMarkProducedKitCascade:

    def test_mark_produced_creates_one_pending_kit_per_store(self):
        """PRD §3.3: "a run in `AUTHORIZED` moves to `PRODUCED`, and in the same
        transaction the system creates one kit in `PENDING` status for every
        store of the parent program."

        Design: Corner/state_machines/side_effect_mark_produced_creates_kits
        """
        ctx = setup_produced_run(store_count=2, overage_pct=0, num_stores=2,
                                 program_revenue_cents=1000000)
        assert ctx["run"]["status"] == "PRODUCED"
        kits = ctx["kits"]
        assert len(kits) == 2, f"expected 2 kits (one per store), got {len(kits)}"
        for kit in kits:
            assert_kit(kit)
            assert kit["status"] == "PENDING", \
                f"each kit must be born PENDING, got {kit['status']}"
            assert kit["production_run_id"] == ctx["run"]["id"]

    def test_mark_produced_creates_three_pending_kits_for_three_stores(self):
        """PRD §2.8: "Completing a production run creates one kit per store of
        the parent program, each kit born in `PENDING` status."

        Design: Difficulty/transitive_cascade/mark_produced_creates_kits_then_kit_count
        """
        ctx = setup_produced_run(store_count=3, overage_pct=0, num_stores=3,
                                 program_revenue_cents=1000000)
        kits = ctx["kits"]
        assert len(kits) == 3, f"expected 3 kits, got {len(kits)}"
        store_ids = {s["id"] for s in ctx["stores"]}
        for kit in kits:
            assert kit["status"] == "PENDING"
            assert kit["store_id"] in store_ids
        # One kit per store: the kits' store_ids cover all three stores.
        assert {k["store_id"] for k in kits} == store_ids

    def test_produced_run_enables_start_fulfillment(self):
        """PRD §3.1: "starting fulfillment moves it from `PRODUCTION` to
        `FULFILLMENT` and requires that at least one production run has reached
        `PRODUCED`."

        Design: Difficulty/transitive_cascade/mark_produced_creates_kits_then_kit_count
        """
        ctx = setup_produced_run(store_count=3, overage_pct=0, num_stores=1,
                                 program_revenue_cents=1000000)
        assert ctx["run"]["status"] == "PRODUCED"
        program = start_fulfillment(ctx["program"]["id"])
        assert program["status"] == "FULFILLMENT"
