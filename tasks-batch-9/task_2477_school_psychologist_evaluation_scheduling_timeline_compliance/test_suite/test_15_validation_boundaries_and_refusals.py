"""Boundary equality, the refusal codes just past it, and the state a rejected write leaves."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    BreachSeverity,
    BreachStatus,
    CaseloadStatus,
    ComplianceStatus,
    CredentialType,
    MeetingStatus,
    OrderStatus,
    ReferralStatus,
    RemedyBasis,
    SeatStatus,
    api_client,
    assert_evaluation,
    assert_protocol_order,
    assert_psychologist,
    assert_referral,
    assert_school,
    assert_timeline_breach,
    assign_evaluator_payload,
    consent_event_payload,
    create_school_payload,
    fixtures,
    is_valid_uuid,
    license_seat_payload,
    make_school_psychologist_headers,
    propose_remedy_payload,
    receive_order_payload,
    start_testing_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _capacity_five_psychologist():
    """A psychologist whose whole week fits exactly one five-point case."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Zephyr Elementary",
        building_code="ZP44",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=310,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Eli Wren",
        employee_number="E-2018",
        credential_type="SSP",
        weekly_capacity_points=5,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-28", requested_domains=["COGNITIVE"]
    )
    return school, psychologist, evaluation


def test_landing_exactly_on_the_caseload_ceiling_is_permitted():
    """Five points into a capacity of five is accepted and labelled AT_CAP.

    "Landing exactly on the ceiling is permitted and simply drives `caseload_status` to `AT_CAP`; exceeding it by even a single point is rejected with `ERR_PSYCH_CASELOAD_OVER_CAP`."

    Design: Corner/validations/caseload_cap_exact_equality_is_allowed
    """
    _, psychologist, evaluation = _capacity_five_psychologist()

    assigned = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    assert assigned["psychologist_id"] == psychologist["id"]
    assert assigned["assessment_status"] == AssessmentStatus.ASSIGNED.value

    loaded = fixtures.get_psychologist(psychologist["id"])
    assert_psychologist(loaded)
    assert loaded["open_case_points"] == 5
    assert loaded["caseload_status"] == CaseloadStatus.AT_CAP.value
    assert loaded["pressure_index_assigned_basis"] == 1.00
    assert loaded["pressure_index_clock_weighted"] == 1.00


