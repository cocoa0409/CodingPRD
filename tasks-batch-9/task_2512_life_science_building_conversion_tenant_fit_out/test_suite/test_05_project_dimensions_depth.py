"""The two project dimensions, and the riser that gates the permit application."""

from test_helpers import (
    AHJ_HEADERS,
    CLOCK_START,
    LANDLORD_HEADERS,
    ApiErrorId,
    assert_money,
    assert_project,
    complete_scope_item,
    create_phase,
    create_project,
    get_building,
    get_phase,
    get_project,
    get_success_data,
    hold_phase,
    same_instant,
    schedule_phase,
    setup_executed_lease,
    start_phase,
    utc,
    validate_error,
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
LEASE = {"base_rent_psf": 105.00, "delivery_deadline": "2026-12-31T00:00:00Z"}

FIRST_WINDOW = (utc(2026, 8, 5), utc(2026, 8, 10))
SECOND_WINDOW = (utc(2026, 8, 20), utc(2026, 8, 25))
REPLACEMENT_WINDOW = (utc(2026, 9, 1), utc(2026, 9, 6))

HOLD_REASON = "Adjacent occupied lab reports floor velocity above VC_C"


def _project_on_a_finished_riser(api):
    """A signed biology lease with its project created and the riser closed out."""
    bundle = setup_executed_lease(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        complete_disciplines=("LAB_EXHAUST",),
    )
    bundle["project"] = create_project(
        api,
        bundle["lease"]["id"],
        bundle["premises_floor"]["id"],
        design_exhaust_cfm=15000,
        design_power_kw=220,
        scope_summary="BSL2 biology fit-out, floor 2",
    )
    return bundle


def _project_on_an_unfinished_riser(api):
    """The same deal, but with the lab exhaust scope item still open."""
    bundle = setup_executed_lease(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        complete_disciplines=(),
    )
    bundle["project"] = create_project(
        api,
        bundle["lease"]["id"],
        bundle["premises_floor"]["id"],
        design_exhaust_cfm=15000,
        design_power_kw=220,
        scope_summary="BSL2 biology fit-out, floor 2",
    )
    return bundle


def _apply(api, project_id):
    return get_success_data(api.apply_for_permit(project_id, LANDLORD_HEADERS))


def _issue(api, project_id):
    return get_success_data(
        api.decide_permit(project_id, {"decision": "ISSUE"}, AHJ_HEADERS)
    )


def test_the_permit_runs_to_its_terminal_state_while_the_work_has_not_begun(api):
    """Neither status dimension is derived from the other.

    The permit dimension travels its whole path, from unpermitted through
    applied to issued, without the construction dimension leaving its initial
    state; the work only moves when a package physically starts, and that in turn
    leaves the permit where it already was.

    Design: Difficulty/non_linear_state_machine/fitout_permit_and_construction_dimensions_advance_independently
    """
    bundle = _project_on_a_finished_riser(api)
    project_id = bundle["project"]["id"]
    assert_project(bundle["project"])
    assert bundle["project"]["permit_status"] == "P_UNPERMITTED"
    assert bundle["project"]["construction_status"] == "C_NOT_STARTED"
    assert bundle["project"]["permit_applied_at"] is None
    assert bundle["project"]["permit_issued_at"] is None

    applied = _apply(api, project_id)
    assert applied["permit_status"] == "P_APPLIED"
    assert applied["construction_status"] == "C_NOT_STARTED"

    issued = _issue(api, project_id)
    assert issued["permit_status"] == "P_ISSUED"
    assert issued["construction_status"] == "C_NOT_STARTED", (
        "issuance is an act of the authority, not of the trades"
    )
    assert issued["permit_issued_at"] is not None
    assert issued["accepted_at"] is None

    phase = create_phase(api, project_id, hard_cost_usd=50000.00)
    started = start_phase(api, phase["id"], *FIRST_WINDOW)
    after = get_project(api, project_id)
    assert started["status"] == "IN_PROGRESS"
    assert after["construction_status"] == "C_IN_PROGRESS"
    assert after["permit_status"] == "P_ISSUED", "the permit dimension did not move"


def test_the_work_can_suspend_and_resume_under_a_permit_that_never_moves(api):
    """The construction dimension takes a reversible detour on its own.

    A hold carries the work into suspension and a release carries it back, so
    the construction dimension visits a state twice while the permit dimension
    stays at the terminal state it reached long before, and the package that was
    already running is never disturbed by either event.

    Design: Difficulty/non_linear_state_machine/fitout_permit_and_construction_dimensions_advance_independently
    """
    bundle = _project_on_a_finished_riser(api)
    project_id = bundle["project"]["id"]
    _apply(api, project_id)
    _issue(api, project_id)

    first = create_phase(api, project_id, sequence_no=1, hard_cost_usd=50000.00,
                         restoration_cost_usd=30000.00)
    second = create_phase(
        api,
        project_id,
        sequence_no=2,
        hard_cost_usd=40000.00,
        restoration_cost_usd=20000.00,
        predecessor_phase_id=first["id"],
    )
    start_phase(api, first["id"], *FIRST_WINDOW)
    schedule_phase(api, second["id"], *SECOND_WINDOW)
    running = get_project(api, project_id)
    assert running["construction_status"] == "C_IN_PROGRESS"
    assert running["delivery_risk"] == "ON_TRACK"

    hold_phase(api, second["id"], HOLD_REASON)
    suspended = get_project(api, project_id)
    assert suspended["construction_status"] == "C_SUSPENDED"
    assert suspended["delivery_risk"] == "AT_RISK"
    assert suspended["permit_status"] == "P_ISSUED"
    assert get_phase(api, first["id"])["status"] == "IN_PROGRESS"

    released = schedule_phase(api, second["id"], *REPLACEMENT_WINDOW)
    resumed = get_project(api, project_id)
    assert released["status"] == "SCHEDULED"
    assert released["hold_reason"] is None
    assert resumed["construction_status"] == "C_IN_PROGRESS"
    assert resumed["construction_status"] == running["construction_status"]
    assert resumed["delivery_risk"] == "ON_TRACK"
    assert resumed["permit_status"] == "P_ISSUED"
    assert get_phase(api, first["id"])["status"] == "IN_PROGRESS"


def test_the_application_is_refused_while_the_exhaust_riser_is_unfinished(api):
    """The gate is the state of a row on another entity entirely.

    Everything the project itself controls is in order -- the lease is signed and
    the base building is approved for conversion -- yet the application is
    refused because the building's lab exhaust scope item has not been closed
    out, and the project's own permit dimension is left untouched.

    Design: Difficulty/cross_entity_state_dependency/permit_application_gated_on_lab_exhaust_scope_item_state
    """
    bundle = _project_on_an_unfinished_riser(api)
    project_id = bundle["project"]["id"]
    scope_item = bundle["scope_items"]["LAB_EXHAUST"]
    assert bundle["lease"]["status"] == "EXECUTED"
    assert get_building(api, bundle["building"]["id"])["suitability_state"] == (
        "CONVERSION_APPROVED"
    )
    assert scope_item["status"] == "PLANNED"

    response = api.apply_for_permit(project_id, LANDLORD_HEADERS)
    validate_error(response, ApiErrorId.ERR_EXHAUST_SCOPE_INCOMPLETE.value, 409)

    unchanged = get_project(api, project_id)
    assert unchanged["permit_status"] == "P_UNPERMITTED"
    assert unchanged["permit_applied_at"] is None
    assert unchanged["construction_status"] == "C_NOT_STARTED"


def test_closing_out_the_riser_is_what_admits_the_application(api):
    """Nothing about the project changes; the other entity's state does.

    The identical application is refused and then accepted, with the only
    intervening act being the completion of the building's lab exhaust scope
    item, which also folds the declared riser capacity into the building's pool.

    Design: Difficulty/cross_entity_state_dependency/permit_application_gated_on_lab_exhaust_scope_item_state
    """
    bundle = _project_on_an_unfinished_riser(api)
    project_id = bundle["project"]["id"]
    validate_error(
        api.apply_for_permit(project_id, LANDLORD_HEADERS),
        ApiErrorId.ERR_EXHAUST_SCOPE_INCOMPLETE.value,
        409,
    )

    completed = complete_scope_item(api, bundle["scope_items"]["LAB_EXHAUST"]["id"])
    assert completed["status"] == "COMPLETE"
    assert completed["completed_at"] is not None

    applied = _apply(api, project_id)
    assert applied["permit_status"] == "P_APPLIED"
    assert same_instant(applied["permit_applied_at"], CLOCK_START), (
        "the stamp is taken from the logical clock"
    )
    assert applied["construction_status"] == "C_NOT_STARTED"

    building = get_building(api, bundle["building"]["id"])
    assert_money(building["exhaust_capacity_total_cfm"], 80000.00, "exhaust total")
    assert building["suitability_state"] == "CONVERSION_APPROVED"
