"""
Gates that live on a *different* entity than the one being written: a preventive
visit whose start depends on the machine's lifecycle, and a parts hold whose
permitted source depends on the catalogue line's obsolescence state.

Each test builds its whole world through declared endpoints and drives the logical
clock itself, because the database is empty when the test starts.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    ERR_PART_SOURCE_UNAVAILABLE,
    ERR_SAFETY_LOCKOUT_OPEN,
    PARTS_PLANNER,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_technician_capacity_identity,
    assignment_for_visit,
    build_fleet,
    call_on_site,
    get_success_data,
    inspector_headers,
    inventory_adjustment_payload,
    new_part,
    parts_hold_payload,
    place_hold,
    read_call,
    read_club,
    read_contract,
    read_equipment,
    read_part,
    read_technician,
    read_visit,
    rows_of,
    schedule_visit,
    set_clock,
    tag_out_payload,
    technician_headers,
    validate_error,
)


def _two_visits_one_technician_and_an_inspector(api):
    """
    Two identically SCHEDULED visits held by one technician on two treadmills, plus
    a NW inspector who can lock a machine out.

    V1 runs 09:00-10:30 on E1 and V2 runs 11:15-12:45 on E2, a gap of exactly the
    travel buffer, so both reservations are legal and the technician holds 180 minutes.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T08:00:00Z",
        club_kwargs={"max_concurrent_visits": 2},
        serials=["SN-XE-1", "SN-XE-2"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[
            {"full_name": "Dana Reyes", "region_code": "NW"},
            {
                "full_name": "Ivo Marsh",
                "region_code": "NW",
                "is_safety_inspector": True,
            },
        ],
    )
    technician_id, inspector_id = fleet["technician_ids"]
    fleet["visit_on_tagged_unit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-19T09:00:00Z",
        "2026-08-19T10:30:00Z",
        technician_id,
    )
    fleet["visit_on_healthy_unit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][1],
        "2026-08-19T11:15:00Z",
        "2026-08-19T12:45:00Z",
        technician_id,
    )
    set_clock(api, "2026-08-19T08:30:00Z")
    get_success_data(
        api.tag_out_equipment(
            fleet["equipment_ids"][0],
            tag_out_payload(),
            inspector_headers(inspector_id),
        )
    )
    fleet["technician_id"] = technician_id
    fleet["inspector_id"] = inspector_id
    return fleet


def test_visit_start_is_refused_because_its_machine_is_tagged_out(api):
    """
    Nothing on the visit row distinguishes it from its sibling, yet starting it is
    refused with ERR_SAFETY_LOCKOUT_OPEN because the machine it names is locked out,
    and the reservation it already holds is left exactly as it was.

    PRD §3.4: "One cross-entity condition guards the start: the machine's
    `lifecycle_status` must not be `TAGGED_OUT`."

    Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_equipment_lifecycle_not_on_the_visit_row
    """
    fleet = _two_visits_one_technician_and_an_inspector(api)
    visit_id = fleet["visit_on_tagged_unit"]["id"]
    technician_id = fleet["technician_id"]

    set_clock(api, "2026-08-19T09:00:00Z")
    response = api.start_visit(visit_id, technician_headers(technician_id))
    validate_error(response, ERR_SAFETY_LOCKOUT_OPEN, 409)

    refused = read_visit(api, visit_id)
    assert_fields(refused, visit_status="SCHEDULED")
    assert_null_fields(refused, "started_at")

    assert_fields(
        read_equipment(api, fleet["equipment_ids"][0]),
        lifecycle_status="TAGGED_OUT",
        safety_lockout_reason="INSPECTOR_TAG_OUT",
    )
    assert_fields(
        read_equipment(api, fleet["equipment_ids"][1]), lifecycle_status="IN_SERVICE"
    )
    assert_fields(read_club(api, fleet["club_id"]), open_safety_lockout_count=1)

    assert_fields(assignment_for_visit(api, visit_id), status="RESERVED")
    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == 180
    assert_technician_capacity_identity(
        technician,
        rows_of(api.list_technician_assignments(CONTRACT_ADMIN, technician_id=technician_id)),
    )


