"""
Teardown paths that must give back exactly what they took: cancelling a part
allocation returns the allowance money and the stock unit to the bucket it left, and
cancelling a preventive visit returns the technician's committed minutes.

Each test captures the ledger before the forward posting, after it, and after the
compensating action, and checks the standing identities at every one of those points.

Each test builds its whole world through declared endpoints and drives the logical
clock itself, because the database is empty when the test starts.
"""

from decimal import Decimal

from test_helpers import (
    CONTRACT_ADMIN,
    SERVICE_COORDINATOR,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_technician_capacity_identity,
    assert_two_decimals,
    assignment_for_visit,
    build_fleet,
    call_on_site,
    expected_pm_compliance_pct,
    get_success_data,
    new_part,
    part_order_cancel_payload,
    place_hold,
    preventive_visit_payload,
    read_call,
    read_contract,
    read_part,
    read_part_order,
    read_technician,
    read_visit,
    rows_of,
    schedule_visit,
    set_clock,
    technician_headers,
    visit_cancel_payload,
)


def _call_on_site_with_a_stocked_belt(api):
    """
    A MINOR call sitting ON_SITE on the only treadmill of a GOLD/FULL contract, with a
    BELT-900 line carrying five new and three refurbished units.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T08:00:00Z",
        serials=["SN-CI-1"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )
    fleet["technician_id"] = fleet["technician_ids"][0]
    fleet["part"] = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-900",
        category="WEAR",
        unit_price_cents=32000,
        is_critical_spare=False,
        initial_on_hand_qty=5,
        initial_refurb_qty=3,
    )
    fleet["call"] = call_on_site(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        fleet["technician_id"],
        "2026-08-19T08:00:00Z",
        severity="MINOR",
        symptom_code="BELT_NOISE",
    )
    return fleet


def _orders_of(api, part_id):
    return rows_of(api.list_part_orders(CONTRACT_ADMIN, part_id=part_id))


def test_cancelling_a_refurbished_allocation_returns_the_money_and_the_refurb_unit(api):
    """
    A refurbished hold draws 19200 cents of allowance and takes one unit out of the
    refurbished bucket; cancelling it credits the allowance back before zeroing the
    order's money, and returns the unit to the refurbished bucket rather than to new
    stock, leaving both standing identities true at all three points.

    PRD §3.7: "The stock movement is reversed into **the same bucket it came from**:
    `on_hand_qty` for a `NEW` order, `refurb_on_hand_qty` for a `REFURBISHED` or
    `LOANER_SWAP` order, and `allocated_qty` falls by `qty`."

    Design: Difficulty/compensating_invariant/part_order_cancel_restores_allowance_and_the_originating_bucket
    """
    fleet = _call_on_site_with_a_stocked_belt(api)
    contract_id = fleet["contract_id"]
    part_id = fleet["part"]["id"]
    call_id = fleet["call"]["id"]

    before_contract = read_contract(api, contract_id)
    assert_money(
        before_contract["parts_allowance_remaining_cents"],
        500000,
        "remaining before hold",
    )
    assert_money(
        before_contract["parts_allowance_total_cents"], 500000, "total before hold"
    )
    before_part = read_part(api, part_id)
    assert_fields(before_part, on_hand_qty=5, refurb_on_hand_qty=3, allocated_qty=0)
    assert_parts_allowance_identity(before_contract, _orders_of(api, part_id))
    assert_part_inventory_identity(before_part, _orders_of(api, part_id))

    order = place_hold(
        api, call_id, fleet["technician_id"], part_id, qty=1, source="REFURBISHED"
    )
    assert_fields(order, status="ALLOCATED", source="REFURBISHED", qty=1)
    assert_money(order["list_total_cents"], 19200, "list_total_cents")
    assert_money(order["allowance_draw_cents"], 19200, "allowance_draw_cents")
    assert_money(order["club_billable_cents"], 0, "club_billable_cents")
    assert_fields(read_call(api, call_id), status="PARTS_HOLD", parts_hold_count=1)

    held_contract = read_contract(api, contract_id)
    assert_money(
        held_contract["parts_allowance_remaining_cents"], 480800, "remaining after hold"
    )
    held_part = read_part(api, part_id)
    assert_fields(held_part, on_hand_qty=5, refurb_on_hand_qty=2, allocated_qty=1)
    assert_parts_allowance_identity(held_contract, _orders_of(api, part_id))
    assert_part_inventory_identity(held_part, _orders_of(api, part_id))

    cancelled = get_success_data(
        api.cancel_part_order(
            order["id"],
            part_order_cancel_payload(reason="Wrong belt width delivered"),
            SERVICE_COORDINATOR,
        )
    )
    assert_fields(
        cancelled,
        status="CANCELLED",
        cancellation_reason="Wrong belt width delivered",
        source="REFURBISHED",
        qty=1,
    )
    assert_money(cancelled["allowance_draw_cents"], 0, "draw after cancel")
    assert_money(cancelled["club_billable_cents"], 0, "billable after cancel")

    restored_contract = read_contract(api, contract_id)
    assert_money(
        restored_contract["parts_allowance_remaining_cents"],
        500000,
        "remaining after cancel",
    )
    assert_money(
        restored_contract["parts_allowance_total_cents"], 500000, "total after cancel"
    )
    restored_part = read_part(api, part_id)
    assert_fields(restored_part, on_hand_qty=5, refurb_on_hand_qty=3, allocated_qty=0)
    assert_parts_allowance_identity(restored_contract, _orders_of(api, part_id))
    assert_part_inventory_identity(restored_part, _orders_of(api, part_id))

    resumed = get_success_data(
        api.resume_service_call(call_id, technician_headers(fleet["technician_id"]))
    )
    assert_fields(resumed, status="ON_SITE", parts_hold_count=1)


def test_installing_the_same_allocation_consumes_the_unit_and_keeps_the_draw(api):
    """
    The contrast that shows the cancellation really is a compensation: installing the
    identical refurbished order also clears allocated_qty, but it restores no stock
    bucket and returns no allowance money, so the drawn 19200 cents stay drawn.

    PRD §3.7: "Installation sets `status` to `INSTALLED`, stamps `installed_at`, and
    reduces `allocated_qty` by `qty` **without** restoring any stock bucket — the unit
    was physically consumed."

    Design: Difficulty/compensating_invariant/part_order_cancel_restores_allowance_and_the_originating_bucket
    """
    fleet = _call_on_site_with_a_stocked_belt(api)
    contract_id = fleet["contract_id"]
    part_id = fleet["part"]["id"]
    call_id = fleet["call"]["id"]

    order = place_hold(
        api, call_id, fleet["technician_id"], part_id, qty=1, source="REFURBISHED"
    )
    assert_money(order["allowance_draw_cents"], 19200, "allowance_draw_cents")
    assert_null_fields(order, "installed_at")
    held_contract = read_contract(api, contract_id)
    assert_money(
        held_contract["parts_allowance_remaining_cents"], 480800, "remaining after hold"
    )
    assert_fields(
        read_part(api, part_id), on_hand_qty=5, refurb_on_hand_qty=2, allocated_qty=1
    )

    set_clock(api, "2026-08-19T09:00:00Z")
    installed = get_success_data(
        api.install_part_order(order["id"], technician_headers(fleet["technician_id"]))
    )
    assert_fields(installed, status="INSTALLED", source="REFURBISHED", qty=1)
    assert_instant(installed["installed_at"], "2026-08-19T09:00:00Z", "installed_at")
    assert_money(installed["allowance_draw_cents"], 19200, "draw after install")
    assert_money(installed["club_billable_cents"], 0, "billable after install")

    after_contract = read_contract(api, contract_id)
    assert_money(
        after_contract["parts_allowance_remaining_cents"],
        480800,
        "remaining after install",
    )
    assert_money(
        after_contract["parts_allowance_total_cents"], 500000, "total after install"
    )
    after_part = read_part(api, part_id)
    assert_fields(after_part, on_hand_qty=5, refurb_on_hand_qty=2, allocated_qty=0)
    assert_parts_allowance_identity(after_contract, _orders_of(api, part_id))
    assert_part_inventory_identity(after_part, _orders_of(api, part_id))

    assert_fields(read_part_order(api, order["id"]), status="INSTALLED")

    resumed = get_success_data(
        api.resume_service_call(call_id, technician_headers(fleet["technician_id"]))
    )
    assert_fields(resumed, status="ON_SITE", parts_hold_count=1)


def _two_visits_holding_one_hundred_eighty_minutes(api):
    """
    One technician holding two 90-minute preventive visits on the same contract — V1
    from 08:00 to 09:30 and V2 from 10:15 to 11:45 — so committed_minutes is 180.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T07:00:00Z",
        club_kwargs={"max_concurrent_visits": 3},
        serials=["SN-CM-1", "SN-CM-2"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )
    fleet["technician_id"] = fleet["technician_ids"][0]
    fleet["first_visit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-19T08:00:00Z",
        "2026-08-19T09:30:00Z",
        fleet["technician_id"],
    )
    fleet["second_visit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][1],
        "2026-08-19T10:15:00Z",
        "2026-08-19T11:45:00Z",
        fleet["technician_id"],
    )
    return fleet


