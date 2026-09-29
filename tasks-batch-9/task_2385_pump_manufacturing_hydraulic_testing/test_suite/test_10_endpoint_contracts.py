"""Endpoint contracts: filtered listings, re-binding, holds, links and the clock.

The checks in this file read the endpoint surface itself rather than any one
calculation.  A performance-test listing must discriminate on all three result
dimensions and must hand back the whole reported curve on the listed row; a
casting-short order must be re-bindable to a replacement lot, which throws away
the assembly measurements taken on the casting that was scrapped; the hold that
the same shortage placed on the engineered package must refuse to lift until the
order is re-bound; a package must resolve both of the foreign keys it joins and
reject one that resolves to nothing; a goods receipt must move the stock ledger
and hand back the concurrency token the next reservation has to echo; and the
logical clock must read its documented startup value, echo whatever an
administrator sets, and be the instant every date comparison is measured
against.
"""

from datetime import datetime, timezone

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_build_order,
    assert_kit_units_conserved,
    assert_pump_package,
    assert_run_dimensions,
    assert_test_run,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    QUALITY_INSPECTOR,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────
def _instant(value: str) -> datetime:
    """The instant an ISO 8601 UTC value denotes, however many decimals it carries."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assemble_another_unit(api, world, lot):
    """A further enquiry, approved selection and assembled order on one lot.

    Each unit draws one more commitment from the same accepted lot, so several
    performance tests can stand side by side in different result states.
    """
    duty = X.create_duty_application(api)
    selection = get_success_data(
        api.create_selection(
            F.selection_payload(
                duty["id"], world["model"]["id"], world["config"]["id"], duty["version"]
            ),
            APPLICATION_ENGINEER,
        )
    )
    get_success_data(api.propose_selection(selection["id"], APPLICATION_ENGINEER))
    get_success_data(api.approve_selection(selection["id"], HYDRAULIC_APPROVER))
    build_order = get_success_data(
        api.create_build_order(
            F.build_order_payload(selection["id"], lot["id"]), PRODUCTION_PLANNER
        )
    )
    get_success_data(
        api.record_assembly(
            build_order["id"], F.assembly_payload(), PRODUCTION_PLANNER
        )
    )
    return build_order


def _scrap_every_piece_of(api, ctx):
    """Write off all four pieces of the bound lot, opening the casting shortage.

    A scrap disposition recomputes the lot's piece ledger, and with no good
    casting left the lot can no longer cover the build it carries.
    """
    defect = X.report_defect(
        api,
        ctx["lot"]["id"],
        headers=ctx["foundry_headers"],
        defect_type="SHRINKAGE",
        severity="MAJOR",
        affected_qty=ctx["lot"]["qty_poured"],
    )
    get_success_data(
        api.disposition_casting_defect(
            defect["id"], F.disposition_payload("SCRAP"), QUALITY_INSPECTOR
        )
    )
    return defect


# ─────────────────────────────────────────────────────────────────────────────
# Listing performance tests by result dimension
# ─────────────────────────────────────────────────────────────────────────────
class TestPerformanceTestListing:
    """Three runs in three different result states, filtered three ways."""

    NPSH_REJECTING_POINTS = [
        {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
        {"measured_flow_m3h": 200.0, "measured_head_m": 80.5, "measured_power_kw": 61.0},
        {
            "measured_flow_m3h": 265.0,
            "measured_head_m": 74.0,
            "measured_power_kw": 67.21,
            "measured_npsh3_m": 4.20,
            "is_npsh_point": True,
        },
        {"measured_flow_m3h": 300.0, "measured_head_m": 70.0, "measured_power_kw": 69.5},
        {"measured_flow_m3h": 330.0, "measured_head_m": 65.0, "measured_power_kw": 71.0},
    ]

    @pytest.fixture
    def three_runs(self, api):
        """One certified run, one out of tolerance, one with the suction rejected.

        All three units are built from the same four-piece lot, so the only thing
        that separates their result dimensions is what the bed measured.
        """
        ctx = X.setup_assembled_build_order(api)

        certified = X.setup_certified_test_run(api, ctx["build_order"]["id"])

        out_of_tolerance_order = _assemble_another_unit(api, ctx, ctx["lot"])
        out_of_tolerance = X.setup_evaluated_test_run(
            api,
            out_of_tolerance_order["id"],
            points=K.GOLDEN_CURVE_POINTS,
            test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
            correction_basis="AS_TESTED",
        )

        rejected_suction_order = _assemble_another_unit(api, ctx, ctx["lot"])
        rejected_suction = X.setup_evaluated_test_run(
            api, rejected_suction_order["id"], points=self.NPSH_REJECTING_POINTS
        )

        assert_run_dimensions(certified, "CERTIFIED", "WITHIN_TOLERANCE", "VERIFIED")
        assert_run_dimensions(
            out_of_tolerance, "EVALUATED", "OUT_OF_TOLERANCE", "VERIFIED"
        )
        assert_run_dimensions(
            rejected_suction, "EVALUATED", "WITHIN_TOLERANCE", "REJECTED"
        )
        ctx["certified_run"] = certified
        ctx["out_of_tolerance_run"] = out_of_tolerance
        ctx["rejected_suction_run"] = rejected_suction
        return ctx

    def test_the_listed_row_carries_the_whole_reported_curve(
        self, api, three_runs, planner_headers
    ):
        """Filtering on all three dimensions at once returns the certified run.

        The run was read at the nameplate 2950 rpm, so the speed ratio is exactly
        1.0000 and the reported curve equals the measured curve.  The guarantee
        flow of 265.0 coincides with a measured point, so the reported head is
        74.00 m and the reported power 67.21 kW verbatim; the efficiency at the
        guarantee point works out at 79.48 percent; the head deviation against
        the predicted 73.97 m is plus 0.04 percent and the efficiency deviation
        against the predicted 80.96 percent is minus 1.83 percent; and the
        reported suction figure is 3.40 m.  Every one of those values is on the
        listed row, so a consumer never has to fetch the run by its identifier
        to read the curve it was certified against.

        Design: Corner/endpoints/list_test_runs_filtered_by_result_dimensions_returns_the_derived_curve
        """
        response = api.list_test_runs(
            planner_headers,
            run_state="CERTIFIED",
            hydraulic_status="WITHIN_TOLERANCE",
            npsh_status="VERIFIED",
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 1, "only the certified run matches all three"
        assert len(rows) == 1

        row = rows[0]
        assert_test_run(row)
        assert row["id"] == three_runs["certified_run"]["id"]
        assert row["speed_ratio"] == pytest.approx(1.0000, abs=0.0001)
        assert row["head_at_guarantee_m"] == pytest.approx(74.00, abs=0.01)
        assert row["power_at_guarantee_kw"] == pytest.approx(67.21, abs=0.01)
        assert row["efficiency_at_guarantee_pct"] == pytest.approx(79.48, abs=0.01)
        assert row["head_deviation_pct"] == pytest.approx(0.04, abs=0.01)
        assert row["efficiency_deviation_pct"] == pytest.approx(-1.83, abs=0.01)
        assert row["npshr_tested_m"] == pytest.approx(3.40, abs=0.01)

    def test_each_result_dimension_narrows_the_listing_on_its_own(
        self, api, three_runs, planner_headers
    ):
        """The three dimensions cannot be derived from one another, and filter apart.

        One run is certified and clean, one failed the head band while its
        suction verified, and one verified its head band while its suction was
        rejected.  Filtering on execution state, on head and efficiency
        acceptance, and on suction performance therefore selects three different
        subsets of the same three rows, and no run is open.

        Design: Corner/endpoints/list_test_runs_filtered_by_result_dimensions_returns_the_derived_curve
        """
        certified_id = three_runs["certified_run"]["id"]
        failed_id = three_runs["out_of_tolerance_run"]["id"]
        rejected_id = three_runs["rejected_suction_run"]["id"]

        rows, meta = validate_paginated(api.list_test_runs(planner_headers, run_state="OPEN"))
        assert meta["total_count"] == 0 and rows == []

        rows, meta = validate_paginated(
            api.list_test_runs(planner_headers, run_state="EVALUATED")
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {failed_id, rejected_id}

        rows, meta = validate_paginated(
            api.list_test_runs(planner_headers, hydraulic_status="OUT_OF_TOLERANCE")
        )
        assert meta["total_count"] == 1 and rows[0]["id"] == failed_id

        rows, meta = validate_paginated(
            api.list_test_runs(planner_headers, npsh_status="REJECTED")
        )
        assert meta["total_count"] == 1 and rows[0]["id"] == rejected_id

        rows, meta = validate_paginated(
            api.list_test_runs(planner_headers, npsh_status="VERIFIED")
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {certified_id, failed_id}


# ─────────────────────────────────────────────────────────────────────────────
# Re-binding a casting-short order
# ─────────────────────────────────────────────────────────────────────────────
class TestReassignLot:
    """A replacement casting is a fresh start, not a relabelled order."""

    @pytest.fixture
    def casting_short_order(self, api):
        """An assembled order stranded by the loss of its lot, plus a good lot.

        The order was measured and balanced on the first lot before all four of
        that lot's pieces were written off, so the shortage arrives with
        assembly results already on the record.
        """
        ctx = X.setup_assembled_build_order(api)
        ctx["replacement_lot"] = X.setup_accepted_lot(
            api,
            ctx,
            pour_window_start="2026-08-12T00:00:00Z",
            pour_window_end="2026-08-17T00:00:00Z",
        )
        _scrap_every_piece_of(api, ctx)
        ctx["build_order"] = X.reread_build_order(api, ctx["build_order"]["id"])
        assert ctx["build_order"]["status"] == "CASTING_SHORT"
        return ctx

    def test_reassignment_rebinds_the_order_and_clears_the_assembly_record(
        self, api, casting_short_order, planner_headers
    ):
        """The order returns to PLANNED against the replacement lot, measurements gone.

        Because the physical casting has changed, the running clearance, the
        residual unbalance, the installed flush plan and the balance allowance
        computed from them are all reset to null, so the rotor has to be
        balanced and measured again on the new casting.  The commitment moves
        with the order: the replacement lot now carries one committed build while
        the quarantined lot carries none and can yield no accepted piece.  The
        rework counter is untouched, because no rework loop was signed off.

        Design: Corner/endpoints/reassign_lot_rebinds_the_casting_and_clears_the_recorded_assembly
        """
        build_order_id = casting_short_order["build_order"]["id"]
        replacement_lot_id = casting_short_order["replacement_lot"]["id"]

        response = api.reassign_build_order_lot(
            build_order_id, F.reassign_lot_payload(replacement_lot_id), planner_headers
        )
        rebound = validate_success(response, 200)

        assert_build_order(rebound)
        assert rebound["status"] == "PLANNED"
        assert rebound["casting_lot_id"] == replacement_lot_id
        assert rebound["running_clearance_mm"] is None
        assert rebound["residual_unbalance_g_mm"] is None
        assert rebound["seal_flush_plan_installed"] is None
        assert rebound["allowable_unbalance_g_mm"] is None
        assert rebound["rework_cycles"] == 0

        replacement = X.reread_casting_lot(api, replacement_lot_id)
        assert replacement["committed_build_count"] == 1
        assert replacement["status"] == "ACCEPTED"

        abandoned = X.reread_casting_lot(api, casting_short_order["lot"]["id"])
        assert abandoned["status"] == "QUARANTINED"
        assert abandoned["qty_accepted"] == 0
        assert abandoned["qty_scrapped"] == abandoned["qty_poured"]
        assert abandoned["committed_build_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Lifting the casting-short hold
# ─────────────────────────────────────────────────────────────────────────────
class TestReleaseHold:
    """The hold reads the build order, not merely the package's own state."""

    @pytest.fixture
    def held_package(self, api):
        """A configured package put on hold by the loss of its castings.

        The order was tested and the package engineered around the certified run
        before all four pieces of the bound lot were written off, so the
        shortage propagates from the lot through the order into the package.
        """
        ctx = X.setup_configured_package(api)
        ctx["replacement_lot"] = X.setup_accepted_lot(
            api,
            ctx,
            pour_window_start="2026-08-12T00:00:00Z",
            pour_window_end="2026-08-17T00:00:00Z",
        )
        _scrap_every_piece_of(api, ctx)
        ctx["build_order"] = X.reread_build_order(api, ctx["build_order"]["id"])
        ctx["package"] = X.reread_pump_package(api, ctx["package"]["id"])
        assert ctx["build_order"]["status"] == "CASTING_SHORT"
        assert ctx["package"]["status"] == "HELD"
        return ctx

    def test_the_hold_cannot_be_lifted_while_the_order_is_casting_short(
        self, api, held_package, planner_headers
    ):
        """A shortage that still stands refuses the release-hold request.

        Lifting the hold is permitted only once the build order is no longer
        casting short, so with the order still stranded the request is refused
        and the package stays exactly where the cascade put it.

        PRD 3.7 states the refusal but names no error id for it, and the
        rung-17 ladder of PRD 2.6 admits either reading: the stranded build
        order is inadmissible for the action (`ERR_BUILD_ORDER_INVALID_STATE`,
        checked first among the entities) or the package cannot leave `HELD`
        yet (`ERR_PACKAGE_INVALID_STATE`).  Both members of that pair are
        accepted; the refusal itself and the untouched state are not.

        Design: Corner/endpoints/release_hold_is_refused_while_casting_short_and_allowed_after_reassignment
        """
        package_id = held_package["package"]["id"]

        response = api.release_pump_package_hold(package_id, planner_headers)
        assert response.status_code == 409, response.text
        validate_error_is_one_of(
            response,
            [ApiErrorId.PACKAGE_INVALID_STATE, ApiErrorId.BUILD_ORDER_INVALID_STATE],
        )

        still_held = X.reread_pump_package(api, package_id)
        assert still_held["status"] == "HELD"
        assert still_held["promised_ship_date"] is None
        assert (
            X.reread_build_order(api, held_package["build_order"]["id"])["status"]
            == "CASTING_SHORT"
        )

    def test_the_identical_request_succeeds_once_the_order_is_rebound(
        self, api, held_package, planner_headers
    ):
        """Re-binding the order to a good lot is what unblocks the very same call.

        Reassignment returns the order to PLANNED, and the release-hold action
        then drives the package from HELD back to CONFIGURED.  The promised ship
        date stays null across the cycle and is not restored, the guarantee basis
        is still null because the package has never been released, and the motor
        requirement fixed at creation from the witnessed run's 67.21 kW at the
        guarantee point still reads 73.93 kW.

        Design: Corner/endpoints/release_hold_is_refused_while_casting_short_and_allowed_after_reassignment
        """
        package_id = held_package["package"]["id"]
        build_order_id = held_package["build_order"]["id"]

        rebound = get_success_data(
            api.reassign_build_order_lot(
                build_order_id,
                F.reassign_lot_payload(held_package["replacement_lot"]["id"]),
                planner_headers,
            )
        )
        assert rebound["status"] == "PLANNED"

        response = api.release_pump_package_hold(package_id, planner_headers)
        released = validate_success(response, 200)

        assert_pump_package(released)
        assert released["status"] == "CONFIGURED"
        assert released["promised_ship_date"] is None
        assert released["guarantee_basis"] is None
        assert released["min_motor_kw"] == pytest.approx(73.93, abs=0.01)
        assert X.reread_pump_package(api, package_id)["status"] == "CONFIGURED"


