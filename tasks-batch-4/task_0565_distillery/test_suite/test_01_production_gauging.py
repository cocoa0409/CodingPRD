"""Gauging arithmetic, angel's share, and proof-gallon conservation."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_distillery,
    create_gauged_run,
    fill_barrel,
    assert_conservation_identity,
    assert_bonded_total,
)

_PM = TEST_USERS["production_headers"]


class TestGaugeDualVariant:
    def test_gauge_volume_variant_proof_gallons(self, api):
        """PRD 3.2: "Under the `VOLUME` variant, the volume in wine gallons is taken
        directly from `collected_wine_gallons`." "In both cases, `proof_gallons` is
        that wine-gallon volume multiplied by `collected_proof` and divided by 100,
        rounded to the nearest tenth using round-half-up."

        Design: Difficulty/dual_variant_calc/gauge_volume_vs_weight_diverge
        """
        dist = create_distillery(api)
        vol_run, _ = create_gauged_run(
            api, dist["id"], collected_wine_gallons=100, collected_proof=140,
            gauge_method="VOLUME",
        )
        assert vol_run["proof_gallons"] == 140.0

    def test_gauge_weight_variant_diverges_from_volume(self, api):
        """PRD 3.2: "Under the `WEIGHT` variant, the volume in wine gallons is
        `collected_weight_lbs` divided by 7.28 (the assumed pounds per gallon of
        spirit); because the two variants derive volume differently, the same
        collected inputs yield a different `proof_gallons` depending on the method."

        Design: Difficulty/dual_variant_calc/gauge_volume_vs_weight_diverge
        """
        dist = create_distillery(api)
        vol_run, _ = create_gauged_run(
            api, dist["id"], collected_wine_gallons=100, collected_proof=140,
            gauge_method="VOLUME",
        )
        wt_run, _ = create_gauged_run(
            api, dist["id"], collected_wine_gallons=100, collected_proof=140,
            gauge_method="WEIGHT", collected_weight_lbs=700,
        )
        assert wt_run["proof_gallons"] == 134.6
        assert vol_run["proof_gallons"] != wt_run["proof_gallons"]


class TestGaugeInvalidState:
    def test_gauge_already_gauged_run_rejected(self, api):
        """PRD 3.2: "Gauging is legal only from `DISTILLING`". PRD 2.1: "then the
        legality of the requested state transition (`ERR_INVALID_STATE`, 409)".

        Design: Corner/state_machines/gauge_twice_returns_invalid_state
        """
        dist = create_distillery(api)
        run, _ = create_gauged_run(api, dist["id"])
        resp = api.gauge_run(run["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAngelShare:
    def test_angel_share_after_six_months(self, api):
        """PRD 3.3: "Its `angel_share_pg` is `fill_proof_gallons` multiplied by the
        annual evaporation rate of 0.05 (five percent per year) and by the number of
        months aged divided by twelve, rounded to the nearest tenth using
        round-half-up. The barrel's `current_proof_gallons` is `fill_proof_gallons`
        minus `angel_share_pg`, floored at zero". PRD 3.3: "Reading a barrel returns
        its `angel_share_pg` and `current_proof_gallons` evaluated at the current clock."

        Design: Corner/entities/barrel_angel_share_computed_after_6_months
        """
        dist = create_distillery(api)
        run, _ = create_gauged_run(api, dist["id"], collected_wine_gallons=100, collected_proof=100)
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=100, char_level="CHAR_2",
                             rickhouse_position="B-3")
        api.set_clock("2026-11-01T00:00:00Z", _PM)
        data = validate_success(api.get_barrel(barrel["id"], _PM))
        assert data["angel_share_pg"] == 2.5
        assert data["current_proof_gallons"] == 97.5


class TestProofGallonConservationFillThenDump:
    def test_dump_writes_off_to_destroyed_losses(self, api):
        """PRD 3.3: "the barrel's entire remaining contents leave storage: the
        distillery's `storage_account_pg` is reduced by the sum of the barrel's
        `current_proof_gallons` and its `angel_share_pg`, its `destroyed_losses_pg`
        is increased by `current_proof_gallons`". PRD 2.7: "`total_gauged_pg` is the
        cumulative proof gallons ever gauged into bond; it only ever increases".

        Design: Difficulty/compensating_invariant/proof_gallon_conservation_fill_then_dump
        """
        dist = create_distillery(api)
        run, _ = create_gauged_run(api, dist["id"], collected_wine_gallons=50, collected_proof=100)
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=50)
        get_success_data(api.dump_barrel(barrel["id"], _PM))
        d = validate_success(api.get_distillery(dist["id"], _PM))
        assert d["total_gauged_pg"] == 50.0
        assert d["destroyed_losses_pg"] == 50.0
        assert_conservation_identity(d)

    def test_dump_zeros_bond_accounts(self, api):
        """PRD 3.3: "the source run's `open_barrel_count` is reduced by one".
        PRD 2.7: "`bonded_total_pg` is a derived figure: the sum of
        `production_account_pg`, `storage_account_pg`, and `processing_account_pg`".

        Design: Difficulty/compensating_invariant/proof_gallon_conservation_fill_then_dump
        """
        dist = create_distillery(api)
        run, _ = create_gauged_run(api, dist["id"], collected_wine_gallons=50, collected_proof=100)
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=50)
        get_success_data(api.dump_barrel(barrel["id"], _PM))
        d = validate_success(api.get_distillery(dist["id"], _PM))
        assert d["production_account_pg"] == 0
        assert d["storage_account_pg"] == 0
        assert d["bonded_total_pg"] == 0
        assert_bonded_total(d)
