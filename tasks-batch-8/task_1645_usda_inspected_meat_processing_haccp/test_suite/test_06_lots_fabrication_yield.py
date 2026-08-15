"""Carcass receiving, fabrication, yield accounting, mass balance, day close."""
import pytest
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_pct,
    assert_version_incremented,
    complete_fabrication_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures

PROD = TEST_USERS["production_manager_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestYieldColdVsHotBasis:
    def test_fabrication_and_packer_yields_diverge(self, api):
        """PRD §3.5: "On success the lot becomes `FABRICATED` and two yield variants are computed from the *unrounded* sum of stored cut weights, each rounded half-up to two decimal places exactly once at the end: `fabrication_yield_pct` divides by the cold carcass weight and is the authoritative lot yield, while `packer_yield_pct` divides by the hot carcass weight so that cooler shrink counts against it — the packer figure is strictly lower than the fabrication figure whenever any drip loss occurred."
        PRD §3.5: "Chilling completes the lot into `CHILLED` and computes `drip_loss_pct` as one hundred times the difference between hot and cold carcass weight divided by the hot weight, rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/yield_cold_vs_hot_basis_divergence
        """
        env, lot, _cuts = fixtures.setup_fabricating_lot(
            establishment_number="EST-1645-A1",
            hot=1030.0, cold=1000.0,
            cuts=(("CHUCK", 200.0625), ("RIB", 200.0625), ("LOIN", 200.0625)),
        )
        done = validate_success(
            api.complete_fabrication(
                lot["id"], complete_fabrication_payload(trim_waste_lbs=399.8125), PROD
            ),
            200,
        )
        assert done["status"] == "FABRICATED"
        # Cold basis: 100 * 600.1875 / 1000.0 = 60.01875 -> 60.02.
        assert_pct(done["fabrication_yield_pct"], 60.02)
        # Hot basis: 100 * 600.1875 / 1030.0 = 58.2706... -> 58.27.
        assert_pct(done["packer_yield_pct"], 58.27)
        # Drip loss: 100 * (1030 - 1000) / 1030 = 2.9126... -> 2.91.
        assert_pct(done["drip_loss_pct"], 2.91)

    def test_packer_yield_strictly_lower_and_day_totals_sync(self, api):
        """PRD §3.5: "the packer figure is strictly lower than the fabrication figure whenever any drip loss occurred."
        PRD §3.5: "Completion also syncs the owning day's `total_cut_weight_lbs` and `total_cold_weight_lbs` running totals."
        PRD §3.5: "From the fabrication yield the server assigns `yield_grade`: `A` when it is at least 72.0, otherwise `B` when at least 68.0, otherwise `C`."

        Design: Difficulty/dual_variant_calc/yield_cold_vs_hot_basis_divergence
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-A2",
            hot=1030.0, cold=1000.0,
            cuts=(("CHUCK", 200.0625), ("RIB", 200.0625), ("LOIN", 200.0625)),
            trim_waste_lbs=399.8125,
        )
        assert lot["fabrication_yield_pct"] > lot["packer_yield_pct"], (
            "with drip loss present the hot-basis packer yield must sit "
            "strictly below the cold-basis fabrication yield"
        )
        assert lot["yield_grade"] == "C", "60.02 is below the 68.0 B threshold"

        day = validate_success(api.get_production_day(env["day"]["id"], PROD), 200)
        assert_pct(day["total_cut_weight_lbs"], 600.1875)
        assert_pct(day["total_cold_weight_lbs"], 1000.0)


class TestPerLineVsTotalRoundingOrder:
    def test_per_line_percentages_rounded_at_line_creation(self, api):
        """PRD §3.5: "Each line's `pct_of_cold_weight` — one hundred times the line weight divided by the lot's cold carcass weight — is rounded half-up to two decimal places at line creation, and the line's weight accumulates into the lot's `total_cut_weight_lbs`."

        Design: Difficulty/combinatorial_formula/yield_per_line_vs_total_rounding_order
        """
        env, lot, records = fixtures.setup_fabricating_lot(
            establishment_number="EST-1645-D1",
            hot=820.0, cold=800.0,
            cuts=(("BELLY", 100.025), ("HAM", 100.025)),
        )
        # Per line: 100 * 100.025 / 800.0 = 12.503125 -> 12.5 (per-line round).
        assert_pct(records[0]["pct_of_cold_weight"], 12.5)
        assert_pct(records[1]["pct_of_cold_weight"], 12.5)

        done = validate_success(
            api.complete_fabrication(
                lot["id"], complete_fabrication_payload(trim_waste_lbs=599.95), PROD
            ),
            200,
        )
        # Lot level: 100 * 200.05 / 800.0 = 25.00625 -> 25.01 (sum-then-round).
        assert_pct(done["fabrication_yield_pct"], 25.01)

    def test_sum_of_per_line_roundings_differs_from_lot_yield(self, api):
        """PRD §3.5: "Because the per-line percentages were rounded line by line, their sum may differ from `fabrication_yield_pct`; the lot-level figure governs."
        PRD §3.5: "Each line's `pct_of_cold_weight` — one hundred times the line weight divided by the lot's cold carcass weight — is rounded half-up to two decimal places at line creation, and the line's weight accumulates into the lot's `total_cut_weight_lbs`."

        Design: Difficulty/combinatorial_formula/yield_per_line_vs_total_rounding_order
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-D2",
            hot=820.0, cold=800.0,
            cuts=(("BELLY", 100.025), ("HAM", 100.025)),
            trim_waste_lbs=599.95,
        )
        # Raw weights accumulate unrounded...
        assert_pct(lot["total_cut_weight_lbs"], 200.05)
        # ...so the rounded per-line sum (12.5 + 12.5 = 25.0) sits 0.01 below
        # the lot-level sum-then-round figure.
        per_line_sum = 12.5 + 12.5
        assert lot["fabrication_yield_pct"] != pytest.approx(per_line_sum, abs=1e-9), (
            "the rounded per-line sum (25.0) must differ from the lot-level "
            "sum-then-round figure (25.01)"
        )
        assert_pct(lot["fabrication_yield_pct"], 25.01)


