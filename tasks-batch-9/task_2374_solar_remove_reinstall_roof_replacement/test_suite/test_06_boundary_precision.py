"""Boundary-precision tests for the Solar Reroof Coordination API.

Three independent boundaries, each exercised at the boundary and just past it:
the inspection backlog floor (a temporal boundary), the deck-upgrade cost floor
(a monetary boundary) and the circuit watt spread (a ratio boundary).
"""

import pytest

from test_helpers import (
    COORD,
    add_circuit,
    add_finding,
    add_unit,
    api_client,
    book_inspection,
    create_core_parties,
    create_jurisdiction,
    create_permit,
    create_project,
    deenergize_circuit,
    drive_finding,
    grade_unit,
    get_success_data,
    raise_sourcing_order,
    receive_sourcing_order,
    refresh_project,
    remove_unit,
    set_clock,
    setup_authorized_project,
    submit_permit,
    validate_error,
    validate_paginated,
)

# --------------------------------------------------------------------------
# Shared composite setups (private to this module)
# --------------------------------------------------------------------------
HOST_OWNED_PROJECT = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2_000_000,
}


def _setup_submitted_permit_under_backlog_jurisdiction() -> dict:
    """Clock at 2026-08-10, a FLATROCK jurisdiction with backlog_days 5, permit SUBMITTED."""
    set_clock("2026-08-10T00:00:00Z")
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=5,
        permit_review_days=7,
    )
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    permit = create_permit(
        project["id"], jurisdiction["id"], scope="REINSTALL_ONLY"
    )
    permit = submit_permit(permit["id"])
    return {
        "jurisdiction": jurisdiction,
        "parties": parties,
        "project": project,
        "permit": permit,
    }


def _setup_project_with_two_low_findings() -> dict:
    """A HOST_OWNED project carrying a 10 sqft and a 52.7 sqft LOW finding."""
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    roofer_id = parties["roofer"]["id"]
    finding_a = add_finding(
        project["id"],
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=10,
        attachment_count_affected=0,
    )
    finding_b = add_finding(
        project["id"],
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=52.7,
        attachment_count_affected=0,
    )
    return {
        "parties": parties,
        "project": project,
        "finding_a": finding_a,
        "finding_b": finding_b,
    }


