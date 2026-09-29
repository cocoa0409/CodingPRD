"""Guards on the way in: the control area range, the shutdown link, the floor-wide
limit and the instant at which a suite fills up."""

from test_helpers import (
    AHJ_HEADERS,
    LANDLORD_HEADERS,
    ApiErrorId,
    add_second_tenant_project,
    allocation_payload,
    assert_amenity,
    assert_hazmat_permit,
    assert_phase,
    book_allocation,
    confirm_allocation,
    create_amenity,
    decide_hazmat_permit,
    file_hazmat_permit,
    get_allocation,
    get_floor,
    get_permit,
    get_phase,
    hazmat_permit_payload,
    ids,
    phase_payload,
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
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
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

# A floor 2 plate carries three control areas, so index 4 lies outside the range
# and index 3 lies on its far edge.
BEYOND_THE_LAST_AREA = 4
THE_LAST_AREA = 3

# Two bookings that already overlap on a suite for two, and a third whose start
# instant is clear but which runs on into the moment the second one begins.
FIRST_BOOKING = (utc(2026, 8, 10, 10), utc(2026, 8, 10, 14))
SECOND_BOOKING = (utc(2026, 8, 10, 12), utc(2026, 8, 10, 16))
STRADDLING_BOOKING = (utc(2026, 8, 10, 11), utc(2026, 8, 10, 18))


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


def _qc_project_with_a_glasswash(api):
    """The same project, plus a glasswash suite serving its own plate."""
    bundle = _qc_permitted_project(api)
    bundle["amenity"] = create_amenity(api, bundle["building"]["id"], 2, **GLASSWASH)
    return bundle


def _file(api, bundle, quantity_gal, control_area_index):
    """Attempt one hazardous material application as the tenant."""
    return api.create_hazmat_permit(
        hazmat_permit_payload(
            bundle["project"]["id"],
            bundle["premises_floor"]["id"],
            "FLAMMABLE_IB",
            "CLOSED_SYSTEM_USE",
            quantity_gal,
            control_area_index,
        ),
        bundle["tenant_headers"],
    )


def _permit_count(api, project_id):
    """How many applications exist against one project."""
    _, meta = validate_paginated(
        api.list_hazmat_permits(LANDLORD_HEADERS, {"project_id": project_id})
    )
    return meta["total_count"]


def test_a_control_area_beyond_the_plates_allowance_is_refused(api):
    """The index is measured against the plate's own entitlement.

    A second-floor plate is entitled to three control areas, so an application
    naming a fourth is refused and no application is recorded against the
    project at all.

    Design: Corner/validations/control_area_index_above_the_floor_allowance_is_rejected
    """
    bundle = _qc_permitted_project(api)
    floor = get_floor(api, bundle["premises_floor"]["id"])
    assert floor["control_areas_allowed"] == 3

    response = _file(api, bundle, 10.00, BEYOND_THE_LAST_AREA)

    validate_error(response, ApiErrorId.ERR_CONTROL_AREA_OUT_OF_RANGE.value, 422)
    assert _permit_count(api, bundle["project"]["id"]) == 0


def test_an_application_on_the_last_permitted_control_area_is_accepted(api):
    """The range is inclusive at its upper end.

    The third control area of a three-area plate is inside the entitlement, so
    the identical application naming it is accepted and lands as a request with
    no ruling recorded on it yet.

    Design: Corner/validations/control_area_index_at_the_last_permitted_area_is_accepted
    """
    bundle = _qc_permitted_project(api)

    permit = validate_success(_file(api, bundle, 10.00, THE_LAST_AREA), 201)

    assert_hazmat_permit(permit)
    assert permit["status"] == "REQUESTED"
    assert permit["control_area_index"] == THE_LAST_AREA
    assert permit["project_id"] == bundle["project"]["id"]
    assert permit["floor_id"] == bundle["premises_floor"]["id"]
    assert permit["decision_reason"] is None
    assert _permit_count(api, bundle["project"]["id"]) == 1


def test_the_range_objection_is_reported_ahead_of_the_quantity_objection(api):
    """One request breaks two rules and hears about the earlier one.

    An application naming a control area the plate does not have, for a quantity
    far past what one control area may hold, is answered on the range alone; the
    same quantity on a control area that does exist is what draws the quantity
    objection instead.

    Design: Corner/validations/out_of_range_index_rejected_before_the_project_maq_check_runs
    """
    bundle = _qc_permitted_project(api)

    both_broken = _file(api, bundle, 999.00, BEYOND_THE_LAST_AREA)
    validate_error(both_broken, ApiErrorId.ERR_CONTROL_AREA_OUT_OF_RANGE.value, 422)

    quantity_only = _file(api, bundle, 999.00, 1)
    validate_error(quantity_only, ApiErrorId.ERR_CONTROL_AREA_MAQ_EXCEEDED.value, 409)

    assert _permit_count(api, bundle["project"]["id"]) == 0


def test_a_shutdown_package_that_names_nothing_it_takes_offline_is_refused(api):
    """The requirement is conditional on the class of work.

    A quiet package is accepted with no amenity named, and the package created
    straight after it is refused for exactly the omission the quiet one was
    forgiven, because its work requires a utility shutdown.

    Design: Corner/validations/shutdown_phase_without_an_affected_amenity_is_rejected
    """
    bundle = _qc_project_with_a_glasswash(api)
    quiet = validate_success(
        api.create_phase(
            bundle["project"]["id"],
            phase_payload(1, "SHELL", "QUIET", 40000.00, restoration_cost_usd=30000.00),
            LANDLORD_HEADERS,
        ),
        201,
    )

    response = api.create_phase(
        bundle["project"]["id"],
        phase_payload(
            2, "LAB_MEP", "SHUTDOWN_REQUIRED", 50000.00, restoration_cost_usd=40000.00
        ),
        LANDLORD_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_SHUTDOWN_AMENITY_REQUIRED.value, 422)
    stored = get_phase(api, quiet["id"])
    assert stored["affected_amenity_id"] is None
    assert stored["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_phases(LANDLORD_HEADERS, {"project_id": bundle["project"]["id"]})
    )
    assert meta["total_count"] == 1
    assert ids(rows) == [quiet["id"]]
    assert_amenity(bundle["amenity"])
    assert bundle["amenity"]["concurrent_capacity"] == 2


def test_the_same_shutdown_package_naming_its_amenity_is_accepted(api):
    """Naming the amenity is the whole of the difference.

    The identical shutdown payload with the glasswash named is accepted at the
    second place in the chain and stored in draft with the link persisted, so the
    earlier refusal was about the missing link rather than the work itself.

    Design: Corner/validations/shutdown_phase_naming_its_affected_amenity_satisfies_the_rule
    """
    bundle = _qc_project_with_a_glasswash(api)
    api.create_phase(
        bundle["project"]["id"],
        phase_payload(1, "SHELL", "QUIET", 40000.00, restoration_cost_usd=30000.00),
        LANDLORD_HEADERS,
    )

    response = api.create_phase(
        bundle["project"]["id"],
        phase_payload(
            2,
            "LAB_MEP",
            "SHUTDOWN_REQUIRED",
            50000.00,
            restoration_cost_usd=40000.00,
            affected_amenity_id=bundle["amenity"]["id"],
        ),
        LANDLORD_HEADERS,
    )

    shutdown = validate_success(response, 201)
    assert_phase(shutdown)
    assert shutdown["status"] == "DRAFT"
    assert shutdown["work_class"] == "SHUTDOWN_REQUIRED"
    assert shutdown["sequence_no"] == 2
    assert shutdown["affected_amenity_id"] == bundle["amenity"]["id"]
    assert get_phase(api, shutdown["id"])["affected_amenity_id"] == (
        bundle["amenity"]["id"]
    )
    _, meta = validate_paginated(
        api.list_phases(LANDLORD_HEADERS, {"project_id": bundle["project"]["id"]})
    )
    assert meta["total_count"] == 2


def test_the_second_tenants_ruling_meets_the_first_tenants_approved_quantity(api):
    """The authority's limit is shared across everyone on the plate.

    Two tenants each file half again as much as the plate can hold in one control
    area between them, and each application passes on its own footprint; the
    first ruling goes through and the second is refused, because by then the
    first tenant's quantity is approved and counts against the same area.

    Design: Corner/validations/floor_wide_approval_maq_rejected_for_the_second_tenant_on_one_control_area
    """
    first = _qc_permitted_project(api)
    second = add_second_tenant_project(api, first, rentable_sf=2000, allowance_psf=70.00)
    first_permit = file_hazmat_permit(
        api,
        first["project"]["id"],
        first["premises_floor"]["id"],
        "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE",
        100.00,
        1,
        first["tenant_headers"],
    )
    second_permit = file_hazmat_permit(
        api,
        second["project"]["id"],
        second["floor"]["id"],
        "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE",
        100.00,
        1,
        second["tenant_headers"],
    )
    assert first_permit["status"] == "REQUESTED"
    assert second_permit["status"] == "REQUESTED"
    approved = decide_hazmat_permit(api, first_permit["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    response = api.decide_hazmat_permit(
        second_permit["id"], {"decision": "APPROVE"}, AHJ_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_CONTROL_AREA_MAQ_EXCEEDED.value, 409)
    assert get_permit(api, first_permit["id"])["status"] == "APPROVED"
    refused = get_permit(api, second_permit["id"])
    assert refused["status"] == "REQUESTED"
    assert refused["decision_reason"] is None


def test_a_booking_that_only_breaches_at_a_later_start_instant_is_refused(api):
    """The peak is looked for at every start instant the window covers.

    The third booking is within the ceiling at its own start instant, where only
    one other booking is running, and it is still refused because at the instant
    the second booking begins the suite would be holding three at once.

    Design: Corner/validations/amenity_capacity_violation_found_at_a_later_candidate_instant
    """
    bundle = _qc_project_with_a_glasswash(api)
    amenity_id = bundle["amenity"]["id"]
    first = book_allocation(
        api, amenity_id, bundle["project"]["id"], *FIRST_BOOKING,
        headcount=3, headers=bundle["tenant_headers"],
    )
    confirm_allocation(api, first["id"])
    second = book_allocation(
        api, amenity_id, bundle["project"]["id"], *SECOND_BOOKING,
        headcount=2, headers=bundle["tenant_headers"],
    )
    assert get_allocation(api, first["id"])["status"] == "CONFIRMED"
    assert second["status"] == "REQUESTED"

    response = api.create_allocation(
        allocation_payload(
            amenity_id, bundle["project"]["id"], *STRADDLING_BOOKING, headcount=4
        ),
        bundle["tenant_headers"],
    )

    validate_error(response, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED.value, 409)
    rows, meta = validate_paginated(
        api.list_allocations(LANDLORD_HEADERS, {"amenity_id": amenity_id})
    )
    assert meta["total_count"] == 2
    assert sorted(ids(rows)) == sorted([first["id"], second["id"]])
    assert get_allocation(api, second["id"])["status"] == "REQUESTED"