def _assignments_of(api, technician_id):
    return rows_of(
        api.list_technician_assignments(CONTRACT_ADMIN, technician_id=technician_id)
    )


def test_cancelling_a_scheduled_visit_gives_back_exactly_its_ninety_minutes(api):
    """
    Cancelling one of the two visits releases its reservation with release_reason
    VISIT_CANCELLED and drops committed_minutes from 180 back to the 90 the surviving
    visit accounts for, while both compliance counters and pm_compliance_pct stay put.

    PRD §3.4: "**Cancelling** a `SCHEDULED` visit records the supplied `reason` into
    `cancellation_reason`, moves `visit_status` to `CANCELLED`, releases the `RESERVED`
    assignment with `release_reason` `VISIT_CANCELLED` and returns the technician's
    minutes — and touches neither `pm_visits_completed_count` nor
    `pm_visits_missed_count`, so `pm_compliance_pct` does not move at all."

    Design: Difficulty/compensating_invariant/visit_cancel_returns_the_technician_capacity_minutes
    """
    fleet = _two_visits_holding_one_hundred_eighty_minutes(api)
    technician_id = fleet["technician_id"]
    contract_id = fleet["contract_id"]
    first_visit_id = fleet["first_visit"]["id"]

    before_technician = read_technician(api, technician_id)
    assert before_technician["committed_minutes"] == 180
    assert_technician_capacity_identity(
        before_technician, _assignments_of(api, technician_id)
    )
    before_contract = read_contract(api, contract_id)
    assert_fields(before_contract, pm_visits_completed_count=0, pm_visits_missed_count=0)
    assert_two_decimals(
        before_contract["pm_compliance_pct"],
        expected_pm_compliance_pct(0, 0),
        "pm_compliance_pct before cancel",
    )

    cancelled = get_success_data(
        api.cancel_visit(
            first_visit_id,
            visit_cancel_payload(reason="Club closed the cardio floor that morning"),
            SERVICE_COORDINATOR,
        )
    )
    assert_fields(
        cancelled,
        visit_status="CANCELLED",
        cancellation_reason="Club closed the cardio floor that morning",
        planned_minutes=90,
    )

    released = assignment_for_visit(api, first_visit_id)
    assert_fields(
        released, status="RELEASED", release_reason="VISIT_CANCELLED", planned_minutes=90
    )
    assert_fields(assignment_for_visit(api, fleet["second_visit"]["id"]), status="RESERVED")

    after_technician = read_technician(api, technician_id)
    assert after_technician["committed_minutes"] == 90
    assert_technician_capacity_identity(
        after_technician, _assignments_of(api, technician_id)
    )

    after_contract = read_contract(api, contract_id)
    assert_fields(after_contract, pm_visits_completed_count=0, pm_visits_missed_count=0)
    assert_two_decimals(
        after_contract["pm_compliance_pct"], Decimal("100.00"), "pm_compliance_pct"
    )
    assert_fields(read_visit(api, fleet["second_visit"]["id"]), visit_status="SCHEDULED")