def test_the_sibling_visit_on_an_in_service_machine_starts_normally(api):
    """
    The satisfied side of the same dependency: with the lockout standing on the other
    machine, the visit whose own machine is still IN_SERVICE starts, stamps started_at
    from the clock and confirms its reservation without changing committed minutes.

    PRD §3.3: "From `RESERVED` an assignment advances to `CONFIRMED` when the
    technician actually turns up — arriving at the service call, or starting the
    preventive visit — and confirmation leaves `committed_minutes` unchanged, because
    a reserved and a confirmed interval occupy the calendar identically."

    Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_equipment_lifecycle_not_on_the_visit_row
    """
    fleet = _two_visits_one_technician_and_an_inspector(api)
    healthy_visit_id = fleet["visit_on_healthy_unit"]["id"]
    tagged_visit_id = fleet["visit_on_tagged_unit"]["id"]
    technician_id = fleet["technician_id"]

    set_clock(api, "2026-08-19T11:15:00Z")
    started = get_success_data(
        api.start_visit(healthy_visit_id, technician_headers(technician_id))
    )
    assert_fields(started, visit_status="IN_PROGRESS")
    assert_instant(started["started_at"], "2026-08-19T11:15:00Z", "started_at")

    assert_fields(assignment_for_visit(api, healthy_visit_id), status="CONFIRMED")
    assert_fields(assignment_for_visit(api, tagged_visit_id), status="RESERVED")
    assert_fields(read_visit(api, tagged_visit_id), visit_status="SCHEDULED")

    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == 180
    assert_technician_capacity_identity(
        technician,
        rows_of(api.list_technician_assignments(CONTRACT_ADMIN, technician_id=technician_id)),
    )

    assert_fields(
        read_equipment(api, fleet["equipment_ids"][1]), lifecycle_status="IN_SERVICE"
    )
    assert_fields(
        read_equipment(api, fleet["equipment_ids"][0]), lifecycle_status="TAGGED_OUT"
    )


