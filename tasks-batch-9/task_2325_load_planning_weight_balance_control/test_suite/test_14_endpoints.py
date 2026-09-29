"""Endpoint surfaces: round trips, bodyless actions, filters, previews, amendment."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ADMIN,
    AUDIT_INSPECTOR,
    CAPTAIN_1,
    LOAD_CONTROLLER,
    LOAD_CONTROLLER_1,
    RAMP_AGENT,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _controller():
    return load_controller_headers(LOAD_CONTROLLER_1)


# ---------------------------------------------------------------------------
# The passenger-line collection
# ---------------------------------------------------------------------------


class TestPaxLineRoundTrip:
    def test_two_lines_are_created_read_listed_and_one_is_removed_again(self):
        """The whole collection surface answers consistently over one plan.

        PRD: "List results are ordered by `created_at` ascending unless a specific
        endpoint narrative states otherwise."

        Design: Corner/endpoints/pax_line_create_read_list_and_delete_round_trip
        """
        world = fx.reference_world(
            compartment_specs=_layout("OB", "OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})

        aft = fx.seat(world, "OC", male_count=25, female_count=35)
        forward = fx.seat(world, "OB", male_count=10)

        aft_id = str(aft["id"])
        forward_id = str(forward["id"])
        assert aft_id != forward_id, "two passenger lines should carry distinct identifiers"

        detail = get_success_data(api_client.get_pax_line(aft_id, AUDIT_INSPECTOR), 200)
        A.assert_kg(detail["line_weight_kg"], 4650.00, "line_weight_kg")
        A.assert_index(detail["index_delta"], 27.44, "index_delta")

        rows, meta = validate_paginated(
            api_client.list_pax_lines(AUDIT_INSPECTOR, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=2, limit=10, offset=0, has_more=False)
        A.assert_ascending_by_created_at(rows)
        assert A.ids_of(rows) == [aft_id, forward_id], (
            "the earlier line should precede the later one in the listing"
        )

        removal = api_client.delete_pax_line(forward_id, LOAD_CONTROLLER)

        assert removal.status_code == 204, (
            f"deleting a passenger line should return 204 but returned {removal.status_code}"
        )
        assert not removal.content, "a 204 response should carry an empty body"
        validate_error(
            api_client.get_pax_line(forward_id, AUDIT_INSPECTOR), E.PAX_LINE_NOT_FOUND, 404
        )
        rows, meta = validate_paginated(
            api_client.list_pax_lines(
                AUDIT_INSPECTOR,
                {
                    "load_plan_id": world.plan_id,
                    "compartment_id": world.compartment_id("OB"),
                },
            )
        )
        A.assert_pagination_meta(meta, total_count=0)
        assert rows == [], "the compartment filter should return no rows after the removal"
        rows, meta = validate_paginated(
            api_client.list_pax_lines(AUDIT_INSPECTOR, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=1)
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")


# ---------------------------------------------------------------------------
# The three reference-data posture actions
# ---------------------------------------------------------------------------


class TestConfigurationPostures:
    def test_grounding_closing_and_withdrawing_each_answer_with_the_mutated_row(self):
        """Three bodyless calls move three postures and advance three counters.

        PRD: "`updated_at` is refreshed and `version` is incremented by exactly 1 on
        every mutation of that row, including mutations reached indirectly through a
        cascade from another entity's transition."

        Design: Corner/endpoints/configuration_posture_endpoints_are_bodyless_actions
        """
        fx.position_clock()
        aircraft = fx.create_aircraft("HB-AAA")
        runway = fx.create_runway()
        program = fx.create_weight_program()

        grounded = get_success_data(
            api_client.ground_aircraft(str(aircraft["id"]), ADMIN), 200
        )
        closed = get_success_data(api_client.close_runway(str(runway["id"]), ADMIN), 200)
        withdrawn = get_success_data(
            api_client.withdraw_weight_program(str(program["id"]), ADMIN), 200
        )

        assert grounded["status"] == "GROUNDED", (
            f"a grounded airframe should read GROUNDED but read {grounded['status']}"
        )
        A.assert_version_is(grounded, int(aircraft["version"]) + 1)
        assert closed["status"] == "CLOSED", (
            f"a closed runway should read CLOSED but read {closed['status']}"
        )
        A.assert_version_is(closed, int(runway["version"]) + 1)
        assert withdrawn["status"] == "WITHDRAWN", (
            f"a withdrawn programme should read WITHDRAWN but read {withdrawn['status']}"
        )
        A.assert_version_is(withdrawn, int(program["version"]) + 1)
        A.assert_kg(grounded["basic_empty_weight_kg"], 41400.00, "basic_empty_weight_kg")
        assert withdrawn["documentation_ref"] == "OM-A 8.1.3 rev 12", (
            "withdrawal should leave the documentation reference untouched"
        )


# ---------------------------------------------------------------------------
# Stowage read back through the consignment filters
# ---------------------------------------------------------------------------

_CG_GENERAL = "724-22000001"
_CG_MAIL = "724-22000002"
_CG_COMPANY = "724-22000003"


class TestAssignmentThroughTheFilter:
    def test_two_agents_stow_into_one_hold_and_the_filter_finds_exactly_those_two(self):
        """Both authorised roles may stow, and the stowage is visible as a filter.

        PRD: "Stowage sets `assigned_compartment_id` to the hold the consignment will
        travel in, and is available to both a `RampAgent` and a `LoadController`
        while the flight is `PLANNING` or `LOAD_CONTROLLED`."

        Design: Corner/endpoints/consignment_assignment_is_reachable_through_the_compartment_filter
        """
        world = fx.reference_world(
            compartment_specs=_layout("H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        fx.book_cargo(world, _CG_GENERAL, item_kind="GENERAL", weight_kg=400, length_m=1.2)
        fx.book_cargo(world, _CG_MAIL, item_kind="MAIL", weight_kg=300, length_m=1.0)
        fx.book_cargo(world, _CG_COMPANY, item_kind="COMPANY", weight_kg=200, length_m=0.8)
        hold = world.compartment_id("H4")

        by_ramp = api_client.assign_cargo_item(
            world.cargo_id(_CG_GENERAL), {"assigned_compartment_id": hold}, RAMP_AGENT
        )
        by_controller = api_client.assign_cargo_item(
            world.cargo_id(_CG_MAIL), {"assigned_compartment_id": hold}, LOAD_CONTROLLER
        )

        stowed_by_ramp = get_success_data(by_ramp, 200)
        stowed_by_controller = get_success_data(by_controller, 200)
        rows, meta = validate_paginated(
            api_client.list_cargo_items(AUDIT_INSPECTOR, {"assigned_compartment_id": hold})
        )
        A.assert_pagination_meta(meta, total_count=2)
        A.assert_ascending_by_created_at(rows)
        assert A.ids_of(rows) == [
            str(stowed_by_ramp["id"]),
            str(stowed_by_controller["id"]),
        ], "the hold filter should return both stowed consignments in creation order"
        company_rows, company_meta = validate_paginated(
            api_client.list_cargo_items(
                AUDIT_INSPECTOR, {"flight_id": world.flight_id, "item_kind": "COMPANY"}
            )
        )
        A.assert_pagination_meta(company_meta, total_count=1)
        assert A.ids_of(company_rows) == [world.cargo_id(_CG_COMPANY)], (
            "the kind filter should return only the company consignment"
        )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_GENERAL), assigned_compartment_id=hold
        )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_MAIL), assigned_compartment_id=hold
        )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_COMPANY), assigned_compartment_id=None
        )
        rows, meta = validate_paginated(
            api_client.list_cargo_items(
                AUDIT_INSPECTOR, {"assigned_compartment_id": world.compartment_id("H1")}
            )
        )
        A.assert_pagination_meta(meta, total_count=0)


# ---------------------------------------------------------------------------
# The offload preview and its committing counterpart
# ---------------------------------------------------------------------------

_CG_H_COMPANY = "724-30000001"
_CG_H_GENERAL = "724-30000002"
_CG_H_MAIL = "724-30000003"


def _performance_restricted_world() -> fx.Scenario:
    """A hot, wet departure carrying 1560 kg more traffic than it may lift."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4", "H5"),
        band_specs=[F.CANONICAL_BANDS[2]],
    )
    fx.plan_world(
        world,
        flight_overrides={
            "flight_number": "LX1610",
            "outside_air_temp_c": 30,
            "runway_condition": "WET",
        },
    )
    fx.seat(world, "OC", male_count=60)
    fx.stow_bags(world, "H1", 346, 4500)
    fx.stow_bags(world, "H5", 92, 1200)
    fx.book_and_stow_cargo(
        world, _CG_H_COMPANY, "H4", item_kind="COMPANY", weight_kg=400, length_m=1.0
    )
    fx.book_and_stow_cargo(
        world, _CG_H_GENERAL, "H4", item_kind="GENERAL", weight_kg=2200, length_m=2.0
    )
    fx.book_and_stow_cargo(
        world, _CG_H_MAIL, "H4", item_kind="MAIL", weight_kg=1000, length_m=1.4
    )
    fx.compute_plan(world)
    return world