class TestMassBalanceInvariant:
    def test_exact_conservation_passes_and_one_pound_imbalance_fails(self, api):
        """PRD §3.5: "Completion of fabrication is where the day's yield accounting crystallizes, and its checks run in order: the day must be `OPEN` (`ERR_DAY_NOT_OPEN`), the lot must be `FABRICATING` (`ERR_LOT_INVALID_STATE`), and then the mass-balance rule bites — at least one cut record must exist, and the absolute difference between the lot's `total_cut_weight_lbs` plus the payload's `trim_waste_lbs` (zero or more) and its `cold_carcass_weight_lbs` must not exceed half a pound, with violations rejected as `ERR_MASS_BALANCE_VIOLATION`."

        Design: Difficulty/compensating_invariant/carcass_mass_balance_compensating_invariant
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-Q")
        # Lot 1 conserves mass exactly: 600.1875 + 399.8125 == 1000.0.
        _e, lot1, _c = fixtures.setup_fabricating_lot(
            env=env, hot=1030.0, cold=1000.0,
            cuts=(("CHUCK", 200.0625), ("RIB", 200.0625), ("LOIN", 200.0625)),
        )
        done1 = validate_success(
            api.complete_fabrication(
                lot1["id"], complete_fabrication_payload(trim_waste_lbs=399.8125), PROD
            ),
            200,
        )
        assert done1["status"] == "FABRICATED"
        assert_pct(done1["total_cut_weight_lbs"], 600.1875)

        # Lot 2 is a full pound out: |400.0 + 449.0 - 850.0| = 1.0 > 0.5.
        _e, lot2, _c2 = fixtures.setup_fabricating_lot(
            env=env, hot=900.0, cold=850.0, cuts=(("CHUCK", 400.0),),
            lot_overrides={"head_count": 8, "live_weight_lbs": 9800},
        )
        blocked = api.complete_fabrication(
            lot2["id"], complete_fabrication_payload(trim_waste_lbs=449.0), PROD
        )
        validate_error(blocked, ApiErrorId.ERR_MASS_BALANCE_VIOLATION)
        assert blocked.status_code == 422

        after = validate_success(api.get_lot(lot2["id"], PROD), 200)
        assert after["status"] == "FABRICATING", (
            "a rejected close-out must leave the lot in FABRICATING"
        )
        assert after.get("fabrication_yield_pct") is None, (
            "no yield fields are written by a rejected close-out"
        )

    def test_zero_cut_records_violates_mass_balance(self, api):
        """PRD §3.5: "the mass-balance rule bites — at least one cut record must exist, and the absolute difference between the lot's `total_cut_weight_lbs` plus the payload's `trim_waste_lbs` (zero or more) and its `cold_carcass_weight_lbs` must not exceed half a pound, with violations rejected as `ERR_MASS_BALANCE_VIOLATION`."

        Design: Difficulty/compensating_invariant/carcass_mass_balance_compensating_invariant
        """
        env, lot, records = fixtures.setup_fabricating_lot(
            establishment_number="EST-1645-Q2", cuts=(),
        )
        assert records == []
        resp = api.complete_fabrication(
            lot["id"], complete_fabrication_payload(trim_waste_lbs=1000.0), PROD
        )
        validate_error(resp, ApiErrorId.ERR_MASS_BALANCE_VIOLATION)
        after = validate_success(api.get_lot(lot["id"], PROD), 200)
        assert after["status"] == "FABRICATING"


class TestLotTransitionOrder:
    def test_harvest_before_ante_mortem_returns_lot_invalid_state(self, api):
        """PRD §3.5: "the lot itself must sit in the step's required from-state, enforced as `ERR_LOT_INVALID_STATE`: ante-mortem requires `RECEIVED`, harvest requires `CLEARED`, chill-complete requires `HARVESTED`, fabrication requires `CHILLED` or `RELEASED`, and fabrication completion requires `FABRICATING`."

        Design: Corner/state_machines/lot_harvest_before_ante_mortem_returns_lot_invalid_state
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-05")
        lot = fixtures.receive_lot(env["day"]["id"])
        assert lot["status"] == "RECEIVED"

        resp = api.harvest_lot(lot["id"], {"hot_carcass_weight_lbs": 1030.0}, PROD)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)
        assert resp.status_code == 409

        after = validate_success(api.get_lot(lot["id"], PROD), 200)
        assert after["status"] == "RECEIVED"


