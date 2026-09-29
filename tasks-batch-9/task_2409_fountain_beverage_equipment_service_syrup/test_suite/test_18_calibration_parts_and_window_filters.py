"""The brix tolerance edge, the van parts ledger, and two window filters.

A machine that passes on the tolerance edge and then drifts one hundredth beyond it,
the conservation identity across a restock and across a partial fitting, and the two
collision tests that ignore work already closed out.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    add_stop,
    arrive_call,
    complete_task,
    create_agreement,
    create_call,
    create_outlet,
    create_route,
    create_task,
    create_unit,
    create_van_stock,
    dispatch_call,
    pin_clock,
    read_call,
    read_stop,
    read_unit,
    read_van_stock,
    resolve_call,
    restock_van,
    skip_stop,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_and_unit():
    """Riverside Diner with one IN_SERVICE machine under an 8000-gallon agreement."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    return outlet, agreement, unit


def _call_holding_two_parts():
    """A VAN-7 row of 5 pump assemblies with 2 of them reserved by a dispatched call."""
    _outlet, _agreement, unit = _outlet_and_unit()
    stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
    call = create_call(unit["id"], "NO_POUR", CLOCK)
    dispatch_call(
        call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z",
        TECH, part_sku="PUMP_ASSY_12", part_units=2,
    )
    return stock, call


class TestBrixTolerance:
    def test_a_ratio_on_the_edge_passes_before_one_hundredth_more_fails(self, api):
        """PRD §3.3: "The measurement is graded against a target syrup-to-water ratio of
        5.00 with a tolerance of 0.15: the absolute difference between the measured ratio
        and 5.00 is compared against 0.15, and a difference at or below the tolerance
        grades the task's `calibration_outcome` as `PASS` while any larger difference
        grades it `FAIL`. The boundary is inclusive on the passing side — a measured ratio
        of exactly 5.15 or exactly 4.85 still passes, whereas 5.16 fails. A `PASS` sets
        the unit's `calibration_status` to `IN_SPEC` and a `FAIL` sets it to
        `OUT_OF_SPEC`; in both cases the measured value is written to the unit's
        `brix_ratio_last_measured` and the unit's `version` advances by one."

        Design: Corner/calculations/brix_pass_at_the_lower_tolerance_edge_then_fail_one_hundredth_beyond
        """
        _outlet, _agreement, unit = _outlet_and_unit()
        first = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-10T00:00:00Z")
        second = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-20T00:00:00Z")
        assert read_unit(unit["id"])["calibration_status"] == "UNVERIFIED"

        passed = complete_task(first["id"], TECH, measured_brix_ratio=4.85)
        assert passed["calibration_outcome"] == "PASS"
        assert read_unit(unit["id"])["calibration_status"] == "IN_SPEC"

        failed = complete_task(second["id"], TECH, measured_brix_ratio=5.16)
        assert failed["calibration_outcome"] == "FAIL"
        drifted = read_unit(unit["id"])
        assert drifted["calibration_status"] == "OUT_OF_SPEC"
        assert drifted["status"] == "IN_SERVICE"


