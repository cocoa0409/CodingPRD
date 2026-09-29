"""The two widest cascades: acceptance on the final pass, and the vibration hold."""

from test_helpers import (
    USER_CX_TECH,
    USER_CX_WITNESS,
    approve_hazmat_permit,
    assert_capacity_pool_identity,
    assert_money,
    book_and_confirm_allocation,
    create_amenity,
    file_hazmat_permit,
    get_allocation,
    get_building,
    get_lease,
    get_permit,
    get_phase,
    get_project,
    get_reservation,
    hold_phase,
    record_result,
    reserve_capacity,
    schedule_phase,
    schedule_script,
    setup_project_at_substantial_completion,
    setup_project_with_phases,
    start_phase,
    utc,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
LEASE = {"delivery_deadline": "2026-12-31T00:00:00Z"}

# The chain of the cascade case: each package waits on the one before it.
CHAIN = [
    {
        "premium_class": "LAB_MEP",
        "work_class": "QUIET",
        "hard_cost_usd": 50000.00,
        "restoration_cost_usd": 30000.00,
    },
    {
        "premium_class": "LAB_MEP",
        "work_class": "QUIET",
        "hard_cost_usd": 40000.00,
        "restoration_cost_usd": 20000.00,
        "predecessor_index": 0,
    },
    {
        "premium_class": "CLEANROOM",
        "work_class": "QUIET",
        "hard_cost_usd": 30000.00,
        "restoration_cost_usd": 15000.00,
        "predecessor_index": 1,
    },
    {
        "premium_class": "SHELL",
        "work_class": "QUIET",
        "hard_cost_usd": 20000.00,
        "restoration_cost_usd": 10000.00,
        "predecessor_index": 2,
    },
]

FIRST_WINDOW = (utc(2026, 8, 5), utc(2026, 8, 10))
SECOND_WINDOW = (utc(2026, 8, 20), utc(2026, 8, 25))
THIRD_WINDOW = (utc(2026, 9, 5), utc(2026, 9, 10))
BOOKING_WINDOW = (utc(2026, 9, 15, 13), utc(2026, 9, 15, 17))

HOLD_REASON = (
    "Occupied tenant on floor 2 reports velocity above VC_C during core drilling"
)


def _qc_project_ready_for_its_scripts(api):
    """An analytical QC project at substantial completion, with capacity reserved
    and a hazardous material permit already approved."""
    bundle = setup_project_at_substantial_completion(
        api,
        [
            {
                "premium_class": "LAB_MEP",
                "work_class": "QUIET",
                "hard_cost_usd": 50000.00,
                "restoration_cost_usd": 30000.00,
            }
        ],
        allowance_psf=70.00,
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides={"base_rent_psf": 95.00, **LEASE},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 12000,
            "design_power_kw": 180,
            "scope_summary": "QC lab fit-out, floor 2",
        },
    )
    bundle["reservation"] = reserve_capacity(
        api, bundle["project"]["id"], bundle["building"]["id"], 12000.00, 180.00
    )
    permit = file_hazmat_permit(
        api,
        bundle["project"]["id"],
        bundle["premises_floor"]["id"],
        "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE",
        100.00,
        1,
        headers=bundle["tenant_headers"],
    )
    bundle["permit"] = approve_hazmat_permit(api, permit["id"])
    return bundle


def _pass_script(api, project_id, script_type, scheduled_for):
    record = schedule_script(api, project_id, script_type, USER_CX_TECH, scheduled_for)
    return record_result(api, record["id"], "PASS", USER_CX_WITNESS, 1.0)