class TestDripLossAndGrade:
    def test_drip_loss_zero_when_hot_equals_cold(self, api):
        """PRD §3.5: "Chilling completes the lot into `CHILLED` and computes `drip_loss_pct` as one hundred times the difference between hot and cold carcass weight divided by the hot weight, rounded half-up to two decimal places."
        PRD §3.5: "When chilling finishes, the recorded `cold_carcass_weight_lbs` must be greater than zero and no more than the hot weight; a cold weight exceeding the hot weight is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/calculations/drip_loss_zero_when_hot_equals_cold
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-18")
        lot = fixtures.receive_lot(env["day"]["id"], species="SWINE",
                                   head_count=20, live_weight_lbs=5200)
        resp = api.pass_ante_mortem(
            lot["id"], fixtures.make_inspector_headers(fixtures.INSPECTOR_1)
        )
        validate_success(resp, 200)
        validate_success(
            api.harvest_lot(lot["id"], {"hot_carcass_weight_lbs": 900.0}, PROD), 200
        )
        chilled = validate_success(
            api.chill_complete_lot(
                lot["id"], {"cold_carcass_weight_lbs": 900.0}, PROD
            ),
            200,
        )
        assert chilled["status"] == "CHILLED"
        assert_pct(chilled["drip_loss_pct"], 0.0)

    def test_yield_grade_a_at_exact_72_threshold(self, api):
        """PRD §3.5: "From the fabrication yield the server assigns `yield_grade`: `A` when it is at least 72.0, otherwise `B` when at least 68.0, otherwise `C`."

        Design: Corner/calculations/yield_grade_a_at_exact_72_threshold
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-17",
            hot=1050.0, cold=1000.0,
            cuts=(("LOIN", 720.0),), trim_waste_lbs=280.0,
        )
        # fabrication_yield_pct == 72.0 exactly -> grade A (inclusive >=).
        assert_pct(lot["fabrication_yield_pct"], 72.0)
        assert lot["yield_grade"] == "A"
        # packer: 100 * 720.0 / 1050.0 = 68.5714... -> 68.57.
        assert_pct(lot["packer_yield_pct"], 68.57)
        # drip: 100 * 50.0 / 1050.0 = 4.7619... -> 4.76.
        assert_pct(lot["drip_loss_pct"], 4.76)

    def test_mass_balance_tolerance_exactly_half_pound_passes(self, api):
        """PRD §3.5: "the absolute difference between the lot's `total_cut_weight_lbs` plus the payload's `trim_waste_lbs` (zero or more) and its `cold_carcass_weight_lbs` must not exceed half a pound, with violations rejected as `ERR_MASS_BALANCE_VIOLATION`."

        Design: Corner/calculations/mass_balance_tolerance_exactly_half_pound_passes
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-23",
            hot=900.0, cold=850.0,
            cuts=(("CHUCK", 400.0),), trim_waste_lbs=449.5,
            lot_overrides={"head_count": 8, "live_weight_lbs": 9800},
        )
        # |400.0 + 449.5 - 850.0| == 0.5, exactly the inclusive tolerance.
        assert lot["status"] == "FABRICATED"
        # fabrication yield: 100 * 400.0 / 850.0 = 47.0588... -> 47.06.
        assert_pct(lot["fabrication_yield_pct"], 47.06)


class TestDayCloseReconciliation:
    def test_close_aggregates_fabricated_lots(self, api):
        """PRD §3.3: "A successful close freezes the day's reconciliation: `total_cut_weight_lbs` and `total_cold_weight_lbs` are summed over the day's `FABRICATED` lots only (`CONDEMNED` lots are excluded from both sums), and `day_yield_pct` is set to one hundred times the frozen cut total divided by the frozen cold total, rounded half-up to two decimal places — or null when the frozen cold total is zero."

        Design: Corner/calculations/day_close_reconciliation_aggregates_fabricated_lots
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-19")
        _e, lot1 = fixtures.setup_fabricated_lot(
            env=env, hot=1030.0, cold=1000.0,
            cuts=(("CHUCK", 200.0625), ("RIB", 200.0625), ("LOIN", 200.0625)),
            trim_waste_lbs=399.8125,
        )
        _e, lot2 = fixtures.setup_fabricated_lot(
            env=env, hot=820.0, cold=800.0,
            cuts=(("BELLY", 200.05),), trim_waste_lbs=599.95,
            lot_overrides={"species": "SWINE", "head_count": 20,
                           "live_weight_lbs": 5200},
        )
        closed = validate_success(
            api.close_production_day(env["day"]["id"], PROD), 200
        )
        assert closed["status"] == "CLOSED"
        assert_pct(closed["total_cut_weight_lbs"], 800.2375)
        assert_pct(closed["total_cold_weight_lbs"], 1800.0)
        # 100 * 800.2375 / 1800.0 = 44.45763... -> 44.46.
        assert_pct(closed["day_yield_pct"], 44.46)


