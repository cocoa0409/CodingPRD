"""Who may act: every role's own operations, the ten refused pairings, the signer who
may not sign what he wrote, and one tenant reaching for another's records."""

from test_helpers import (
    AHJ_HEADERS,
    CX_AGENT_HEADERS,
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    LANDLORD_SIGNER_HEADERS,
    USER_CX_TECH,
    USER_CX_WITNESS,
    USER_LANDLORD_SIGNER,
    ApiErrorId,
    add_second_tenant_project,
    allocation_payload,
    assert_lease,
    assert_money,
    assessment_decision_payload,
    assessment_payload,
    book_allocation,
    commissioning_record_payload,
    commissioning_result_payload,
    create_amenity,
    create_building,
    escrow_deposit_payload,
    floor_payload,
    fund_escrow_exactly,
    get_allocation,
    get_lease,
    get_project,
    get_success_data,
    hazmat_decision_payload,
    hazmat_permit_payload,
    hold_payload,
    ids,
    lease_payload,
    make_tenant_headers,
    permit_decision_payload,
    phase_payload,
    project_payload,
    proposal_payload,
    reservation_payload,
    schedule_payload,
    schedule_phase,
    schedule_script,
    scope_item_payload,
    setup_lease_at_terms_accepted,
    setup_permitted_project,
    tenant_payload,
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
EXHAUST_RISER = {
    "description": "New 20000 CFM lab exhaust riser and manifold",
    "budget_usd": 4200000.00,
    "capacity_delta_cfm": 20000,
    "capacity_delta_kw": 0,
}
GLASSWASH = {
    "name": "Glasswash and autoclave suite",
    "amenity_type": "GLASSWASH",
    "concurrent_capacity": 2,
    "vibration_sensitive": False,
    "utility_draw_kw": 40,
}

QC_NAME = "Assay Metrics QC Inc"
CHEMISTRY_NAME = "Northline Chemistry Co"
PERMIT_NOTE = "Permit issued for QC fit-out"
VIBRATION_REPORT = "Adjacent VC_C tenant reports vibration during core drilling"
LANDLORD_STOP_WORK = "Landlord attempts an engineer stop-work"
FIRST_SCRIPT_AT = "2026-10-01T09:00:00Z"

PACKAGE_WINDOW = (utc(2026, 9, 1), utc(2026, 9, 5))
AMENITY_WINDOW = (utc(2026, 9, 10, 8), utc(2026, 9, 10, 12))
SECOND_AMENITY_WINDOW = (utc(2026, 9, 11, 8), utc(2026, 9, 11, 12))


def _qc_terms(**extra):
    """The quality control deal: 2000 square feet on floor 2 of the standard plate."""
    return dict(
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides=dict(QC_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        **extra,
    )


def _qc_permitted_project(api):
    """A conversion-approved plate on floor 2 with an executed QC lease and a
    permitted project on it."""
    return setup_permitted_project(
        api, allowance_psf=70.00, **_qc_terms(project_overrides=dict(QC_PROJECT))
    )


def test_all_five_roles_carry_one_deal_from_a_bare_asset_to_a_stopped_job(api):
    """Each role does its own work and each also does work it shares.

    The engineer measures and stops the job, the landlord decides and trades, the
    tenant signs up and books, the authority rules on the code and reads the
    plate's loading, and the commissioning agent books its script and reads the
    lease behind it, so no role in the system is defined only by refusals.

    Design: Corner/rbac/each_role_exercises_its_own_exclusive_and_shared_operations
    """
    building = create_building(api, **NAMEPLATE)
    building_id = building["id"]
    floor = validate_success(
        api.create_floor(building_id, floor_payload(2, **PLATE), ENGINEER_HEADERS), 201
    )
    assessment = validate_success(
        api.create_assessment(
            building_id, assessment_payload(**DEMAND), ENGINEER_HEADERS
        ),
        201,
    )
    validate_success(api.submit_assessment(assessment["id"], ENGINEER_HEADERS), 200)
    decided = validate_success(
        api.decide_assessment(
            assessment["id"], assessment_decision_payload("ACCEPT"), LANDLORD_HEADERS
        ),
        200,
    )
    riser = validate_success(
        api.create_scope_item(
            building_id,
            scope_item_payload("LAB_EXHAUST", **EXHAUST_RISER),
            LANDLORD_HEADERS,
        ),
        201,
    )
    approved = validate_success(
        api.approve_conversion(building_id, LANDLORD_HEADERS), 200
    )
    validate_success(api.complete_scope_item(riser["id"], ENGINEER_HEADERS), 200)

    tenant = validate_success(
        api.create_tenant(
            tenant_payload("ANALYTICAL_QC", legal_name=QC_NAME), LANDLORD_HEADERS
        ),
        201,
    )
    tenant_headers = make_tenant_headers(tenant["id"])
    lease = validate_success(
        api.create_lease(
            lease_payload(tenant["id"], building_id, floor["id"], 2000, **QC_LEASE),
            LANDLORD_HEADERS,
        ),
        201,
    )
    proposal = validate_success(
        api.create_proposal(
            lease["id"],
            proposal_payload(lease["version"], 70.00),
            LANDLORD_NEGOTIATOR_HEADERS,
        ),
        201,
    )
    validate_success(api.accept_proposal(proposal["id"], tenant_headers), 200)
    get_success_data(
        api.create_escrow_deposit(
            lease["id"], escrow_deposit_payload(20000.00), tenant_headers
        )
    )
    validate_success(api.execute_lease(lease["id"], LANDLORD_SIGNER_HEADERS), 200)

    project = validate_success(
        api.create_project(
            project_payload(lease["id"], floor["id"], **QC_PROJECT), LANDLORD_HEADERS
        ),
        201,
    )
    validate_success(api.apply_for_permit(project["id"], LANDLORD_HEADERS), 200)
    issued = validate_success(
        api.decide_permit(
            project["id"],
            permit_decision_payload("ISSUE", decision_note=PERMIT_NOTE),
            AHJ_HEADERS,
        ),
        200,
    )
    permit = validate_success(
        api.create_hazmat_permit(
            hazmat_permit_payload(
                project["id"], floor["id"], "FLAMMABLE_IB", "CLOSED_SYSTEM_USE",
                100.00, 1,
            ),
            tenant_headers,
        ),
        201,
    )
    ruled = validate_success(
        api.decide_hazmat_permit(
            permit["id"], hazmat_decision_payload("APPROVE"), AHJ_HEADERS
        ),
        200,
    )
    report = validate_success(
        api.get_hazmat_utilization(
            floor["id"], AHJ_HEADERS, {"hazard_class": "FLAMMABLE_IB"}
        ),
        200,
    )

    amenity = validate_success(
        api.create_amenity(
            building_id, dict(GLASSWASH, serving_floor_number=2), LANDLORD_HEADERS
        ),
        201,
    )
    allocation = validate_success(
        api.create_allocation(
            allocation_payload(
                amenity["id"], project["id"], *AMENITY_WINDOW, headcount=3
            ),
            tenant_headers,
        ),
        201,
    )
    confirmed = validate_success(
        api.confirm_allocation(allocation["id"], LANDLORD_HEADERS), 200
    )
    package = validate_success(
        api.create_phase(
            project["id"],
            phase_payload(1, "SHELL", "QUIET", 100000.00, restoration_cost_usd=90000.00),
            LANDLORD_HEADERS,
        ),
        201,
    )
    validate_success(
        api.schedule_phase(
            package["id"], schedule_payload(*PACKAGE_WINDOW), LANDLORD_HEADERS
        ),
        200,
    )
    record = validate_success(
        api.create_commissioning_record(
            project["id"],
            commissioning_record_payload("IQ", USER_CX_TECH, FIRST_SCRIPT_AT),
            CX_AGENT_HEADERS,
        ),
        201,
    )
    read_by_the_agent = validate_success(api.get_lease(lease["id"], CX_AGENT_HEADERS), 200)
    held = validate_success(
        api.hold_phase(package["id"], hold_payload(VIBRATION_REPORT), ENGINEER_HEADERS),
        200,
    )

    assert decided["status"] == "ACCEPTED"
    assert approved["suitability_state"] == "CONVERSION_APPROVED"
    assert issued["permit_status"] == "P_ISSUED"
    assert ruled["status"] == "APPROVED"
    assert_money(report["aggregate_basis_gal"], 100.00, "aggregate basis")
    assert confirmed["status"] == "CONFIRMED"
    assert record["status"] == "SCHEDULED"
    assert_lease(read_by_the_agent)
    assert read_by_the_agent["status"] == "EXECUTED"
    assert held["status"] == "VIBRATION_HOLD"
    assert_money(get_lease(api, lease["id"])["ti_authorized_usd"], 200000.00, "authorized")
    assert get_project(api, project["id"])["construction_status"] == "C_NOT_STARTED"
    assert get_allocation(api, allocation["id"])["status"] == "PREEMPTED"


def test_ten_role_pairings_are_refused_before_any_rule_of_the_endpoint_runs(api):
    """The gate is closed before the request is ever examined on its merits.

    Each of the ten calls is made by a role the operation is not open to, and two
    of them would have failed on their merits as well -- a ruling on an already
    decided assessment and a reservation quoting a version that was never the
    asset's -- yet both answer on the role, and nothing in the store moves.

    Design: Corner/rbac/wrong_role_cannot_invoke_another_roles_exclusive_operation_returns_4XX
    """
    bundle = _qc_permitted_project(api)
    building_id = bundle["building"]["id"]
    floor_id = bundle["premises_floor"]["id"]
    project_id = bundle["project"]["id"]
    tenant_headers = bundle["tenant_headers"]
    package = get_success_data(
        api.create_phase(
            project_id,
            phase_payload(1, "SHELL", "QUIET", 100000.00, restoration_cost_usd=90000.00),
            LANDLORD_HEADERS,
        )
    )
    schedule_phase(api, package["id"], *PACKAGE_WINDOW)
    amenity = create_amenity(api, building_id, 2, **GLASSWASH)
    allocation = book_allocation(
        api, amenity["id"], project_id, *AMENITY_WINDOW, headcount=3,
        headers=tenant_headers,
    )
    record = schedule_script(api, project_id, "IQ", USER_CX_TECH, FIRST_SCRIPT_AT)
    a_version_that_was_never_the_assets = 1

    refused = [
        api.create_floor(building_id, floor_payload(3, **PLATE), LANDLORD_HEADERS),
        api.decide_assessment(
            bundle["assessment"]["id"],
            assessment_decision_payload("ACCEPT"),
            ENGINEER_HEADERS,
        ),
        api.hold_phase(
            package["id"], hold_payload(LANDLORD_STOP_WORK), LANDLORD_HEADERS
        ),
        api.decide_permit(project_id, permit_decision_payload("ISSUE"), LANDLORD_HEADERS),
        api.create_hazmat_permit(
            hazmat_permit_payload(
                project_id, floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 50.00, 1
            ),
            ENGINEER_HEADERS,
        ),
        api.create_reservation(
            reservation_payload(project_id, a_version_that_was_never_the_assets, 12000, 180),
            CX_AGENT_HEADERS,
        ),
        api.record_commissioning_result(
            record["id"],
            commissioning_result_payload("PASS", USER_CX_WITNESS),
            AHJ_HEADERS,
        ),
        api.confirm_allocation(allocation["id"], tenant_headers),
        api.execute_lease(bundle["lease"]["id"], tenant_headers),
        api.create_tenant(
            tenant_payload("VIVARIUM", legal_name="Self Enrolled Labs"), tenant_headers
        ),
    ]

    assert len(refused) == 10
    for response in refused:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    _, floor_meta = validate_paginated(
        api.list_building_floors(building_id, LANDLORD_HEADERS)
    )
    assert floor_meta["total_count"] == 1
    _, permit_meta = validate_paginated(api.list_hazmat_permits(LANDLORD_HEADERS))
    assert permit_meta["total_count"] == 0
    _, reservation_meta = validate_paginated(api.list_reservations(LANDLORD_HEADERS))
    assert reservation_meta["total_count"] == 0
    assert get_success_data(api.get_phase(package["id"], LANDLORD_HEADERS))["status"] == (
        "SCHEDULED"
    )
    assert get_allocation(api, allocation["id"])["status"] == "REQUESTED"
    assert get_success_data(
        api.get_commissioning_record(record["id"], LANDLORD_HEADERS)
    )["status"] == "SCHEDULED"


def test_the_operator_who_wrote_the_winning_round_may_not_sign_the_lease(api):
    """The bar is on the person, not on the job title.

    The negotiator who authored the accepted round is refused the signature even
    though asset management is the only role allowed to sign at all, and a
    different operator wearing that same role signs on the very next call.

    Design: Corner/rbac/same_user_cannot_author_and_then_execute_the_accepted_lease
    """
    bundle = setup_lease_at_terms_accepted(api, allowance_psf=70.00, **_qc_terms())
    lease_id = bundle["lease"]["id"]
    fund_escrow_exactly(api, lease_id)
    assert bundle["proposal"]["authored_by_user_id"] == (
        LANDLORD_NEGOTIATOR_HEADERS["X-User-ID"]
    )

    refused = api.execute_lease(lease_id, LANDLORD_NEGOTIATOR_HEADERS)
    signed = validate_success(api.execute_lease(lease_id, LANDLORD_SIGNER_HEADERS), 200)

    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert signed["status"] == "EXECUTED"
    final = get_lease(api, lease_id)
    assert final["status"] == "EXECUTED"
    assert final["executed_by_user_id"] == USER_LANDLORD_SIGNER
    assert_money(final["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_money(final["ti_uncommitted_usd"], 200000.00, "ti_uncommitted_usd")


def test_one_tenant_may_not_read_or_touch_the_other_tenants_records(api):
    """Tenancy is scoped on the way in as well as on the way out.

    The chemistry tenant is refused the neighbour's lease and project even though
    it only wants to look, refused the cancellation of the neighbour's booking and
    refused a booking of its own against the neighbour's project, while the tenant
    who actually owns the booking cancels it on the next call.

    Design: Corner/rbac/tenant_cannot_read_or_act_on_another_tenants_lease_project_or_allocation
    """
    first = _qc_permitted_project(api)
    second = add_second_tenant_project(
        api, first, rentable_sf=3000, allowance_psf=60.00
    )
    amenity = create_amenity(api, first["building"]["id"], 2, **GLASSWASH)
    booking = book_allocation(
        api, amenity["id"], first["project"]["id"], *AMENITY_WINDOW, headcount=3,
        headers=first["tenant_headers"],
    )
    neighbour_headers = second["tenant_headers"]
    assert second["tenant"]["legal_name"] != first["tenant"]["legal_name"]

    read_lease = api.get_lease(first["lease"]["id"], neighbour_headers)
    read_project = api.get_project(first["project"]["id"], neighbour_headers)
    cancel_theirs = api.cancel_allocation(booking["id"], neighbour_headers)
    book_theirs = api.create_allocation(
        allocation_payload(
            amenity["id"], first["project"]["id"], *SECOND_AMENITY_WINDOW, headcount=2
        ),
        neighbour_headers,
    )
    cancel_mine = validate_success(
        api.cancel_allocation(booking["id"], first["tenant_headers"]), 200
    )

    for response in (read_lease, read_project, cancel_theirs, book_theirs):
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert cancel_mine["status"] == "CANCELLED"
    rows, meta = validate_paginated(
        api.list_allocations(LANDLORD_HEADERS, {"amenity_id": amenity["id"]})
    )
    assert meta["total_count"] == 1
    assert ids(rows) == [booking["id"]]
    assert get_lease(api, first["lease"]["id"])["status"] == "EXECUTED"
    assert_money(
        get_lease(api, second["lease"]["id"])["ti_authorized_usd"],
        367500.00,
        "ti_authorized_usd",
    )