def _chained_project_with_a_booking(api):
    """Four chained packages, the first running, plus a confirmed conference booking."""
    bundle = setup_project_with_phases(
        api,
        CHAIN,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides={"base_rent_psf": 105.00, **LEASE},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 15000,
            "design_power_kw": 220,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    phases = bundle["phases"]
    start_phase(api, phases[0]["id"], *FIRST_WINDOW)
    schedule_phase(api, phases[1]["id"], *SECOND_WINDOW)
    schedule_phase(api, phases[2]["id"], *THIRD_WINDOW)
    bundle["amenity"] = create_amenity(
        api,
        bundle["building"]["id"],
        2,
        name="Level 2 Conference Suite",
        amenity_type="CONFERENCE",
        concurrent_capacity=2,
        vibration_sensitive=False,
        utility_draw_kw=5.00,
    )
    bundle["allocation"] = book_and_confirm_allocation(
        api,
        bundle["amenity"]["id"],
        bundle["project"]["id"],
        *BOOKING_WINDOW,
        headcount=12,
    )
    bundle["phases"] = [get_phase(api, p["id"]) for p in phases]
    return bundle


def test_the_final_pass_moves_five_entity_families_in_one_request(api):
    """One recorded result carries the whole deal across four hops.

    The pass that completes the required battery accepts the project, commits
    every reservation it holds, activates its approved hazardous material
    permits, shifts the building's pools from reserved to committed without
    touching what remains available, and carries the lease into occupancy.

    Design: Difficulty/transitive_cascade/commissioning_pass_cascades_project_reservation_permit_building_and_lease
    """
    bundle = _qc_project_ready_for_its_scripts(api)
    project_id = bundle["project"]["id"]
    assert bundle["project"]["required_commissioning_scripts"] == ["IQ", "OQ"]
    before = get_building(api, bundle["building"]["id"])
    assert_money(before["exhaust_reserved_cfm"], 12000.00, "exhaust_reserved_cfm")
    assert_money(before["exhaust_available_cfm"], 68000.00, "exhaust_available_cfm")
    assert_money(before["power_reserved_kw"], 180.00, "power_reserved_kw")
    assert_money(before["power_available_kw"], 620.00, "power_available_kw")

    _pass_script(api, project_id, "IQ", utc(2026, 8, 12, 9))
    final = _pass_script(api, project_id, "OQ", utc(2026, 8, 13, 9))

    assert final["status"] == "PASSED"
    project = get_project(api, project_id)
    assert project["passed_script_count"] == 2
    assert project["construction_status"] == "C_ACCEPTED"
    assert project["accepted_at"] is not None
    assert project["permit_status"] == "P_ISSUED", (
        "the authority's dimension is not part of the cascade"
    )
    assert get_reservation(api, bundle["reservation"]["id"])["status"] == "COMMITTED"
    assert get_permit(api, bundle["permit"]["id"])["status"] == "ACTIVE"
    assert get_lease(api, bundle["lease"]["id"])["status"] == "ACTIVE"

    after = get_building(api, bundle["building"]["id"])
    assert_money(after["exhaust_capacity_total_cfm"], 80000.00, "exhaust total")
    assert_money(after["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(after["exhaust_committed_cfm"], 12000.00, "exhaust_committed_cfm")
    assert_money(after["exhaust_available_cfm"], 68000.00, "exhaust_available_cfm")
    assert_money(after["power_reserved_kw"], 0.00, "power_reserved_kw")
    assert_money(after["power_committed_kw"], 180.00, "power_committed_kw")
    assert_money(after["power_available_kw"], 620.00, "power_available_kw")
    assert_capacity_pool_identity(after)


def test_a_pass_short_of_the_battery_moves_nothing_but_the_counter(api):
    """The cascade is keyed to the count reaching the battery size.

    The first of two required scripts passes and raises the counter, but the
    project, the reservation, the permit and the lease all stay exactly where
    they were, so the four hops cannot be firing on each pass.

    Design: Difficulty/transitive_cascade/commissioning_pass_cascades_project_reservation_permit_building_and_lease
    """
    bundle = _qc_project_ready_for_its_scripts(api)
    project_id = bundle["project"]["id"]

    passed = _pass_script(api, project_id, "IQ", utc(2026, 8, 12, 9))

    assert passed["status"] == "PASSED"
    project = get_project(api, project_id)
    assert project["passed_script_count"] == 1
    assert project["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    assert project["accepted_at"] is None
    assert get_reservation(api, bundle["reservation"]["id"])["status"] == "RESERVED"
    assert get_permit(api, bundle["permit"]["id"])["status"] == "APPROVED"
    assert get_lease(api, bundle["lease"]["id"])["status"] == "EXECUTED"

    building = get_building(api, bundle["building"]["id"])
    assert_money(building["exhaust_reserved_cfm"], 12000.00, "exhaust_reserved_cfm")
    assert_money(building["exhaust_committed_cfm"], 0.00, "exhaust_committed_cfm")
    assert_money(building["power_reserved_kw"], 180.00, "power_reserved_kw")
    assert_money(building["power_committed_kw"], 0.00, "power_committed_kw")


def test_a_hold_reaches_every_package_downstream_of_it_and_the_bookings(api):
    """The hold travels the whole chain, not just one link.

    Holding the second package blocks the third and, through it, the fourth,
    recording for each the state it came from; the package already running is
    left alone, the project suspends and reports risk, and the project's future
    booking is preempted.

    Design: Difficulty/transitive_cascade/phase_hold_cascades_transitive_successors_project_and_amenity_allocations
    """
    bundle = _chained_project_with_a_booking(api)
    first, second, third, fourth = bundle["phases"]
    assert first["status"] == "IN_PROGRESS"
    assert second["status"] == "SCHEDULED"
    assert third["status"] == "SCHEDULED"
    assert fourth["status"] == "DRAFT"
    assert bundle["allocation"]["status"] == "CONFIRMED"

    held = hold_phase(api, second["id"], HOLD_REASON)

    assert held["status"] == "VIBRATION_HOLD"
    assert held["hold_reason"] == HOLD_REASON
    assert held["prior_status"] is None
    downstream = get_phase(api, third["id"])
    assert downstream["status"] == "BLOCKED"
    assert downstream["prior_status"] == "SCHEDULED"
    transitive = get_phase(api, fourth["id"])
    assert transitive["status"] == "BLOCKED", (
        "the successor of a successor is downstream too"
    )
    assert transitive["prior_status"] == "DRAFT"
    untouched = get_phase(api, first["id"])
    assert untouched["status"] == "IN_PROGRESS"
    assert untouched["prior_status"] is None

    project = get_project(api, bundle["project"]["id"])
    assert project["construction_status"] == "C_SUSPENDED"
    assert project["delivery_risk"] == "AT_RISK"
    assert get_allocation(api, bundle["allocation"]["id"])["status"] == "PREEMPTED"


def test_the_release_restores_the_chain_verbatim_but_not_the_booking(api):
    """Each blocked package returns to the state it recorded, and no further.

    The third package goes back to being scheduled and keeps the window it held
    throughout, the fourth goes back to being a draft rather than being silently
    promoted, and the preempted booking stays preempted because preemption is
    terminal.

    Design: Difficulty/transitive_cascade/phase_hold_cascades_transitive_successors_project_and_amenity_allocations
    """
    bundle = _chained_project_with_a_booking(api)
    first, second, third, fourth = bundle["phases"]
    hold_phase(api, second["id"], HOLD_REASON)

    released = schedule_phase(api, second["id"], *SECOND_WINDOW)

    assert released["status"] == "SCHEDULED"
    assert released["hold_reason"] is None
    restored_third = get_phase(api, third["id"])
    assert restored_third["status"] == "SCHEDULED"
    assert restored_third["prior_status"] is None
    assert restored_third["window_start"] == third["window_start"]
    assert restored_third["window_end"] == third["window_end"]
    restored_fourth = get_phase(api, fourth["id"])
    assert restored_fourth["status"] == "DRAFT"
    assert restored_fourth["prior_status"] is None
    assert restored_fourth["window_start"] is None
    assert restored_fourth["window_end"] is None
    assert get_phase(api, first["id"])["status"] == "IN_PROGRESS"

    project = get_project(api, bundle["project"]["id"])
    assert project["construction_status"] == "C_IN_PROGRESS"
    assert project["delivery_risk"] == "ON_TRACK"
    assert get_allocation(api, bundle["allocation"]["id"])["status"] == "PREEMPTED"