class TestImmediateVisibility:
    def test_harvest_response_reflects_mutation_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §2.5: "`version` (integer): a system-managed integer that increments on every mutation."
        PRD §3.5: "Harvest then records `hot_carcass_weight_lbs` — greater than zero — and moves the lot to `HARVESTED`."

        Design: Corner/consistency_model/harvest_response_reflects_mutation_immediately
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-44")
        lot = fixtures.receive_lot(env["day"]["id"])
        create_version = lot["version"]
        validate_success(
            api.pass_ante_mortem(
                lot["id"], fixtures.make_inspector_headers(fixtures.INSPECTOR_1)
            ),
            200,
        )

        resp = api.harvest_lot(lot["id"], {"hot_carcass_weight_lbs": 1030.0}, PROD)
        harvested = validate_success(resp, 200)
        # The mutation is visible in the harvest response itself.
        assert harvested["status"] == "HARVESTED"
        assert_pct(harvested["hot_carcass_weight_lbs"], 1030.0)
        assert_version_incremented(harvested["version"], create_version)

        # A re-read agrees with the response.
        reread = validate_success(api.get_lot(lot["id"], PROD), 200)
        assert reread["status"] == "HARVESTED"
        assert_pct(reread["hot_carcass_weight_lbs"], 1030.0)
