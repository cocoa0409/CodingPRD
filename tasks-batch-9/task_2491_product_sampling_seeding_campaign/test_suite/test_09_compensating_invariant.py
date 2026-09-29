"""Round trips that must restore a conserved quantity to the cent and the unit."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_budget_conserved,
    assert_kit_line_buckets,
    assert_kit_unit_conservation,
    campaign_manager_headers,
    fulfillment_ops_headers,
)


class TestKitUnitFourBucketConservation:
    """Cancellation returning exactly the reserved units, sink bucket intact."""

    @staticmethod
    def _allocation_over_a_written_off_line(api):
        """Three units written off before an allocation reserves one, two and one.

        The write-off bucket is a sink, so a correct compensation restores the
        first line to seven available units rather than to the ten it received.
        """
        campaign = fx.create_campaign(api, name="Unit Conservation")
        kit_lines = fx.build_kit(api, campaign["id"])
        fx.write_off_units(api, kit_lines[0]["id"], 3, "crushed during inbound handling")

        fx.open_screening(api, campaign["id"])
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, campaign["id"], panelist["id"])
        enrollment = fx.screen_enrollment(api, enrollment["id"])
        fx.activate_sampling(api, campaign["id"])

        center = fx.create_center(api, freight_cents_per_kit=300)
        wave = fx.create_wave(api, center["id"], planned_capacity_units=20)
        shipment = fx.allocate_shipment(
            api, enrollment["id"], wave["id"], surcharge_cents=0
        )
        return campaign, kit_lines, shipment

    def test_cancellation_restores_the_pre_allocation_bucket_values(self, api):
        """PRD §2.7: "The same snapshot discipline applies to inventory:
        cancellation returns exactly the per-line amounts recorded in the
        shipment's `reserved_line_units` map, so an allocate-then-cancel round
        trip restores every one of the four unit buckets to the value it held
        before the allocation."

        Design: Difficulty/compensating_invariant/kit_unit_four_bucket_conservation_across_allocate_and_cancel
        """
        campaign, kit_lines, shipment = self._allocation_over_a_written_off_line(api)
        manager = campaign_manager_headers()

        cancelled = validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), shipment["id"])
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["kit_unit_total"] == 4

        hero = validate_success(api.get_kit_line(manager, kit_lines[0]["id"]))
        assert_kit_line_buckets(
            hero,
            units_received=10,
            units_available=7,
            units_reserved=0,
            units_shipped=0,
            units_written_off=3,
        )

        accessory = validate_success(api.get_kit_line(manager, kit_lines[1]["id"]))
        assert_kit_line_buckets(
            accessory,
            units_received=20,
            units_available=20,
            units_reserved=0,
            units_written_off=0,
        )

        insert = validate_success(api.get_kit_line(manager, kit_lines[2]["id"]))
        assert_kit_line_buckets(
            insert, units_received=10, units_available=10, units_reserved=0
        )

    def test_the_four_bucket_identity_holds_on_every_line(self, api):
        """PRD §2.7: "For every kit line, the sum of `units_available`,
        `units_reserved`, `units_shipped` and `units_written_off` equals
        `units_received` exactly."

        Design: Difficulty/compensating_invariant/kit_unit_four_bucket_conservation_across_allocate_and_cancel
        """
        campaign, kit_lines, shipment = self._allocation_over_a_written_off_line(api)
        manager = campaign_manager_headers()

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), shipment["id"])
        )

        for line in kit_lines:
            assert_kit_unit_conservation(
                validate_success(api.get_kit_line(manager, line["id"]))
            )

    def test_the_write_off_cost_stays_charged_to_the_campaign(self, api):
        """PRD §3.5: "A write-off names a `units` count and a `reason` describing
        the damage or expiry, moves that many units out of `units_available` and
        into `units_written_off`, adds the units multiplied by the line's
        `unit_cost_cents` to the campaign's `write_off_cost_cents`, refreshes
        `cost_per_sample_final_cents`, and increases both the line's and the
        campaign's `version` by 1."

        Design: Difficulty/compensating_invariant/kit_unit_four_bucket_conservation_across_allocate_and_cancel
        """
        campaign, _, shipment = self._allocation_over_a_written_off_line(api)

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), shipment["id"])
        )

        refreshed = validate_success(
            api.get_campaign(campaign_manager_headers(), campaign["id"])
        )
        assert refreshed["write_off_cost_cents"] == 4251
        assert refreshed["cost_per_sample_final_cents"] == 0


class TestBudgetCentsConservationUsesTheSnapshot:
    """Cancellation returning the allocation-time figure, not a recomputation."""

    @staticmethod
    def _allocation_then_a_kit_cost_cut(api):
        """A 754-cent allocation followed by retiring the 55-cent insert line.

        After retirement the kit assembles at 283 + 116 = 399, so a compensation
        that recomputes from the current kit cost would return only 699 cents and
        leave 55 cents stranded in the committed bucket forever.
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 20},
            name="Budget Conservation",
        )
        fx.retire_kit_line(api, world.kit_line_id(2))
        return world

    def test_the_shipment_keeps_its_allocation_time_snapshot(self, api):
        """PRD §2.7: "Cancellation moves back **exactly the amount recorded on the
        shipment at allocation time**, read from the shipment's own
        `committed_cost_cents` snapshot, and never a fresh recomputation from the
        campaign's current kit cost."

        Design: Difficulty/compensating_invariant/budget_cents_conservation_uses_the_allocation_snapshot_not_current_kit_cost
        """
        world = self._allocation_then_a_kit_cost_cut(api)

        cancelled = validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )
        assert cancelled["committed_cost_cents"] == 754
        assert cancelled["status"] == "CANCELLED"

        insert = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(2))
        )
        assert insert["status"] == "RETIRED"
        assert insert["units_available"] == 10
        assert insert["units_reserved"] == 0

    def test_the_retirement_cut_the_campaign_kit_cost_before_the_cancel(self, api):
        """PRD §3.1: "Retirement recomputes the campaign's
        `kit_assembly_unit_cost_cents` — the retired line stops contributing — and
        increases both the line's and the campaign's `version`."

        Design: Difficulty/compensating_invariant/budget_cents_conservation_uses_the_allocation_snapshot_not_current_kit_cost
        """
        world = self._allocation_then_a_kit_cost_cut(api)

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["kit_assembly_unit_cost_cents"] == 399

    def test_the_budget_lands_back_on_the_full_total_with_no_leak(self, api):
        """PRD §2.7: "For every campaign, the sum of `budget_committed_cents` and
        `budget_available_cents` equals `budget_total_cents` exactly."

        Design: Difficulty/compensating_invariant/budget_cents_conservation_uses_the_allocation_snapshot_not_current_kit_cost
        """
        world = self._allocation_then_a_kit_cost_cut(api)

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["budget_committed_cents"] == 0
        assert campaign["budget_available_cents"] == 1000000
        assert campaign["budget_available_cents"] != 999945
        assert_budget_conserved(campaign)
        assert campaign["allocated_sample_count"] == 0
        assert campaign["cost_per_sample_provisional_cents"] == 0