class TestVanPartsLedger:
    def test_a_restock_raises_the_conserved_total_and_spares_the_reservation(self, api):
        """PRD §2.11: "For every van part stock row, the sum of `on_van_units`,
        `reserved_units` and `consumed_units` equals the sum of `initial_units` and
        `restocked_units`." The restock movement is the only one that lifts that total:
        "a restock raises `on_van_units` and `restocked_units` together, which is the only
        operation that raises the conserved total. `initial_units` is fixed at creation
        from the units first loaded onto the van and never changes thereafter."

        Design: Corner/calculations/van_parts_restock_preserves_the_conservation_identity
        """
        stock, _call = _call_holding_two_parts()

        restocked = restock_van(stock["id"], 4)
        assert restocked["on_van_units"] == 7
        assert restocked["reserved_units"] == 2
        assert restocked["consumed_units"] == 0
        assert restocked["restocked_units"] == 4
        assert restocked["initial_units"] == 5

        settled = read_van_stock(stock["id"])
        assert (
            settled["on_van_units"]
            + settled["reserved_units"]
            + settled["consumed_units"]
            == settled["initial_units"] + settled["restocked_units"]
        )

    def test_fitting_one_of_two_held_parts_returns_the_other_to_the_van(self, api):
        """PRD §3.8: "Settlement of the van row then follows the ledger of §2.11 exactly:
        the whole held reservation leaves `reserved_units`, the fitted quantity is added
        to `consumed_units`, and the difference between what was held and what was fitted
        returns to `on_van_units`. The call records its `consumed_part_units` and
        `resolution_code`, returns `reserved_part_units` to 0 and `reserved_part_stock_id`
        to null, and both the call's and the van row's `version` advance by one."

        Design: Corner/calculations/van_parts_partial_consumption_splits_the_reservation_on_resolve
        """
        stock, call = _call_holding_two_parts()
        arrive_call(call["id"], TECH)

        resolved = resolve_call(call["id"], "PART_REPLACED", TECH, consumed_part_units=1)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_code"] == "PART_REPLACED"
        assert resolved["consumed_part_units"] == 1
        assert resolved["reserved_part_units"] == 0
        assert resolved["reserved_part_stock_id"] is None

        settled = read_van_stock(stock["id"])
        assert settled["on_van_units"] == 4
        assert settled["reserved_units"] == 0
        assert settled["consumed_units"] == 1
        assert settled["initial_units"] == 5


class TestWindowFilters:
    def test_a_skipped_stop_no_longer_blocks_the_hours_it_had_booked(self, api):
        """PRD §2.9: "A newly proposed stop conflicts with an existing stop of the same
        route when that existing stop is in `PENDING` or `ARRIVED` status and,
        simultaneously, the existing stop's start lies strictly before the new stop's end
        and the new stop's start lies strictly before the existing stop's end." A closed
        stop is out of scope: "Stops already in `SERVED` or `SKIPPED` no longer occupy the
        van's day and are ignored by this test."

        Design: Corner/calculations/stop_window_overlap_ignores_a_skipped_stop
        """
        pin_clock(CLOCK)
        outlet = create_outlet(
            name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
        )
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        first = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T11:00:00Z",
        )
        skip_stop(first["id"])
        assert read_stop(first["id"])["status"] == "SKIPPED"

        second = add_stop(
            route["id"], outlet["id"], 2,
            "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        )
        assert second["status"] == "PENDING"
        assert second["window_start"] == "2026-08-03T10:00:00Z"
        assert second["route_id"] == route["id"]

    def test_a_resolved_call_holds_no_van_time_for_the_next_dispatch(self, api):
        """PRD §2.9: "The dispatch then conflicts with any other service call — excluding
        the call being dispatched itself — that names the same `van_code`, sits in
        `DISPATCHED` or `ON_SITE` status, and whose own `scheduled_window_start` is at or
        before the padded upper bound while the padded lower bound is at or before that
        call's `scheduled_window_end`." Closed calls are out of scope: "Calls in `OPEN`,
        `ESCALATED`, `RESOLVED` or `CANCELLED` hold no van time and are ignored."

        Design: Corner/calculations/van_window_conflict_ignores_a_resolved_call
        """
        outlet, agreement, first_unit = _outlet_and_unit()
        second_unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9002", installed_at="2025-11-01T00:00:00Z",
        )
        first_call = create_call(first_unit["id"], "LEAK", CLOCK)
        dispatch_call(
            first_call["id"], "VAN-7",
            "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
        )
        arrive_call(first_call["id"], TECH)
        resolve_call(first_call["id"], "NO_FAULT_FOUND", TECH)
        second_call = create_call(second_unit["id"], "CO2_LOW", CLOCK)

        dispatched = validate_success(
            api.dispatch_service_call(
                second_call["id"],
                {
                    "van_code": "VAN-7",
                    "scheduled_window_start": "2026-08-02T11:00:00Z",
                    "scheduled_window_end": "2026-08-02T12:00:00Z",
                },
                TECH_ALT,
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["van_code"] == "VAN-7"
        assert dispatched["assigned_tech_user_id"] == TECH_ALT["X-User-ID"]
        assert read_call(first_call["id"])["status"] == "RESOLVED"