def _setup_two_circuits_with_damaged_panels() -> dict:
    """Two structurally identical circuits, each with a 400 W neighbour and a DAMAGED 410 W panel.

    Order o1 offers 412 W (spread 3.00 percent) and order o2 offers 413 W
    (spread 3.25 percent); both are COMPATIBLE and auto-APPROVED on a HOST_OWNED
    project.
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_authorized_project(ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]

    circuit_1 = add_circuit(project_id, circuit_label="S1", module_count=2, dc_kw=0.81)
    circuit_2 = add_circuit(project_id, circuit_label="S2", module_count=2, dc_kw=0.81)

    ref_1 = add_unit(
        project_id,
        circuit_1["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-400",
        serial_number="SN-1001",
        rated_watts=400,
    )
    dmg_1 = add_unit(
        project_id,
        circuit_1["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-1002",
        rated_watts=410,
    )
    ref_2 = add_unit(
        project_id,
        circuit_2["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-400",
        serial_number="SN-2001",
        rated_watts=400,
    )
    dmg_2 = add_unit(
        project_id,
        circuit_2["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-2002",
        rated_watts=410,
    )

    deenergize_circuit(circuit_1["id"], crew_id, True)
    deenergize_circuit(circuit_2["id"], crew_id, True)

    remove_unit(dmg_1["id"], crew_id)
    grade_unit(
        dmg_1["id"],
        crew_id,
        "DAMAGED",
        "RETAIN",
        damage_note="Cell string open circuit",
    )
    remove_unit(dmg_2["id"], crew_id)
    grade_unit(
        dmg_2["id"],
        crew_id,
        "DAMAGED",
        "RETAIN",
        damage_note="Junction box burn mark",
    )

    order_1 = raise_sourcing_order(
        project_id,
        dmg_1["id"],
        requested_model_code="MS-410",
        offered_manufacturer="Meridian Solar",
        offered_model_code="MS-412",
        offered_rated_watts=412,
        unit_cost_cents=30_500,
    )
    order_2 = raise_sourcing_order(
        project_id,
        dmg_2["id"],
        requested_model_code="MS-410",
        offered_manufacturer="Meridian Solar",
        offered_model_code="MS-413",
        offered_rated_watts=413,
        unit_cost_cents=30_700,
    )

    ctx.update(
        {
            "circuits": [circuit_1, circuit_2],
            "ref_1": ref_1,
            "ref_2": ref_2,
            "dmg_1": dmg_1,
            "dmg_2": dmg_2,
            "order_1": order_1,
            "order_2": order_2,
        }
    )
    return ctx


# --------------------------------------------------------------------------
# The inspection backlog floor
# --------------------------------------------------------------------------
class TestInspectionBacklogFloorBoundary:
    def test_booking_starting_exactly_at_the_backlog_floor_is_accepted(self):
        """A window_start_utc exactly at current instant + backlog_days is bookable.

        PRD §3.7: "A candidate starting exactly at the floor is accepted."

        Design: Difficulty/boundary_precision_check/inspection_backlog_floor_accepts_exact_earliest_start_and_refuses_one_hour_earlier
        """
        ctx = _setup_submitted_permit_under_backlog_jurisdiction()
        permit_id = ctx["permit"]["id"]

        inspection = book_inspection(
            permit_id,
            inspection_type="ROOF_DECK",
            slot_date="2026-08-15",
            window_start_utc="2026-08-15T00:00:00Z",
            window_end_utc="2026-08-15T02:00:00Z",
        )

        assert inspection["status"] == "SCHEDULED", (
            "a booking at exactly the backlog floor must be created SCHEDULED, got "
            f"{inspection['status']}"
        )
        assert inspection["window_start_utc"] == "2026-08-15T00:00:00.000Z", (
            f"window_start_utc must be preserved, got {inspection['window_start_utc']}"
        )
        assert inspection["attempt_number"] == 1, (
            f"a new booking is attempt 1, got {inspection['attempt_number']}"
        )

        permit = get_success_data(
            api_client.get_permit_application(permit_id, COORD)
        )
        assert permit["fee_cents"] == 23100, (
            f"REINSTALL_ONLY at 6.0 kW must cost 23100 cents, got {permit['fee_cents']}"
        )
        assert permit["review_deadline_utc"] == "2026-08-17T00:00:00.000Z", (
            "review deadline is submitted_at plus 7 whole days, got "
            f"{permit['review_deadline_utc']}"
        )

    def test_booking_one_hour_before_the_backlog_floor_is_refused(self):
        """A window_start_utc one hour earlier than the floor is refused.

        PRD §3.7: "The backlog floor comes first: the earliest bookable instant is the current instant plus the jurisdiction's `backlog_days` whole days, and a `window_start_utc` strictly earlier than that floor is refused with `ERR_INSPECTION_BACKLOG_VIOLATION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/inspection_backlog_floor_accepts_exact_earliest_start_and_refuses_one_hour_earlier
        """
        ctx = _setup_submitted_permit_under_backlog_jurisdiction()
        permit_id = ctx["permit"]["id"]

        response = api_client.create_inspection(
            permit_id,
            {
                "inspection_type": "MOUNTING",
                "slot_date": "2026-08-14",
                "window_start_utc": "2026-08-14T23:00:00Z",
                "window_end_utc": "2026-08-14T23:59:00Z",
            },
            COORD,
        )

        validate_error(response, "ERR_INSPECTION_BACKLOG_VIOLATION")

        listed, _meta = validate_paginated(
            api_client.list_permit_inspections(permit_id, COORD)
        )
        assert listed == [], (
            f"the refused booking must not have been persisted, got {listed}"
        )


# --------------------------------------------------------------------------
# The deck-upgrade cost floor
# --------------------------------------------------------------------------
class TestDeckUpgradeFloorBoundary:
    def test_ten_sqft_finding_is_pulled_up_to_the_fifty_thousand_cent_floor(self):
        """A 10 sqft LOW finding with no attachments prices at the 50000-cent floor.

        PRD §3.6: "The finding's `upgrade_cost_cents` is the larger of the capped figure and the effective floor."

        Design: Difficulty/boundary_precision_check/deck_upgrade_floor_boundary_zero_attachments_versus_fifty_two_point_seven_sqft
        """
        ctx = _setup_project_with_two_low_findings()
        roofer_id = ctx["parties"]["roofer"]["id"]

        scoped = drive_finding(ctx["finding_a"]["id"], roofer_id, "SCOPE")

        assert scoped["upgrade_cost_cents"] == 50000, (
            "a 9500-cent raw amount must be lifted to the 50000-cent floor, got "
            f"{scoped['upgrade_cost_cents']}"
        )
        assert scoped["requires_repermit"] is False, (
            "a LOW FASTENER_PULLOUT never requires a re-permit, got "
            f"{scoped['requires_repermit']}"
        )
        project = refresh_project(ctx["project"]["id"])
        assert project["posture"] == "OPEN", (
            f"scoping a LOW finding leaves posture OPEN, got {project['posture']}"
        )

    def test_fifty_two_point_seven_sqft_finding_prices_just_above_the_floor(self):
        """A 52.7 sqft LOW finding computes 50065 cents, so the floor stops binding.

        PRD §3.6: "The first 100 square feet of `affected_area_sqft` cost 950 cents each."

        Design: Difficulty/boundary_precision_check/deck_upgrade_floor_boundary_zero_attachments_versus_fifty_two_point_seven_sqft
        """
        ctx = _setup_project_with_two_low_findings()
        roofer_id = ctx["parties"]["roofer"]["id"]

        drive_finding(ctx["finding_a"]["id"], roofer_id, "SCOPE")
        scoped_b = drive_finding(ctx["finding_b"]["id"], roofer_id, "SCOPE")

        assert scoped_b["upgrade_cost_cents"] == 50065, (
            "52.7 sqft at 950 cents each is 50065 cents, got "
            f"{scoped_b['upgrade_cost_cents']}"
        )
        assert scoped_b["upgrade_cost_cents"] != 50000, (
            "the fractional square footage must not be truncated back onto the floor"
        )

        project = refresh_project(ctx["project"]["id"])
        assert project["scoped_upgrade_cost_cents"] == 100065, (
            "the project rolls up 50000 + 50065, got "
            f"{project['scoped_upgrade_cost_cents']}"
        )


# --------------------------------------------------------------------------
# The circuit watt spread
# --------------------------------------------------------------------------
class TestCircuitWattSpreadBoundary:
    def test_receipt_at_exactly_three_percent_spread_is_accepted(self):
        """A 412 W part beside a 400 W neighbour is exactly 3.00 percent and is received.

        PRD §3.8: "When that spread is strictly greater than 3.00 percent the receipt is refused with `ERR_CIRCUIT_WATT_SPREAD_EXCEEDED` (HTTP 422); a spread exactly equal to 3.00 percent is accepted."

        Design: Difficulty/boundary_precision_check/circuit_watt_spread_accepts_exactly_three_percent_and_refuses_three_point_two_five
        """
        ctx = _setup_two_circuits_with_damaged_panels()
        order_1 = ctx["order_1"]

        assert order_1["match_class"] == "COMPATIBLE", (
            f"same manufacturer inside tolerance is COMPATIBLE, got {order_1['match_class']}"
        )
        assert order_1["watt_delta_pct"] == pytest.approx(0.49, abs=0.01), (
            f"412 W against 410 W of record is 0.49 percent, got {order_1['watt_delta_pct']}"
        )

        received = receive_sourcing_order(order_1["id"], "SN-1102")

        assert received["status"] == "RECEIVED", (
            f"a 3.00 percent spread must be accepted, got {received['status']}"
        )
        unit = get_success_data(
            api_client.get_hardware_unit(ctx["dmg_1"]["id"], COORD)
        )
        assert unit["condition_grade"] == "REPLACED", (
            f"receipt moves DAMAGED to REPLACED, got {unit['condition_grade']}"
        )
        assert unit["rated_watts"] == 412, (
            f"the offered wattage is written onto the unit, got {unit['rated_watts']}"
        )
        assert unit["serial_number"] == "SN-1102", (
            f"the received serial is written onto the unit, got {unit['serial_number']}"
        )
        assert unit["model_code"] == "MS-412", (
            f"the offered model code is written onto the unit, got {unit['model_code']}"
        )

    def test_receipt_at_three_point_two_five_percent_spread_is_refused(self):
        """A 413 W part beside a 400 W neighbour is 3.25 percent and the receipt is refused.

        PRD §3.8: "When that spread is strictly greater than 3.00 percent the receipt is refused with `ERR_CIRCUIT_WATT_SPREAD_EXCEEDED` (HTTP 422); a spread exactly equal to 3.00 percent is accepted."

        Design: Difficulty/boundary_precision_check/circuit_watt_spread_accepts_exactly_three_percent_and_refuses_three_point_two_five
        """
        ctx = _setup_two_circuits_with_damaged_panels()
        order_2 = ctx["order_2"]

        assert order_2["watt_delta_pct"] == pytest.approx(0.73, abs=0.01), (
            f"413 W against 410 W of record is 0.73 percent, got {order_2['watt_delta_pct']}"
        )

        receive_sourcing_order(ctx["order_1"]["id"], "SN-1102")

        response = api_client.receive_sourcing_order(
            order_2["id"], {"received_serial_number": "SN-2102"}, COORD
        )
        validate_error(response, "ERR_CIRCUIT_WATT_SPREAD_EXCEEDED")

        order_2_after = get_success_data(
            api_client.get_sourcing_order(order_2["id"], COORD)
        )
        assert order_2_after["status"] == "APPROVED", (
            f"a refused receipt leaves the order APPROVED, got {order_2_after['status']}"
        )
        unit = get_success_data(
            api_client.get_hardware_unit(ctx["dmg_2"]["id"], COORD)
        )
        assert unit["condition_grade"] == "DAMAGED", (
            f"a refused receipt writes nothing onto the unit, got {unit['condition_grade']}"
        )
        assert unit["rated_watts"] == 410, (
            f"the unit keeps its wattage of record, got {unit['rated_watts']}"
        )
        project = refresh_project(ctx["project"]["id"])
        assert project["damaged_unit_count"] == 1, (
            "only the still-damaged panel counts, got "
            f"{project['damaged_unit_count']}"
        )