def _obsolete_belt_with_one_call_on_site(api):
    """
    A BELT-900 catalogue line driven to OBSOLETE, then restocked with two
    refurbished units, while a MINOR call on the matching treadmill sits ON_SITE.

    End-of-support is declared while the refurbished bucket is empty, which is the
    branch that skips END_OF_SUPPORT_ANNOUNCED entirely.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T08:00:00Z",
        serials=["SN-PS-1"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-900",
        category="WEAR",
        unit_price_cents=32000,
        is_critical_spare=False,
        initial_on_hand_qty=5,
        initial_refurb_qty=0,
    )
    call = call_on_site(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        technician_id,
        "2026-08-19T08:00:00Z",
        severity="MINOR",
        symptom_code="BELT_NOISE",
    )
    declared = get_success_data(api.declare_end_of_support(part["id"], PARTS_PLANNER))
    assert_fields(declared, lifecycle_status="OBSOLETE")
    get_success_data(
        api.adjust_inventory(
            part["id"],
            inventory_adjustment_payload(new_qty_delta=0, refurb_qty_delta=2),
            PARTS_PLANNER,
        )
    )
    fleet["part"] = part
    fleet["call"] = call
    fleet["technician_id"] = technician_id
    return fleet


def test_refurbished_sourcing_still_succeeds_on_an_obsolete_catalogue_line(api):
    """
    The satisfied side of the dependency: with the catalogue line OBSOLETE a
    REFURBISHED hold is allowed, prices at the 0.60 source factor and draws the whole
    19200 cents from the FULL-inclusion allowance.

    PRD §3.7: "The source must be permitted for the part's `lifecycle_status`: once a
    part is `OBSOLETE`, `NEW` sourcing is refused with `ERR_PART_SOURCE_UNAVAILABLE`,
    and refurbished or loaner sourcing must be used instead."

    Design: Difficulty/cross_entity_state_dependency/new_part_sourcing_depends_on_part_catalog_lifecycle
    """
    fleet = _obsolete_belt_with_one_call_on_site(api)
    part_id = fleet["part"]["id"]
    call_id = fleet["call"]["id"]

    order = place_hold(
        api, call_id, fleet["technician_id"], part_id, qty=1, source="REFURBISHED"
    )
    assert_fields(order, status="ALLOCATED", source="REFURBISHED", qty=1)
    assert_money(order["list_total_cents"], 19200, "list_total_cents")
    assert_money(order["allowance_draw_cents"], 19200, "allowance_draw_cents")
    assert_money(order["club_billable_cents"], 0, "club_billable_cents")

    part = read_part(api, part_id)
    assert_fields(
        part,
        lifecycle_status="OBSOLETE",
        on_hand_qty=5,
        refurb_on_hand_qty=1,
        allocated_qty=1,
    )
    assert_part_inventory_identity(
        part, rows_of(api.list_part_orders(CONTRACT_ADMIN, part_id=part_id))
    )

    contract = read_contract(api, fleet["contract_id"])
    assert_money(
        contract["parts_allowance_remaining_cents"],
        480800,
        "parts_allowance_remaining_cents",
    )
    assert_money(
        contract["parts_allowance_total_cents"], 500000, "parts_allowance_total_cents"
    )
    assert_parts_allowance_identity(
        contract, rows_of(api.list_part_orders(CONTRACT_ADMIN, service_call_id=call_id))
    )

    assert_fields(read_call(api, call_id), status="PARTS_HOLD", parts_hold_count=1)
    assert_fields(
        read_equipment(api, fleet["equipment_ids"][0]), support_status="SUPPORTED"
    )
    assert_null_fields(read_equipment(api, fleet["equipment_ids"][0]), "eos_notified_at")


def test_new_sourcing_is_refused_on_an_obsolete_line_despite_full_new_stock(api):
    """
    The violated side: the same OBSOLETE line refuses a NEW hold with
    ERR_PART_SOURCE_UNAVAILABLE even though five new units are on the shelf, and the
    refusal creates no order and moves no bucket or allowance.

    PRD §3.7: "The source must be permitted for the part's `lifecycle_status`: once a
    part is `OBSOLETE`, `NEW` sourcing is refused with `ERR_PART_SOURCE_UNAVAILABLE`,
    and refurbished or loaner sourcing must be used instead."

    Design: Difficulty/cross_entity_state_dependency/new_part_sourcing_depends_on_part_catalog_lifecycle
    """
    fleet = _obsolete_belt_with_one_call_on_site(api)
    part_id = fleet["part"]["id"]
    call_id = fleet["call"]["id"]

    response = api.place_parts_hold(
        call_id,
        parts_hold_payload(part_id, qty=1, source="NEW"),
        technician_headers(fleet["technician_id"]),
    )
    validate_error(response, ERR_PART_SOURCE_UNAVAILABLE, 422)

    assert rows_of(api.list_part_orders(CONTRACT_ADMIN, service_call_id=call_id)) == []

    part = read_part(api, part_id)
    assert_fields(
        part,
        lifecycle_status="OBSOLETE",
        on_hand_qty=5,
        refurb_on_hand_qty=2,
        allocated_qty=0,
    )
    assert_part_inventory_identity(
        part, rows_of(api.list_part_orders(CONTRACT_ADMIN, part_id=part_id))
    )

    contract = read_contract(api, fleet["contract_id"])
    assert_money(
        contract["parts_allowance_remaining_cents"],
        500000,
        "parts_allowance_remaining_cents",
    )
    assert_parts_allowance_identity(
        contract, rows_of(api.list_part_orders(CONTRACT_ADMIN, service_call_id=call_id))
    )

    assert_fields(read_call(api, call_id), status="ON_SITE", parts_hold_count=0)
