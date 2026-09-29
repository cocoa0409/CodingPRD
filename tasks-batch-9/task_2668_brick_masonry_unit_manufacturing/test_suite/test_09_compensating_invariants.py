"""
Ledgers that must balance after a compensating write: rejecting a blend must return
every reserved unit, and the clay reserve must survive commit, transfer and release.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CLAY_RESERVE_INSUFFICIENT
from test_helpers.assertions import (
    assert_clay_reserve_conserved,
    assert_fired_units_conserved,
    expected_blend_profile,
)
from test_helpers.test_users import BLEND_TECHNICIAN, PLANT_ADMIN, QUALITY_MANAGER


def _allocation(color_index, units, dye_lot_code):
    return {"color_index": color_index, "units": units, "dye_lot_code": dye_lot_code}


class TestBlendRejectRestoresFiredUnitConservation:
    """
    Section 2.9 holds that a lot's available, reserved and consumed units always sum
    to fired_units, and section 3.7 makes rejection the compensating write: the
    voided units move "out of reserved_units and back into available_units".
    """

    def _composed_two_lot_blend(self, api, splits=(5000, 7000)):
        env = fx.build_two_fired_lots(api, clock=None)
        order = fx.build_assigned_order(api, requested_units=12000)
        blend = fx.build_composed_blend(
            api,
            order,
            [
                (env["lot_one"]["id"], splits[0]),
                (env["lot_two"]["id"], splits[1]),
            ],
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        env["order"] = order
        env["blend"] = blend
        return env

    def test_rejecting_returns_every_unit_to_both_lots(self, api, clock):
        """
        An unequal 5000 / 7000 draw is compensated exactly on both lots.

        Section 3.7: rejection "moves COMPOSED to DRAFT, records rejection_reason,
        increments rejection_count by 1, and clears weighted_color_index,
        color_range_span, dye_lot_count and composed_by_user_id", then voids the
        components, then returns their units so "a lot whose reserved_units reaches
        exactly 0 moves RESERVED to AVAILABLE with available_units restored to its
        pre-reservation value, which is precisely the fired-unit conservation
        identity of section 2.9."

        Design: Difficulty/compensating_invariant/blend_reject_restores_fired_unit_conservation_across_two_lots
        """
        env = self._composed_two_lot_blend(api)
        lot_one_id = env["lot_one"]["id"]
        lot_two_id = env["lot_two"]["id"]
        assert env["lot_one"]["color_index"] == 52.18
        assert env["lot_two"]["color_index"] == 49.81
        assert env["lot_one"]["fired_units"] == env["lot_two"]["fired_units"] == 9600

        blend = env["blend"]
        assert blend["status"] == "COMPOSED"
        assert blend["allocated_units"] == 12000
        assert blend["weighted_color_index"] == 50.80
        assert blend["color_range_span"] == 2.37
        assert blend["dye_lot_count"] == 2

        reserved_one = validate_success(api.get_fired_lot(lot_one_id, BLEND_TECHNICIAN))
        reserved_two = validate_success(api.get_fired_lot(lot_two_id, BLEND_TECHNICIAN))
        assert (reserved_one["available_units"], reserved_one["reserved_units"]) == (4600, 5000)
        assert (reserved_two["available_units"], reserved_two["reserved_units"]) == (2600, 7000)
        assert reserved_one["status"] == reserved_two["status"] == "RESERVED"
        assert_fired_units_conserved(reserved_one)
        assert_fired_units_conserved(reserved_two)

        rejected = validate_success(
            api.reject_blend(
                blend["id"],
                F.reject_payload("Range too wide at the mock-up wall"),
                QUALITY_MANAGER,
            )
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["allocated_units"] == 0
        assert rejected["weighted_color_index"] is None
        assert rejected["color_range_span"] is None
        assert rejected["composed_by_user_id"] is None
        assert rejected["rejection_count"] == 1
        assert rejected["rejection_reason"] == "Range too wide at the mock-up wall"

        restored_one = validate_success(api.get_fired_lot(lot_one_id, BLEND_TECHNICIAN))
        restored_two = validate_success(api.get_fired_lot(lot_two_id, BLEND_TECHNICIAN))
        for lot in (restored_one, restored_two):
            assert lot["status"] == "AVAILABLE"
            assert lot["available_units"] == 9600
            assert lot["reserved_units"] == 0
            assert lot["consumed_units"] == 0
            assert_fired_units_conserved(lot)

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert [c["status"] for c in components] == ["VOIDED", "VOIDED"]
        assert [c["units"] for c in components] == [5000, 7000]

    def test_the_recomposed_profile_ignores_the_voided_round(self, api, clock):
        """
        After a reject the blend recomposes from scratch on a 6000 / 6000 draw.

        Section 3.7: "The colour profile is computed over the blend's ALLOCATED
        components only; VOIDED components are excluded, so a reject-then-recompose
        cycle recomputes the profile from scratch rather than accumulating the
        discarded rounds", and "the DRAFT to COMPOSED to DRAFT cycle is legal any
        number of times, with rejection_count recording the rounds."

        Design: Difficulty/compensating_invariant/blend_reject_restores_fired_unit_conservation_across_two_lots
        """
        env = self._composed_two_lot_blend(api)
        blend = validate_success(
            api.reject_blend(
                env["blend"]["id"], F.reject_payload("Try an even split"), QUALITY_MANAGER
            )
        )

        blend = fx.add_blend_component(api, blend, env["lot_one"]["id"], 6000)
        blend = fx.add_blend_component(api, blend, env["lot_two"]["id"], 6000)
        recomposed = fx.compose_blend(api, blend["id"])

        expected = expected_blend_profile(
            [
                _allocation(52.18, 6000, env["lot_one"]["dye_lot_code"]),
                _allocation(49.81, 6000, env["lot_two"]["dye_lot_code"]),
            ]
        )
        assert recomposed["status"] == "COMPOSED"
        assert recomposed["allocated_units"] == 12000
        assert recomposed["weighted_color_index"] == expected["weighted_color_index"] == 51.00
        assert recomposed["color_range_span"] == 2.37
        assert recomposed["dye_lot_count"] == 2
        assert recomposed["rejection_count"] == 1

        components = validate_success(
            api.list_blend_components(recomposed["id"], BLEND_TECHNICIAN)
        )
        assert [c["status"] for c in components] == [
            "VOIDED",
            "VOIDED",
            "ALLOCATED",
            "ALLOCATED",
        ]
        for lot_id in (env["lot_one"]["id"], env["lot_two"]["id"]):
            lot = validate_success(api.get_fired_lot(lot_id, BLEND_TECHNICIAN))
            assert lot["reserved_units"] == 6000
            assert lot["available_units"] == 3600
            assert_fired_units_conserved(lot)


class TestClayReserveSurvivesCommitTransferAndRelease:
    """
    Section 2.9: "available_tons plus committed_tons plus consumed_tons equals
    proven_reserve_tons exactly", with tonnage moving available to committed on run
    creation, committed to consumed on green close-out, and committed back to
    available when a run is scrapped by the plant-idle cascade.
    """

    def test_four_checkpoints_each_balance_and_only_committed_clay_returns(
        self, api, clock
    ):
        """
        Commit 16.00, transfer it to consumed, commit 16.00 again, then release it.

        Section 2.9: tonnage "never moves out of consumed", so the idle cascade of
        section 3.9 returns only the second run's committed 16.00 tons and leaves the
        first run's consumed 16.00 alone.

        Design: Difficulty/compensating_invariant/clay_reserve_conservation_survives_commit_transfer_and_release
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        car_two = fx.create_kiln_car(api, plant_id)

        opening = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["proven_reserve_tons"] for p in opening] == [5000.00, 5000.00]
        assert [p["available_tons"] for p in opening] == [5000.00, 5000.00]
        assert [p["committed_tons"] for p in opening] == [0.00, 0.00]
        assert [p["consumed_tons"] for p in opening] == [0.00, 0.00]
        for pit in opening:
            assert_clay_reserve_conserved(pit)

        first = fx.create_production_run(
            api, plant_id, env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert first["clay_tons_committed"] == 32.00
        committed = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["available_tons"] for p in committed] == [4984.00, 4984.00]
        assert [p["committed_tons"] for p in committed] == [16.00, 16.00]
        assert [p["consumed_tons"] for p in committed] == [0.00, 0.00]
        for pit in committed:
            assert_clay_reserve_conserved(pit)

        closed = fx.close_green(api, plant_id, first["id"])
        assert closed["status"] == "SET"
        transferred = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["available_tons"] for p in transferred] == [4984.00, 4984.00]
        assert [p["committed_tons"] for p in transferred] == [0.00, 0.00]
        assert [p["consumed_tons"] for p in transferred] == [16.00, 16.00]
        for pit in transferred:
            assert_clay_reserve_conserved(pit)

        second = fx.create_production_run(
            api, plant_id, env["formulation"]["id"], car_two["id"]
        )
        recommitted = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["available_tons"] for p in recommitted] == [4968.00, 4968.00]
        assert [p["committed_tons"] for p in recommitted] == [16.00, 16.00]
        assert [p["consumed_tons"] for p in recommitted] == [16.00, 16.00]
        for pit in recommitted:
            assert_clay_reserve_conserved(pit)

        idled = validate_success(api.idle_plant(plant_id, PLANT_ADMIN))
        assert idled["status"] == "IDLED"

        released = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["status"] for p in released] == ["SUSPENDED", "SUSPENDED"]
        assert [p["available_tons"] for p in released] == [4984.00, 4984.00]
        assert [p["committed_tons"] for p in released] == [0.00, 0.00]
        assert [p["consumed_tons"] for p in released] == [16.00, 16.00]
        for pit in released:
            assert_clay_reserve_conserved(pit)
            assert pit["available_tons"] <= pit["proven_reserve_tons"]

        operator = env["operator"]
        assert (
            validate_success(api.get_production_run(second["id"], operator))["status"]
            == "SCRAPPED"
        )
        assert (
            validate_success(api.get_production_run(first["id"], operator))["status"]
            == "SET"
        )

    def test_a_rejected_commitment_moves_no_pit_at_all(self, api, clock):
        """
        A pit drawn to exactly 0.00 goes DEPLETED, and the next run moves nothing.

        Section 3.2: "A pit whose available_tons reaches exactly 0.00 as the result
        of a clay commitment moves OPEN to DEPLETED." Section 3.3: "Before a single
        pit is written, the commitment checks that every contributing pit's
        available_tons is at least its own per-pit share. If any one pit falls short,
        the whole run is rejected with ERR_CLAY_RESERVE_INSUFFICIENT and no pit is
        mutated."

        Design: Difficulty/compensating_invariant/clay_reserve_conservation_survives_commit_transfer_and_release
        """
        env = fx.build_plant_with_assets(api, clock=None, pit_reserve_tons=16.00)
        plant_id = env["plant"]["id"]
        car_two = fx.create_kiln_car(api, plant_id)

        drawn_down = fx.create_production_run(
            api, plant_id, env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert drawn_down["clay_tons_committed"] == 32.00

        depleted = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["available_tons"] for p in depleted] == [0.00, 0.00]
        assert [p["committed_tons"] for p in depleted] == [16.00, 16.00]
        assert [p["status"] for p in depleted] == ["DEPLETED", "DEPLETED"]
        for pit in depleted:
            assert_clay_reserve_conserved(pit)

        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    plant_id, env["formulation"]["id"], car_two["id"]
                ),
                env["operator"],
            ),
            ERR_CLAY_RESERVE_INSUFFICIENT,
            422,
        )

        unmoved = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["available_tons"] for p in unmoved] == [0.00, 0.00]
        assert [p["committed_tons"] for p in unmoved] == [16.00, 16.00]
        assert [p["consumed_tons"] for p in unmoved] == [0.00, 0.00]
        assert [p["version"] for p in unmoved] == [p["version"] for p in depleted]
        for pit in unmoved:
            assert_clay_reserve_conserved(pit)

        idle_car = validate_success(api.list_kiln_cars(plant_id, PLANT_ADMIN))
        assert idle_car[1]["status"] == "IDLE"
        assert idle_car[1]["current_production_run_id"] is None
