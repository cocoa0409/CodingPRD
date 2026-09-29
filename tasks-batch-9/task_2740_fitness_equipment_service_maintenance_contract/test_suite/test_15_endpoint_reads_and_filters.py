"""
Endpoint behaviour: computed reads, cross-aggregate filters and paging windows.

Every test builds its own world from scratch through declared endpoints — the harness
restarts the API with an empty database before each test — and sets the logical clock
explicitly whenever the scenario names an instant.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    DEFAULT_LIMIT,
    ERR_TECHNICIAN_OFF_DUTY,
    PARTS_PLANNER,
    SERVICE_COORDINATOR,
    assert_created_at_ascending,
    assert_fields,
    assert_instant,
    assert_money,
    assert_pagination_meta,
    assert_technician_capacity_identity,
    assignment_for_call,
    build_fleet,
    call_on_site,
    contract_version,
    credit_reconciliation_payload,
    dispatch_call,
    dispatch_payload,
    duty_status_payload,
    get_success_data,
    inventory_adjustment_payload,
    new_part,
    open_call,
    place_hold,
    read_equipment,
    read_part,
    read_technician,
    resolve_payload,
    rows_of,
    set_clock,
    technician_headers,
    validate_error,
    validate_paginated,
)


def test_credit_summary_partitions_events_by_status_without_advancing_the_contract(api):
    """
    The credit ledger read is derived on every call and repeats itself for every permitted role.

    PRD: "A separate computed read exposes the standing ledger for a contract to a
    `ContractAdministrator`, `ClubManager` or `ServiceCoordinator`: `contract_id`,
    `credit_provisional_cents`, `credit_accrued_cents`, `credit_forgone_cents`,
    `credit_cap_cents`, and the `open_event_count`, `closed_event_count` and
    `reconciled_event_count` behind them."

    Design: Corner/endpoints/credit_summary_is_a_pure_read_that_partitions_events_by_status
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-CS-A", "SN-CS-B"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{}],
    )
    contract_id = fleet["contract_id"]
    e1, e2 = fleet["equipment_ids"]
    t1 = fleet["technician_ids"][0]

    call_1 = call_on_site(api, contract_id, e1, t1, "2026-08-15T08:00:00Z")
    set_clock(api, "2026-08-15T14:00:00Z")
    get_success_data(
        api.resolve_service_call(
            call_1["id"], resolve_payload(), technician_headers(t1)
        )
    )

    # A club may read its own ledger: one CLOSED event, nothing reconciled yet.
    before = get_success_data(api.get_credit_summary(contract_id, fleet["manager"]))
    assert_fields(
        before, open_event_count=0, closed_event_count=1, reconciled_event_count=0
    )
    assert_money(before["credit_provisional_cents"], 4800, "provisional at closure")
    assert_money(before["credit_accrued_cents"], 0, "accrued before reconciliation")

    set_clock(api, "2026-08-15T15:00:00Z")
    open_call(api, contract_id, e2, severity="MINOR", symptom_code="CONSOLE_DIM")

    version_before = contract_version(api, contract_id)
    run = get_success_data(
        api.reconcile_credits(
            contract_id,
            credit_reconciliation_payload("2026-08", version_before),
            CONTRACT_ADMIN,
        )
    )
    assert run["contract_version"] == version_before + 1, (
        "the reconciliation increments the contract version by exactly one"
    )

    first = get_success_data(api.get_credit_summary(contract_id, CONTRACT_ADMIN))
    second = get_success_data(api.get_credit_summary(contract_id, SERVICE_COORDINATOR))

    assert first["contract_id"] == contract_id
    assert_money(first["credit_provisional_cents"], 4800, "provisional after posting")
    assert_money(first["credit_accrued_cents"], 4800, "accrued after posting")
    assert_money(first["credit_forgone_cents"], 0, "forgone credit")
    assert_money(first["credit_cap_cents"], 37500, "credit cap")
    assert_fields(
        first, open_event_count=1, closed_event_count=0, reconciled_event_count=1
    )
    for field in (
        "contract_id",
        "credit_provisional_cents",
        "credit_accrued_cents",
        "credit_forgone_cents",
        "credit_cap_cents",
        "open_event_count",
        "closed_event_count",
        "reconciled_event_count",
    ):
        assert second[field] == first[field], (
            f"{field} differed between two consecutive summary reads"
        )

    assert contract_version(api, contract_id) == version_before + 1, (
        "reading the summary twice must not advance the contract version"
    )


