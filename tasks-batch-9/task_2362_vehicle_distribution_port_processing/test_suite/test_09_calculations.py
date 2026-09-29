"""Derived money and derived reports: the ageing report, the deterministic carrier
pick, the zone constant, the half-cent rounding rule and the storage handover.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    CARRIER_ACTIVE,
    CARRIER_SUSPENDED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_INTERIOR,
    MANAGER,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    POSTURE_OPEN,
    RO_ALLOCATED,
    RO_CANCELLED,
    ROUTE_ZONE_A,
    ROUTE_ZONE_C,
    Vpc,
    assert_center_ledgers,
    assert_dwell_row,
    assert_dwell_rows_cover_every_model_line,
    assert_freight_breakdown,
    assert_slot_ledger,
    assert_storage_charges,
    assert_subset,
    assert_yard_state,
    dwell_row,
    factories as f,
    ok,
    open_port,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)
BODY_PANEL_LINE = f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 40_000)

FOUR_HOUR_WINDOW = {
    "pickup_window_start": "2026-08-04T08:00:00Z",
    "pickup_window_end": "2026-08-04T12:00:00Z",
}


class TestDwellMetrics:
    def test_the_report_buckets_every_model_line_including_the_empty_one(self, flow: Vpc):
        """Two LX500 units of different ages, one damaged TX300, no EV900 at all.

        PRD: "For each model line the report emits `unit_count`, the number of
        matching units; `avg_dwell_days`, the sum of those units' dwell days divided
        by the unit count and rounded half up to one decimal place; three aging
        buckets, `aging_0_15` counting units at 15 dwell days or fewer, `aging_16_30`
        counting units from 16 through 30 dwell days inclusive, and `aging_31_plus`
        counting units at 31 dwell days or more; `blocked_count`, counting units that
        either have `stop_ship_blocked` true or have a `damage_status` of
        `SURVEY_DAMAGE_OPEN` or `REPAIR_AUTHORIZED`; and `accrued_storage_cents`, the
        sum of `storage_charge_provisional_cents` across those units."

        PRD: "Every declared model line is always emitted: a line with no units in
        the yard appears with a `unit_count` of 0, an `avg_dwell_days` of 0.0, and
        every counter at 0 rather than being omitted."

        Design: Corner/calculations/corner_dwell_metrics_aggregates_ageing_buckets_per_model_line
        """
        port = open_port(flow)
        port.discharge("000301", model_line=MODEL_LINE_LX500)
        damaged = port.discharge("000302", model_line=MODEL_LINE_TX300)
        port.surveyed(damaged["id"], [BODY_PANEL_LINE])
        assert (
            port.get_vehicle(damaged["id"])["damage_status"] == DAMAGE_SURVEY_DAMAGE_OPEN
        )

        port.set_clock("2026-08-10T00:00:00Z")
        port.discharge("000303", model_line=MODEL_LINE_LX500)

        port.set_clock("2026-08-20T00:00:00Z")
        rows = port.dwell_metrics()["rows"]

        assert_dwell_rows_cover_every_model_line(rows)
        assert_dwell_row(
            dwell_row(rows, MODEL_LINE_EV900),
            unit_count=0,
            avg_dwell_days=0.0,
            aging_0_15=0,
            aging_16_30=0,
            aging_31_plus=0,
            blocked_count=0,
            accrued_storage_cents=0,
        )
        assert_dwell_row(
            dwell_row(rows, MODEL_LINE_LX500),
            unit_count=2,
            avg_dwell_days=14.0,
            aging_0_15=1,
            aging_16_30=1,
            aging_31_plus=0,
            blocked_count=0,
            accrued_storage_cents=0,
        )
        assert_dwell_row(
            dwell_row(rows, MODEL_LINE_TX300),
            unit_count=1,
            avg_dwell_days=18.0,
            aging_0_15=0,
            aging_16_30=1,
            aging_31_plus=0,
            blocked_count=1,
            accrued_storage_cents=0,
        )


def _two_carriers_one_suspended(flow: Vpc) -> Dict[str, Any]:
    """A cheap suspended carrier beside a dearer active one, and one ready unit."""
    port = open_port(flow)
    dealer = port.create_dealer(
        dealer_code="D-ATL",
        name="Atlanta Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=100,
        allocation_quota=2,
    )
    cheap = port.create_carrier(
        carrier_code="TC-CHEAP",
        name="Budget Car Haul",
        served_route_zones=["A"],
        linehaul_rate_cents_per_mile=300,
        slot_capacity=2,
        concurrent_load_capacity=2,
    )
    road = port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["A", "B", "C"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=2,
        concurrent_load_capacity=2,
    )
    suspended = ok(
        port.api.patch_carrier(cheap["id"], {"status": CARRIER_SUSPENDED}, MANAGER)
    )
    ready = port.shipping_ready_unit("000304", line_items=[CLEAN_LINE])
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "cheap_id": cheap["id"],
        "road_id": road["id"],
        "suspended": suspended,
        "ready": ready,
    }


class TestCarrierSelectionInputSet:
    def test_status_filters_the_candidate_set_before_the_rate_ranking_runs(self, flow: Vpc):
        """The cheaper carrier only wins once it is active again.

        PRD: "The candidate set is every carrier whose `status` is `ACTIVE`, whose
        `served_route_zones` includes the route zone of this allocation (which is the
        dealer's `route_zone`), and whose `slot_capacity` less `committed_slots` is at
        least 1. Candidates are ranked by `linehaul_rate_cents_per_mile` ascending —
        cheapest first."

        PRD: "A carrier's `status`, `linehaul_rate_cents_per_mile` and
        `concurrent_load_capacity` may each be updated later; suspending a carrier
        removes it from future selection without disturbing any release order it
        already holds, and already-committed slots are retained."

        Design: Corner/calculations/corner_carrier_selection_input_set_excludes_suspended_carriers
        """
        scenario = _two_carriers_one_suspended(flow)
        port = scenario["port"]
        ready = scenario["ready"]

        assert scenario["suspended"]["status"] == CARRIER_SUSPENDED

        first = port.allocate(
            ready["id"], scenario["dealer_id"], ready["version"], **FOUR_HOUR_WINDOW
        )
        assert first["truck_carrier_id"] == scenario["road_id"]
        assert port.get_carrier(scenario["cheap_id"])["committed_slots"] == 0

        cancelled = port.cancel(first["id"])
        assert cancelled["status"] == RO_CANCELLED
        assert_slot_ledger(
            port.get_carrier(scenario["road_id"]), committed_slots=0, available_slots=2
        )

        reactivated = ok(
            port.api.patch_carrier(scenario["cheap_id"], {"status": CARRIER_ACTIVE}, MANAGER)
        )
        assert reactivated["status"] == CARRIER_ACTIVE

        current = port.get_vehicle(ready["id"])
        second = port.allocate(
            current["id"], scenario["dealer_id"], current["version"], **FOUR_HOUR_WINDOW
        )

        assert second["truck_carrier_id"] == scenario["cheap_id"]
        assert second["status"] == RO_ALLOCATED
        assert port.get_release_order(first["id"])["status"] == RO_CANCELLED


def _two_dealers_in_two_zones(flow: Vpc) -> Dict[str, Any]:
    """Identical distance and rate, differing only by the dealer's route zone."""
    port = open_port(flow)
    dealer_a = port.create_dealer(
        dealer_code="D-ZA",
        name="Zone A Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=100,
        allocation_quota=1,
    )
    dealer_c = port.create_dealer(
        dealer_code="D-ZC",
        name="Zone C Motors",
        route_zone=ROUTE_ZONE_C,
        distance_miles=100,
        allocation_quota=1,
    )
    carrier = port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["A", "B", "C"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=4,
        concurrent_load_capacity=2,
    )
    unit_a = port.discharge("000305", model_line=MODEL_LINE_LX500)
    unit_c = port.discharge("000306", model_line=MODEL_LINE_LX500)
    port.complete_voyage()
    ready = []
    for unit in (unit_a, unit_c):
        port.surveyed(unit["id"], [CLEAN_LINE])
        port.pass_inspection(unit["id"])
        ready.append(port.prep_complete(unit["id"]))

    order_a = port.allocate(
        ready[0]["id"], dealer_a["id"], ready[0]["version"], **FOUR_HOUR_WINDOW
    )
    order_c = port.allocate(
        ready[1]["id"], dealer_c["id"], ready[1]["version"], **FOUR_HOUR_WINDOW
    )
    port.set_clock("2026-08-04T08:00:00Z")
    return {
        "port": port,
        "carrier_id": carrier["id"],
        "order_a": order_a,
        "order_c": order_c,
    }


class TestZoneAccessorial:
    def test_the_zone_constant_is_the_whole_difference_between_two_settlements(
        self, flow: Vpc
    ):
        """Same base, same surcharge, no discount — only the accessorial moves.

        PRD: "Step three: set `zone_accessorial_cents` from the release order's
        `route_zone` — zone `A` adds nothing, zone `B` adds 4,500 cents, zone `C`
        adds 9,800 cents."

        PRD: "Step five: choose the volume discount rate from that gross figure and
        from nothing else — 6 percent when `gross_freight_cents` is 120,000 cents or
        more, otherwise 3 percent when it is 60,000 cents or more, otherwise no
        discount at all; both comparisons are inclusive at the boundary."

        Design: Corner/calculations/corner_zone_accessorial_constant_is_the_only_delta_between_zone_a_and_zone_c
        """
        scenario = _two_dealers_in_two_zones(flow)
        port = scenario["port"]

        assert scenario["order_a"]["route_zone"] == ROUTE_ZONE_A
        assert scenario["order_c"]["route_zone"] == ROUTE_ZONE_C

        settled_a = port.dispatch(scenario["order_a"]["id"])
        settled_c = port.dispatch(scenario["order_c"]["id"])

        assert_freight_breakdown(
            settled_a,
            base_linehaul_cents=41_200,
            fuel_surcharge_cents=3_811,
            zone_accessorial_cents=0,
            gross_freight_cents=45_011,
            freight_discount_cents=0,
            freight_total_cents=45_011,
        )
        assert_freight_breakdown(
            settled_c,
            base_linehaul_cents=41_200,
            fuel_surcharge_cents=3_811,
            zone_accessorial_cents=9_800,
            gross_freight_cents=54_811,
            freight_discount_cents=0,
            freight_total_cents=54_811,
        )
        assert settled_c["freight_total_cents"] - settled_a["freight_total_cents"] == 9_800
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=2, available_slots=2
        )