class TestOffloadPreview:
    def test_two_identical_reads_quote_the_selection_and_leave_the_plan_alone(self):
        """The preview names what would go, and nothing moves while it is read.

        PRD: "A read-only preview available to a `LoadControlAdmin` or a
        `LoadController` reports the plan's current `strategy`, the
        `excess_weight_kg` to relieve, the `offloaded_total_kg` the waterfall would
        relieve, the `offloaded_piece_count` it would touch, and
        `offloaded_awb_numbers`, the air waybill numbers of the selected consignments
        in selection order."

        Design: Corner/endpoints/offload_preview_reads_the_selection_without_mutating_the_plan
        """
        world = _performance_restricted_world()
        A.assert_flight_capacity(
            fx.refresh_flight(world),
            performance_limited_takeoff_weight_kg=65120.00,
            allowed_payload_kg=13020.00,
            limiting_factor="PERFORMANCE",
        )
        A.assert_plan_figures(
            world.plan,
            status="RESTRICTED",
            base_payload_kg=14580.00,
            frozen_underload_kg=-1560.00,
            restriction_status="WEIGHT_RESTRICTED",
        )

        by_admin = get_success_data(
            api_client.get_offload_preview(world.plan_id, ADMIN), 200
        )
        by_controller = get_success_data(
            api_client.get_offload_preview(world.plan_id, LOAD_CONTROLLER), 200
        )

        for preview in (by_admin, by_controller):
            A.assert_offload_preview(
                preview,
                strategy="PRIORITY_FIRST",
                excess_weight_kg=1560.00,
                offloaded_total_kg=2600.00,
                offloaded_piece_count=2,
                offloaded_awb_numbers=[_CG_H_COMPANY, _CG_H_GENERAL],
            )
        untouched = fx.refresh_plan(world)
        A.assert_plan_figures(
            untouched,
            status="RESTRICTED",
            planned_payload_kg=14580.00,
            underload_kg=-1560.00,
            index_tow=108.22,
        )
        A.assert_version_is(untouched, int(world.plan["version"]))
        for awb in (_CG_H_COMPANY, _CG_H_GENERAL):
            A.assert_cargo_state(
                fx.refresh_cargo(world, awb),
                status="ACCEPTED",
                assigned_compartment_id=world.compartment_id("H4"),
            )
        rows, meta = validate_paginated(
            api_client.list_cargo_items(
                LOAD_CONTROLLER, {"flight_id": world.flight_id, "status": "OFFLOADED"}
            )
        )
        A.assert_pagination_meta(meta, total_count=0)

    def test_one_apply_call_releases_every_selected_consignment(self):
        """The commit walks both selected pieces off and re-flies the balance chain.

        PRD: "First, each selected consignment transitions `ACCEPTED` → `OFFLOADED`
        with its `assigned_compartment_id` cleared and its own `version` incremented
        by 1."

        Design: Corner/endpoints/apply_offload_releases_every_selected_consignment_in_one_call
        """
        world = _performance_restricted_world()

        response = api_client.apply_offload(world.plan_id, LOAD_CONTROLLER)

        relieved = get_success_data(response, 200)
        for awb in (_CG_H_COMPANY, _CG_H_GENERAL):
            A.assert_cargo_state(
                fx.refresh_cargo(world, awb),
                status="OFFLOADED",
                assigned_compartment_id=None,
            )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_H_MAIL),
            status="ACCEPTED",
            assigned_compartment_id=world.compartment_id("H4"),
        )
        rows, meta = validate_paginated(
            api_client.list_cargo_items(
                LOAD_CONTROLLER, {"flight_id": world.flight_id, "status": "OFFLOADED"}
            )
        )
        A.assert_pagination_meta(meta, total_count=2)
        A.assert_plan_figures(
            relieved,
            planned_payload_kg=11980.00,
            underload_kg=1040.00,
            zero_fuel_weight_kg=54530.00,
            index_zfw=79.86,
            mac_zfw_pct=13.04,
            index_tow=88.46,
            mac_tow_pct=14.29,
            envelope_ok=True,
            base_payload_kg=14580.00,
            frozen_underload_kg=-1560.00,
            restriction_status="WEIGHT_RESTRICTED",
        )