def test_one_point_past_the_caseload_ceiling_is_refused():
    """A second five-point case would make ten against a capacity of five.

    "Finally the caseload ceiling: the target's current `open_case_points` plus this evaluation's `caseload_points` must be no greater than the target's `weekly_capacity_points`."

    Design: Corner/validations/caseload_cap_exceeded_by_one_point_rejected
    """
    school, psychologist, evaluation = _capacity_five_psychologist()
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    _, waiting = fixtures.consented_referral(
        school["id"], student_local_id="STU-29", requested_domains=["ACADEMIC"]
    )

    response = api_client.assign_evaluator(
        waiting["id"],
        assign_evaluator_payload(
            fixtures.evaluation_version(waiting["id"]), psychologist["id"]
        ),
        SUPERVISOR,
    )

    validate_error(response, ApiErrorId.ERR_PSYCH_CASELOAD_OVER_CAP.value, 409)

    refused = fixtures.get_evaluation(waiting["id"])
    assert refused["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert refused["psychologist_id"] is None

    unchanged = fixtures.get_psychologist(psychologist["id"])
    assert unchanged["open_case_points"] == 5
    assert unchanged["caseload_status"] == CaseloadStatus.AT_CAP.value


def test_an_intern_is_refused_a_first_evaluation_but_takes_the_reexamination():
    """The scope rule reads the evaluation's referral type, not the credential alone.

    "A target whose `credential_type` is `INTERN` may only take evaluations whose `referral_type` is `REEVALUATION`; handing an intern an `INITIAL` case fails with `ERR_INTERN_SCOPE_VIOLATION`."

    Design: Corner/validations/intern_may_only_take_reevaluations
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Thistle Elementary",
        building_code="TH45",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=330,
    )
    intern = fixtures.create_psychologist(
        [school["id"]],
        full_name="Fern Ito",
        employee_number="E-2019",
        credential_type=CredentialType.INTERN.value,
    )
    _, initial_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-30", requested_domains=["COGNITIVE"]
    )
    _, reevaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-31",
        referral_type="REEVALUATION",
        prior_evaluation_id=initial_evaluation["id"],
        requested_domains=["COGNITIVE"],
    )

    response = api_client.assign_evaluator(
        initial_evaluation["id"],
        assign_evaluator_payload(
            fixtures.evaluation_version(initial_evaluation["id"]), intern["id"]
        ),
        SUPERVISOR,
    )

    validate_error(response, ApiErrorId.ERR_INTERN_SCOPE_VIOLATION.value, 422)
    refused = fixtures.get_evaluation(initial_evaluation["id"])
    assert refused["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert fixtures.get_psychologist(intern["id"])["open_case_points"] == 0

    accepted = fixtures.assign_evaluator(reevaluation["id"], intern["id"])
    assert accepted["assessment_status"] == AssessmentStatus.ASSIGNED.value
    # 3 base + 0 extra domain + 0 interpreter + 1 for the REEVALUATION type.
    assert fixtures.get_psychologist(intern["id"])["open_case_points"] == 4


def test_language_certification_is_demanded_only_when_the_bilingual_flag_is_set():
    """Two Spanish-speaking referrals differ only in the bilingual requirement.

    "When the referral has `bilingual_evaluation_required` set to true, the referral's `primary_language` must appear in the target's `languages_certified`; otherwise the request fails with `ERR_LANGUAGE_CERT_MISSING`."

    Design: Corner/validations/bilingual_referral_requires_language_certification
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Willow Springs Middle",
        building_code="WS46",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=520,
    )
    english_only = fixtures.create_psychologist(
        [school["id"]],
        full_name="Gil Marsh",
        employee_number="E-2020",
        credential_type="SSP",
        languages_certified=["en"],
    )
    bilingual = fixtures.create_psychologist(
        [school["id"]],
        full_name="Hana Ruiz",
        employee_number="E-2021",
        credential_type="SSP",
        languages_certified=["en", "es"],
    )
    _, bilingual_case = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-32",
        primary_language="es",
        bilingual_evaluation_required=True,
        requested_domains=["COGNITIVE"],
    )
    _, monolingual_case = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-33",
        primary_language="es",
        bilingual_evaluation_required=False,
        requested_domains=["COGNITIVE"],
    )

    response = api_client.assign_evaluator(
        bilingual_case["id"],
        assign_evaluator_payload(
            fixtures.evaluation_version(bilingual_case["id"]), english_only["id"]
        ),
        SUPERVISOR,
    )

    validate_error(response, ApiErrorId.ERR_LANGUAGE_CERT_MISSING.value, 422)
    assert fixtures.get_evaluation(bilingual_case["id"])["psychologist_id"] is None

    certified = fixtures.assign_evaluator(bilingual_case["id"], bilingual["id"])
    assert certified["assessment_status"] == AssessmentStatus.ASSIGNED.value

    # The same Spanish-speaking student with the flag off assigns to the same
    # English-only psychologist, so the flag rather than the language is the trigger.
    without_the_flag = fixtures.assign_evaluator(
        monolingual_case["id"], english_only["id"]
    )
    assert without_the_flag["psychologist_id"] == english_only["id"]
    assert without_the_flag["assessment_status"] == AssessmentStatus.ASSIGNED.value


