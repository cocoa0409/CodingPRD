"""Every guard reached at least once: the rest of the not-found family, then the
conversion, negotiation, fiscal, construction, code and commissioning refusals."""

from test_helpers import (
    AHJ_HEADERS,
    CX_AGENT_HEADERS,
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    LANDLORD_SIGNER_HEADERS,
    NON_EXISTENT_UUID,
    OMIT,
    USER_CX_TECH,
    USER_CX_WITNESS,
    ApiErrorId,
    add_scope_item,
    add_second_tenant_project,
    approve_conversion,
    assert_ledger_identity,
    assert_money,
    assessment_payload,
    commissioning_record_payload,
    commissioning_result_payload,
    complete_scope_item,
    create_phase,
    decide_assessment,
    decide_hazmat_permit,
    disbursement_payload,
    escrow_deposit_payload,
    expiration_notice_payload,
    file_hazmat_permit,
    floor_payload,
    get_lease,
    get_permit,
    get_phase,
    get_project,
    get_record,
    get_success_data,
    hazmat_decision_payload,
    hold_payload,
    issue_expiration_notice,
    milestone_payload,
    open_assessment,
    pass_all_scripts,
    phase_payload,
    progress_payload,
    progress_phase,
    proposal_payload,
    reserve_capacity,
    schedule_payload,
    schedule_phase,
    schedule_script,
    scope_item_payload,
    set_clock,
    setup_building_with_floors,
    setup_lease_at_loi,
    setup_lease_at_terms_accepted,
    setup_lease_with_committed_phases,
    setup_permitted_project,
    submit_assessment,
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
WASTE_ROOM = {
    "description": "Hazardous waste accumulation room and cart route",
    "budget_usd": 650000.00,
}
EXHAUST_RISER = {
    "description": "New 20000 CFM lab exhaust riser and manifold",
    "budget_usd": 4200000.00,
    "capacity_delta_cfm": 20000,
    "capacity_delta_kw": 0,
}

# Ten days after the round is written, on the logical clock.
FIRST_ROUND_EXPIRY = "2026-08-11T00:00:00Z"
AFTER_THE_ROUNDS_EXPIRE = "2026-08-12T00:00:00Z"

# Windows for the two sibling projects' packages, and the degenerate one.
PACKAGE_B_WINDOW = (utc(2026, 8, 3), utc(2026, 8, 4))
PACKAGE_A_WINDOW = (utc(2026, 8, 6), utc(2026, 8, 7))
DEGENERATE_WINDOW = (utc(2026, 8, 9), utc(2026, 8, 9))
PACKAGE_D_WINDOW = (utc(2026, 8, 11), utc(2026, 8, 12))

BLANK_HOLD_REASON = "   "
DENIAL_REASON = "Control area 1 already committed to an incompatible class"
FAR_EXPIRATION = "2036-07-31T00:00:00Z"
SECOND_EXPIRATION = "2036-08-31T00:00:00Z"


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


def _round(api, lease_id, expected_version, allowance_psf, headers):
    """Open one negotiation round and return the raw response."""
    return api.create_proposal(
        lease_id, proposal_payload(expected_version, allowance_psf), headers
    )


def test_the_remaining_reads_each_name_the_entity_they_could_not_find(api):
    """Eight more read paths answer an unknown identifier in their own words.

    None of them falls back on a shared generic condition, so the not-found
    family is fully discriminated across every entity that can be read on its
    own.

    Design: Corner/errors/remaining_entity_lookups_each_return_their_own_not_found
    """
    expected = [
        (api.get_assessment(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value),
        (api.get_scope_item(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_SCOPE_ITEM_NOT_FOUND.value),
        (api.get_proposal(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value),
        (api.get_reservation(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_RESERVATION_NOT_FOUND.value),
        (api.get_hazmat_permit(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_PERMIT_NOT_FOUND.value),
        (api.get_amenity(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_AMENITY_NOT_FOUND.value),
        (api.get_allocation(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value),
        (api.get_commissioning_record(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_COMMISSIONING_RECORD_NOT_FOUND.value),
    ]

    for response, error_id in expected:
        validate_error(response, error_id, 404)


def test_the_conversion_side_guards_all_fire_in_one_walk(api):
    """Six refusals on the way from a bare building to an approved conversion.

    A repeated plate number, a second assessment opened while one is still in
    draft, an approval with no exhaust package declared, a repeated discipline, a
    close-out before approval and a close-out of something already closed are
    each answered in their own terms, and the walk still ends with an approved
    building carrying two packages.

    Design: Corner/errors/base_building_and_scope_guards_return_4XX
    """
    bundle = setup_building_with_floors(
        api, (2,), dict(NAMEPLATE), {2: dict(PLATE)}
    )
    building_id = bundle["building"]["id"]
    assessment = open_assessment(api, building_id, **DEMAND)

    validate_error(
        api.create_floor(
            building_id,
            floor_payload(2, floor_to_floor_ft=15.0, live_load_psf=100,
                          vibration_class="VC_D", sprinklered=True),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_FLOOR_NUMBER.value,
        409,
    )
    validate_error(
        api.create_assessment(
            building_id,
            assessment_payload(
                assessment_basis="INVESTIGATION",
                required_exhaust_cfm=50000,
                required_power_kw=700,
                measured_live_load_psf=OMIT,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_ASSESSMENT_ALREADY_OPEN.value,
        409,
    )
    submit_assessment(api, assessment["id"])
    decide_assessment(api, assessment["id"], "ACCEPT")
    validate_error(
        api.approve_conversion(building_id, LANDLORD_HEADERS),
        ApiErrorId.ERR_CONVERSION_SCOPE_INCOMPLETE.value,
        409,
    )

    waste = add_scope_item(api, building_id, "WASTE_HANDLING", **WASTE_ROOM)
    validate_error(
        api.create_scope_item(
            building_id,
            scope_item_payload("WASTE_HANDLING",
                              description="Duplicate waste handling package",
                              budget_usd=100000.00),
            LANDLORD_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_SCOPE_DISCIPLINE.value,
        409,
    )
    validate_error(
        api.complete_scope_item(waste["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_BUILDING_NOT_CONVERSION_APPROVED.value,
        409,
    )

    exhaust = add_scope_item(api, building_id, "LAB_EXHAUST", **EXHAUST_RISER)
    approved = approve_conversion(api, building_id)
    complete_scope_item(api, waste["id"])
    validate_error(
        api.complete_scope_item(waste["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_INVALID_SCOPE_ITEM_STATE.value,
        409,
    )

    assert approved["suitability_state"] == "CONVERSION_APPROVED"
    _, floor_meta = validate_paginated(
        api.list_building_floors(building_id, LANDLORD_HEADERS)
    )
    assert floor_meta["total_count"] == 1
    _, item_meta = validate_paginated(
        api.list_building_scope_items(building_id, LANDLORD_HEADERS)
    )
    assert item_meta["total_count"] == 2
    assert get_success_data(
        api.get_scope_item(waste["id"], LANDLORD_HEADERS)
    )["status"] == "COMPLETE"
    assert get_success_data(
        api.get_scope_item(exhaust["id"], LANDLORD_HEADERS)
    )["status"] == "PLANNED"


def test_the_three_negotiation_refusals_land_on_the_same_pair_of_rounds(api):
    """Who wrote it, what state it is in, and how old it is.

    The side that wrote a round may not accept it, a round already countered may
    not be accepted by anyone, and a round left open past its ten days may not be
    accepted once the clock has moved beyond it -- and through all three the
    ledger is still closed.

    Design: Corner/errors/negotiation_guards_return_4XX
    """
    bundle = setup_lease_at_loi(api, **_qc_terms())
    lease = bundle["lease"]
    tenant_headers = bundle["tenant_headers"]

    first = validate_success(
        _round(api, lease["id"], lease["version"], 70.00,
               LANDLORD_NEGOTIATOR_HEADERS),
        201,
    )
    validate_error(
        api.accept_proposal(first["id"], LANDLORD_NEGOTIATOR_HEADERS),
        ApiErrorId.ERR_SELF_ACCEPT_FORBIDDEN.value,
        403,
    )
    countered = get_lease(api, lease["id"])
    second = validate_success(
        _round(api, lease["id"], countered["version"], 90.00, tenant_headers), 201
    )
    validate_error(
        api.accept_proposal(first["id"], LANDLORD_SIGNER_HEADERS),
        ApiErrorId.ERR_INVALID_PROPOSAL_STATE.value,
        409,
    )

    set_clock(api, AFTER_THE_ROUNDS_EXPIRE)
    validate_error(
        api.accept_proposal(second["id"], LANDLORD_SIGNER_HEADERS),
        ApiErrorId.ERR_PROPOSAL_EXPIRED.value,
        409,
    )

    assert first["expires_at"].startswith(FIRST_ROUND_EXPIRY[:10])
    assert get_success_data(
        api.get_proposal(first["id"], LANDLORD_HEADERS)
    )["status"] == "COUNTERED"
    assert get_success_data(
        api.get_proposal(second["id"], LANDLORD_HEADERS)
    )["status"] == "OPEN"
    settled = get_lease(api, lease["id"])
    assert settled["status"] == "COUNTER_PENDING"
    assert settled["negotiation_round_count"] == 2
    assert_money(settled["ti_authorized_usd"], 0.00, "ti_authorized_usd")


def test_a_seventh_round_is_refused_once_six_have_been_exchanged(api):
    """The round budget is a ceiling reached rather than a ceiling passed.

    Six rounds are exchanged in turn and the sixth is accepted onto the lease,
    and the seventh -- correctly versioned and offered by the side whose turn it
    genuinely is -- is refused because the budget is already spent.

    Design: Corner/errors/seventh_negotiation_round_returns_4XX_at_the_round_limit
    """
    bundle = setup_lease_at_loi(api, **_qc_terms())
    lease_id = bundle["lease"]["id"]
    tenant_headers = bundle["tenant_headers"]
    exchange = [
        (70.00, LANDLORD_NEGOTIATOR_HEADERS),
        (95.00, tenant_headers),
        (75.00, LANDLORD_NEGOTIATOR_HEADERS),
        (92.00, tenant_headers),
        (78.00, LANDLORD_NEGOTIATOR_HEADERS),
        (88.00, tenant_headers),
    ]
    rounds = []
    for allowance_psf, headers in exchange:
        version = get_lease(api, lease_id)["version"]
        rounds.append(
            validate_success(_round(api, lease_id, version, allowance_psf, headers), 201)
        )
    sixth = rounds[-1]
    before = get_lease(api, lease_id)
    assert before["negotiation_round_count"] == 6
    assert before["version"] == 7
    assert sixth["round_number"] == 6

    response = _round(api, lease_id, before["version"], 80.00,
                      LANDLORD_NEGOTIATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value, 409)
    assert get_success_data(
        api.get_proposal(sixth["id"], LANDLORD_HEADERS)
    )["status"] == "OPEN"
    after = get_lease(api, lease_id)
    assert after["status"] == "COUNTER_PENDING"
    assert after["negotiation_round_count"] == 6
    _, meta = validate_paginated(
        api.list_lease_proposals(lease_id, LANDLORD_HEADERS)
    )
    assert meta["total_count"] == 6


def test_the_three_fiscal_refusals_bracket_execution_and_the_first_draw(api):
    """Money will not move before the escrow, nor after it without a commitment.

    Execution is refused while the escrow account is empty, and once it is funded
    to the requirement and the lease is signed a draw is still refused because no
    package has committed anything, and the wind-down notice is refused because
    the lease has only just begun.

    Design: Corner/errors/lease_fiscal_guards_return_4XX
    """
    bundle = setup_lease_at_terms_accepted(api, allowance_psf=70.00, **_qc_terms())
    lease_id = bundle["lease"]["id"]
    tenant_headers = bundle["tenant_headers"]
    assert_money(bundle["lease"]["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_money(
        bundle["lease"]["restoration_escrow_required_usd"], 20000.00, "escrow required"
    )

    validate_error(
        api.execute_lease(lease_id, LANDLORD_SIGNER_HEADERS),
        ApiErrorId.ERR_ESCROW_DEPOSIT_INSUFFICIENT.value,
        422,
    )
    get_success_data(
        api.create_escrow_deposit(
            lease_id, escrow_deposit_payload(20000.00), tenant_headers
        )
    )
    executed = validate_success(
        api.execute_lease(lease_id, LANDLORD_SIGNER_HEADERS), 200
    )
    validate_error(
        api.create_disbursement(
            lease_id, disbursement_payload(10000.00), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_TI_ALLOWANCE_EXHAUSTED.value,
        409,
    )
    validate_error(
        api.issue_expiration_notice(
            lease_id, expiration_notice_payload(FAR_EXPIRATION), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
        409,
    )

    assert executed["status"] == "EXECUTED"
    final = get_lease(api, lease_id)
    assert final["status"] == "EXECUTED"
    assert_money(final["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_money(final["ti_uncommitted_usd"], 200000.00, "ti_uncommitted_usd")
    assert_money(final["ti_committed_usd"], 0.00, "ti_committed_usd")
    assert_money(final["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert_money(final["restoration_escrow_held_usd"], 20000.00, "escrow held")
    assert final["expiration_date"] is None
    assert_ledger_identity(final)


def test_eight_construction_refusals_across_two_projects_on_one_plate(api):
    """The package chain, the permit dimension and the milestone all say no.

    A predecessor borrowed from the neighbour's project, a place in the chain
    already taken, a permit already issued, a package still in draft, a window
    with no duration, a predecessor not yet finished, a hold with nothing written
    on it and a milestone already declared are each refused in their own terms,
    and every package is left exactly where the walk found it.

    Design: Corner/errors/project_and_phase_guards_return_4XX
    """
    first = _qc_permitted_project(api)
    second = add_second_tenant_project(api, first, rentable_sf=2000, allowance_psf=70.00)
    package_b = create_phase(
        api, first["project"]["id"], 1, "SHELL", "QUIET", 40000.00,
        restoration_cost_usd=30000.00,
    )
    schedule_phase(api, package_b["id"], *PACKAGE_B_WINDOW)
    package_a = create_phase(
        api, second["project"]["id"], 1, "LAB_MEP", "QUIET", 50000.00,
        restoration_cost_usd=45000.00,
    )
    schedule_phase(api, package_a["id"], *PACKAGE_A_WINDOW)
    package_c = create_phase(
        api, second["project"]["id"], 2, "LAB_MEP", "QUIET", 30000.00,
        restoration_cost_usd=25000.00,
    )

    validate_error(
        api.create_phase(
            first["project"]["id"],
            phase_payload(5, "LAB_MEP", "QUIET", 10000.00,
                          restoration_cost_usd=9000.00,
                          predecessor_phase_id=package_a["id"]),
            LANDLORD_HEADERS,
        ),
        ApiErrorId.ERR_PREDECESSOR_NOT_IN_PROJECT.value,
        422,
    )
    validate_error(
        api.create_phase(
            first["project"]["id"],
            phase_payload(1, "LAB_MEP", "QUIET", 10000.00,
                          restoration_cost_usd=9000.00),
            LANDLORD_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_PHASE_SEQUENCE.value,
        409,
    )
    validate_error(
        api.apply_for_permit(first["project"]["id"], LANDLORD_HEADERS),
        ApiErrorId.ERR_INVALID_PERMIT_STATE.value,
        409,
    )
    validate_error(
        api.progress_phase(
            package_c["id"], progress_payload("IN_PROGRESS"), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_PHASE_STATE.value,
        409,
    )
    validate_error(
        api.schedule_phase(
            package_c["id"], schedule_payload(*DEGENERATE_WINDOW), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_WINDOW.value,
        422,
    )

    package_d = create_phase(
        api, second["project"]["id"], 3, "LAB_MEP", "QUIET", 20000.00,
        restoration_cost_usd=18000.00, predecessor_phase_id=package_a["id"],
    )
    schedule_phase(api, package_d["id"], *PACKAGE_D_WINDOW)
    validate_error(
        api.progress_phase(
            package_d["id"], progress_payload("IN_PROGRESS"), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_PREDECESSOR_NOT_COMPLETE.value,
        409,
    )
    validate_error(
        api.hold_phase(
            package_a["id"], hold_payload(BLANK_HOLD_REASON), ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_HOLD_REASON_REQUIRED.value,
        422,
    )

    progress_phase(api, package_b["id"], "IN_PROGRESS")
    progress_phase(api, package_b["id"], "COMPLETE")
    declared = get_success_data(
        api.declare_milestone(
            first["project"]["id"], milestone_payload(), LANDLORD_HEADERS
        )
    )
    validate_error(
        api.declare_milestone(
            first["project"]["id"], milestone_payload(), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    assert declared["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    assert declared["permit_status"] == "P_ISSUED"
    still_draft = get_phase(api, package_c["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["window_start"] is None
    assert get_phase(api, package_a["id"])["status"] == "SCHEDULED"
    assert get_phase(api, package_d["id"])["status"] == "SCHEDULED"
    assert get_phase(api, package_b["id"])["status"] == "COMPLETE"
    assert get_project(api, second["project"]["id"])["construction_status"] == (
        "C_NOT_STARTED"
    )
    _, meta = validate_paginated(
        api.list_phases(LANDLORD_HEADERS, {"project_id": first["project"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_cancelled_reservation_and_a_ruled_permit_both_refuse_a_second_act(api):
    """Three refusals across the capacity book and the code ruling.

    Capacity already given back cannot be given back again, a refusal must say
    why before it is accepted, and once the application has been refused it can
    no longer be approved -- and the pools are left with nothing spoken for.

    Design: Corner/errors/capacity_and_hazmat_decision_guards_return_4XX
    """
    bundle = _qc_permitted_project(api)
    reservation = reserve_capacity(
        api, bundle["project"]["id"], bundle["building"]["id"], 12000, 180
    )
    permit = file_hazmat_permit(
        api, bundle["project"]["id"], bundle["premises_floor"]["id"],
        "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 100.00, 1, bundle["tenant_headers"],
    )

    cancelled = get_success_data(
        api.cancel_reservation(reservation["id"], LANDLORD_HEADERS)
    )
    validate_error(
        api.cancel_reservation(reservation["id"], LANDLORD_HEADERS),
        ApiErrorId.ERR_INVALID_RESERVATION_STATE.value,
        409,
    )
    validate_error(
        api.decide_hazmat_permit(
            permit["id"], hazmat_decision_payload("DENY"), AHJ_HEADERS
        ),
        ApiErrorId.ERR_DECISION_REASON_REQUIRED.value,
        422,
    )
    denied = decide_hazmat_permit(api, permit["id"], "DENY", DENIAL_REASON)
    validate_error(
        api.decide_hazmat_permit(
            permit["id"], hazmat_decision_payload("APPROVE"), AHJ_HEADERS
        ),
        ApiErrorId.ERR_INVALID_PERMIT_DECISION.value,
        409,
    )

    assert cancelled["status"] == "CANCELLED"
    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == DENIAL_REASON
    assert get_permit(api, permit["id"])["status"] == "DENIED"
    building = get_success_data(
        api.get_building(bundle["building"]["id"], LANDLORD_HEADERS)
    )
    assert_money(building["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(building["power_reserved_kw"], 0.00, "power_reserved_kw")


def test_the_five_commissioning_refusals_on_a_two_script_programme(api):
    """A quality control programme wants two scripts and no others.

    A script the programme does not require cannot be scheduled, a script it
    already has cannot be scheduled twice, a result cannot be written before the
    work is substantially complete, the technician who ran the script may not
    witness it, and once the result is written it cannot be written again.

    Design: Corner/errors/commissioning_guards_return_4XX
    """
    bundle = setup_lease_with_committed_phases(
        api,
        [{"premium_class": "SHELL", "work_class": "QUIET",
          "hard_cost_usd": 100000.00, "restoration_cost_usd": 90000.00}],
        allowance_psf=70.00,
        **_qc_terms(project_overrides=dict(QC_PROJECT)),
    )
    project_id = bundle["project"]["id"]
    installation = schedule_script(
        api, project_id, "IQ", USER_CX_TECH, "2026-08-20T09:00:00Z"
    )

    validate_error(
        api.create_commissioning_record(
            project_id,
            commissioning_record_payload("PQ", USER_CX_TECH, "2026-08-21T09:00:00Z"),
            CX_AGENT_HEADERS,
        ),
        ApiErrorId.ERR_SCRIPT_NOT_REQUIRED.value,
        422,
    )
    validate_error(
        api.create_commissioning_record(
            project_id,
            commissioning_record_payload("IQ", USER_CX_TECH, "2026-08-22T09:00:00Z"),
            CX_AGENT_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_COMMISSIONING_SCRIPT.value,
        409,
    )
    validate_error(
        api.record_commissioning_result(
            installation["id"],
            commissioning_result_payload("PASS", USER_CX_WITNESS, measured_value=1.00),
            CX_AGENT_HEADERS,
        ),
        ApiErrorId.ERR_COMMISSIONING_INCOMPLETE.value,
        409,
    )

    get_success_data(
        api.declare_milestone(project_id, milestone_payload(), LANDLORD_HEADERS)
    )
    validate_error(
        api.record_commissioning_result(
            installation["id"],
            commissioning_result_payload("PASS", USER_CX_TECH, measured_value=1.00),
            CX_AGENT_HEADERS,
        ),
        ApiErrorId.ERR_WITNESS_CONFLICT.value,
        403,
    )
    passed = get_success_data(
        api.record_commissioning_result(
            installation["id"],
            commissioning_result_payload("PASS", USER_CX_WITNESS, measured_value=1.00),
            CX_AGENT_HEADERS,
        )
    )
    validate_error(
        api.record_commissioning_result(
            installation["id"],
            commissioning_result_payload("PASS", USER_CX_WITNESS, measured_value=1.00),
            CX_AGENT_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_COMMISSIONING_STATE.value,
        409,
    )

    assert passed["status"] == "PASSED"
    assert get_record(api, installation["id"])["status"] == "PASSED"
    assert bundle["tenant"]["required_commissioning_scripts"] == ["IQ", "OQ"]
    project = get_project(api, project_id)
    assert project["passed_script_count"] == 1
    assert project["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    assert get_lease(api, bundle["lease"]["id"])["status"] == "EXECUTED"
    _, meta = validate_paginated(
        api.list_project_commissioning_records(project_id, LANDLORD_HEADERS)
    )
    assert meta["total_count"] == 1


def test_a_surrendered_lease_refuses_everything_that_follows(api):
    """Settlement is the last thing that happens to a lease.

    The escrow covers the whole restoration bill and the balance is refunded, the
    entire undrawn allowance lapses, and then a second settlement, a draw, a
    second notice and a fresh negotiation round are all refused because the lease
    has reached the end.

    Design: Corner/errors/surrendered_lease_is_terminal_further_transitions_returns_4XX
    """
    bundle = setup_lease_with_committed_phases(
        api,
        [{"premium_class": "SHELL", "work_class": "QUIET",
          "hard_cost_usd": 100000.00, "restoration_cost_usd": 90000.00}],
        allowance_psf=70.00,
        **_qc_terms(project_overrides=dict(QC_PROJECT)),
    )
    project_id = bundle["project"]["id"]
    lease_id = bundle["lease"]["id"]
    permit = file_hazmat_permit(
        api, project_id, bundle["premises_floor"]["id"], "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE", 100.00, 1, bundle["tenant_headers"],
    )
    decide_hazmat_permit(api, permit["id"], "APPROVE")
    get_success_data(
        api.declare_milestone(project_id, milestone_payload(), LANDLORD_HEADERS)
    )
    pass_all_scripts(api, project_id, "ANALYTICAL_QC")
    noticed = issue_expiration_notice(api, lease_id, FAR_EXPIRATION)
    assert noticed["status"] == "EXPIRING"
    assert_money(noticed["restoration_liability_usd"], 550.00, "restoration liability")

    settled = validate_success(api.settle_restoration(lease_id, LANDLORD_HEADERS), 200)

    validate_error(
        api.settle_restoration(lease_id, LANDLORD_HEADERS),
        ApiErrorId.ERR_RESTORATION_ALREADY_SETTLED.value,
        409,
    )
    validate_error(
        api.create_disbursement(
            lease_id, disbursement_payload(1000.00), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
        409,
    )
    validate_error(
        api.issue_expiration_notice(
            lease_id, expiration_notice_payload(SECOND_EXPIRATION), LANDLORD_HEADERS
        ),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
        409,
    )
    validate_error(
        _round(api, lease_id, settled["version"], 60.00, LANDLORD_NEGOTIATOR_HEADERS),
        ApiErrorId.ERR_INVALID_LEASE_STATE.value,
        409,
    )

    assert settled["status"] == "SURRENDERED"
    assert_money(settled["restoration_liability_usd"], 550.00, "restoration liability")
    assert_money(settled["restoration_escrow_refunded_usd"], 19450.00, "escrow refunded")
    assert_money(settled["restoration_cash_due_usd"], 0.00, "cash due")
    assert_money(settled["ti_forfeited_usd"], 200000.00, "ti_forfeited_usd")
    final = get_lease(api, lease_id)
    assert_money(final["restoration_escrow_held_usd"], 0.00, "escrow held")
    assert_money(final["ti_uncommitted_usd"], 0.00, "ti_uncommitted_usd")
    assert_money(final["ti_committed_usd"], 0.00, "ti_committed_usd")
    assert_money(final["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert final["expiration_date"].startswith(FAR_EXPIRATION[:10])
    assert_ledger_identity(final)
    assert get_permit(api, permit["id"])["status"] == "SURRENDERED"
    assert_money(
        get_phase(api, bundle["phases"][0]["id"])["ti_committed_usd"],
        60000.00,
        "ti_committed_usd",
    )
    assert get_project(api, project_id)["construction_status"] == "C_ACCEPTED"
