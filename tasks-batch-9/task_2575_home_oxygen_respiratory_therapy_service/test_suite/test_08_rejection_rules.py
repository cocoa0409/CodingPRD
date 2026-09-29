"""Rejection rules: the guards that refuse a request outright.

Every test here drives one request that the PRD says must be refused, names the
error identifier the PRD binds to that rule, and then reads the affected rows
back to confirm the refusal changed nothing it was not allowed to change.
Where the PRD pins a rule to a single instant, a single litre or a single
cylinder, the accepted neighbour is exercised alongside the refused one so the
boundary itself is observable rather than merely asserted.

Every test builds its own state from scratch: the database is empty and the
logical clock sits at its startup value when each test begins.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    DELIVERY_DRIVER,
    INTAKE_COORDINATOR,
    NON_EXISTENT_UUID,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_clock_advance_result,
    assert_equipment_unit,
    assign_equipment,
    create_cmn_payload,
    create_delivery_route_payload,
    create_equipment_unit_payload,
    create_qualifying_test_payload,
    create_rental_contract_payload,
    create_route_stop_payload,
    create_transfer_request_payload,
    create_travel_authorization_payload,
    drive_cmn_to_active,
    file_malfunction,
    make_branch,
    make_cmn,
    make_delivery_route,
    make_equipment_unit,
    make_liquid_branch,
    make_patient,
    make_qualifying_test,
    make_route_stop,
    open_transfer,
    post_billing_month_payload,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_placement,
    read_route,
    request_travel,
    service_unit,
    set_clock_payload,
    setup_active_cmn,
    setup_admitted_patient,
    setup_cap_reached_contract,
    setup_contract_in_service,
    setup_liquid_in_service,
    setup_open_contract,
    setup_posted_month,
    setup_qualifying_study,
    setup_recalled_contract,
    setup_reserved_equipment,
    sole_placement,
    unlock_route,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─────────────────────────────────────────────────────────────────────────────
# Qualifying studies and certificate documentation
# ─────────────────────────────────────────────────────────────────────────────


def test_a_study_dated_after_the_logical_clock_is_refused():
    """A qualifying study cannot be recorded as having been performed in the future.

    PRD: "A study performed in the future is nonsense, so a `tested_at` strictly after the logical clock is rejected with `ERR_TEST_DATE_IN_FUTURE`."

    Design: Corner/validations/clinical_study_and_certificate_documentation_rules_reject
    """
    scenario = setup_admitted_patient()
    patient_id = scenario["patient"]["id"]

    # The clock sits at its startup value of 2026-08-01T00:00:00Z.
    future_payload = create_qualifying_test_payload(
        patient_id, tested_at="2026-08-02T09:00:00Z"
    )
    validate_error(
        api_client.create_qualifying_test(future_payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_TEST_DATE_IN_FUTURE.value,
    )

    rows, meta = validate_paginated(
        api_client.list_qualifying_tests(
            INTAKE_COORDINATOR, params={"patient_id": patient_id}
        )
    )
    assert meta["total_count"] == 0, (
        "a study rejected as future-dated leaves no row on the chart"
    )
    assert rows == [], "the rejected study was not recorded"


def test_a_certificate_may_not_be_drafted_on_a_non_qualifying_study():
    """A certificate cannot be drafted against a study whose computed group does not qualify.

    PRD: "The named study's computed group must not be `NON_QUALIFYING`, or the draft is refused with `ERR_TEST_NON_QUALIFYING`."

    Design: Corner/validations/clinical_study_and_certificate_documentation_rules_reject
    """
    scenario = setup_admitted_patient()
    patient = scenario["patient"]

    # 92 percent saturation is neither a Group I hit nor a borderline reading.
    non_qualifying = make_qualifying_test(patient["id"], spo2_percent=92)
    assert non_qualifying["qualifying_group"] == "NON_QUALIFYING", (
        "a saturation of 92 percent qualifies for nothing"
    )

    payload = create_cmn_payload(
        patient["id"], non_qualifying["id"], patient["version"]
    )
    validate_error(
        api_client.create_cmn(payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_TEST_NON_QUALIFYING.value,
    )

    _, meta = validate_paginated(
        api_client.list_cmns(INTAKE_COORDINATOR, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "the refused draft was never created"


def test_a_certificate_may_not_name_another_patients_study():
    """A certificate must name a study belonging to the same patient it is drafted for.

    PRD: "An `IntakeCoordinator` drafts one against a `patient_id` and a `qualifying_test_id`, and the two must agree: a study belonging to a different patient than the one named on the certificate is rejected with `ERR_TEST_PATIENT_MISMATCH`."

    Design: Corner/validations/clinical_study_and_certificate_documentation_rules_reject
    """
    scenario = setup_qualifying_study()
    first_patient_study = scenario["qualifying_test"]
    second_patient = make_patient(
        scenario["branch"]["id"], mrn="MRN-0002", full_name="Dennis Okafor"
    )

    payload = create_cmn_payload(
        second_patient["id"], first_patient_study["id"], second_patient["version"]
    )
    validate_error(
        api_client.create_cmn(payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_TEST_PATIENT_MISMATCH.value,
    )

    reread = read_patient(second_patient["id"])
    assert reread["current_cmn_status"] == "NONE", (
        "the refused draft left the second patient's certificate mirror untouched"
    )
    assert reread["version"] == second_patient["version"], (
        "a refused draft does not advance the patient's version"
    )


def test_a_stale_study_is_reported_before_incomplete_documentation():
    """Submitting on a study past its grace window reports staleness, not thin documentation.

    PRD: "This check is ordered deliberately *ahead* of the documentation-completeness threshold below it: once a study is past its grace window its currency component scores zero and the remaining five components cap at 80.00, so a stale-study submission would otherwise always surface as an incomplete-documentation failure and this rule could never be observed."

    Design: Corner/validations/clinical_study_and_certificate_documentation_rules_reject
    """
    scenario = setup_admitted_patient()
    patient = scenario["patient"]

    # A resting-room-air study is current for 30 days, so this one expired on
    # 2026-07-01 and its 15-day grace window closed on 2026-07-16.
    stale_study = make_qualifying_test(patient["id"], tested_at="2026-06-01T00:00:00Z")
    assert stale_study["validity_days"] == 30
    assert stale_study["test_validity_expires_at"] == "2026-07-01T00:00:00.000Z"

    cmn = make_cmn(patient, stale_study["id"])
    # Group 30 plus currency 0 plus usage 15 plus narrative 20 plus portable
    # consistency 10 plus duration 5.
    assert cmn["documentation_score"] == 80.00, (
        "a stale study caps the remaining five components at 80.00"
    )

    validate_error(
        api_client.submit_cmn(cmn["id"], INTAKE_COORDINATOR),
        ApiErrorId.ERR_QUALIFYING_TEST_STALE.value,
    )

    reread = read_cmn(cmn["id"])
    assert reread["status"] == "DRAFT", "the refused submission left the certificate in DRAFT"
    assert reread["submitted_by_user_id"] is None, (
        "submitted_by_user_id is stamped only on a successful submission"
    )


def test_a_thin_certificate_fails_the_documentation_threshold():
    """A certificate whose documentation score falls short of the pass threshold cannot be submitted.

    PRD: "`ERR_DOCUMENTATION_INCOMPLETE` — the certificate's documentation score has reached the pass threshold of 85.00."

    Design: Corner/validations/clinical_study_and_certificate_documentation_rules_reject
    """
    scenario = setup_qualifying_study()
    patient = scenario["patient"]

    thin = make_cmn(
        patient,
        scenario["qualifying_test"]["id"],
        hours_per_day=1,
        length_of_need_months=6,
        narrative_element_count=0,
    )
    # Group 30 plus currency 20 plus usage 0.625 plus narrative 0 plus portable
    # consistency 10 plus duration 0, summed at full precision and rounded once.
    assert thin["documentation_score"] == 60.63, (
        "the six components sum to 60.625 and round half up to 60.63"
    )

    validate_error(
        api_client.submit_cmn(thin["id"], INTAKE_COORDINATOR),
        ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE.value,
    )

    reread = read_cmn(thin["id"])
    assert reread["status"] == "DRAFT", "the refused submission left the certificate in DRAFT"
    assert reread["submitted_by_user_id"] is None, (
        "submitted_by_user_id is stamped only on a successful submission"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patient lifecycle and branch transfer
# ─────────────────────────────────────────────────────────────────────────────


def test_a_discharged_patient_accepts_no_further_qualifying_study():
    """A discharged chart is closed to new qualifying studies.

    PRD: "`DISCHARGED` is terminal: no qualifying study may be recorded, no certificate drafted or submitted, no contract opened, no equipment assigned and no travel requested for a discharged patient, each such attempt being refused with `ERR_PATIENT_NOT_ACTIVE`."

    Design: Corner/validations/patient_lifecycle_and_transfer_rules_reject
    """
    scenario = setup_admitted_patient()
    patient_id = scenario["patient"]["id"]

    discharged = validate_success(api_client.discharge_patient(patient_id, BRANCH_MANAGER))
    assert discharged["status"] == "DISCHARGED", "a patient with no live service discharges"

    payload = create_qualifying_test_payload(patient_id)
    validate_error(
        api_client.create_qualifying_test(payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_PATIENT_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api_client.list_qualifying_tests(
            INTAKE_COORDINATOR, params={"patient_id": patient_id}
        )
    )
    assert meta["total_count"] == 0, "no study was recorded against the discharged chart"


def test_a_discharged_patient_accepts_no_further_certificate_draft():
    """A discharged chart is closed to new certificates even when the version token is current.

    PRD: "Drafting for a patient who is not `ACTIVE` is refused with `ERR_PATIENT_NOT_ACTIVE`."

    Design: Corner/validations/patient_lifecycle_and_transfer_rules_reject
    """
    scenario = setup_qualifying_study()
    patient_id = scenario["patient"]["id"]

    discharged = validate_success(api_client.discharge_patient(patient_id, BRANCH_MANAGER))
    assert discharged["status"] == "DISCHARGED"

    # The stale-read token is the version the discharge itself produced, so the
    # optimistic-concurrency guard is satisfied and the lifecycle guard is what
    # must fire.
    payload = create_cmn_payload(
        patient_id, scenario["qualifying_test"]["id"], discharged["version"]
    )
    validate_error(
        api_client.create_cmn(payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_PATIENT_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api_client.list_cmns(INTAKE_COORDINATOR, params={"patient_id": patient_id})
    )
    assert meta["total_count"] == 0, "no certificate was drafted for the discharged patient"


def test_a_transfer_may_not_take_effect_in_the_past():
    """A transfer cannot be opened with an effective date earlier than today.

    PRD: "An `IntakeCoordinator` opens it by supplying `receiving_branch_id`, which must resolve to an existing branch and must differ from the patient's current `branch_id`, and `transfer_effective_date`, which must be at or after the logical clock's date or the request is refused with `ERR_TRANSFER_DATE_IN_PAST`."

    Design: Corner/validations/patient_lifecycle_and_transfer_rules_reject
    """
    scenario = setup_admitted_patient()
    patient = scenario["patient"]
    receiving = make_branch(name="Orlando", state_code="FL", competitive_bid_area=False)

    payload = create_transfer_request_payload(receiving["id"], "2026-07-31")
    validate_error(
        api_client.create_transfer_request(patient["id"], payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_TRANSFER_DATE_IN_PAST.value,
    )

    reread = read_patient(patient["id"])
    assert reread["status"] == "ACTIVE", "the refused transfer left the patient ACTIVE"
    assert reread["transfer_to_branch_id"] is None
    assert reread["transfer_effective_date"] is None


def test_a_transfer_may_not_name_the_patients_own_branch():
    """A transfer must name a receiving branch other than the one already serving the patient.

    PRD: "`ERR_RECEIVING_BRANCH_INVALID` — the supplied `receiving_branch_id` differs from the patient's current serving branch."

    Design: Corner/validations/patient_lifecycle_and_transfer_rules_reject
    """
    scenario = setup_admitted_patient()
    patient = scenario["patient"]

    payload = create_transfer_request_payload(scenario["branch"]["id"], "2026-08-15")
    validate_error(
        api_client.create_transfer_request(patient["id"], payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_RECEIVING_BRANCH_INVALID.value,
    )

    reread = read_patient(patient["id"])
    assert reread["status"] == "ACTIVE", "the refused transfer left the patient ACTIVE"
    assert reread["branch_id"] == scenario["branch"]["id"]


def test_a_transfer_may_not_be_completed_before_its_effective_date():
    """A pending transfer completes only once the clock has reached its effective date.

    PRD: "A `BranchManager` completes the transfer, moving the patient `TRANSFER_PENDING → ACTIVE`, but only once the logical clock's date has reached `transfer_effective_date`; completing early is refused with `ERR_TRANSFER_NOT_DUE`."

    Design: Corner/validations/patient_lifecycle_and_transfer_rules_reject
    """
    scenario = setup_admitted_patient()
    patient = scenario["patient"]
    origin_branch_id = scenario["branch"]["id"]
    receiving = make_branch(name="Orlando", state_code="FL", competitive_bid_area=False)

    pending = open_transfer(patient["id"], receiving["id"], "2026-08-05")
    assert pending["status"] == "TRANSFER_PENDING"
    assert pending["transfer_to_branch_id"] == receiving["id"]
    assert pending["branch_id"] == origin_branch_id, (
        "the serving branch does not move when the transfer is opened"
    )

    # The clock is still at 2026-08-01, four days short of the effective date.
    validate_error(
        api_client.complete_transfer_request(patient["id"], BRANCH_MANAGER),
        ApiErrorId.ERR_TRANSFER_NOT_DUE.value,
    )
    assert read_patient(patient["id"])["status"] == "TRANSFER_PENDING"

    advance_clock("2026-08-05T00:00:00Z")
    completed = validate_success(
        api_client.complete_transfer_request(patient["id"], BRANCH_MANAGER)
    )
    assert completed["status"] == "ACTIVE"
    assert completed["branch_id"] == receiving["id"], (
        "completion sets branch_id to transfer_to_branch_id"
    )
    assert completed["transfer_to_branch_id"] is None
    assert completed["transfer_effective_date"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Contract opening coherence
# ─────────────────────────────────────────────────────────────────────────────


def test_a_contract_may_not_name_another_patients_certificate():
    """A rental contract must be opened against a certificate belonging to its own patient.

    PRD: "The contract names a `patient_id` and the `cmn_id` of the authorising certificate, and the two must agree — a certificate belonging to a different patient is rejected with `ERR_CMN_PATIENT_MISMATCH`."

    Design: Corner/validations/contract_opening_coherence_rules_reject
    """
    scenario = setup_active_cmn()
    first_patient = scenario["patient"]

    second_patient = make_patient(
        scenario["branch"]["id"], mrn="MRN-0002", full_name="Dennis Okafor"
    )
    second_study = make_qualifying_test(second_patient["id"])
    second_cmn = make_cmn(second_patient, second_study["id"])
    second_cmn = drive_cmn_to_active(second_cmn["id"])
    assert second_cmn["status"] == "ACTIVE"

    payload = create_rental_contract_payload(first_patient["id"], second_cmn["id"])
    validate_error(
        api_client.create_rental_contract(payload, BILLING_SPECIALIST),
        ApiErrorId.ERR_CMN_PATIENT_MISMATCH.value,
    )

    _, meta = validate_paginated(
        api_client.list_rental_contracts(
            BILLING_SPECIALIST, params={"patient_id": first_patient["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused opening created no contract"


def test_a_contract_may_not_be_opened_on_a_draft_certificate():
    """A rental contract may only be opened against a certificate that is ACTIVE.

    PRD: "The certificate must be `ACTIVE` at that moment, or the request fails with `ERR_CMN_NOT_ACTIVE`; the patient must be `ACTIVE`, or it fails with `ERR_PATIENT_NOT_ACTIVE`; and the patient must not already hold a contract whose billing dimension is anything other than `CLOSED`, or it fails with `ERR_PATIENT_HAS_OPEN_CONTRACT`."

    Design: Corner/validations/contract_opening_coherence_rules_reject
    """
    scenario = setup_active_cmn()
    patient_id = scenario["patient"]["id"]

    # A second certificate for the same patient, left sitting in DRAFT.
    draft = make_cmn(read_patient(patient_id), scenario["qualifying_test"]["id"])
    assert draft["status"] == "DRAFT"

    payload = create_rental_contract_payload(patient_id, draft["id"])
    validate_error(
        api_client.create_rental_contract(payload, BILLING_SPECIALIST),
        ApiErrorId.ERR_CMN_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api_client.list_rental_contracts(
            BILLING_SPECIALIST, params={"patient_id": patient_id}
        )
    )
    assert meta["total_count"] == 0, "the refused opening created no contract"


def test_a_patient_may_not_hold_two_open_contracts():
    """A second rental contract cannot be opened while the patient already holds an open one.

    PRD: "`ERR_PATIENT_HAS_OPEN_CONTRACT` — no other contract for the same patient has a `billing_status` other than `CLOSED`, on contract opening."

    Design: Corner/validations/contract_opening_coherence_rules_reject
    """
    scenario = setup_open_contract()
    patient_id = scenario["patient"]["id"]
    contract = scenario["contract"]
    assert contract["billing_status"] == "ACCRUING"
    assert contract["service_status"] == "PENDING_SETUP"
    assert contract["monthly_allowable_cents"] == 0, (
        "nothing is in the home yet, so the allowable opens at 0"
    )
    assert contract["posted_months"] == []
    assert contract["lifetime_paid_cents"] == 0

    payload = create_rental_contract_payload(patient_id, scenario["cmn"]["id"])
    validate_error(
        api_client.create_rental_contract(payload, BILLING_SPECIALIST),
        ApiErrorId.ERR_PATIENT_HAS_OPEN_CONTRACT.value,
    )

    rows, meta = validate_paginated(
        api_client.list_rental_contracts(
            BILLING_SPECIALIST, params={"patient_id": patient_id}
        )
    )
    assert meta["total_count"] == 1, "the patient still holds exactly one contract"
    assert rows[0]["id"] == contract["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Route shifts and buffered stop windows
# ─────────────────────────────────────────────────────────────────────────────


def test_a_route_shift_must_be_coherent_with_its_service_date():
    """A route shift must run forwards and must start on its own service date.

    PRD: "A shift that violates either condition is rejected with `ERR_INVALID_SHIFT`."

    Design: Corner/validations/route_shift_and_window_temporal_rules_reject
    """
    branch = make_branch()

    zero_length = create_delivery_route_payload(
        branch["id"],
        service_date="2026-08-01",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T12:00:00Z",
    )
    validate_error(
        api_client.create_delivery_route(zero_length, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_SHIFT.value,
    )

    wrong_date = create_delivery_route_payload(
        branch["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T22:00:00Z",
    )
    validate_error(
        api_client.create_delivery_route(wrong_date, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_SHIFT.value,
    )

    _, meta = validate_paginated(
        api_client.list_delivery_routes(BRANCH_MANAGER, params={"branch_id": branch["id"]})
    )
    assert meta["total_count"] == 0, "neither incoherent shift produced a route"


def test_a_stop_window_must_run_forwards():
    """A stop's arrival window must end strictly after it starts.

    PRD: "The promised arrival window is given by `window_start_utc` and `window_end_utc`, with the end instant required to be strictly after the start instant or the stop is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/route_shift_and_window_temporal_rules_reject
    """
    scenario = setup_reserved_equipment()
    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-01",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T14:00:00Z",
    )

    payload = create_route_stop_payload(
        route["id"],
        scenario["contract"]["id"],
        window_start_utc="2026-08-01T13:00:00Z",
        window_end_utc="2026-08-01T13:00:00Z",
    )
    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_WINDOW.value,
    )
    assert read_route(route["id"])["planned_stop_count"] == 0


def test_a_buffered_stop_window_must_fit_inside_the_shift():
    """A stop's window plus the branch turnaround buffer must sit wholly inside the shift.

    PRD: "That buffered span must fit inside the route's shift: the window start must be at or after the shift start, and the buffered end must be at or before the shift end, or the stop is rejected with `ERR_WINDOW_OUTSIDE_SHIFT`."

    Design: Corner/validations/route_shift_and_window_temporal_rules_reject
    """
    scenario = setup_reserved_equipment()
    assert scenario["branch"]["tank_exchange_buffer_minutes"] == 30
    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-01",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T14:00:00Z",
    )
    contract_id = scenario["contract"]["id"]

    # The window opens half an hour before the driver's shift does.
    early = create_route_stop_payload(
        route["id"],
        contract_id,
        window_start_utc="2026-08-01T11:30:00Z",
        window_end_utc="2026-08-01T12:30:00Z",
    )
    validate_error(
        api_client.create_route_stop(early, BRANCH_MANAGER),
        ApiErrorId.ERR_WINDOW_OUTSIDE_SHIFT.value,
    )

    # The window itself ends inside the shift, but the 30-minute buffer carries
    # the buffered end out to 14:15, a quarter of an hour past the shift end.
    late = create_route_stop_payload(
        route["id"],
        contract_id,
        window_start_utc="2026-08-01T13:00:00Z",
        window_end_utc="2026-08-01T13:45:00Z",
    )
    validate_error(
        api_client.create_route_stop(late, BRANCH_MANAGER),
        ApiErrorId.ERR_WINDOW_OUTSIDE_SHIFT.value,
    )

    # Pulled back to 13:30 the buffered end lands exactly on the shift end.
    accepted = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                route["id"],
                contract_id,
                window_start_utc="2026-08-01T13:00:00Z",
                window_end_utc="2026-08-01T13:30:00Z",
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert accepted["sequence_index"] == 1, "the accepted stop is first on the route"
    assert accepted["liters_committed"] == 0, "no cylinders were requested"

    reread = read_route(route["id"])
    assert reread["planned_stop_count"] == 1, "only the boundary stop was accepted"
    assert reread["total_o2_liters_committed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Stop eligibility against the contract's service dimension
# ─────────────────────────────────────────────────────────────────────────────


def test_a_setup_stop_requires_reserved_equipment():
    """A setup delivery cannot be scheduled until something has been reserved to install.

    PRD: "A `SETUP_DELIVERY` stop is by definition scheduled while the contract is still `PENDING_SETUP`, so the in-service requirement does not apply to it; but it does require that the contract already holds at least one placement in `RESERVED`, because there is nothing to install otherwise, and a setup stop for a contract with no reserved equipment is rejected with `ERR_NO_RESERVED_EQUIPMENT`."

    Design: Corner/validations/route_stop_eligibility_rules_reject
    """
    scenario = setup_open_contract()
    route = make_delivery_route(scenario["branch"]["id"])
    payload = create_route_stop_payload(route["id"], scenario["contract"]["id"])

    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_NO_RESERVED_EQUIPMENT.value,
    )
    assert read_route(route["id"])["planned_stop_count"] == 0

    # Reserve a unit and replay the byte-identical request.
    placement = assign_equipment(scenario["contract"]["id"])
    assert placement["status"] == "RESERVED"
    stop = validate_success(api_client.create_route_stop(payload, BRANCH_MANAGER), 201)
    assert stop["stop_type"] == "SETUP_DELIVERY"
    assert read_route(route["id"])["planned_stop_count"] == 1


def test_a_tank_exchange_requires_the_contract_to_be_in_service():
    """A tank exchange cannot be scheduled for a contract whose setup has not yet happened.

    PRD: "The other four stop types all require the contract's service dimension to be exactly `IN_SERVICE`, failing with `ERR_CONTRACT_NOT_IN_SERVICE` otherwise."

    Design: Corner/validations/route_stop_eligibility_rules_reject
    """
    scenario = setup_open_contract()
    assert scenario["contract"]["service_status"] == "PENDING_SETUP"
    route = make_delivery_route(scenario["branch"]["id"])

    payload = create_route_stop_payload(
        route["id"],
        scenario["contract"]["id"],
        stop_type="TANK_EXCHANGE",
        cylinders_requested=2,
    )
    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_CONTRACT_NOT_IN_SERVICE.value,
    )
    assert read_route(route["id"])["planned_stop_count"] == 0


def test_a_stop_route_must_belong_to_the_branch_serving_the_patient():
    """A stop cannot put a contract onto a route run out of a different branch.

    PRD: "Each stop names the `route_id` it belongs to and the `contract_id` being serviced there, and the two must belong to the same branch: a route whose branch differs from the branch serving the contract's patient is rejected with `ERR_STOP_BRANCH_MISMATCH`."

    Design: Corner/validations/route_stop_eligibility_rules_reject
    """
    scenario = setup_contract_in_service()
    other_branch = make_branch(name="Orlando", state_code="FL", competitive_bid_area=False)
    foreign_route = make_delivery_route(
        other_branch["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )

    payload = create_route_stop_payload(
        foreign_route["id"],
        scenario["contract"]["id"],
        stop_type="TANK_EXCHANGE",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        cylinders_requested=2,
    )
    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_STOP_BRANCH_MISMATCH.value,
    )
    assert read_route(foreign_route["id"])["planned_stop_count"] == 0


def test_a_pickup_stop_may_not_request_cylinders():
    """A pickup collects equipment, so it may not carry a cylinder drop.

    PRD: "`cylinders_requested` records how many E-cylinders the driver will drop, accepts 0 through 6, defaults to 0, and is consulted only for setup deliveries, tank exchanges and maintenance swaps — supplying a non-zero cylinder count on a `PICKUP` or a `PORTABLE_REFILL` stop is rejected with `ERR_CYLINDERS_NOT_APPLICABLE`."

    Design: Corner/validations/route_stop_eligibility_rules_reject
    """
    scenario = setup_contract_in_service()
    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )

    payload = create_route_stop_payload(
        route["id"],
        scenario["contract"]["id"],
        stop_type="PICKUP",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=30,
        cylinders_requested=2,
    )
    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_CYLINDERS_NOT_APPLICABLE.value,
    )
    assert read_route(route["id"])["planned_stop_count"] == 0
    assert read_contract(scenario["contract"]["id"])["service_status"] == "IN_SERVICE", (
        "the refused pickup did not move the contract to PICKUP_SCHEDULED"
    )


def test_a_portable_refill_requires_a_placed_liquid_portable():
    """A refill stop needs a liquid portable vessel in the home to refill.

    PRD: "A refill stop for a contract with no such placed unit is rejected with `ERR_REFILL_REQUIRES_LIQUID_PORTABLE`."

    Design: Corner/validations/route_stop_eligibility_rules_reject
    """
    scenario = setup_contract_in_service()
    placed = sole_placement(scenario["contract"]["id"], status="PLACED")
    unit = read_equipment_unit(placed["equipment_unit_id"])
    assert unit["equipment_class"] == "STATIONARY_CONCENTRATOR", (
        "the only placed unit is a concentrator, not a liquid vessel"
    )

    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )
    payload = create_route_stop_payload(
        route["id"],
        scenario["contract"]["id"],
        stop_type="PORTABLE_REFILL",
        window_start_utc="2026-08-02T15:00:00Z",
        window_end_utc="2026-08-02T16:00:00Z",
        service_minutes=30,
    )
    validate_error(
        api_client.create_route_stop(payload, BRANCH_MANAGER),
        ApiErrorId.ERR_REFILL_REQUIRES_LIQUID_PORTABLE.value,
    )
    reread = read_route(route["id"])
    assert reread["planned_stop_count"] == 0
    assert reread["total_o2_liters_committed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Route locking capacity guards
# ─────────────────────────────────────────────────────────────────────────────


def test_an_empty_route_cannot_be_locked():
    """A route with nothing planned on it cannot be frozen for dispatch.

    PRD: "The route must carry at least one planned stop, or the lock is refused with `ERR_ROUTE_HAS_NO_STOPS` — an empty route cannot be locked."

    Design: Corner/validations/route_lock_capacity_rules_reject
    """
    branch = make_branch()
    route = make_delivery_route(branch["id"])
    assert route["status"] == "PLANNING"
    assert route["planned_stop_count"] == 0

    validate_error(
        api_client.lock_route(route["id"], BRANCH_MANAGER),
        ApiErrorId.ERR_ROUTE_HAS_NO_STOPS.value,
    )
    reread = read_route(route["id"])
    assert reread["status"] == "PLANNING", "the refused lock left the route editable"
    assert reread["version"] == route["version"], "a refused lock does not bump the version"


def test_route_lock_refuses_more_refills_than_the_branch_can_service():
    """A route may not be locked carrying more refill stops than the branch's daily capacity.

    PRD: "And the route's used refill slots must not exceed the branch's `refill_capacity_per_day`, or the lock is refused with `ERR_REFILL_CAPACITY_EXCEEDED`; a branch configured for the default four refill stops a day can lock a route carrying four but not one carrying five."

    Design: Corner/validations/route_lock_capacity_rules_reject
    """
    scenario = setup_liquid_in_service(refill_capacity_per_day=1)
    assert scenario["branch"]["refill_capacity_per_day"] == 1
    contract_id = scenario["contract"]["id"]

    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )
    first_refill = make_route_stop(
        route["id"],
        contract_id,
        stop_type="PORTABLE_REFILL",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=30,
    )
    assert first_refill["liters_committed"] == 1085, "a refill commits a full vessel"

    locked = validate_success(api_client.lock_route(route["id"], BRANCH_MANAGER))
    assert locked["status"] == "LOCKED"
    assert locked["refill_slots_used"] == 1, "one refill fits the branch's single slot"
    assert locked["total_o2_liters_committed"] == 1085

    # Reopen the route and add a second refill, taking the day to two slots.
    unlock_route(route["id"])
    second_refill = make_route_stop(
        route["id"],
        contract_id,
        stop_type="PORTABLE_REFILL",
        window_start_utc="2026-08-02T15:00:00Z",
        window_end_utc="2026-08-02T16:00:00Z",
        service_minutes=30,
    )
    assert second_refill["liters_committed"] == 1085

    validate_error(
        api_client.lock_route(route["id"], BRANCH_MANAGER),
        ApiErrorId.ERR_REFILL_CAPACITY_EXCEEDED.value,
    )
    reread = read_route(route["id"])
    assert reread["status"] == "PLANNING", "the refused lock left the route in PLANNING"
    assert reread["refill_slots_used"] == 2, "both refills are still planned on the route"
    assert reread["total_o2_liters_committed"] == 2170


# ─────────────────────────────────────────────────────────────────────────────
# The billable month window, ledger uniqueness and the empty home
# ─────────────────────────────────────────────────────────────────────────────


def test_a_month_outside_the_billable_window_is_refused():
    """A month before the contract started, or later than the clock, cannot be posted.

    PRD: "The month itself must be at or after `first_service_month` under a plain lexicographic comparison of the `YYYY-MM` strings, or the post is refused with `ERR_SERVICE_MONTH_BEFORE_START`; it must be at or before the `YYYY-MM` of the logical clock, or it is refused as a future month with `ERR_SERVICE_MONTH_IN_FUTURE`; and it must not already appear as the `service_month` of an element of `posted_months`, or it is refused with `ERR_SERVICE_MONTH_ALREADY_POSTED`."

    Design: Corner/validations/billing_month_window_and_uniqueness_rules_reject
    """
    scenario = setup_contract_in_service()
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["first_service_month"] == "2026-08"
    assert scenario["contract"]["monthly_allowable_cents"] == 5590, (
        "one stationary concentrator in the primary role on a competitive-bid contract"
    )

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-07"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_SERVICE_MONTH_BEFORE_START.value,
    )
    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-09"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_SERVICE_MONTH_IN_FUTURE.value,
    )
    assert read_contract(contract_id)["posted_month_count"] == 0, (
        "neither refused month reached the ledger"
    )

    # The month the clock is actually in is inside the window.
    posted = validate_success(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        )
    )
    assert posted["billing_status"] == "ACCRUING"
    assert posted["posted_month_count"] == 1
    assert posted["lifetime_paid_cents"] == 5590


def test_a_month_already_in_the_ledger_cannot_be_posted_twice():
    """A service month may appear in the ledger only once, until it is reversed.

    PRD: "`ERR_SERVICE_MONTH_ALREADY_POSTED` — the supplied `service_month` is not already an element of the contract's posted ledger, on month posting."

    Design: Corner/validations/billing_month_window_and_uniqueness_rules_reject
    """
    scenario = setup_posted_month()
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["posted_month_count"] == 1
    assert scenario["contract"]["lifetime_paid_cents"] == 5590

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_SERVICE_MONTH_ALREADY_POSTED.value,
    )
    unchanged = read_contract(contract_id)
    assert unchanged["posted_month_count"] == 1, "the refused post appended nothing"
    assert unchanged["lifetime_paid_cents"] == 5590

    # Reversal takes the month back out of the ledger, and the month is free again.
    reversed_contract = validate_success(
        api_client.reverse_billing_month(contract_id, "2026-08", BILLING_SPECIALIST)
    )
    assert reversed_contract["posted_month_count"] == 0
    assert reversed_contract["lifetime_paid_cents"] == 0
    assert reversed_contract["last_posted_service_month"] is None

    reposted = validate_success(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        )
    )
    assert reposted["posted_month_count"] == 1
    assert reposted["lifetime_paid_cents"] == 5590


def test_a_contract_with_nothing_in_the_home_cannot_post_a_month():
    """A contract whose equipment has been pulled has no monthly allowable to bill.

    PRD: "Finally the contract must actually have something in the home: its `monthly_allowable_cents` must be greater than 0, or the post is refused with `ERR_NO_PLACED_EQUIPMENT`."

    Design: Corner/validations/billing_month_window_and_uniqueness_rules_reject
    """
    scenario = setup_contract_in_service()
    contract_id = scenario["contract"]["id"]
    placement = sole_placement(contract_id, status="PLACED")

    # A no-flow report grades TIER_1 on the symptom alone, which pulls the unit.
    file_malfunction(placement["id"], symptom="NO_FLOW", oxygen_gap_minutes=0)
    pulled = read_placement(placement["id"])
    assert pulled["last_severity_tier"] == "TIER_1"
    assert pulled["status"] == "REMOVED"
    assert pulled["removal_reason"] == "MALFUNCTION"

    emptied = read_contract(contract_id)
    assert emptied["monthly_allowable_cents"] == 0, "nothing is left in the home"
    assert emptied["service_status"] == "IN_SERVICE"
    assert emptied["billing_status"] == "ACCRUING"

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_NO_PLACED_EQUIPMENT.value,
    )
    final = read_contract(contract_id)
    assert final["posted_month_count"] == 0
    assert final["lifetime_paid_cents"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# The capped-rental ceiling, reversal and the exhausted cap
# ─────────────────────────────────────────────────────────────────────────────


def test_a_competitive_bid_cap_cannot_be_cleared_by_reversal():
    """Reversing the only posted month cannot bring a service-month-basis contract back under its cap.

    PRD: "A reversal from `CAP_REACHED` moves the contract `CAP_REACHED → ACCRUING`, but only when the cap position, **recomputed over `posted_months` with the reversed month removed**, falls strictly below `cap_month_limit`; if removing that month would still leave the contract at or above its cap, the reversal is refused with `ERR_REVERSAL_WOULD_NOT_CLEAR_CAP`."

    Design: Corner/validations/cap_reversal_and_exhaustion_rules_reject
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["billing_status"] == "CAP_REACHED"
    assert scenario["contract"]["lifetime_paid_cents"] == 5590

    validate_error(
        api_client.reverse_billing_month(contract_id, "2026-08", BILLING_SPECIALIST),
        ApiErrorId.ERR_REVERSAL_WOULD_NOT_CLEAR_CAP.value,
    )
    unchanged = read_contract(contract_id)
    assert unchanged["billing_status"] == "CAP_REACHED", "the refused reversal changed nothing"
    assert unchanged["posted_month_count"] == 1
    assert unchanged["lifetime_paid_cents"] == 5590

    summary = validate_success(api_client.get_cap_summary(contract_id, BILLING_SPECIALIST))
    assert summary["variant_applied"] == "SERVICE_MONTH_BASIS", (
        "a competitive-bid contract counts elapsed calendar months"
    )
    assert summary["cap_month_limit"] == 1
    assert summary["months_remaining"] == 0
    assert summary["lifetime_paid_cents"] == 5590


