"""Lifecycles: the transitions that are allowed, the ones that are not, and what
each one drags along behind it."""

from test_helpers import (
    AHJ_HEADERS,
    CLOCK_START,
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    ApiErrorId,
    add_scope_item,
    approve_conversion,
    assert_allocation,
    assert_assessment,
    assert_lease,
    assert_ledger_identity,
    assert_money,
    assert_phase,
    assert_reservation,
    assert_score,
    assert_scope_item,
    book_allocation,
    complete_scope_item,
    confirm_allocation,
    create_amenity,
    create_building,
    create_floor,
    create_lease,
    create_phase,
    create_project,
    create_tenant,
    decide_assessment,
    execute_lease,
    fund_escrow_exactly,
    get_allocation,
    get_assessment,
    get_building,
    get_lease,
    get_phase,
    get_project,
    get_success_data,
    hazmat_permit_payload,
    make_tenant_headers,
    open_assessment,
    phase_payload,
    progress_phase,
    proposal_payload,
    reservation_payload,
    same_instant,
    schedule_phase,
    set_clock,
    setup_assessed_building,
    setup_building_with_floors,
    setup_permitted_project,
    submit_assessment,
    utc,
    validate_error,
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
ALL_FOUR_DISCIPLINES = (
    "LAB_EXHAUST",
    "EMERGENCY_POWER",
    "CHEMICAL_STORAGE",
    "WASTE_HANDLING",
)

RETURN_NOTE = "Confirm live load by core sampling on floor 2"
HOLD_REASON = "Adjacent occupied tenant reports VC_C exceedance during core drilling"

FIRST_PACKAGE_WINDOW = (utc(2026, 8, 5), utc(2026, 8, 6))
SECOND_PACKAGE_WINDOW = (utc(2026, 8, 25), utc(2026, 8, 26))
PAST_BOOKING = (utc(2026, 8, 3), utc(2026, 8, 4))
FUTURE_BOOKING = (utc(2026, 8, 20, 8), utc(2026, 8, 20, 12))
INSIDE_THE_PAST_BOOKING = "2026-08-03T12:00:00Z"
SHELL_WINDOW = (utc(2026, 9, 1), utc(2026, 9, 5))
RESCHEDULE_ATTEMPT = (utc(2026, 10, 1), utc(2026, 10, 5))
CANCELLED_BOOKING = (utc(2026, 9, 10, 8), utc(2026, 9, 10, 12))


def _qc_tenant(api):
    return create_tenant(
        api,
        "ANALYTICAL_QC",
        legal_name="Assay Metrics QC Inc",
        credit_tier="VENTURE_BACKED",
    )


def _a_submitted_screening(api):
    """A building with a plate and one screening assessment already submitted."""
    bundle = setup_building_with_floors(api, (2,), dict(NAMEPLATE), {2: dict(PLATE)})
    assessment = open_assessment(api, bundle["building"]["id"], **DEMAND)
    bundle["assessment"] = submit_assessment(api, assessment["id"])
    return bundle


def _qc_project_with_one_package(api, phase_spec):
    """A permitted QC project on floor 2 carrying one package in draft."""
    bundle = setup_permitted_project(
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
    bundle["phase"] = create_phase(api, bundle["project"]["id"], **phase_spec)
    return bundle


def test_submitting_the_screening_freezes_the_verdict_without_moving_the_building(api):
    """Submission computes the numbers; only a decision moves the asset.

    The submitted assessment carries a frozen score and verdict and has nobody
    recorded as having decided it, while the building is still in assessment with
    no verdict copied onto it.

    Design: Corner/state_machines/assessment_submit_transitions_draft_to_submitted_and_freezes_verdict
    """
    bundle = setup_building_with_floors(api, (2,), dict(NAMEPLATE), {2: dict(PLATE)})
    assessment = open_assessment(api, bundle["building"]["id"], **DEMAND)
    assert assessment["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_assessment(assessment["id"], ENGINEER_HEADERS), 200
    )

    assert_assessment(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert_score(submitted["suitability_score"], 78.0)
    assert submitted["verdict"] == "SUITABLE"
    assert submitted["hard_fail_capped"] is False
    assert submitted["decided_by_user_id"] is None
    building = get_building(api, bundle["building"]["id"])
    assert building["suitability_state"] == "ASSESSING"
    assert building["latest_assessment_verdict"] is None


def test_sending_the_screening_back_requires_saying_why(api):
    """A return without a note is refused; with one it is recorded.

    The bare return leaves the assessment submitted, and the same decision
    carrying the engineer's instruction is accepted, stores the note verbatim and
    still leaves the building in assessment.

    Design: Corner/state_machines/assessment_return_decision_without_note_rejected
    """
    bundle = _a_submitted_screening(api)
    assessment_id = bundle["assessment"]["id"]

    bare = api.decide_assessment(
        assessment_id, {"decision": "RETURN"}, LANDLORD_HEADERS
    )
    validate_error(bare, ApiErrorId.ERR_RETURN_NOTE_REQUIRED.value, 422)
    assert get_assessment(api, assessment_id)["status"] == "SUBMITTED"

    returned = validate_success(
        api.decide_assessment(
            assessment_id,
            {"decision": "RETURN", "return_note": RETURN_NOTE},
            LANDLORD_HEADERS,
        ),
        200,
    )

    assert returned["status"] == "RETURNED"
    assert returned["return_note"] == RETURN_NOTE
    assert get_building(api, bundle["building"]["id"])["suitability_state"] == "ASSESSING"


def test_the_asset_turns_over_only_when_the_last_discipline_closes_out(api):
    """Three closed-out disciplines are not enough; the fourth is.

    With three of the four conversion disciplines complete the building is still
    merely approved, and closing the fourth carries it to its terminal state and
    leaves both pools standing at the augmented figures.

    Design: Corner/state_machines/last_discipline_completion_bubbles_building_to_conversion_complete
    """
    bundle = setup_assessed_building(
        api, (2,), dict(NAMEPLATE), {2: dict(PLATE)}, dict(DEMAND)
    )
    building_id = bundle["building"]["id"]
    items = {
        "LAB_EXHAUST": add_scope_item(
            api, building_id, "LAB_EXHAUST", capacity_delta_cfm=20000
        ),
        "EMERGENCY_POWER": add_scope_item(
            api, building_id, "EMERGENCY_POWER", capacity_delta_kw=400
        ),
        "CHEMICAL_STORAGE": add_scope_item(api, building_id, "CHEMICAL_STORAGE"),
        "WASTE_HANDLING": add_scope_item(api, building_id, "WASTE_HANDLING"),
    }
    approve_conversion(api, building_id)
    for discipline in ("LAB_EXHAUST", "EMERGENCY_POWER", "CHEMICAL_STORAGE"):
        complete_scope_item(api, items[discipline]["id"])
    assert get_building(api, building_id)["suitability_state"] == "CONVERSION_APPROVED"

    last = validate_success(
        api.complete_scope_item(items["WASTE_HANDLING"]["id"], ENGINEER_HEADERS), 200
    )

    assert_scope_item(last)
    assert last["status"] == "COMPLETE"
    assert same_instant(last["completed_at"], CLOCK_START)
    building = get_building(api, building_id)
    assert building["suitability_state"] == "CONVERSION_COMPLETE"
    assert building["scope_disciplines_covered"] == sorted(ALL_FOUR_DISCIPLINES)
    assert building["scope_disciplines_complete"] == sorted(ALL_FOUR_DISCIPLINES)
    assert_money(building["exhaust_capacity_total_cfm"], 80000.00, "exhaust total")
    assert_money(building["exhaust_available_cfm"], 80000.00, "exhaust_available_cfm")
    assert_money(building["power_capacity_total_kw"], 1200.00, "power total")
    assert_money(building["power_available_kw"], 1200.00, "power_available_kw")


def test_an_unsubmitted_screening_cannot_be_accepted(api):
    """There is no decision path out of the drafting state.

    Accepting a draft is refused and leaves both the assessment and the building
    untouched, and the identical acceptance succeeds once the engineer has
    submitted the score, carrying the building along the branch its verdict names.

    Design: Corner/state_machines/assessment_cannot_be_decided_while_still_draft
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(api, building["id"], **DEMAND)

    premature = api.decide_assessment(
        assessment["id"], {"decision": "ACCEPT"}, LANDLORD_HEADERS
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value, 409)
    assert get_assessment(api, assessment["id"])["status"] == "DRAFT"
    assert get_building(api, building["id"])["latest_assessment_verdict"] is None

    submit_assessment(api, assessment["id"])
    accepted = validate_success(
        api.decide_assessment(
            assessment["id"], {"decision": "ACCEPT"}, LANDLORD_HEADERS
        ),
        200,
    )

    assert accepted["status"] == "ACCEPTED"
    assert get_building(api, building["id"])["suitability_state"] == "ASSESSED_SUITABLE"


def test_nothing_is_born_part_way_through_its_lifecycle(api):
    """Every create lands in the declared opening state.

    Nine kinds of row are created along one deal and each one is observed at the
    state its lifecycle opens in, with no create-time advance and no prior status
    recorded on a package that has never moved.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    building = create_building(api, **NAMEPLATE)
    assert building["suitability_state"] == "DRAFT"
    floor = create_floor(api, building["id"], 2, **PLATE)
    assessment = open_assessment(api, building["id"], **DEMAND)
    assert assessment["status"] == "DRAFT"
    submit_assessment(api, assessment["id"])
    decide_assessment(api, assessment["id"], "ACCEPT")
    scope_item = add_scope_item(
        api, building["id"], "LAB_EXHAUST", capacity_delta_cfm=20000
    )
    assert scope_item["status"] == "PLANNED"
    approve_conversion(api, building["id"])
    complete_scope_item(api, scope_item["id"])
    amenity = create_amenity(
        api,
        building["id"],
        2,
        name="Glasswash 2A",
        amenity_type="GLASSWASH",
        concurrent_capacity=20,
    )
    tenant = _qc_tenant(api)
    tenant_headers = make_tenant_headers(tenant["id"])
    lease = create_lease(
        api, tenant["id"], building["id"], floor["id"], 2000, **QC_LEASE
    )
    assert lease["status"] == "LOI"
    proposal = get_success_data(
        api.create_proposal(
            lease["id"],
            proposal_payload(lease["version"], 70.00),
            LANDLORD_NEGOTIATOR_HEADERS,
        )
    )
    assert proposal["status"] == "OPEN"
    get_success_data(api.accept_proposal(proposal["id"], tenant_headers))
    fund_escrow_exactly(api, lease["id"], tenant_headers)
    execute_lease(api, lease["id"])
    project = create_project(api, lease["id"], floor["id"], **QC_PROJECT)
    assert project["permit_status"] == "P_UNPERMITTED"
    assert project["construction_status"] == "C_NOT_STARTED"
    assert project["delivery_risk"] == "ON_TRACK"
    get_success_data(api.apply_for_permit(project["id"], LANDLORD_HEADERS))
    get_success_data(
        api.decide_permit(project["id"], {"decision": "ISSUE"}, AHJ_HEADERS)
    )

    phase = validate_success(
        api.create_phase(
            project["id"],
            phase_payload(1, "LAB_MEP", "QUIET", 50000.00, restoration_cost_usd=30000.00),
            LANDLORD_HEADERS,
        ),
        201,
    )
    reservation = validate_success(
        api.create_reservation(
            reservation_payload(
                project["id"],
                get_building(api, building["id"])["version"],
                12000.00,
                180.00,
            ),
            LANDLORD_HEADERS,
        ),
        201,
    )
    permit = validate_success(
        api.create_hazmat_permit(
            hazmat_permit_payload(
                project["id"],
                floor["id"],
                "FLAMMABLE_IB",
                "CLOSED_SYSTEM_USE",
                50.00,
                1,
            ),
            tenant_headers,
        ),
        201,
    )
    allocation = validate_success(
        api.create_allocation(
            {
                "amenity_id": amenity["id"],
                "project_id": project["id"],
                "window_start": utc(2026, 8, 10, 8),
                "window_end": utc(2026, 8, 10, 12),
                "headcount": 5,
            },
            tenant_headers,
        ),
        201,
    )

    assert_phase(phase)
    assert phase["status"] == "DRAFT"
    assert phase["prior_status"] is None
    assert_reservation(reservation)
    assert reservation["status"] == "RESERVED"
    assert permit["status"] == "REQUESTED"
    assert_allocation(allocation)
    assert allocation["status"] == "REQUESTED"


def test_the_conversion_can_only_be_approved_once(api):
    """A repeated approval is refused rather than absorbed.

    The first approval carries the building across and the identical second call
    is refused on the building's state, leaving the version exactly where the
    first approval left it.

    Design: Corner/state_machines/second_conversion_approval_returns_4XX
    """
    bundle = setup_assessed_building(api, (2,), dict(NAMEPLATE), {2: dict(PLATE)}, dict(DEMAND))
    building_id = bundle["building"]["id"]
    add_scope_item(api, building_id, "LAB_EXHAUST", capacity_delta_cfm=20000)

    first = validate_success(api.approve_conversion(building_id, LANDLORD_HEADERS), 200)
    assert first["suitability_state"] == "CONVERSION_APPROVED"

    second = api.approve_conversion(building_id, LANDLORD_HEADERS)
    validate_error(second, ApiErrorId.ERR_INVALID_BUILDING_STATE.value, 409)

    final = get_building(api, building_id)
    assert final["version"] == first["version"]
    assert final["suitability_state"] == "CONVERSION_APPROVED"


def test_the_hold_spares_the_booking_that_is_already_under_way(api):
    """The cascade onto bookings is judged against the clock.

    Two confirmed bookings sit on the same amenity, one of them already running
    at the current instant, and the hold preempts only the one whose window has
    not opened yet while the project is suspended and flagged.

    Design: Corner/state_machines/hold_cascade_preempts_only_allocations_whose_window_has_not_started
    """
    bundle = setup_permitted_project(
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
    project_id = bundle["project"]["id"]
    amenity = create_amenity(
        api,
        bundle["building"]["id"],
        2,
        name="Glasswash 2A",
        amenity_type="GLASSWASH",
        concurrent_capacity=20,
    )
    running_package = create_phase(
        api,
        project_id,
        sequence_no=1,
        premium_class="LAB_MEP",
        work_class="QUIET",
        hard_cost_usd=50000.00,
        restoration_cost_usd=30000.00,
    )
    schedule_phase(api, running_package["id"], *FIRST_PACKAGE_WINDOW)
    progress_phase(api, running_package["id"], "IN_PROGRESS")
    noisy_package = create_phase(
        api,
        project_id,
        sequence_no=2,
        premium_class="LAB_MEP",
        work_class="VIBRATION_GENERATING",
        hard_cost_usd=40000.00,
        restoration_cost_usd=25000.00,
    )
    schedule_phase(api, noisy_package["id"], *SECOND_PACKAGE_WINDOW)
    under_way = confirm_allocation(
        api,
        book_allocation(
            api, amenity["id"], project_id, *PAST_BOOKING, headcount=5,
            headers=bundle["tenant_headers"],
        )["id"],
    )
    still_to_come = confirm_allocation(
        api,
        book_allocation(
            api, amenity["id"], project_id, *FUTURE_BOOKING, headcount=5,
            headers=bundle["tenant_headers"],
        )["id"],
    )
    set_clock(api, INSIDE_THE_PAST_BOOKING)

    held = validate_success(
        api.hold_phase(
            noisy_package["id"], {"hold_reason": HOLD_REASON}, ENGINEER_HEADERS
        ),
        200,
    )

    assert held["status"] == "VIBRATION_HOLD"
    assert held["hold_reason"] == HOLD_REASON
    assert get_allocation(api, under_way["id"])["status"] == "CONFIRMED"
    assert get_allocation(api, still_to_come["id"])["status"] == "PREEMPTED"
    project = get_project(api, project_id)
    assert project["construction_status"] == "C_SUSPENDED"
    assert project["delivery_risk"] == "AT_RISK"
    assert get_phase(api, running_package["id"])["status"] == "IN_PROGRESS"


def test_completing_the_package_moves_the_money_out_of_the_uncommitted_bucket(api):
    """The commitment is the package's eligible figure, to the cent.

    Completion computes the package's eligible amount from its class and its hard
    cost, commits exactly that much, and takes precisely the same amount out of
    the lease's uncommitted bucket into its committed bucket with the ledger
    identity intact.

    Design: Corner/state_machines/phase_completion_ledger_syncs_lease_commitment_buckets
    """
    bundle = _qc_project_with_one_package(
        api,
        {
            "sequence_no": 1,
            "premium_class": "LAB_MEP",
            "work_class": "QUIET",
            "hard_cost_usd": 50000.00,
            "restoration_cost_usd": 30000.00,
        },
    )
    phase_id = bundle["phase"]["id"]
    schedule_phase(api, phase_id, *FIRST_PACKAGE_WINDOW)
    progress_phase(api, phase_id, "IN_PROGRESS")
    before = get_lease(api, bundle["lease"]["id"])
    assert_money(before["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_money(before["ti_uncommitted_usd"], 200000.00, "ti_uncommitted_usd")
    assert_money(before["ti_committed_usd"], 0.00, "ti_committed_usd")

    completed = validate_success(
        api.progress_phase(phase_id, {"target_status": "COMPLETE"}, LANDLORD_HEADERS),
        200,
    )

    assert_phase(completed)
    assert completed["status"] == "COMPLETE"
    assert_money(completed["ti_eligible_usd"], 50150.00, "ti_eligible_usd")
    assert_money(completed["ti_committed_usd"], 50150.00, "ti_committed_usd")
    assert_money(completed["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    after = get_lease(api, bundle["lease"]["id"])
    assert_lease(after)
    assert_money(after["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_money(after["ti_committed_usd"], 50150.00, "ti_committed_usd")
    assert_money(after["ti_uncommitted_usd"], 149850.00, "ti_uncommitted_usd")
    assert_money(after["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert_money(after["ti_forfeited_usd"], 0.00, "ti_forfeited_usd")
    assert_ledger_identity(after)


def test_a_finished_package_and_a_cancelled_booking_accept_nothing_further(api):
    """Terminal means terminal on both entities.

    Five further transitions are attempted against a completed package and a
    cancelled booking and every one is refused with that entity's own state
    condition, leaving the package's window, hold reason and committed figure
    exactly as completion left them.

    Design: Corner/state_machines/terminal_rows_refuse_every_further_transition
    """
    bundle = _qc_project_with_one_package(
        api,
        {
            "sequence_no": 1,
            "premium_class": "SHELL",
            "work_class": "QUIET",
            "hard_cost_usd": 100000.00,
            "restoration_cost_usd": 90000.00,
        },
    )
    phase_id = bundle["phase"]["id"]
    schedule_phase(api, phase_id, *SHELL_WINDOW)
    progress_phase(api, phase_id, "IN_PROGRESS")
    progress_phase(api, phase_id, "COMPLETE")
    amenity = create_amenity(
        api,
        bundle["building"]["id"],
        2,
        name="Glasswash and autoclave suite",
        amenity_type="GLASSWASH",
        concurrent_capacity=2,
        vibration_sensitive=False,
        utility_draw_kw=40,
    )
    booking = book_allocation(
        api,
        amenity["id"],
        bundle["project"]["id"],
        *CANCELLED_BOOKING,
        headcount=3,
        headers=bundle["tenant_headers"],
    )
    get_success_data(api.cancel_allocation(booking["id"], bundle["tenant_headers"]))

    validate_error(
        api.progress_phase(phase_id, {"target_status": "IN_PROGRESS"}, LANDLORD_HEADERS),
        ApiErrorId.ERR_INVALID_PHASE_STATE.value,
        409,
    )
    validate_error(
        api.schedule_phase(
            phase_id,
            {
                "window_start": RESCHEDULE_ATTEMPT[0],
                "window_end": RESCHEDULE_ATTEMPT[1],
            },
            LANDLORD_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_PHASE_STATE.value,
        409,
    )
    validate_error(
        api.hold_phase(
            phase_id,
            {"hold_reason": "Late vibration complaint on a finished phase"},
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_PHASE_STATE.value,
        409,
    )
    validate_error(
        api.confirm_allocation(booking["id"], LANDLORD_HEADERS),
        ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value,
        409,
    )
    validate_error(
        api.cancel_allocation(booking["id"], bundle["tenant_headers"]),
        ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value,
        409,
    )

    phase = get_phase(api, phase_id)
    assert phase["status"] == "COMPLETE"
    assert same_instant(phase["window_start"], SHELL_WINDOW[0])
    assert same_instant(phase["window_end"], SHELL_WINDOW[1])
    assert phase["hold_reason"] is None
    assert_money(phase["ti_committed_usd"], 60000.00, "ti_committed_usd")
    assert get_allocation(api, booking["id"])["status"] == "CANCELLED"
    lease = get_lease(api, bundle["lease"]["id"])
    assert_money(lease["ti_committed_usd"], 60000.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 140000.00, "ti_uncommitted_usd")
