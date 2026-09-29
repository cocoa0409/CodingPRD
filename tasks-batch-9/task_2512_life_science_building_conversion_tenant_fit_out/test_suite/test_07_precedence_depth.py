"""Fixed rule order: which refusal a request that breaks two rules receives."""

from test_helpers import (
    AHJ_HEADERS,
    LANDLORD_HEADERS,
    ApiErrorId,
    assert_money,
    create_project,
    get_building,
    get_phase,
    get_project,
    get_success_data,
    same_instant,
    schedule_phase,
    setup_executed_lease,
    setup_project_with_phases,
    utc,
    validate_error,
    validate_paginated,
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

# Far more exhaust and far more power than the building will ever hold.
OVERDRAW_EXHAUST_CFM = 999999.00
OVERDRAW_POWER_KW = 5000.00

# The tight case: the outside date falls a fortnight after the lease is signed.
TIGHT_LEASE = {"base_rent_psf": 105.00, "delivery_deadline": "2026-08-15T00:00:00Z"}

GENERATING_WINDOW = (utc(2026, 8, 5), utc(2026, 8, 7))
CONFLICTING_AND_LATE = (utc(2026, 8, 8), utc(2026, 8, 20))
CLEAR_BUT_LATE = (utc(2026, 8, 10), utc(2026, 8, 20))
CLEAR_AND_INSIDE = (utc(2026, 8, 10), utc(2026, 8, 14))


def _project_awaiting_a_ruling(api):
    """A project whose permit application has been filed but not yet ruled on."""
    bundle = setup_executed_lease(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides={"base_rent_psf": 105.00, "delivery_deadline": "2026-12-31T00:00:00Z"},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        complete_disciplines=("LAB_EXHAUST",),
    )
    project = create_project(
        api,
        bundle["lease"]["id"],
        bundle["premises_floor"]["id"],
        design_exhaust_cfm=15000,
        design_power_kw=220,
        scope_summary="BSL2 biology fit-out, floor 2",
    )
    bundle["project"] = get_success_data(
        api.apply_for_permit(project["id"], LANDLORD_HEADERS)
    )
    return bundle


def _reserve(api, project_id, building_id, exhaust_cfm, power_kw):
    """Attempt a reservation against the building's version as it stands now."""
    return api.create_reservation(
        {
            "project_id": project_id,
            "exhaust_cfm": exhaust_cfm,
            "power_kw": power_kw,
            "expected_building_version": get_building(api, building_id)["version"],
        },
        LANDLORD_HEADERS,
    )


def _project_with_generating_work_underway(api):
    """A tight-term project with one vibration-generating package scheduled and
    a second still in draft."""
    bundle = setup_project_with_phases(
        api,
        [
            {
                "premium_class": "LAB_MEP",
                "work_class": "VIBRATION_GENERATING",
                "hard_cost_usd": 50000.00,
                "restoration_cost_usd": 30000.00,
            },
            {
                "premium_class": "CLEANROOM",
                "work_class": "VIBRATION_GENERATING",
                "hard_cost_usd": 30000.00,
                "restoration_cost_usd": 15000.00,
            },
        ],
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(TIGHT_LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 15000,
            "design_power_kw": 220,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    schedule_phase(api, bundle["phases"][0]["id"], *GENERATING_WINDOW)
    bundle["phases"] = [get_phase(api, p["id"]) for p in bundle["phases"]]
    return bundle


def test_an_unruled_permit_is_reported_ahead_of_both_overdrawn_pools(api):
    """The posture of the project is tested before either pool is measured.

    A request for far more exhaust and far more power than the building holds is
    refused for the permit that has not yet been issued, and issuing the permit
    changes the answer on an identical request -- so the pools were never the
    first objection.

    Design: Difficulty/priority_pair_validation_conflict/reservation_state_error_precedes_capacity_and_power_errors
    """
    bundle = _project_awaiting_a_ruling(api)
    project_id = bundle["project"]["id"]
    building_id = bundle["building"]["id"]
    assert bundle["project"]["permit_status"] == "P_APPLIED"
    before = get_building(api, building_id)
    assert_money(before["exhaust_available_cfm"], 80000.00, "exhaust_available_cfm")
    assert_money(before["power_available_kw"], 800.00, "power_available_kw")

    unpermitted = _reserve(
        api, project_id, building_id, OVERDRAW_EXHAUST_CFM, OVERDRAW_POWER_KW
    )
    validate_error(unpermitted, ApiErrorId.ERR_PROJECT_NOT_PERMITTED.value, 409)

    get_success_data(
        api.decide_permit(project_id, {"decision": "ISSUE"}, AHJ_HEADERS)
    )
    assert get_project(api, project_id)["permit_status"] == "P_ISSUED"
    permitted = _reserve(
        api, project_id, building_id, OVERDRAW_EXHAUST_CFM, OVERDRAW_POWER_KW
    )
    validate_error(permitted, ApiErrorId.ERR_EXHAUST_CAPACITY_EXCEEDED.value, 409)

    after = get_building(api, building_id)
    assert_money(after["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(after["power_reserved_kw"], 0.00, "power_reserved_kw")
    rows, _ = validate_paginated(
        api.list_reservations(LANDLORD_HEADERS, {"project_id": project_id})
    )
    assert rows == [], "neither refusal left a reservation behind"


def test_the_scarcer_pool_is_reported_ahead_of_the_generator(api):
    """Exhaust is measured before power, and each pool speaks for itself.

    A permitted request that overdraws both pools names the exhaust riser, while
    a request the riser can absorb and the generator cannot names the generator,
    so the two pools are tested in a fixed order rather than reported jointly.

    Design: Difficulty/priority_pair_validation_conflict/reservation_state_error_precedes_capacity_and_power_errors
    """
    bundle = _project_awaiting_a_ruling(api)
    project_id = bundle["project"]["id"]
    building_id = bundle["building"]["id"]
    get_success_data(
        api.decide_permit(project_id, {"decision": "ISSUE"}, AHJ_HEADERS)
    )

    both = _reserve(
        api, project_id, building_id, OVERDRAW_EXHAUST_CFM, OVERDRAW_POWER_KW
    )
    validate_error(both, ApiErrorId.ERR_EXHAUST_CAPACITY_EXCEEDED.value, 409)

    power_only = _reserve(api, project_id, building_id, 70000.00, OVERDRAW_POWER_KW)
    validate_error(power_only, ApiErrorId.ERR_POWER_CAPACITY_EXCEEDED.value, 409)

    building = get_building(api, building_id)
    assert_money(building["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(building["power_reserved_kw"], 0.00, "power_reserved_kw")


def test_the_neighbours_settling_day_is_reported_ahead_of_the_outside_date(api):
    """A window that both disturbs a neighbour and overruns the term reports the
    disturbance.

    The requested window starts inside the buffer that the scheduled generating
    package earns on each side and also ends after the lease's outside date, and
    the refusal names the vibration conflict, which is the objection that
    endangers somebody else's experiment today.

    Design: Difficulty/priority_pair_validation_conflict/phase_vibration_safety_error_precedes_delivery_term_error
    """
    bundle = _project_with_generating_work_underway(api)
    draft = bundle["phases"][1]
    assert bundle["phases"][0]["status"] == "SCHEDULED"
    assert draft["status"] == "DRAFT"

    response = api.schedule_phase(
        draft["id"],
        {
            "window_start": CONFLICTING_AND_LATE[0],
            "window_end": CONFLICTING_AND_LATE[1],
        },
        LANDLORD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_VIBRATION_WINDOW_CONFLICT.value, 409)

    unchanged = get_phase(api, draft["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["window_start"] is None
    assert unchanged["window_end"] is None


def test_clearing_the_settling_day_reveals_the_outside_date_underneath(api):
    """The second objection surfaces only once the first is satisfied.

    Moving the start clear of the buffer leaves the same overrunning end date,
    which is now reported on its own, and pulling the end back inside the term
    schedules the package -- so both objections were live on the first attempt.

    Design: Difficulty/priority_pair_validation_conflict/phase_vibration_safety_error_precedes_delivery_term_error
    """
    bundle = _project_with_generating_work_underway(api)
    draft = bundle["phases"][1]

    late = api.schedule_phase(
        draft["id"],
        {"window_start": CLEAR_BUT_LATE[0], "window_end": CLEAR_BUT_LATE[1]},
        LANDLORD_HEADERS,
    )
    validate_error(late, ApiErrorId.ERR_WINDOW_OUTSIDE_DELIVERY_TERM.value, 422)
    assert get_phase(api, draft["id"])["status"] == "DRAFT"

    scheduled = schedule_phase(api, draft["id"], *CLEAR_AND_INSIDE)

    assert scheduled["status"] == "SCHEDULED"
    assert same_instant(scheduled["window_start"], CLEAR_AND_INSIDE[0])
    assert same_instant(scheduled["window_end"], CLEAR_AND_INSIDE[1])