def test_a_dispatched_call_with_a_parts_hold_is_reachable_from_every_child_filter(api):
    """
    Every child row a call spawns is findable through the list filter naming its parent.

    PRD: "Assignments may be listed and filtered by `technician_id`, `service_call_id`,
    `preventive_visit_id` and `status`."

    Design: Corner/endpoints/linked_child_rows_are_reachable_from_their_parents_filters
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-LK-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{}],
    )
    contract_id = fleet["contract_id"]
    e1 = fleet["equipment_ids"][0]
    t1 = fleet["technician_ids"][0]
    belt = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=4,
    )
    unrelated = new_part(
        api,
        fleet["model_id"],
        part_number="DECK-STD",
        category="STRUCTURAL",
        unit_price_cents=12000,
        initial_on_hand_qty=2,
    )

    call = call_on_site(
        api,
        contract_id,
        e1,
        t1,
        "2026-08-15T08:00:00Z",
        severity="MAJOR",
        symptom_code="BELT_FRAY",
    )
    order = place_hold(api, call["id"], t1, belt["id"], 1, "NEW")

    # The calendar reservation, reached from the call it serves.
    rows, meta = validate_paginated(
        api.list_technician_assignments(SERVICE_COORDINATOR, service_call_id=call["id"])
    )
    assert_pagination_meta(meta, DEFAULT_LIMIT, 0, 1, False)
    assignment = rows[0]
    assert_fields(
        assignment,
        technician_id=t1,
        service_call_id=call["id"],
        status="CONFIRMED",
        planned_minutes=120,
    )
    assert assignment["preventive_visit_id"] is None, (
        "a call assignment must not name a preventive visit"
    )

    # The same row, reached from the technician side with a status filter.
    by_technician, meta_t = validate_paginated(
        api.list_technician_assignments(
            CONTRACT_ADMIN, technician_id=t1, status="CONFIRMED"
        )
    )
    assert_pagination_meta(meta_t, DEFAULT_LIMIT, 0, 1, False)
    assert by_technician[0]["id"] == assignment["id"]

    # The part order, reached from the call.
    orders, meta_o = validate_paginated(
        api.list_part_orders(CONTRACT_ADMIN, service_call_id=call["id"])
    )
    assert_pagination_meta(meta_o, DEFAULT_LIMIT, 0, 1, False)
    assert_fields(
        orders[0],
        id=order["id"],
        part_id=belt["id"],
        status="ALLOCATED",
        source="NEW",
        qty=1,
    )

    # The downtime event, reached from the contract with a status filter.
    events, meta_e = validate_paginated(
        api.list_downtime_events(CONTRACT_ADMIN, contract_id=contract_id, status="OPEN")
    )
    assert_pagination_meta(meta_e, DEFAULT_LIMIT, 0, 1, False)
    assert_fields(
        events[0],
        contract_id=contract_id,
        equipment_id=e1,
        service_call_id=call["id"],
        status="OPEN",
    )

    # A filter naming an unrelated parent returns an empty page, not everything.
    empty, meta_x = validate_paginated(
        api.list_part_orders(CONTRACT_ADMIN, part_id=unrelated["id"])
    )
    assert empty == [], f"expected no orders for an unused part, got {empty}"
    assert_pagination_meta(meta_x, DEFAULT_LIMIT, 0, 0, False)


def test_going_off_duty_stops_new_routing_but_leaves_booked_work_untouched(api):
    """
    An off-duty technician is skipped by the router and refused by name, yet keeps their minutes.

    PRD: "Going off duty removes the technician from automatic routing and causes any
    dispatch or visit that names them explicitly to be refused with
    `ERR_TECHNICIAN_OFF_DUTY`, but it does **not** disturb work already booked: existing
    assignments in `RESERVED` or `CONFIRMED` remain exactly as they are and continue to
    occupy the technician's calendar and their `committed_minutes`."

    Design: Corner/endpoints/taking_a_technician_off_duty_removes_them_from_routing_only
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        serials=["SN-DT-A", "SN-DT-B", "SN-DT-C", "SN-DT-D"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes"}, {"full_name": "Ilan Cruz"}],
    )
    contract_id = fleet["contract_id"]
    e1, e2, e3, e4 = fleet["equipment_ids"]
    t1, t2 = fleet["technician_ids"]

    # Ilan carries a three-hour CRITICAL booking; Dana carries a two-hour MAJOR booking,
    # which leaves Dana the lighter — and therefore the preferred — candidate.
    critical = open_call(
        api, contract_id, e1, severity="CRITICAL", symptom_code="MOTOR_DEAD"
    )
    dispatch_call(api, critical["id"], "2026-08-15T08:00:00Z", t2)
    major = open_call(api, contract_id, e2, severity="MAJOR", symptom_code="BELT_NOISE")
    dispatch_call(api, major["id"], "2026-08-15T08:00:00Z", t1)
    assert read_technician(api, t1)["committed_minutes"] == 120
    assert read_technician(api, t2)["committed_minutes"] == 180

    booked = assignment_for_call(api, major["id"])
    get_success_data(
        api.set_duty_status(t1, duty_status_payload("OFF_DUTY"), CONTRACT_ADMIN)
    )

    # Naming the off-duty technician explicitly is refused.
    named = open_call(api, contract_id, e4, severity="MINOR", symptom_code="CONSOLE_DIM")
    validate_error(
        api.dispatch_service_call(
            named["id"],
            dispatch_payload("2026-08-15T13:00:00Z", t1),
            SERVICE_COORDINATOR,
        ),
        ERR_TECHNICIAN_OFF_DUTY,
    )

    # An unnamed dispatch routes past the off-duty technician to the busier one.
    routed = open_call(api, contract_id, e3, severity="MINOR", symptom_code="ROLLER_WEAR")
    dispatched = dispatch_call(api, routed["id"], "2026-08-15T13:00:00Z")
    assert dispatched["assigned_technician_id"] == t2, (
        "routing must skip the off-duty technician even though they hold fewer minutes"
    )
    new_assignment = assignment_for_call(api, routed["id"])
    assert_fields(new_assignment, technician_id=t2, status="RESERVED", planned_minutes=60)
    assert_instant(new_assignment["start_at"], "2026-08-15T13:00:00Z", "start_at")
    assert_instant(new_assignment["end_at"], "2026-08-15T14:00:00Z", "end_at")
    assert read_technician(api, t2)["committed_minutes"] == 240

    # The off-duty technician's own booking is exactly as it was.
    still_booked = assignment_for_call(api, major["id"])
    assert_fields(
        still_booked,
        id=booked["id"],
        technician_id=t1,
        status="RESERVED",
        planned_minutes=120,
    )
    assert_instant(still_booked["start_at"], "2026-08-15T08:00:00Z", "start_at")
    off_duty = read_technician(api, t1)
    assert_fields(off_duty, duty_status="OFF_DUTY", committed_minutes=120)
    assert_technician_capacity_identity(
        off_duty, rows_of(api.list_technician_assignments(CONTRACT_ADMIN, technician_id=t1))
    )

    # Coming back on duty neither doubles nor drops those minutes.
    get_success_data(
        api.set_duty_status(t1, duty_status_payload("ON_DUTY"), SERVICE_COORDINATOR)
    )
    back = read_technician(api, t1)
    assert_fields(back, duty_status="ON_DUTY", committed_minutes=120)