# ─────────────────────────────────────────────────────────────────────────────
# The package as the join between a build and its certificate
# ─────────────────────────────────────────────────────────────────────────────
class TestPumpPackageReferences:
    """Both foreign keys must resolve, and both must be searchable afterwards."""

    @pytest.fixture
    def tested_unit(self, api):
        """A build order driven to TESTED by certifying one run on it."""
        return X.setup_tested_build_order(api)

    def test_an_unresolvable_test_run_reference_is_refused(
        self, api, tested_unit, planner_headers
    ):
        """A test run identifier that resolves to nothing stops the request.

        Every foreign key supplied in the request body has to resolve to an
        existing row, so naming an unknown performance test is refused and no
        package comes into existence.

        Design: Corner/endpoints/pump_package_links_build_order_and_test_run_and_rejects_an_unknown_reference
        """
        response = api.create_pump_package(
            F.pump_package_payload(
                tested_unit["build_order"]["id"], NON_EXISTENT_UUID
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.REFERENCED_RESOURCE_NOT_FOUND)

        _, meta = validate_paginated(api.list_pump_packages(planner_headers))
        assert meta["total_count"] == 0, "a refused create must leave nothing behind"

    def test_the_created_package_is_reachable_from_both_foreign_keys(
        self, api, tested_unit, planner_headers, adjudicator_headers
    ):
        """The real pair creates the package and both filtered list forms find it.

        Packages may be filtered by the build order they were engineered around
        and by the performance test whose curve they ship against, so either key
        alone locates the row.

        Design: Corner/endpoints/pump_package_links_build_order_and_test_run_and_rejects_an_unknown_reference
        """
        build_order_id = tested_unit["build_order"]["id"]
        test_run_id = tested_unit["test_run"]["id"]

        response = api.create_pump_package(
            F.pump_package_payload(build_order_id, test_run_id), planner_headers
        )
        package = validate_success(response, 201)

        assert_pump_package(package)
        assert package["build_order_id"] == build_order_id
        assert package["test_run_id"] == test_run_id
        assert package["status"] == "CONFIGURED"

        for filters in ({"build_order_id": build_order_id}, {"test_run_id": test_run_id}):
            rows, meta = validate_paginated(
                api.list_pump_packages(adjudicator_headers, **filters)
            )
            assert meta["total_count"] == 1, f"{filters} should match exactly one package"
            assert len(rows) == 1 and rows[0]["id"] == package["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Kit receipts and the token they hand back
# ─────────────────────────────────────────────────────────────────────────────
class TestRepairKitReceipts:
    """A goods receipt moves two counters and mints the next concurrency token."""

    def test_two_receipts_add_to_stock_and_leave_the_version_at_three(
        self, api, admin_headers, planner_headers
    ):
        """Each receipt adds its quantity to on-hand and received-total stock.

        A newly catalogued kit is ACTIVE with every quantity at 0 and its version
        at 1.  Receiving 6 units and then 4 units leaves 10 units on hand and 10
        ever received, with the reserved, issued and consumed buckets untouched
        at 0, so the units ever received are still fully accounted for.  Each
        receipt bumps the version by exactly one, so after two receipts the
        version reads 3 rather than 2.

        Design: Corner/endpoints/repair_kit_receipt_adds_to_stock_and_bumps_the_version_used_for_concurrency
        """
        model = X.create_pump_model(api)
        kit = get_success_data(
            api.create_repair_kit(F.repair_kit_payload(model["id"]), admin_headers)
        )
        assert kit["version"] == 1
        assert kit["qty_received_total"] == 0 and kit["qty_on_hand"] == 0

        first = validate_success(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(6), planner_headers
            ),
            200,
        )
        assert first["qty_on_hand"] == 6
        assert first["qty_received_total"] == 6
        assert first["version"] == 2

        second = validate_success(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(4), planner_headers
            ),
            200,
        )
        assert second["qty_on_hand"] == 10
        assert second["qty_received_total"] == 10
        assert second["qty_reserved"] == 0
        assert second["qty_issued"] == 0
        assert second["qty_consumed_total"] == 0
        assert second["version"] == 3
        assert second["status"] == "ACTIVE"
        assert_kit_units_conserved(second)

        stored = X.reread_repair_kit(api, kit["id"])
        assert stored["version"] == 3
        assert stored["qty_on_hand"] == 10
        assert stored["qty_received_total"] == 10
        assert_kit_units_conserved(stored)

    def test_a_reservation_must_echo_the_version_the_receipts_left_behind(
        self, api, admin_headers, planner_headers
    ):
        """The version a receipt returns is the token the next reservation carries.

        Two receipts leave the kit at version 3.  A reservation echoing the
        version observed before the second receipt is rejected, because the
        client would be committing stock against counters it has not seen, while
        the same request echoing 3 reserves a unit and moves it out of the
        on-hand bucket.

        Design: Corner/endpoints/repair_kit_receipt_adds_to_stock_and_bumps_the_version_used_for_concurrency
        """
        ctx = X.setup_planned_build_order(api)
        kit = get_success_data(
            api.create_repair_kit(F.repair_kit_payload(ctx["model"]["id"]), admin_headers)
        )
        stale = get_success_data(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(6), planner_headers
            )
        )
        current = get_success_data(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(4), planner_headers
            )
        )
        assert stale["version"] == 2 and current["version"] == 3

        refused = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 1, stale["version"]
            ),
            planner_headers,
        )
        validate_error(refused, ApiErrorId.STALE_REPAIR_KIT_VERSION)
        assert X.reread_repair_kit(api, kit["id"])["qty_reserved"] == 0

        accepted = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 1, current["version"]
            ),
            planner_headers,
        )
        allocation = validate_success(accepted, 201)
        assert allocation["status"] == "RESERVED"
        assert allocation["repair_kit_id"] == kit["id"]

        after = X.reread_repair_kit(api, kit["id"])
        assert after["qty_reserved"] == 1
        assert after["qty_on_hand"] == 9
        assert_kit_units_conserved(after)