class TestFuelSurchargeRounding:
    def test_an_exact_half_cent_surcharge_rounds_up(self, flow: Vpc):
        """50 miles at 412 cents gives 20,600 x 0.0925 = 1905.5 exactly.

        PRD: "Step two: multiply that base by the center's `fuel_surcharge_pct` as
        read at dispatch time and round half up to whole cents, giving
        `fuel_surcharge_cents` — the surcharge applies to the base linehaul only,
        never to the accessorial."

        Design: Corner/calculations/corner_fuel_surcharge_half_cent_rounds_half_up_not_truncated
        """
        port = open_port(flow)
        dealer = port.create_dealer(
            dealer_code="D-NEAR",
            name="Nearby Motors",
            route_zone=ROUTE_ZONE_A,
            distance_miles=50,
            allocation_quota=1,
        )
        port.create_carrier(
            carrier_code="TC-ROAD",
            name="Roadway Auto Transport",
            served_route_zones=["A"],
            linehaul_rate_cents_per_mile=412,
            slot_capacity=2,
            concurrent_load_capacity=1,
        )
        ready = port.shipping_ready_unit("000307", line_items=[CLEAN_LINE])
        order = port.allocate(
            ready["id"], dealer["id"], ready["version"], **FOUR_HOUR_WINDOW
        )

        port.set_clock("2026-08-04T08:00:00Z")
        settled = port.dispatch(order["id"])

        assert_freight_breakdown(
            settled,
            base_linehaul_cents=20_600,
            fuel_surcharge_cents=1_906,
            zone_accessorial_cents=0,
            gross_freight_cents=22_506,
            freight_discount_cents=0,
            freight_total_cents=22_506,
        )