def test_draining_the_last_refurbished_unit_only_obsoletes_a_part_already_announced(api):
    """
    The refurbished bucket hitting zero completes an announced part's slide and nothing else.

    PRD: "A part already announced can also slide the rest of the way: an inventory
    adjustment that drives `refurb_on_hand_qty` to exactly `0` moves
    `END_OF_SUPPORT_ANNOUNCED` → `OBSOLETE`."

    Design: Corner/endpoints/draining_the_last_refurbished_unit_only_obsoletes_an_announced_part
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T09:00:00Z",
        serials=["SN-OB-1"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    contract_id = fleet["contract_id"]
    e1 = fleet["equipment_ids"][0]
    announced = new_part(
        api,
        fleet["model_id"],
        part_number="MOTOR-A",
        category="ELECTRONIC",
        unit_price_cents=45000,
        is_critical_spare=True,
        initial_on_hand_qty=0,
        initial_refurb_qty=1,
    )
    untouched = new_part(
        api,
        fleet["model_id"],
        part_number="GRIP-PAD",
        category="CONSUMABLE",
        unit_price_cents=1500,
        is_critical_spare=True,
        initial_on_hand_qty=5,
        initial_refurb_qty=1,
    )
    assert_fields(read_equipment(api, e1), support_status="SUPPORTED")

    # Refurbished stock survives the declaration, so the part is only announced.
    declared = get_success_data(
        api.declare_end_of_support(announced["id"], PARTS_PLANNER)
    )
    assert_fields(declared, lifecycle_status="END_OF_SUPPORT_ANNOUNCED", refurb_on_hand_qty=1)
    assert_instant(declared["eos_declared_at"], "2026-08-15T09:00:00Z", "eos_declared_at")
    notified = read_equipment(api, e1)
    assert_fields(notified, support_status="END_OF_SUPPORT_ANNOUNCED", replacement_recommended=False)
    assert_instant(notified["eos_notified_at"], "2026-08-15T09:00:00Z", "eos_notified_at")

    # Emptying the refurbished bucket of a part that was never announced changes nothing.
    still_active = get_success_data(
        api.adjust_inventory(
            untouched["id"],
            inventory_adjustment_payload(refurb_qty_delta=-1),
            PARTS_PLANNER,
        )
    )
    assert_fields(still_active, lifecycle_status="ACTIVE", refurb_on_hand_qty=0, on_hand_qty=5)
    assert still_active["eos_declared_at"] is None, (
        "an inventory adjustment must not stamp eos_declared_at"
    )
    assert_fields(read_equipment(api, e1), support_status="END_OF_SUPPORT_ANNOUNCED")

    # The same adjustment on the announced part completes the slide and strands the fleet.
    set_clock(api, "2026-08-15T11:00:00Z")
    obsoleted = get_success_data(
        api.adjust_inventory(
            announced["id"],
            inventory_adjustment_payload(refurb_qty_delta=-1),
            PARTS_PLANNER,
        )
    )
    assert_fields(obsoleted, lifecycle_status="OBSOLETE", refurb_on_hand_qty=0)
    assert_instant(obsoleted["eos_declared_at"], "2026-08-15T09:00:00Z", "eos_declared_at")
    stranded = read_equipment(api, e1)
    assert_fields(stranded, support_status="UNSUPPORTED", replacement_recommended=False)
    assert_instant(stranded["eos_notified_at"], "2026-08-15T11:00:00Z", "eos_notified_at")
    assert_fields(read_part(api, untouched["id"]), lifecycle_status="ACTIVE")
    rolled_up = get_success_data(api.get_contract(contract_id, CONTRACT_ADMIN))
    assert_fields(
        rolled_up,
        obsolete_unit_count=1,
        replacement_candidate_count=0,
        fleet_renewal_risk="LOW",
    )


def test_registering_three_technicians_supports_every_filter_and_a_one_row_page(api):
    """
    Technician registration, filtered listing, a paging window and the live single read.

    PRD: "Technicians may be listed and filtered by `region_code`, `duty_status` and
    `is_safety_inspector`, and a single-technician read always shows the live
    `committed_minutes`."

    Design: Corner/endpoints/technician_crud_round_trip_with_filters_and_a_paging_window
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-TC-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[
            {"full_name": "Dana Reyes", "region_code": "NW"},
            {"full_name": "Ilan Cruz", "region_code": "NW", "is_safety_inspector": True},
            {
                "full_name": "Mira Osei",
                "region_code": "SW",
                "skill_categories": ["BIKE"],
            },
        ],
    )
    t1, t2, t3 = fleet["technician_ids"]

    # Registration defaults, straight off the created row.
    assert_fields(
        fleet["technicians"][0],
        full_name="Dana Reyes",
        region_code="NW",
        duty_status="ON_DUTY",
        committed_minutes=0,
        is_safety_inspector=False,
    )

    north, north_meta = validate_paginated(
        api.list_technicians(CONTRACT_ADMIN, region_code="NW")
    )
    assert_pagination_meta(north_meta, DEFAULT_LIMIT, 0, 2, False)
    assert [row["id"] for row in north] == [t1, t2]
    assert_created_at_ascending(north)

    south, south_meta = validate_paginated(
        api.list_technicians(SERVICE_COORDINATOR, region_code="SW")
    )
    assert_pagination_meta(south_meta, DEFAULT_LIMIT, 0, 1, False)
    assert south[0]["id"] == t3

    inspectors, inspector_meta = validate_paginated(
        api.list_technicians(CONTRACT_ADMIN, is_safety_inspector="true")
    )
    assert_pagination_meta(inspector_meta, DEFAULT_LIMIT, 0, 1, False)
    assert inspectors[0]["id"] == t2

    # A one-row window over the middle of the roster.
    window, window_meta = validate_paginated(
        api.list_technicians(CONTRACT_ADMIN, limit=1, offset=1)
    )
    assert_pagination_meta(window_meta, 1, 1, 3, True)
    assert [row["id"] for row in window] == [t2]

    # The duty filter tracks a live change.
    get_success_data(
        api.set_duty_status(t3, duty_status_payload("OFF_DUTY"), CONTRACT_ADMIN)
    )
    on_duty, on_duty_meta = validate_paginated(
        api.list_technicians(CONTRACT_ADMIN, duty_status="ON_DUTY")
    )
    assert_pagination_meta(on_duty_meta, DEFAULT_LIMIT, 0, 2, False)
    assert [row["id"] for row in on_duty] == [t1, t2]
    off_duty, off_duty_meta = validate_paginated(
        api.list_technicians(CONTRACT_ADMIN, duty_status="OFF_DUTY")
    )
    assert_pagination_meta(off_duty_meta, DEFAULT_LIMIT, 0, 1, False)
    assert off_duty[0]["id"] == t3

    # The single-technician read carries the minutes a dispatch just committed.
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], "2026-08-15T10:00:00Z", t1)
    assert_fields(read_technician(api, t1), committed_minutes=120, duty_status="ON_DUTY")
    assert_fields(read_technician(api, t2), committed_minutes=0)