# ─────────────────────────────────────────────────────────────────────────────
# The logical clock
# ─────────────────────────────────────────────────────────────────────────────
class TestLogicalClock:
    """The only mutable platform state, and the instant every date is read against."""

    LATER_INSTANT = "2028-09-15T00:00:00Z"

    def test_the_clock_reads_its_startup_value_and_echoes_whatever_is_set(
        self, api, engineer_headers, admin_headers, foundry_partner_headers_factory
    ):
        """Before anyone sets it the clock reads exactly 2026-08-01T00:00:00Z.

        It never falls back to real time, so an untouched deployment answers with
        that instant.  An administrator moving it is answered with the resulting
        value, and the next read returns the same value verbatim; because every
        role may read the clock, the foundry partner sees it too.  Setting the
        clock mutates no entity, so the foundry registered beforehand is still at
        version 1 afterwards.

        Design: Corner/endpoints/clock_set_and_read_expose_the_logical_time_every_calculation_uses
        """
        first_read = validate_success(api.get_clock(engineer_headers), 200)
        assert _instant(first_read["current_utc"]) == _instant(K.DEFAULT_CLOCK_UTC)

        foundry = X.create_foundry(api)
        assert foundry["version"] == 1

        set_response = api.set_clock(
            F.clock_payload(self.LATER_INSTANT), admin_headers
        )
        moved = validate_success(set_response, 200)
        assert _instant(moved["current_utc"]) == _instant(self.LATER_INSTANT)

        partner_read = validate_success(
            api.get_clock(foundry_partner_headers_factory(foundry["id"])), 200
        )
        assert _instant(partner_read["current_utc"]) == _instant(self.LATER_INSTANT)

        unchanged = get_success_data(api.get_foundry(foundry["id"], PLATFORM_ADMIN))
        assert unchanged["version"] == 1, "setting the clock mutates no entity"

    def test_the_spare_parts_support_window_is_measured_against_the_clock(
        self, api, planner_headers
    ):
        """Moving the clock changes a date comparison the contract derives from it.

        A kit may be allocated when the clock is at or after its support window
        start and strictly before its window end.  At the startup instant the
        window from 2026-01-01 to 2029-01-01 is open, so the reservation is
        accepted; with the clock moved to the exclusive end instant the identical
        reservation is refused, which shows the comparison reads the logical
        clock rather than anything stored on the request.

        Design: Corner/endpoints/clock_set_and_read_expose_the_logical_time_every_calculation_uses
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=5)

        inside = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 1, kit["version"]
            ),
            planner_headers,
        )
        allocation = validate_success(inside, 201)
        assert allocation["status"] == "RESERVED"

        X.set_clock(api, K.KIT_HSC14_G2["support_window_end"])
        clock = validate_success(api.get_clock(planner_headers), 200)
        assert _instant(clock["current_utc"]) == _instant(
            K.KIT_HSC14_G2["support_window_end"]
        )

        reread = X.reread_repair_kit(api, kit["id"])
        outside = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 1, reread["version"]
            ),
            planner_headers,
        )
        validate_error(outside, ApiErrorId.KIT_SUPPORT_WINDOW_EXPIRED)