class TestStorageHandover:
    def test_the_projection_is_replaced_by_the_bill_without_double_counting(self, flow: Vpc):
        """7,250 accrued at allocation becomes 5,800 realized at gate-out.

        PRD: "The **provisional** evaluation is stamped at allocation into the unit's
        `storage_charge_provisional_cents`. Its end instant is the allocation instant
        advanced forward by two days — a forward-looking projection of when the unit
        will actually leave — and its credit days are zero, because at allocation time
        nobody knows yet whether the carrier will concede the damage-open period. The
        **final** evaluation is stamped at gate-out into the unit's
        `storage_charge_final_cents`, and `storage_charge_provisional_cents` is reset
        to 0 in the same request."

        PRD: "The center then recomputes `realized_storage_revenue_cents` — the sum of
        `storage_charge_final_cents` over its departed units — and
        `provisional_storage_accrued_cents` — the sum of
        `storage_charge_provisional_cents` over its units in `ALLOCATED` or
        `RELEASED` — along with `yard_occupied_slots`, `yard_free_slots` and
        `yard_posture`, since the yard just gained a slot."

        Design: Corner/calculations/corner_provisional_to_final_storage_switch_reconciles_the_center_ledger
        """
        port = open_port(flow)
        dealer = port.create_dealer(
            dealer_code="D-ATL",
            name="Atlanta Motors",
            route_zone=ROUTE_ZONE_A,
            distance_miles=100,
            allocation_quota=1,
        )
        port.create_carrier(
            carrier_code="TC-ROAD",
            name="Roadway Auto Transport",
            served_route_zones=["A"],
            linehaul_rate_cents_per_mile=412,
            slot_capacity=2,
            concurrent_load_capacity=1,
        )
        ready = port.shipping_ready_unit("000308", line_items=[CLEAN_LINE])

        port.set_clock("2026-08-10T00:00:00Z")
        order = port.allocate(
            ready["id"],
            dealer["id"],
            ready["version"],
            pickup_window_start="2026-08-10T20:00:00Z",
            pickup_window_end="2026-08-11T02:00:00Z",
        )

        assert_storage_charges(port.get_vehicle(ready["id"]), provisional_cents=7_250)
        assert_center_ledgers(port.get_center(), provisional_storage_accrued_cents=7_250)

        port.set_clock("2026-08-10T22:00:00Z")
        port.dispatch(order["id"])
        port.gate_out(order["id"])

        departed = port.get_vehicle(ready["id"])
        assert_storage_charges(
            departed, provisional_cents=0, final_cents=5_800, blocked_credit_days=0
        )
        center = port.get_center()
        assert_center_ledgers(
            center,
            provisional_storage_accrued_cents=0,
            realized_storage_revenue_cents=5_800,
        )
        assert_yard_state(center, occupied_slots=0, free_slots=50, posture=POSTURE_OPEN)
        assert_subset(port.get_release_order(order["id"]), {"vehicle_id": ready["id"]})