# ---------------------------------------------------------------------------
# The post-departure amendment
# ---------------------------------------------------------------------------


class TestPostDepartureAmendment:
    def test_the_amendment_waits_for_the_aircraft_to_go_off_blocks(self):
        """The same call is refused before departure and honoured after it.

        PRD: "Amendment requires the sheet's `status` to be `ACCEPTED` and the
        flight's `status` to be `DEPARTED`; it moves the sheet `ACCEPTED` →
        `AMENDED`, recomputes `final_takeoff_weight_kg`, `final_index_tow`,
        `final_mac_tow_pct` and `final_payload_kg` from the applied changes one final
        time, and increments the sheet's `version` by 1."

        Design: Corner/endpoints/post_departure_amendment_is_conditional_on_the_flight_having_departed
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        fx.issue_sheet(world, _controller())
        fx.accept_sheet(world, captain_headers(CAPTAIN_1))
        A.assert_sheet_figures(
            world.sheet,
            status="ACCEPTED",
            issued_takeoff_weight_kg=58200.00,
            issued_index_tow=87.26,
            issued_payload_kg=6100.00,
            lmc_allowance_kg=500.00,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), status="LOAD_CONTROLLED", load_release_state="RELEASED"
        )

        too_early = api_client.amend_load_sheet(world.sheet_id, _controller())

        validate_error(too_early, E.FLIGHT_INVALID_STATE, 409)
        assert fx.refresh_sheet(world)["status"] == "ACCEPTED", (
            "a refused amendment should leave the sheet ACCEPTED"
        )
        A.assert_flight_state(fx.depart(world), status="DEPARTED")

        amended = get_success_data(
            api_client.amend_load_sheet(world.sheet_id, _controller()), 200
        )

        A.assert_sheet_figures(
            amended,
            status="AMENDED",
            accepted_by_user_id=CAPTAIN_1,
            final_takeoff_weight_kg=58200.00,
            final_index_tow=87.26,
            final_mac_tow_pct=15.24,
            final_payload_kg=6100.00,
            lmc_net_weight_delta_kg=0.00,
        )
