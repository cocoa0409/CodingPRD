"""Concurrency and freshness: the two version-guarded writes, the version counter
itself, and the derived counters read back straight after the write that moved them.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    CLAIM_FILED,
    DAMAGE_ZONE_INTERIOR,
    DAMAGE_ZONE_UNDERBODY,
    ERR_INVALID_STATE,
    ERR_STALE_SURVEY_VERSION,
    ERR_STALE_VEHICLE_VERSION,
    INSPECTOR,
    MANAGER,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    PLANNER,
    POSTURE_OPEN,
    PROC_DISCHARGED,
    PROC_SHIPPING_READY,
    RO_ALLOCATED,
    ROUTE_ZONE_A,
    SURVEYOR,
    SURVEY_SUBMITTED,
    Vpc,
    assert_center_ledgers,
    assert_open_allocation_count,
    assert_pagination_meta,
    assert_slot_ledger,
    assert_storage_charges,
    assert_subset,
    assert_vehicle_dimensions,
    assert_yard_state,
    factories as f,
    ids_of,
    open_port,
    validate_error,
    validate_paginated,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)
UNDERBODY_LINE = f.damage_line(DAMAGE_ZONE_UNDERBODY, 35, 90_000)

PICKUP_WINDOW = {
    "pickup_window_start": "2026-08-04T08:00:00Z",
    "pickup_window_end": "2026-08-04T12:00:00Z",
}


def _ready_unit_with_a_stale_version(flow: Vpc) -> Dict[str, Any]:
    """A shipping-ready unit plus the version observed one write earlier."""
    port = open_port(flow)
    dealer = port.create_dealer(
        dealer_code="D-ATL",
        name="Atlanta Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=100,
        allocation_quota=5,
    )
    carrier = port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["A"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=4,
        concurrent_load_capacity=2,
    )
    unit = port.discharge("000607", model_line=MODEL_LINE_EV900)
    port.complete_voyage()
    port.surveyed(unit["id"], [CLEAN_LINE])
    port.pass_inspection(unit["id"])
    stale = port.get_vehicle(unit["id"])["version"]
    ready = port.prep_complete(unit["id"])
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "carrier_id": carrier["id"],
        "vehicle_id": unit["id"],
        "stale_version": stale,
        "ready": ready,
    }


class TestVehicleVersionGuard:
    def test_a_version_one_write_behind_is_refused_and_the_retry_is_accepted(self, flow: Vpc):
        """Identical body, only the expectation changes.

        PRD: "Allocating a unit to a dealer requires the request to carry
        `expected_vehicle_version`, holding the `version` of the target unit as the
        client last observed it."

        PRD: "If it does not equal the unit's current `version`, the allocation is
        rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_vehicle_version_blocks_allocation
        """
        scenario = _ready_unit_with_a_stale_version(flow)
        port = scenario["port"]
        ready = scenario["ready"]

        assert_vehicle_dimensions(ready, processing_status=PROC_SHIPPING_READY)
        assert ready["version"] > scenario["stale_version"]

        refused = port.api.allocate(
            scenario["vehicle_id"],
            f.allocation_payload(
                scenario["dealer_id"], scenario["stale_version"], **PICKUP_WINDOW
            ),
            MANAGER,
        )
        validate_error(refused, ERR_STALE_VEHICLE_VERSION, 412)

        _, meta = validate_paginated(
            port.api.list_release_orders(
                MANAGER, params={"vehicle_id": scenario["vehicle_id"]}
            )
        )
        assert_pagination_meta(meta, total_count=0)
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=0, available_slots=4
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 0)

        order = port.allocate(
            scenario["vehicle_id"],
            scenario["dealer_id"],
            ready["version"],
            **PICKUP_WINDOW,
        )

        assert_subset(
            order,
            {"status": RO_ALLOCATED, "truck_carrier_id": scenario["carrier_id"]},
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)


class TestSurveyVersionGuard:
    def test_the_pre_submission_survey_version_cannot_file_a_claim(self, flow: Vpc):
        """Submission moved the survey on, so the captured version no longer matches.

        PRD: "Filing a carrier claim against a damage survey requires the request to
        carry `expected_damage_survey_version`, holding the `version` of the target
        survey as the client last observed it, again as a mandatory field."

        PRD: "A mismatch against the survey's current `version` is rejected with
        `ERR_STALE_SURVEY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_survey_version_blocks_claim_filing
        """
        port = open_port(flow)
        unit = port.discharge("000608", model_line=MODEL_LINE_LX500)
        draft = port.survey(unit["id"], [UNDERBODY_LINE])
        stale_version = draft["version"]

        submitted = port.submit_survey(draft["id"])
        assert_subset(
            submitted, {"status": SURVEY_SUBMITTED, "severity_index": 63}
        )
        assert submitted["version"] > stale_version

        refused = port.api.file_claim(
            draft["id"], f.claim_payload(stale_version), SURVEYOR
        )
        validate_error(refused, ERR_STALE_SURVEY_VERSION, 412)

        claim = port.file_claim(draft["id"], submitted["version"])

        assert_subset(
            claim, {"status": CLAIM_FILED, "recoverable_amount_cents": 55_000}
        )
        rows, meta = validate_paginated(
            port.api.list_claims(MANAGER, params={"damage_survey_id": draft["id"]})
        )
        assert_pagination_meta(meta, total_count=1)
        assert ids_of(rows) == [claim["id"]]


class TestVersionCounter:
    def test_reads_and_a_refused_write_leave_the_version_where_it_was(self, flow: Vpc):
        """One at discharge, still one after two reads and a rejection, four after three writes.

        PRD: "Almost all resources additionally carry an `updated_at` timestamp in
        the same format, refreshed on every mutation, and a `version` integer that
        starts at 1 on creation and increments by one on every mutation of the
        record — including mutations the server performs on its own initiative, such
        as recomputing a center's occupancy counters or reverting a unit to a prior
        processing state as part of a cascade."

        PRD: "8. State legality: the requested transition must exist from the
        target's current state — `ERR_INVALID_STATE` (409)."

        Design: Corner/cross_cutting_complexity_layers/corner_version_advances_on_every_accepted_write_and_never_on_a_read
        """
        port = open_port(flow)
        unit = port.discharge("000609", model_line=MODEL_LINE_EV900)
        port.complete_voyage()
        assert unit["version"] == 1

        assert port.get_vehicle(unit["id"])["version"] == 1
        assert port.get_vehicle(unit["id"])["version"] == 1

        too_early = port.api.prep_complete(unit["id"], INSPECTOR)
        validate_error(too_early, ERR_INVALID_STATE, 409)
        after_refusal = port.get_vehicle(unit["id"])
        assert after_refusal["version"] == 1
        assert_vehicle_dimensions(after_refusal, processing_status=PROC_DISCHARGED)

        port.surveyed(unit["id"], [CLEAN_LINE])
        after_survey = port.get_vehicle(unit["id"])["version"]

        port.pass_inspection(unit["id"])
        after_pass = port.get_vehicle(unit["id"])["version"]

        after_prep = port.prep_complete(unit["id"])["version"]

        assert after_survey == 2
        assert after_pass == 3
        assert after_prep == 4


class TestDerivedCountersAreImmediate:
    def test_the_allocation_response_and_the_next_reads_already_agree(self, flow: Vpc):
        """No intervening write: the order, the dealer, the carrier and the center all agree.

        PRD: "Its `vehicle_id` is the unit from the path, `truck_carrier_id` is the
        selected carrier, `route_zone` is copied from the dealer's `route_zone` at
        this moment (so a later change to the dealer does not retroactively re-route
        the shipment), and `allocated_at` is stamped from the logical clock while
        `dispatched_at` and `gated_out_at` stay null."

        PRD: "Alongside the order, the carrier's `committed_slots` and
        `available_slots` and the dealer's `open_allocation_count` are recomputed, the
        unit's processing dimension advances `SHIPPING_READY → ALLOCATED`, the unit's
        `storage_charge_provisional_cents` is stamped on the provisional basis of §3.9
        with the center's `provisional_storage_accrued_cents` recomputed, and the
        unit's `version` increments by one."

        PRD: "The chargeable days are the dwell days less the center's
        `free_storage_days` less whatever credit days apply, floored at zero, and the
        charge is that chargeable-day count multiplied by the center's
        `daily_storage_rate_cents`."

        PRD: "When that ratio is at least 0.95, posture is `GRIDLOCK`; otherwise, when
        it is at least 0.80, posture is `CONSTRAINED`; otherwise it is `OPEN`."

        Design: Corner/consistency_model/corner_every_derived_counter_is_current_in_the_same_response
        """
        port = open_port(flow)
        dealer = port.create_dealer(
            dealer_code="D-ATL",
            name="Atlanta Motors",
            route_zone=ROUTE_ZONE_A,
            distance_miles=100,
            allocation_quota=5,
        )
        carrier = port.create_carrier(
            carrier_code="TC-ROAD",
            name="Roadway Auto Transport",
            served_route_zones=["A"],
            linehaul_rate_cents_per_mile=412,
            slot_capacity=4,
            concurrent_load_capacity=2,
        )
        ready = port.shipping_ready_unit(
            "000610", model_line=MODEL_LINE_EV900, line_items=[CLEAN_LINE]
        )

        port.set_clock("2026-08-10T00:00:00Z")
        order = port.allocate(
            ready["id"],
            dealer["id"],
            ready["version"],
            pickup_window_start="2026-08-11T08:00:00Z",
            pickup_window_end="2026-08-11T12:00:00Z",
        )

        assert_subset(
            order,
            {
                "status": RO_ALLOCATED,
                "vehicle_id": ready["id"],
                "truck_carrier_id": carrier["id"],
                "route_zone": ROUTE_ZONE_A,
                "dispatched_at": None,
                "gated_out_at": None,
            },
        )

        assert_open_allocation_count(port.get_dealer(dealer["id"]), 1)
        assert_slot_ledger(
            port.get_carrier(carrier["id"]), committed_slots=1, available_slots=3
        )

        center = port.get_center()
        assert_yard_state(center, occupied_slots=1, free_slots=49, posture=POSTURE_OPEN)
        assert_center_ledgers(
            center,
            provisional_storage_accrued_cents=7_250,
            realized_storage_revenue_cents=0,
        )

        assert_storage_charges(
            port.get_vehicle(ready["id"], PLANNER), provisional_cents=7_250, final_cents=0
        )
