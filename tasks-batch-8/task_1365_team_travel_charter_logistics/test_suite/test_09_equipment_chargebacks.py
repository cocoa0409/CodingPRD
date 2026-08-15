"""Equipment shipments: tiered weight chargebacks and the cargo ceiling (PRD §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_equipment, setup_charter_leg_booked, setup_team_season_trip,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
EQ = TEST_USERS["equipment_headers"]


def _equipment(api, team_id, trip_id, shipment_id):
    return get_success_data(api.get_equipment(team_id, trip_id, shipment_id, ANY))


class TestChargebackDefaults:
    def test_new_shipment_staged_with_zero_chargeback(self, api, equipment_headers):
        """PRD §3.7: "Shipments start `STAGED` with `chargeback_cents` at 0".

        Design: Corner/entities/equipment_chargeback_default_zero
        """
        team, season, trip = setup_team_season_trip(
            trip_overrides={"game_tipoff_utc": "2027-03-15T00:00:00Z"})
        ship = validate_success(
            api.create_equipment(team["id"], trip["id"],
                                 {"shipment_kind": "TEAM_GEAR", "gross_weight_lb": 500,
                                  "piece_count": 5, "declared_value_cents": 50000},
                                 equipment_headers), 201)
        assert ship["status"] == "STAGED"
        assert ship["chargeback_cents"] == 0


class TestTieredChargeback:
    def test_straddle_of_85_percent_boundary(self, api):
        """PRD §3.7: "Weight up to and including 85 percent of
        `cargo_capacity_lb` is free — the 85-percent boundary itself is 85
        percent of capacity rounded down to a whole pound. Committed weight in
        the band above that boundary and up to the full capacity is charged 350
        cents per pound."

        Design: Difficulty/combinatorial_formula/equipment_weight_tiered_straddle
        """
        ctx = setup_charter_leg_booked(
            contract_overrides={"cargo_capacity_lb": 10000},
            trip_overrides={"game_tipoff_utc": "2026-12-01T02:00:00Z"})
        team_id, trip_id, contract_id = (
            ctx["team"]["id"], ctx["trip"]["id"], ctx["contract"]["id"])
        assert ctx["contract"]["status"] == "ACTIVE"

        ship1 = create_equipment(team_id, trip_id,
                                 gross_weight_lb=8000, piece_count=20,
                                 declared_value_cents=100000,
                                 assigned_contract_id=contract_id)
        loaded1 = validate_success(
            api.load_equipment(team_id, trip_id, ship1["id"], EQ), 200)
        assert loaded1["chargeback_cents"] == 0, \
            "8000 lb is under the 8500 lb free boundary"

        # Committed becomes 9000 lb: only the 500 lb slice above 8500 is charged.
        ship2 = create_equipment(team_id, trip_id, shipment_kind="BROADCAST",
                                 gross_weight_lb=1000, piece_count=5,
                                 declared_value_cents=200000,
                                 assigned_contract_id=contract_id)
        loaded2 = validate_success(
            api.load_equipment(team_id, trip_id, ship2["id"], EQ), 200)
        assert loaded2["chargeback_cents"] == 175000, "500 lb over 85% at 350 cents/lb"

    def test_exact_boundary_and_full_tier2_slice(self, api):
        """PRD §3.7: "Weight up to and including 85 percent of
        `cargo_capacity_lb` is free" — a shipment taking committed weight to
        exactly the 85-percent boundary owes nothing; a further shipment filling
        the band to full capacity is charged 350 cents per pound on the whole
        band ("Committed weight in the band above that boundary and up to the
        full capacity is charged 350 cents per pound.").

        Design: Difficulty/combinatorial_formula/equipment_weight_tiered_straddle
        """
        ctx = setup_charter_leg_booked(
            contract_overrides={"cargo_capacity_lb": 10000},
            trip_overrides={"game_tipoff_utc": "2026-12-01T02:00:00Z"})
        team_id, trip_id, contract_id = (
            ctx["team"]["id"], ctx["trip"]["id"], ctx["contract"]["id"])

        ship1 = create_equipment(team_id, trip_id, gross_weight_lb=8500,
                                 piece_count=20, declared_value_cents=100000,
                                 assigned_contract_id=contract_id)
        loaded1 = validate_success(api.load_equipment(team_id, trip_id, ship1["id"], EQ), 200)
        assert loaded1["chargeback_cents"] == 0, \
            "committed weight exactly at the 85% boundary is still free"

        ship2 = create_equipment(team_id, trip_id, gross_weight_lb=1500,
                                 piece_count=4, declared_value_cents=50000,
                                 assigned_contract_id=contract_id)
        loaded2 = validate_success(api.load_equipment(team_id, trip_id, ship2["id"], EQ), 200)
        # Committed = 10000 = full capacity: entire 8500..10000 band at 350/lb.
        assert loaded2["chargeback_cents"] == 525000, "1500 lb * 350 cents/lb"


class TestCargoCeiling:
    def test_overweight_load_rejected(self, api):
        """PRD §3.7: "the cumulative `gross_weight_lb` of all non-lost shipments
        on the contract, this shipment included, must not exceed the contract's
        `cargo_capacity_lb` — an overload is rejected with `ERR_CARGO_OVERWEIGHT`."

        Design: Corner/validations/cargo_overweight_rejected
        """
        ctx = setup_charter_leg_booked(
            contract_overrides={"cargo_capacity_lb": 5000, "seat_capacity": 20},
            trip_overrides={"game_tipoff_utc": "2027-05-10T00:00:00Z"})
        team_id, trip_id, contract_id = (
            ctx["team"]["id"], ctx["trip"]["id"], ctx["contract"]["id"])

        ship1 = create_equipment(team_id, trip_id, gross_weight_lb=4000,
                                 piece_count=10, declared_value_cents=100000,
                                 assigned_contract_id=contract_id)
        validate_success(api.load_equipment(team_id, trip_id, ship1["id"], EQ), 200)

        ship2 = create_equipment(team_id, trip_id, shipment_kind="BROADCAST",
                                 gross_weight_lb=1500, piece_count=3,
                                 declared_value_cents=50000,
                                 assigned_contract_id=contract_id)
        res = api.load_equipment(team_id, trip_id, ship2["id"], EQ)
        validate_error(res, "ERR_CARGO_OVERWEIGHT", expected_status=409)
        assert _equipment(api, team_id, trip_id, ship2["id"])["status"] == "STAGED", \
            "rejected load must not move the shipment out of STAGED"