def test_a_month_that_was_never_posted_cannot_be_reversed():
    """Only a month that actually sits in the ledger can be reversed.

    PRD: "`ERR_POSTED_MONTH_NOT_FOUND` — the service-month path segment matches a posted element of the named contract's ledger, on month reversal."

    Design: Corner/validations/cap_reversal_and_exhaustion_rules_reject
    """
    scenario = setup_posted_month()
    contract_id = scenario["contract"]["id"]

    validate_error(
        api_client.reverse_billing_month(contract_id, "2026-07", BILLING_SPECIALIST),
        ApiErrorId.ERR_POSTED_MONTH_NOT_FOUND.value,
    )
    unchanged = read_contract(contract_id)
    assert unchanged["posted_month_count"] == 1, "the ledger is untouched"
    assert unchanged["lifetime_paid_cents"] == 5590
    assert unchanged["last_posted_service_month"] == "2026-08"


def test_the_month_after_a_cancelled_transfer_is_refused_on_the_cap():
    """A contract resumed from a cancelled transfer is refused its next month by the cap, not the state.

    PRD: "Both paths resume billing on the `ACCRUING` branch unconditionally, even for a contract that was `CAP_REACHED` when the transfer opened; such a contract's next posted month is therefore rejected by the cap check rather than by the billing-state check."

    Design: Corner/validations/cap_reversal_and_exhaustion_rules_reject
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract_id = scenario["contract"]["id"]
    patient_id = scenario["patient"]["id"]

    receiving = make_branch(name="Orlando", state_code="FL", competitive_bid_area=False)
    open_transfer(patient_id, receiving["id"], "2026-08-15")
    suspended = read_contract(contract_id)
    assert suspended["billing_status"] == "SUSPENDED", (
        "a transfer request suspends even a contract already at its cap"
    )
    assert suspended["suspension_reason"] == "TRANSFER"

    validate_success(api_client.cancel_transfer_request(patient_id, INTAKE_COORDINATOR))
    resumed = read_contract(contract_id)
    assert resumed["billing_status"] == "ACCRUING", "cancellation resumes on the ACCRUING branch"
    assert resumed["suspension_reason"] == "NONE"

    sweep = advance_clock("2026-09-01T00:00:00Z")
    assert sweep["expired_cmn_count"] == 0, "the certificate recertifies in 2027"
    assert sweep["suspended_contract_count"] == 0

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-09"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_CAP_MONTHS_EXHAUSTED.value,
    )
    final = read_contract(contract_id)
    assert final["posted_month_count"] == 1, "nothing was posted at all"
    assert final["lifetime_paid_cents"] == 5590


# ─────────────────────────────────────────────────────────────────────────────
# Liquid certification, unit state and the recall bar on billing recovery
# ─────────────────────────────────────────────────────────────────────────────


def test_an_uncertified_branch_may_not_register_liquid_oxygen():
    """A branch without liquid certification cannot take liquid units into its fleet.

    PRD: "Registering a unit whose class is `LIQUID_RESERVOIR` or `LIQUID_PORTABLE` at a branch whose liquid certification is false is rejected with `ERR_BRANCH_NOT_LIQUID_CERTIFIED` — an uncertified branch may not hold liquid oxygen at all."

    Design: Corner/validations/equipment_certification_recall_and_state_rules_reject
    """
    uncertified = make_branch()
    assert uncertified["liquid_oxygen_certified"] is False

    validate_error(
        api_client.create_equipment_unit(
            create_equipment_unit_payload(
                uncertified["id"],
                serial_number="LIQ-RES-9",
                model_code="LIQ-RES",
                equipment_class="LIQUID_RESERVOIR",
                max_continuous_lpm=6.0,
                max_pulse_setting=0,
            ),
            BRANCH_MANAGER,
        ),
        ApiErrorId.ERR_BRANCH_NOT_LIQUID_CERTIFIED.value,
    )
    validate_error(
        api_client.create_equipment_unit(
            create_equipment_unit_payload(
                uncertified["id"],
                serial_number="LIQ-POR-9",
                model_code="LIQ-POR",
                equipment_class="LIQUID_PORTABLE",
                max_continuous_lpm=6.0,
                max_pulse_setting=0,
            ),
            BRANCH_MANAGER,
        ),
        ApiErrorId.ERR_BRANCH_NOT_LIQUID_CERTIFIED.value,
    )
    _, meta = validate_paginated(
        api_client.list_equipment_units(
            BRANCH_MANAGER,
            params={
                "branch_id": uncertified["id"],
                "equipment_class": "LIQUID_PORTABLE",
            },
        )
    )
    assert meta["total_count"] == 0, "no liquid stock ever reached the uncertified branch"

    # The same unit is accepted at a certified branch.
    certified = make_liquid_branch()
    unit = make_equipment_unit(
        certified["id"],
        serial_number="LIQ-POR-9",
        model_code="LIQ-POR",
        equipment_class="LIQUID_PORTABLE",
        max_continuous_lpm=6.0,
        max_pulse_setting=0,
    )
    assert_equipment_unit(unit)
    assert unit["status"] == "IN_STOCK"
    assert unit["quarantine_reason"] == "NONE"


def test_a_deployed_unit_cannot_be_serviced():
    """Servicing a unit that is out in a patient's home is not a declared transition.

    PRD: "`ERR_INVALID_STATE` — the target row's state field equals one of the origin states declared for the requested transition."

    Design: Corner/validations/equipment_certification_recall_and_state_rules_reject
    """
    scenario = setup_contract_in_service()
    unit_id = scenario["stationary_unit"]["id"]
    assert read_equipment_unit(unit_id)["status"] == "DEPLOYED"

    # Service is declared only out of IN_QUARANTINE.
    validate_error(
        api_client.service_equipment_unit(unit_id, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    unchanged = read_equipment_unit(unit_id)
    assert unchanged["status"] == "DEPLOYED", "the refused service left the unit in the home"
    assert unchanged["recall_remediated_at"] is None


def test_remediating_recalled_hardware_does_not_unblock_billing():
    """A contract carrying a recalled placement cannot resume billing, even after the unit is serviced.

    PRD: "A contract may not resume billing while any of its placements still sits in `RECALLED_OUT_OF_SERVICE`; the attempt is refused with `ERR_CONTRACT_HAS_RECALLED_EQUIPMENT`, and the only way forward is to take the recalled placement out of the way and re-equip the patient."

    Design: Corner/validations/equipment_certification_recall_and_state_rules_reject
    """
    scenario = setup_recalled_contract(severity="CLASS_I")
    contract_id = scenario["contract"]["id"]
    unit_id = scenario["stationary_unit"]["id"]
    assert scenario["recall_notice"]["affected_unit_count"] == 1
    assert scenario["recall_notice"]["auto_quarantined_unit_count"] == 1

    placement = read_placement(scenario["placements"][0]["id"])
    assert placement["status"] == "RECALLED_OUT_OF_SERVICE"
    assert placement["removal_reason"] == "RECALL"
    assert scenario["contract"]["billing_status"] == "SUSPENDED"
    assert scenario["contract"]["suspension_reason"] == "RECALL"

    validate_error(
        api_client.resume_billing(contract_id, BILLING_SPECIALIST),
        ApiErrorId.ERR_CONTRACT_HAS_RECALLED_EQUIPMENT.value,
    )

    # Servicing the unit clears the hardware side and credits the notice.
    serviced = service_unit(unit_id)
    assert serviced["status"] == "IN_STOCK"
    assert serviced["quarantine_reason"] == "NONE"
    assert serviced["recall_remediated_at"] is not None

    validate_error(
        api_client.resume_billing(contract_id, BILLING_SPECIALIST),
        ApiErrorId.ERR_CONTRACT_HAS_RECALLED_EQUIPMENT.value,
    )
    still_barred = read_contract(contract_id)
    assert still_barred["billing_status"] == "SUSPENDED"
    assert still_barred["suspension_reason"] == "RECALL"
    assert read_placement(placement["id"])["status"] == "RECALLED_OUT_OF_SERVICE", (
        "the placement is still in the way"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Travel authorization: destination, interval and the cylinder ceiling
# ─────────────────────────────────────────────────────────────────────────────


def test_travel_may_not_name_the_patients_own_branch_as_destination():
    """A travel hand-off to the branch already serving the patient is refused.

    PRD: "The contract must not be `CLOSED` and its certificate must be `ACTIVE`, the patient must be `ACTIVE` and not on compliance hold, and when a receiving branch is named it must differ from the patient's current `branch_id`, or the request is refused with `ERR_RECEIVING_BRANCH_INVALID`."

    Design: Corner/validations/travel_authorization_interval_and_supply_limit_rules_reject
    """
    scenario = setup_open_contract(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    contract = scenario["contract"]

    validate_error(
        api_client.create_travel_authorization(
            contract["id"],
            create_travel_authorization_payload(
                contract["version"],
                receiving_branch_id=scenario["branch"]["id"],
                destination_altitude_feet=500,
                depart_utc="2026-08-02T00:00:00Z",
                return_utc="2026-08-03T06:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_RECEIVING_BRANCH_INVALID.value,
    )
    _, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused request created nothing"

    # A genuinely different branch is accepted for the same itinerary.
    destination = make_branch(
        name="Asheville", state_code="NC", competitive_bid_area=False
    )
    accepted = request_travel(
        contract,
        receiving_branch_id=destination["id"],
        destination_altitude_feet=500,
        depart_utc="2026-08-02T00:00:00Z",
        return_utc="2026-08-03T06:00:00Z",
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["receiving_branch_id"] == destination["id"]


def test_a_zero_length_trip_is_not_a_valid_itinerary():
    """The return instant must be strictly later than the departure instant.

    PRD: "The return instant must be strictly after the departure instant, or the request is refused with `ERR_INVALID_TRAVEL_INTERVAL`."

    Design: Corner/validations/travel_authorization_interval_and_supply_limit_rules_reject
    """
    scenario = setup_open_contract(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    contract = scenario["contract"]
    destination = make_branch(
        name="Asheville", state_code="NC", competitive_bid_area=False
    )

    validate_error(
        api_client.create_travel_authorization(
            contract["id"],
            create_travel_authorization_payload(
                contract["version"],
                receiving_branch_id=destination["id"],
                destination_altitude_feet=500,
                depart_utc="2026-08-02T00:00:00Z",
                return_utc="2026-08-02T00:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_TRAVEL_INTERVAL.value,
    )
    _, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 0, "a zero-length trip is an error, not an empty trip"

    # A return one hour later clears the strict comparison.
    accepted = request_travel(
        contract,
        receiving_branch_id=destination["id"],
        destination_altitude_feet=500,
        depart_utc="2026-08-02T00:00:00Z",
        return_utc="2026-08-02T01:00:00Z",
    )
    assert accepted["status"] == "REQUESTED"
    _, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_trip_needing_thirteen_cylinders_is_refused_at_the_ceiling():
    """One extra travel hour crosses the twelve-cylinder ceiling and the trip is refused outright.

    PRD: "If that total exceeds 12 cylinders the request is refused with `ERR_TRAVEL_SUPPLY_EXCEEDS_LIMIT` and **no authorization row is created at all** — a raw count of 12 becomes 13 with the surcharge and is refused, while a raw count of 11 becomes 12 and is accepted exactly at the ceiling."

    Design: Corner/validations/travel_authorization_interval_and_supply_limit_rules_reject
    """
    scenario = setup_open_contract(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    contract = scenario["contract"]
    assert scenario["cmn"]["prescribed_lpm"] == 3.0
    assert scenario["cmn"]["hours_per_day"] == 24
    assert scenario["patient"]["altitude_feet"] == 500
    destination = make_branch(
        name="Asheville", state_code="NC", competitive_bid_area=False
    )

    # 31 hours: base 5580 L, reserve 1953 L, required 7533 L, 12 raw cylinders
    # plus the handling surcharge is 13.
    validate_error(
        api_client.create_travel_authorization(
            contract["id"],
            create_travel_authorization_payload(
                contract["version"],
                receiving_branch_id=destination["id"],
                destination_altitude_feet=500,
                depart_utc="2026-08-05T00:00:00Z",
                return_utc="2026-08-06T07:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_TRAVEL_SUPPLY_EXCEEDS_LIMIT.value,
    )
    _, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 0, "no authorization row was created at all"

    # 30 hours: base 5400 L, reserve 1890 L, required 7290 L, 11 raw cylinders
    # plus the surcharge is exactly 12.
    accepted = request_travel(
        contract,
        receiving_branch_id=destination["id"],
        destination_altitude_feet=500,
        depart_utc="2026-08-02T00:00:00Z",
        return_utc="2026-08-03T06:00:00Z",
    )
    assert accepted["trip_hours"] == 30
    assert accepted["base_liters"] == 5400
    assert accepted["reserve_liters"] == 1890
    assert accepted["required_liters"] == 7290
    assert accepted["cylinders_raw"] == 11
    assert accepted["handling_surcharge_cylinders"] == 1, (
        "the surcharge reads the raw count, never the surcharged total"
    )
    assert accepted["supply_cylinders_authorized"] == 12
    assert accepted["status"] == "REQUESTED"

    rows, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


# ─────────────────────────────────────────────────────────────────────────────
# The logical clock moves forward only
# ─────────────────────────────────────────────────────────────────────────────


def test_the_logical_clock_refuses_to_stand_still_or_go_back():
    """Re-sending the instant the clock already holds is an error, not a no-op.

    PRD: "The clock is monotone and forward-only: a supplied instant that is not strictly later than the current logical clock is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), and nothing is changed."

    Design: Corner/validations/logical_clock_monotonicity_rules_reject
    """
    validate_error(
        api_client.set_clock(set_clock_payload("2026-08-01T00:00:00Z"), BRANCH_MANAGER),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
    )
    validate_error(
        api_client.set_clock(set_clock_payload("2026-07-31T23:59:59Z"), BRANCH_MANAGER),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
    )

    # One second forward is enough, and its previous_utc proves the two refusals
    # above changed nothing.
    advanced = validate_success(
        api_client.set_clock(set_clock_payload("2026-08-01T00:00:01Z"), BRANCH_MANAGER)
    )
    assert_clock_advance_result(advanced)
    assert advanced["previous_utc"].startswith("2026-08-01T00:00:00")
    assert advanced["current_utc"].startswith("2026-08-01T00:00:01")
    assert advanced["expired_cmn_count"] == 0
    assert advanced["suspended_contract_count"] == 0

    # The rule reads the live clock, so the literal that just succeeded now fails.
    validate_error(
        api_client.set_clock(set_clock_payload("2026-08-01T00:00:01Z"), BRANCH_MANAGER),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
    )


def test_an_unparseable_instant_never_reaches_the_clock_comparison():
    """A value that is not an instant at all fails the shape check, not the monotonicity check.

    PRD: "`ERR_INVALID_REQUEST` — every field the endpoint declares as required is present, every supplied value matches its declared type, and every numeric value lies inside its declared range."

    Design: Corner/validations/logical_clock_monotonicity_rules_reject
    """
    validate_error(
        api_client.set_clock(set_clock_payload("not-a-timestamp"), BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # The clock never moved: the next advance still reports the startup instant.
    advanced = validate_success(
        api_client.set_clock(set_clock_payload("2026-08-01T00:00:01Z"), BRANCH_MANAGER)
    )
    assert advanced["previous_utc"].startswith("2026-08-01T00:00:00")


# ─────────────────────────────────────────────────────────────────────────────
# One request, several broken rules, exactly one error
# ─────────────────────────────────────────────────────────────────────────────


def test_an_unauthorized_caller_cannot_probe_which_rows_exist():
    """The role check is reported ahead of path existence and ahead of payload shape.

    PRD: "When more than one rule could reject the same request, exactly one error is reported: the one belonging to the earliest position in the ladder below."

    Design: Corner/validations/role_shape_and_existence_priority_order
    """
    scenario = setup_admitted_patient()

    # A driver may not read a risk assessment, and never learns the patient is absent.
    validate_error(
        api_client.get_patient_risk_assessment(NON_EXISTENT_UUID, DELIVERY_DRIVER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # The identical path, from a role that may read it, reports the missing row.
    validate_error(
        api_client.get_patient_risk_assessment(NON_EXISTENT_UUID, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )

    # The role check also outranks the shape check: 200 percent saturation is
    # never mentioned to a caller who may not record studies at all.
    validate_error(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(NON_EXISTENT_UUID, spo2_percent=200),
            BILLING_SPECIALIST,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _, meta = validate_paginated(
        api_client.list_qualifying_tests(
            INTAKE_COORDINATOR, params={"patient_id": scenario["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "none of the refused requests recorded a study"


def test_a_malformed_body_is_reported_before_its_missing_reference():
    """Payload shape is checked before the body's foreign keys are resolved.

    PRD: "When more than one rule could reject the same request, exactly one error is reported: the one belonging to the earliest position in the ladder below."

    Design: Corner/validations/role_shape_and_existence_priority_order
    """
    scenario = setup_admitted_patient()
    patient_id = scenario["patient"]["id"]

    # Both broken at once: saturation out of range and a patient that does not exist.
    validate_error(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(NON_EXISTENT_UUID, spo2_percent=200),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    # With the shape repaired, the same body reaches the existence rule.
    validate_error(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(NON_EXISTENT_UUID, spo2_percent=87),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )
    # And with a real patient the request is accepted, which shows each refusal
    # above came from the rule it was aimed at.
    created = validate_success(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(patient_id, spo2_percent=87),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert created["qualifying_group"] == "GROUP_I"

    _, meta = validate_paginated(
        api_client.list_qualifying_tests(
            INTAKE_COORDINATOR, params={"patient_id": patient_id}
        )
    )
    assert meta["total_count"] == 1, "only the accepted request created a study"


# ─────────────────────────────────────────────────────────────────────────────
# The inclusive edge of the cap: the month that is paid and still exhausts it
# ─────────────────────────────────────────────────────────────────────────────


def test_the_month_that_lands_exactly_on_the_cap_is_paid_and_closes_it():
    """Reaching the cap limit exactly still pays the month and moves the contract to CAP_REACHED.

    PRD: "When the effective position **equals** `cap_month_limit` exactly, the post still succeeds — the month is paid — and the billing dimension then advances `ACCRUING → CAP_REACHED`."

    Design: Corner/validations/billing_window_and_cap_boundaries_pass
    """
    scenario = setup_contract_in_service(contract_overrides={"cap_month_limit": 2})
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["cap_month_limit"] == 2
    assert scenario["contract"]["first_service_month"] == "2026-08", (
        "service began in the month the clock is in, so the first post sits on both bounds at once"
    )
    assert scenario["contract"]["monthly_allowable_cents"] == 5590

    first = validate_success(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        )
    )
    assert first["billing_status"] == "ACCRUING", "position 1 is strictly below the limit"
    assert first["lifetime_paid_cents"] == 5590
    assert first["last_posted_service_month"] == "2026-08"

    summary = validate_success(api_client.get_cap_summary(contract_id, BILLING_SPECIALIST))
    assert summary["effective_position"] == 1
    assert summary["months_remaining"] == 1

    sweep = advance_clock("2026-09-01T00:00:00Z")
    assert sweep["expired_cmn_count"] == 0, "the certificate recertifies in 2027"

    second = validate_success(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-09"), BILLING_SPECIALIST
        )
    )
    assert second["billing_status"] == "CAP_REACHED"
    assert second["lifetime_paid_cents"] == 11180
    assert second["posted_month_count"] == 2

    final_summary = validate_success(
        api_client.get_cap_summary(contract_id, BILLING_SPECIALIST)
    )
    assert final_summary["effective_position"] == 2
    assert final_summary["months_remaining"] == 0, "the allowance floors at zero"

    ledger = read_contract(contract_id)["posted_months"]
    assert [element["service_month"] for element in ledger] == ["2026-08", "2026-09"]
    assert [element["amount_cents"] for element in ledger] == [5590, 5590], (
        "the placed set did not change between the two months"
    )