def test_an_empty_candidate_pool_refuses_the_selector_without_burning_the_version():
    """Three psychologists are filtered out for three different reasons.

    "If the filter leaves nobody at all, the request is rejected with `ERR_NO_ELIGIBLE_PSYCHOLOGIST`, the evaluation stays in `PENDING_ASSIGNMENT`, and its `version` is **not** incremented."

    Design: Corner/validations/selector_empty_pool_leaves_evaluation_untouched
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    home = fixtures.create_school(
        name="Birch Hollow Elementary",
        building_code="BH47",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=280,
    )
    elsewhere = fixtures.create_school(
        name="Cedar Point High",
        building_code="CP48",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=910,
    )
    on_leave = fixtures.create_psychologist(
        [home["id"]],
        full_name="Ivy Doss",
        employee_number="E-2022",
        credential_type="SSP",
    )
    fixtures.place_on_leave(on_leave["id"])
    fixtures.create_psychologist(
        [elsewhere["id"]],
        full_name="Jonas Pike",
        employee_number="E-2023",
        credential_type="SSP",
    )
    fixtures.create_psychologist(
        [home["id"]],
        full_name="Kira Lund",
        employee_number="E-2024",
        credential_type=CredentialType.INTERN.value,
    )
    _, evaluation = fixtures.consented_referral(
        home["id"], student_local_id="STU-34", requested_domains=["COGNITIVE"]
    )
    guard_version = fixtures.evaluation_version(evaluation["id"])

    response = api_client.assign_evaluator(
        evaluation["id"], assign_evaluator_payload(guard_version), SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_PSYCHOLOGIST.value, 409)
    untouched = fixtures.get_evaluation(evaluation["id"])
    assert untouched["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert untouched["psychologist_id"] is None
    assert untouched["version"] == guard_version

    hired = fixtures.create_psychologist(
        [home["id"]],
        full_name="Lena Voss",
        employee_number="E-2025",
        credential_type="SSP",
    )
    # The same guard value still works, which proves the refused call wrote nothing.
    routed = fixtures.assign_evaluator(
        evaluation["id"], expected_version=guard_version
    )
    assert routed["psychologist_id"] == hired["id"]
    assert routed["assessment_status"] == AssessmentStatus.ASSIGNED.value


def test_a_building_code_already_in_use_is_refused_while_a_distinct_one_is_taken():
    """Uniqueness is an exact comparison over the whole code.

    "A building is registered with a display `name` and a `building_code`, which is an uppercase alphanumeric string of two to eight characters and must be unique across all buildings — a second building registered with a code already in use, compared case-sensitively and exactly, is rejected with `ERR_DUPLICATE_BUILDING_CODE`."

    Design: Corner/validations/duplicate_building_code_is_case_sensitive
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    original = fixtures.create_school(
        name="Fairground High",
        building_code="FG50",
        grade_band="HIGH",
        concurrent_meeting_capacity=1,
        enrollment_count=90,
    )

    response = api_client.create_school(
        create_school_payload(
            name="Fairground Annex",
            building_code="FG50",
            grade_band="HIGH",
            concurrent_meeting_capacity=1,
            enrollment_count=90,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_BUILDING_CODE.value, 409)
    survivor = validate_success(api_client.get_school(original["id"], ADMIN))
    assert_school(survivor)
    assert survivor["name"] == "Fairground High"
    assert survivor["version"] == 1

    # A code that differs at all is a different code, so the annex registers.
    annex = validate_success(
        api_client.create_school(
            create_school_payload(
                name="Fairground Annex",
                building_code="FG501",
                grade_band="HIGH",
                concurrent_meeting_capacity=1,
                enrollment_count=90,
            ),
            ADMIN,
        ),
        201,
    )
    assert annex["building_code"] == "FG501"
    assert is_valid_uuid(annex["id"])
    assert annex["id"] != original["id"]


def test_a_waiver_needs_both_a_reevaluation_and_a_reason():
    """One error code guards two independent clauses.

    "Because a waiver is documentation of a reevaluation decision, it is accepted only when the referral's `referral_type` is `REEVALUATION` **and** the supplied `waiver_reason` is a non-empty string; a waiver on an `INITIAL` referral, or one with a missing or empty reason, is rejected with `ERR_WAIVER_NOT_APPLICABLE`."

    Design: Corner/validations/consent_waiver_requires_reevaluation_and_reason
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Gladeview Middle",
        building_code="GV49",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=540,
    )
    _, prior_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-35", requested_domains=["COGNITIVE"]
    )
    initial_referral = fixtures.create_referral(
        school["id"], student_local_id="STU-36", referral_type="INITIAL"
    )
    reevaluation_referral = fixtures.create_referral(
        school["id"],
        student_local_id="STU-37",
        referral_type="REEVALUATION",
        prior_evaluation_id=prior_evaluation["id"],
    )

    response = api_client.create_consent_event(
        initial_referral["id"],
        consent_event_payload(
            "CONSENT_WAIVED", waiver_reason="Family declined a full reevaluation."
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_APPLICABLE.value, 422)
    untouched = fixtures.get_referral(initial_referral["id"])
    assert_referral(untouched)
    assert untouched["status"] == ReferralStatus.INTAKE_RECEIVED.value
    assert untouched["active_evaluation_id"] is None
    assert untouched["waiver_reason"] is None

    empty_reason = api_client.create_consent_event(
        reevaluation_referral["id"],
        consent_event_payload("CONSENT_WAIVED", waiver_reason=""),
        INTAKE,
    )
    validate_error(empty_reason, ApiErrorId.ERR_WAIVER_NOT_APPLICABLE.value, 422)
    assert (
        fixtures.get_referral(reevaluation_referral["id"])["status"]
        == ReferralStatus.INTAKE_RECEIVED.value
    )

    waived = validate_success(
        api_client.create_consent_event(
            reevaluation_referral["id"],
            consent_event_payload(
                "CONSENT_WAIVED", waiver_reason="Team documented the waiver decision."
            ),
            INTAKE,
        )
    )
    assert waived["status"] == ReferralStatus.CONSENT_WAIVED.value


def test_a_consent_one_second_ahead_of_the_clock_is_refused():
    """The comparison is inclusive, so the clock's own instant is legal.

    "No event may be back-dated into the future: an `effective_at` later than the current logical clock instant is rejected with `ERR_CONSENT_TIMESTAMP_FUTURE`."

    Design: Corner/validations/consent_effective_at_in_the_future_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Harbor Ridge High",
        building_code="HR53",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=880,
    )
    referral = fixtures.create_referral(school["id"], student_local_id="STU-38")

    response = api_client.create_consent_event(
        referral["id"],
        consent_event_payload(
            "CONSENT_RECEIVED",
            effective_at="2026-08-01T00:00:01Z",
            parent_signature_reference="SIG-38",
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_CONSENT_TIMESTAMP_FUTURE.value, 422)
    refused = fixtures.get_referral(referral["id"])
    assert refused["status"] == ReferralStatus.INTAKE_RECEIVED.value
    assert refused["consent_received_at"] is None
    assert refused["active_evaluation_id"] is None
    _, meta = validate_paginated(api_client.list_evaluations(SUPERVISOR))
    assert meta["total_count"] == 0

    consented = fixtures.record_consent(
        referral["id"],
        event_type="CONSENT_RECEIVED",
        effective_at="2026-08-01T00:00:00Z",
        parent_signature_reference="SIG-38",
    )
    assert consented["status"] == ReferralStatus.CONSENTED.value
    evaluation = fixtures.get_evaluation(consented["active_evaluation_id"])
    assert_evaluation(evaluation)
    assert evaluation["clock_start_date"] == "2026-08-01"


def test_both_ends_of_the_receipt_window_are_closed_and_a_partial_receipt_is_legal():
    """Thirty-one and zero are both out of range against a thirty-unit order.

    "Receipt is recorded by a `PsychServicesSupervisor` or a `DistrictAdmin` supplying `received_quantity`, which must be at least one and no greater than `quantity_requested`; anything outside that range is rejected with `ERR_RECEIPT_QUANTITY_EXCEEDS_ORDER`."

    Design: Corner/validations/receipt_quantity_bounds_enforced
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="WISC-V",
        instrument_code="WISC5",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    order = fixtures.order_protocols(instrument["id"], 30, rush_flag=False)
    assert order["total_cost_cents"] == 47681
    assert order["status"] == OrderStatus.SUBMITTED.value
    fixtures.decide_order(order["id"], "APPROVE")

    response = api_client.receive_protocol_order(
        order["id"], receive_order_payload(31), SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_RECEIPT_QUANTITY_EXCEEDS_ORDER.value, 422)
    still_open = fixtures.list_rows(
        api_client.list_instrument_protocol_orders(instrument["id"], SUPERVISOR)
    )[0]
    assert still_open["status"] == OrderStatus.APPROVED.value
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0

    nothing_received = api_client.receive_protocol_order(
        order["id"], receive_order_payload(0), SUPERVISOR
    )
    validate_error(
        nothing_received, ApiErrorId.ERR_RECEIPT_QUANTITY_EXCEEDS_ORDER.value, 422
    )

    partial = fixtures.receive_order(order["id"], 29)
    assert_protocol_order(partial)
    assert partial["status"] == OrderStatus.RECEIVED.value
    assert partial["received_quantity"] == 29
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 29


def test_a_remedy_award_over_the_ceiling_is_refused_rather_than_clamped():
    """A forty-day breach prices at exactly the 1,800-minute ceiling on one basis.

    "That sum may not exceed 1,800 minutes — thirty hours of compensatory service — and a proposal that would exceed the ceiling is rejected outright with `ERR_REMEDY_MINUTES_EXCEED_CAP`; the award is **never** silently clamped down to the ceiling."

    Design: Corner/validations/remedy_award_cap_is_never_silently_clamped
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    school = fixtures.create_school(
        name="Marlowe High",
        building_code="ML51",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=940,
    )
    evaluations = [
        fixtures.consented_referral(
            school["id"],
            effective_at="2026-06-01T00:00:00Z",
            student_local_id=f"STU-4{index}",
            requested_domains=["COGNITIVE"],
        )[1]
        for index in range(3)
    ]
    fixtures.set_clock("2026-09-09T00:00:00Z")
    summary = fixtures.run_sweep()
    assert summary["evaluated_count"] == 3

    breaches = [fixtures.first_breach(row["id"]) for row in evaluations]
    for breach in breaches:
        assert_timeline_breach(breach)
        assert breach["breach_days"] == 40
        assert breach["severity"] == BreachSeverity.SEVERE.value
        # 40 * 30 * 1.5 is 1800; six whole missed weeks * 150 * 1.5 is 1350.
        assert breach["minutes_breach_day_basis"] == 1800
        assert breach["minutes_missed_service_basis"] == 1350

    response = api_client.propose_remedy(
        breaches[0]["id"],
        propose_remedy_payload(
            RemedyBasis.BREACH_DAY_BASIS.value,
            5,
            "Compensatory sessions plus staff retraining.",
        ),
        COMPLIANCE,
    )

    validate_error(response, ApiErrorId.ERR_REMEDY_MINUTES_EXCEED_CAP.value, 422)
    refused = fixtures.first_breach(evaluations[0]["id"])
    assert refused["status"] == BreachStatus.DETECTED.value
    assert refused["remedy_basis"] is None
    assert refused["additional_minutes"] == 0
    assert refused["remedy_minutes_awarded"] == 0

    on_the_ceiling = fixtures.propose_remedy(
        breaches[1]["id"],
        RemedyBasis.BREACH_DAY_BASIS.value,
        additional_minutes=0,
        corrective_action_note="Compensatory sessions plus staff retraining.",
    )
    assert on_the_ceiling["remedy_minutes_awarded"] == 1800

    # The cap is tested after the basis is chosen, so the cheaper basis has room.
    other_basis = fixtures.propose_remedy(
        breaches[2]["id"],
        RemedyBasis.MISSED_SERVICE_BASIS.value,
        additional_minutes=5,
        corrective_action_note="Compensatory sessions plus staff retraining.",
    )
    assert other_basis["remedy_minutes_awarded"] == 1355


def test_the_inventory_gate_counts_one_administration_per_domain():
    """Two booklets cover one two-domain case exactly and leave the shelf empty.

    "The inventory gate comes third: the instrument's `protocol_stock_count` must be at least its `protocol_units_per_administration` multiplied by the number of entries in the evaluation's `evaluation_domains`."

    "Exact equality passes and drives the shelf to zero; anything less is rejected with `ERR_PROTOCOL_STOCK_INSUFFICIENT`."

    Design: Corner/validations/protocol_stock_exact_equality_then_exhaustion
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Norse Ridge Middle",
        building_code="NR52",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=505,
    )
    first_owner = fixtures.create_psychologist(
        [school["id"]],
        full_name="Otis Grey",
        employee_number="E-2026",
        credential_type="SSP",
    )
    second_owner = fixtures.create_psychologist(
        [school["id"]],
        full_name="Priya Nand",
        employee_number="E-2027",
        credential_type="SSP",
    )
    instrument = fixtures.create_instrument(
        name="KTEA-3",
        instrument_code="KTEA3",
        protocol_stock_count=2,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1000,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    fixtures.assign_license_seat(instrument["id"], first_owner["id"])
    fixtures.assign_license_seat(instrument["id"], second_owner["id"])
    _, two_domain_case = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-44",
        requested_domains=["COGNITIVE", "ACADEMIC"],
    )
    fixtures.assign_evaluator(two_domain_case["id"], first_owner["id"])
    _, one_domain_case = fixtures.consented_referral(
        school["id"], student_local_id="STU-45", requested_domains=["COGNITIVE"]
    )
    fixtures.assign_evaluator(one_domain_case["id"], second_owner["id"])

    started = fixtures.start_testing(
        two_domain_case["id"], instrument["id"], first_owner["id"]
    )
    assert started["protocol_units_consumed"] == 2
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0

    response = api_client.start_testing(
        one_domain_case["id"],
        start_testing_payload(instrument["id"]),
        make_school_psychologist_headers(second_owner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PROTOCOL_STOCK_INSUFFICIENT.value, 409)
    refused = fixtures.get_evaluation(one_domain_case["id"])
    assert refused["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert refused["testing_instrument_id"] is None
    assert refused["protocol_units_consumed"] == 0
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0

    restock = fixtures.order_protocols(instrument["id"], 5)
    assert restock["auto_approved"] is True
    fixtures.receive_order(restock["id"], 5)

    resumed = fixtures.start_testing(
        one_domain_case["id"], instrument["id"], second_owner["id"]
    )
    assert resumed["assessment_status"] == AssessmentStatus.IN_TESTING.value
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 4


def test_a_meeting_one_second_early_is_not_yet_due():
    """The report gate above it already passes, so the refusal is purely temporal.

    "And the meeting must actually be due: the current clock instant must be at or after `scheduled_start_at`, otherwise the attempt is rejected with `ERR_MEETING_NOT_DUE`."

    Design: Corner/validations/meeting_hold_before_scheduled_start_rejected
    """
    context = fixtures.final_report_evaluation(
        school_overrides={
            "name": "Quarrybrook Elementary",
            "building_code": "QB54",
            "grade_band": "ELEMENTARY",
            "concurrent_meeting_capacity": 2,
            "enrollment_count": 300,
        },
        psychologist_overrides={
            "full_name": "Rune Salas",
            "employee_number": "E-2028",
            "credential_type": "SSP",
        },
        referral_overrides={
            "student_local_id": "STU-46",
            "requested_domains": ["COGNITIVE"],
        },
        instrument_overrides={
            "name": "WJ-IV",
            "instrument_code": "WJIV",
            "protocol_stock_count": 4,
        },
    )
    evaluation = context["evaluation"]
    meeting = fixtures.create_meeting(
        evaluation["id"],
        context["school"]["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    fixtures.set_clock("2026-09-10T00:00:00Z")
    fixtures.send_notice(meeting["id"])
    fixtures.set_clock("2026-09-19T23:59:59Z")

    response = api_client.hold_meeting(meeting["id"], SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_MEETING_NOT_DUE.value, 409)
    waiting = fixtures.get_meeting(meeting["id"])
    assert waiting["status"] == MeetingStatus.NOTICED.value
    assert waiting["held_at"] is None
    assert (
        fixtures.get_evaluation(evaluation["id"])["compliance_status"]
        == ComplianceStatus.ON_TRACK.value
    )
    assert (
        fixtures.get_referral(context["referral"]["id"])["status"]
        == ReferralStatus.CONSENTED.value
    )

    fixtures.set_clock("2026-09-20T15:00:00Z")
    held = fixtures.hold_meeting(meeting["id"])
    assert held["status"] == MeetingStatus.HELD.value


def test_re_seating_the_same_psychologist_is_refused_while_a_seat_is_still_free():
    """The exhaustion code also covers the one-seat-per-psychologist clause.

    "Two conditions block a seat assignment and share a single code: `license_seats_free` already standing at zero, and the named psychologist already holding an `ASSIGNED` seat for that same instrument."

    "Either case is rejected with `ERR_LICENSE_SEATS_EXHAUSTED`."

    Design: Corner/validations/duplicate_license_seat_for_same_psychologist_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Rosemead High",
        building_code="RM55",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=770,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Sasha Rowe",
        employee_number="E-2029",
        credential_type="SSP",
    )
    instrument = fixtures.create_instrument(
        name="CTOPP-2",
        instrument_code="CTOPP2",
        protocol_stock_count=4,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1000,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    seat = fixtures.assign_license_seat(instrument["id"], psychologist["id"])
    assert fixtures.get_instrument(instrument["id"])["license_seats_free"] == 1

    response = api_client.assign_license_seat(
        instrument["id"], license_seat_payload(psychologist["id"]), SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_SEATS_EXHAUSTED.value, 409)
    assert fixtures.get_instrument(instrument["id"])["license_seats_free"] == 1
    assert len(fixtures.instrument_seats(instrument["id"])) == 1

    held = fixtures.psychologist_seats(psychologist["id"])
    assert len(held) == 1
    assert held[0]["id"] == seat["id"]
    assert held[0]["status"] == SeatStatus.ASSIGNED.value