def test_the_minutes_returned_by_a_cancellation_are_immediately_bookable_again(api):
    """
    The returned minutes are real capacity, not just a smaller number: the very window
    the cancelled visit occupied can be booked again for the same technician, taking
    committed_minutes back to 180 across two live reservations and one released one.

    PRD §2.11: "Assignments in `RELEASED` or `COMPLETED` contribute nothing, which is
    why releasing a reservation frees its slot immediately."

    Design: Difficulty/compensating_invariant/visit_cancel_returns_the_technician_capacity_minutes
    """
    fleet = _two_visits_holding_one_hundred_eighty_minutes(api)
    technician_id = fleet["technician_id"]

    get_success_data(
        api.cancel_visit(
            fleet["first_visit"]["id"],
            visit_cancel_payload(reason="Club closed the cardio floor that morning"),
            SERVICE_COORDINATOR,
        )
    )
    freed_technician = read_technician(api, technician_id)
    assert freed_technician["committed_minutes"] == 90
    assert_technician_capacity_identity(
        freed_technician, _assignments_of(api, technician_id)
    )

    rebooked = get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                fleet["contract_id"],
                fleet["equipment_ids"][0],
                "2026-08-19T08:00:00Z",
                "2026-08-19T09:30:00Z",
                technician_id,
            ),
            SERVICE_COORDINATOR,
        ),
        201,
    )
    assert_fields(rebooked, visit_status="SCHEDULED", planned_minutes=90)
    assert_instant(rebooked["window_start"], "2026-08-19T08:00:00Z", "window_start")
    assert_instant(rebooked["window_end"], "2026-08-19T09:30:00Z", "window_end")

    new_assignment = assignment_for_visit(api, rebooked["id"])
    assert_fields(new_assignment, status="RESERVED", planned_minutes=90)
    assert_instant(new_assignment["start_at"], "2026-08-19T08:00:00Z", "start_at")

    final_technician = read_technician(api, technician_id)
    assert final_technician["committed_minutes"] == 180
    assignments = _assignments_of(api, technician_id)
    assert len(assignments) == 3, f"the released row must survive, got {len(assignments)}"
    statuses = sorted(row["status"] for row in assignments)
    assert statuses == ["RELEASED", "RESERVED", "RESERVED"], statuses
    assert_technician_capacity_identity(final_technician, assignments)

    assert_fields(read_visit(api, fleet["first_visit"]["id"]), visit_status="CANCELLED")
