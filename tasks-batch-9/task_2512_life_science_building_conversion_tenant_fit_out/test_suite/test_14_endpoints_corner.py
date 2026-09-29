"""Endpoint shapes: a round trip through a collection, an action and its replay, a
cross-reference that resolves but does not match, and a report that stores nothing."""

from test_helpers import (
    LANDLORD_HEADERS,
    ApiErrorId,
    allocation_payload,
    assert_allocation,
    assert_amenity,
    assert_money,
    assert_project,
    assert_utilization_report,
    book_allocation,
    create_amenity,
    create_building,
    create_floor,
    create_phase,
    decide_hazmat_permit,
    file_hazmat_permit,
    get_allocation,
    get_floor,
    get_permit,
    get_phase,
    get_project,
    get_utilization,
    ids,
    milestone_payload,
    progress_phase,
    schedule_phase,
    setup_permitted_project,
    utc,
    validate_error,
    validate_paginated,
    validate_success,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "address_city": "Cambridge",
    "occupancy_status": "PARTIALLY_OCCUPIED",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
NEIGHBOUR = {
    "name": "Alewife Labs 90",
    "address_city": "Cambridge",
    "occupancy_status": "VACANT",
    "published_floor_to_floor_ft": 13.0,
    "published_live_load_psf": 80,
    "published_vibration_class": "VC_A",
    "exhaust_riser_capacity_cfm": 30000,
    "emergency_power_capacity_kw": 400,
    "chilled_water_capacity_tons": 600,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
NEIGHBOUR_PLATE = {
    "floor_to_floor_ft": 13.0,
    "live_load_psf": 80,
    "vibration_class": "VC_A",
    "sprinklered": True,
}
DEMAND = {
    "assessment_basis": "SCREENING",
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
QC_LEASE = {
    "term_months": 120,
    "base_rent_psf": 95.00,
    "delivery_deadline": "2026-12-31T00:00:00Z",
}
QC_PROJECT = {
    "design_exhaust_cfm": 12000,
    "design_power_kw": 180,
    "scope_summary": "QC lab fit-out, floor 2",
}
GLASSWASH = {
    "name": "Glasswash and autoclave suite",
    "amenity_type": "GLASSWASH",
    "concurrent_capacity": 2,
    "vibration_sensitive": False,
    "utility_draw_kw": 40,
}
NMR = {
    "name": "NMR suite",
    "amenity_type": "NMR_SUITE",
    "concurrent_capacity": 1,
    "vibration_sensitive": True,
    "utility_draw_kw": 65,
}
LOADING_DOCK = {
    "name": "Alewife loading dock",
    "amenity_type": "LOADING_DOCK",
    "concurrent_capacity": 1,
}

BOOKING_WINDOW = (utc(2026, 8, 10, 10), utc(2026, 8, 10, 14))
FIRST_PACKAGE_WINDOW = (utc(2026, 8, 3), utc(2026, 8, 4))
SECOND_PACKAGE_WINDOW = (utc(2026, 8, 5), utc(2026, 8, 6))


def _qc_permitted_project(api):
    """A conversion-approved plate on floor 2 with an executed QC lease and a
    permitted project on it."""
    return setup_permitted_project(
        api,
        allowance_psf=70.00,
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides=dict(QC_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides=dict(QC_PROJECT),
    )


def _neighbouring_building_with_a_dock(api):
    """A second asset with its own plate and its own amenity."""
    other = create_building(api, **NEIGHBOUR)
    floor = create_floor(api, other["id"], 2, **NEIGHBOUR_PLATE)
    dock = create_amenity(api, other["id"], 2, **LOADING_DOCK)
    return other, floor, dock


def test_an_amenity_reads_back_and_lists_under_its_own_asset(api):
    """One row seen three ways agrees with itself.

    The suite comes back from its create, from its own read and from the
    collection scoped to its asset, at the same version each time, and the
    scoped collection holds only that asset's two amenities and not the
    neighbouring building's dock.

    Design: Corner/endpoints/shared_amenity_create_read_and_filtered_list_round_trip
    """
    building = create_building(api, **NAMEPLATE)
    create_floor(api, building["id"], 2, **PLATE)
    create_floor(api, building["id"], 5, **PLATE)
    _, _, dock = _neighbouring_building_with_a_dock(api)

    nmr = validate_success(
        api.create_amenity(
            building["id"],
            dict(NMR, serving_floor_number=5),
            LANDLORD_HEADERS,
        ),
        201,
    )
    glasswash = validate_success(
        api.create_amenity(
            building["id"],
            dict(GLASSWASH, serving_floor_number=2),
            LANDLORD_HEADERS,
        ),
        201,
    )
    read = validate_success(api.get_amenity(nmr["id"], LANDLORD_HEADERS), 200)
    rows, meta = validate_paginated(
        api.list_amenities(
            LANDLORD_HEADERS,
            {"building_id": building["id"], "limit": 10, "offset": 0},
        )
    )

    assert_amenity(read)
    assert read["id"] == nmr["id"]
    assert read["name"] == "NMR suite"
    assert read["vibration_sensitive"] is True
    assert read["version"] == nmr["version"] == 1
    assert_money(read["utility_draw_kw"], 65.00, "utility_draw_kw")
    assert glasswash["vibration_sensitive"] is False
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert sorted(ids(rows)) == sorted([nmr["id"], glasswash["id"]])
    assert dock["id"] not in ids(rows)


def test_confirming_a_booking_once_moves_it_and_twice_does_not(api):
    """The action is a state change, so its replay is not idempotent.

    The first confirmation carries the booking out of request and bumps its
    version, and the byte-identical second call is refused because the booking is
    no longer in a state that can be confirmed, leaving the version where the
    first call put it.

    Design: Corner/endpoints/allocation_confirm_action_flips_status_then_rejects_the_replay
    """
    bundle = _qc_permitted_project(api)
    amenity = create_amenity(api, bundle["building"]["id"], 2, **GLASSWASH)
    booking = book_allocation(
        api, amenity["id"], bundle["project"]["id"], *BOOKING_WINDOW,
        headcount=4, headers=bundle["tenant_headers"],
    )
    assert booking["status"] == "REQUESTED"
    assert booking["version"] == 1

    confirmed = validate_success(
        api.confirm_allocation(booking["id"], LANDLORD_HEADERS), 200
    )
    replay = api.confirm_allocation(booking["id"], LANDLORD_HEADERS)

    assert_allocation(confirmed)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["version"] == 2
    validate_error(replay, ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value, 409)
    unchanged = get_allocation(api, booking["id"])
    assert unchanged["status"] == "CONFIRMED"
    assert unchanged["version"] == 2


def test_a_booking_on_a_neighbouring_assets_amenity_is_refused(api):
    """Both rows exist, so the objection is the mismatch rather than a lookup.

    The dock and the project are each perfectly real, and the booking is still
    refused because the dock belongs to the neighbouring asset while the
    project's asset is reached through the plate it is fitting out.

    Design: Corner/endpoints/allocation_cross_reference_requires_amenity_and_project_in_one_building
    """
    bundle = _qc_permitted_project(api)
    other, other_floor, dock = _neighbouring_building_with_a_dock(api)

    response = api.create_allocation(
        allocation_payload(
            dock["id"], bundle["project"]["id"], *BOOKING_WINDOW, headcount=2
        ),
        bundle["tenant_headers"],
    )

    validate_error(response, ApiErrorId.ERR_AMENITY_NOT_IN_BUILDING.value, 422)
    assert dock["building_id"] == other["id"]
    assert other_floor["building_id"] == other["id"]
    assert bundle["project"]["floor_id"] == bundle["premises_floor"]["id"]
    assert get_floor(api, bundle["premises_floor"]["id"])["building_id"] == (
        bundle["building"]["id"]
    )
    _, meta = validate_paginated(
        api.list_allocations(
            LANDLORD_HEADERS, {"project_id": bundle["project"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_utilisation_report_is_computed_and_leaves_the_plate_alone(api):
    """Nothing the report says is stored on the plate it describes.

    One approved hundred-gallon flammable permit fills a little over half of one
    control area and under a fifth of the whole plate, the same plate reports
    nothing at all against a corrosive allowance four times larger, and reading
    the report repeatedly leaves the plate at the version it was created with.

    Design: Corner/endpoints/hazmat_utilization_computed_read_is_derived_and_side_effect_free
    """
    bundle = _qc_permitted_project(api)
    floor_id = bundle["premises_floor"]["id"]
    permit = file_hazmat_permit(
        api, bundle["project"]["id"], floor_id, "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE", 100.00, 1, bundle["tenant_headers"],
    )
    decide_hazmat_permit(api, permit["id"], "APPROVE")

    flammable = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)
    corrosive = get_utilization(api, floor_id, "CORROSIVE", 1)
    plate = get_floor(api, floor_id)

    assert_utilization_report(flammable, floor_id, "FLAMMABLE_IB")
    assert_money(flammable["allowance_per_control_area_gal"], 180.00, "allowance")
    assert_money(flammable["per_control_area_basis_gal"], 100.00, "per-area basis")
    assert_money(flammable["per_control_area_utilization_pct"], 55.56, "per-area pct")
    assert_money(flammable["aggregate_allowance_gal"], 540.00, "aggregate allowance")
    assert_money(flammable["aggregate_utilization_pct"], 18.52, "aggregate pct")
    assert_utilization_report(corrosive, floor_id, "CORROSIVE")
    assert_money(corrosive["allowance_per_control_area_gal"], 750.00, "allowance")
    assert_money(corrosive["aggregate_basis_gal"], 0.00, "aggregate basis")
    assert_money(corrosive["per_control_area_utilization_pct"], 0.00, "per-area pct")
    assert plate["version"] == 1
    assert get_permit(api, permit["id"])["status"] == "APPROVED"
    assert get_floor(api, floor_id)["version"] == 1


def test_substantial_completion_waits_for_the_last_package_to_settle(api):
    """The same call is refused and then accepted with no change to its payload.

    While one package is still booked into a window the declaration is refused,
    and once that package has run and closed out the identical declaration is
    accepted, so what the rule tests is the state of the packages rather than
    anything the caller sends.

    Design: Corner/endpoints/construction_milestone_is_conditional_on_phase_quiescence
    """
    bundle = _qc_permitted_project(api)
    project_id = bundle["project"]["id"]
    first = create_phase(
        api, project_id, 1, "SHELL", "QUIET", 40000.00, restoration_cost_usd=30000.00
    )
    second = create_phase(
        api, project_id, 2, "LAB_MEP", "QUIET", 60000.00, restoration_cost_usd=50000.00
    )
    schedule_phase(api, first["id"], *FIRST_PACKAGE_WINDOW)
    schedule_phase(api, second["id"], *SECOND_PACKAGE_WINDOW)
    progress_phase(api, first["id"], "IN_PROGRESS")
    progress_phase(api, first["id"], "COMPLETE")
    assert get_phase(api, second["id"])["status"] == "SCHEDULED"

    too_early = api.declare_milestone(
        project_id, milestone_payload(), LANDLORD_HEADERS
    )
    validate_error(too_early, ApiErrorId.ERR_PHASES_NOT_QUIESCED.value, 409)
    assert get_project(api, project_id)["construction_status"] == "C_IN_PROGRESS"

    progress_phase(api, second["id"], "IN_PROGRESS")
    progress_phase(api, second["id"], "COMPLETE")
    declared = validate_success(
        api.declare_milestone(project_id, milestone_payload(), LANDLORD_HEADERS), 200
    )

    assert_project(declared)
    assert declared["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    assert declared["permit_status"] == "P_ISSUED"
    assert declared["delivery_risk"] == "ON_TRACK"
    assert declared["accepted_at"] is None
    assert get_phase(api, first["id"])["status"] == "COMPLETE"
    assert get_phase(api, second["id"])["status"] == "COMPLETE"
