"""Who may act, who may not, and what a version guard refuses to let through."""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    BreachSeverity,
    BreachStatus,
    CaseloadStatus,
    ComplianceStatus,
    ExclusionType,
    MeetingStatus,
    RemedyBasis,
    SeatStatus,
    api_client,
    assert_eligibility_meeting,
    assert_evaluation,
    assert_psychologist,
    assert_scoring_license_seat,
    assert_timeline_breach,
    assign_evaluator_payload,
    decision_payload,
    eligibility_meeting_payload,
    fixtures,
    license_seat_payload,
    make_school_psychologist_headers,
    propose_remedy_payload,
    scores_payload,
    timeline_exclusion_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_only_the_supervisor_reaches_the_routing_endpoint_at_all():
    """Two other roles are turned away before the building rule is ever consulted.

    "If both headers are well-formed but the declared role is not listed among the authorized roles for the endpoint being called (see the table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    "The building whose intervention team raised the referral must appear in the target's `assigned_school_ids`; otherwise the request fails with `ERR_PSYCH_BUILDING_MISMATCH`."

    Design: Corner/rbac/intake_coordinator_cannot_assign_evaluator
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    referring_school = fixtures.create_school(
        name="Ironwood Elementary",
        building_code="IW62",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=330,
    )
    other_school = fixtures.create_school(
        name="Juniper Middle",
        building_code="JN63",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=505,
    )
    psychologist = fixtures.create_psychologist(
        [other_school["id"]],
        full_name="Kai Nolan",
        employee_number="E-2033",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        referring_school["id"],
        student_local_id="STU-53",
        requested_domains=["COGNITIVE"],
    )
    guard_version = fixtures.evaluation_version(evaluation["id"])
    payload = assign_evaluator_payload(guard_version, psychologist["id"])

    response = api_client.assign_evaluator(evaluation["id"], payload, INTAKE)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Owning the reference data confers no routing authority either.
    as_admin = api_client.assign_evaluator(evaluation["id"], payload, ADMIN)
    validate_error(as_admin, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Only with the routing role does the request get far enough to fail on merit.
    as_supervisor = api_client.assign_evaluator(evaluation["id"], payload, SUPERVISOR)
    validate_error(as_supervisor, ApiErrorId.ERR_PSYCH_BUILDING_MISMATCH.value, 422)

    untouched = fixtures.get_evaluation(evaluation["id"])
    assert_evaluation(untouched)
    assert untouched["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert untouched["psychologist_id"] is None
    assert untouched["version"] == guard_version
    assert fixtures.get_psychologist(psychologist["id"])["open_case_points"] == 0


def test_the_drafter_is_refused_their_own_approval_and_a_colleague_grants_it():
    """The same call with the same body succeeds only from a different psychologist.

    "If the reviewing `X-User-ID` equals the evaluation's `report_drafted_by_psychologist_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` — no exception, no override, no supervisor bypass."

    Design: Corner/rbac/drafter_cannot_review_their_own_report
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    context = fixtures.drafted_evaluation(
        school_overrides={
            "name": "Kestrel High",
            "building_code": "KL64",
            "grade_band": "HIGH",
            "concurrent_meeting_capacity": 2,
            "enrollment_count": 780,
        },
        psychologist_overrides={
            "full_name": "Lena Park",
            "employee_number": "E-2034",
            "credential_type": "SSP",
        },
        referral_overrides={"student_local_id": "STU-54"},
        instrument_overrides={"name": "KABC-II", "instrument_code": "KABC2"},
    )
    author = context["psychologist"]
    evaluation = context["evaluation"]
    peer = fixtures.create_psychologist(
        [context["school"]["id"]],
        full_name="Milo Rhee",
        employee_number="E-2035",
        credential_type="PHD",
    )
    assert evaluation["report_drafted_by_psychologist_id"] == author["id"]

    response = api_client.review_report(
        evaluation["id"],
        decision_payload("APPROVE"),
        make_school_psychologist_headers(author["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    still_drafted = fixtures.get_evaluation(evaluation["id"])
    assert still_drafted["assessment_status"] == AssessmentStatus.REPORT_DRAFTED.value
    assert still_drafted["report_drafted_by_psychologist_id"] == author["id"]

    finalized = fixtures.review_report(
        evaluation["id"], "APPROVE", reviewer_psychologist_id=peer["id"]
    )
    assert finalized["assessment_status"] == AssessmentStatus.REPORT_FINAL.value
    assert finalized["report_drafted_by_psychologist_id"] == author["id"]

    # A finalized report is no longer an open case for either party.
    assert fixtures.get_psychologist(author["id"])["open_case_points"] == 0
    assert fixtures.get_psychologist(peer["id"])["open_case_points"] == 0


def test_the_remedy_is_proposed_by_one_role_and_approved_by_the_other():
    """Each half of the remedy is closed to the role that owns the other half.

    "A `ComplianceOfficer` runs the district compliance sweep and proposes compensatory remedies and corrective action, but may never approve them."

    "A `DistrictAdmin` — never the proposing compliance officer's role — approves a `REMEDY_PROPOSED` breach, moving it to the terminal `REMEDY_APPROVED` status and recording `approved_by_user_id`."

    Design: Corner/rbac/district_admin_cannot_propose_remedy
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    school = fixtures.create_school(
        name="Northgate High",
        building_code="NG65",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=910,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        effective_at="2026-06-01T00:00:00Z",
        student_local_id="STU-55",
        requested_domains=["COGNITIVE"],
    )
    fixtures.set_clock("2026-08-10T00:00:00Z")

    # The sweep itself is shared, so the administrator may open the breach.
    summary = fixtures.run_sweep(headers=ADMIN)
    assert summary["evaluated_count"] == 1
    assert len(summary["breach_ids"]) == 1
    breach = fixtures.first_breach(evaluation["id"])
    assert_timeline_breach(breach)
    assert breach["breach_days"] == 10
    assert breach["severity"] == BreachSeverity.MODERATE.value
    assert breach["minutes_breach_day_basis"] == 375

    response = api_client.propose_remedy(
        breach["id"],
        propose_remedy_payload(
            RemedyBasis.BREACH_DAY_BASIS.value,
            corrective_action_note="Compensatory counselling blocks.",
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    unproposed = fixtures.first_breach(evaluation["id"])
    assert unproposed["status"] == BreachStatus.DETECTED.value
    assert unproposed["proposed_by_user_id"] is None
    assert unproposed["remedy_minutes_awarded"] == 0

    proposed = fixtures.propose_remedy(
        breach["id"],
        RemedyBasis.BREACH_DAY_BASIS.value,
        corrective_action_note="Compensatory counselling blocks.",
    )
    assert proposed["status"] == BreachStatus.REMEDY_PROPOSED.value
    assert proposed["proposed_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert proposed["remedy_minutes_awarded"] == 375

    officer_approval = api_client.approve_remedy(breach["id"], COMPLIANCE)
    validate_error(officer_approval, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert fixtures.first_breach(evaluation["id"])["approved_by_user_id"] is None

    approved = fixtures.approve_remedy(breach["id"])
    assert approved["status"] == BreachStatus.REMEDY_APPROVED.value
    assert approved["approved_by_user_id"] == ADMIN["X-User-ID"]
    assert approved["remedy_minutes_awarded"] == 375
    closed = fixtures.get_evaluation(evaluation["id"])
    assert closed["compliance_status"] == ComplianceStatus.BREACH_CLOSED_REMEDIED.value


def test_a_colleague_holding_the_right_role_still_cannot_score_the_case():
    """Ownership is checked against the acting identity, not against the role name.

    "Concretely, a `SchoolPsychologist` may start testing, record scores, or submit a report draft only on an evaluation whose `psychologist_id` equals their own `X-User-ID`, and may claim a timeline exclusion only against such an evaluation; a mismatch is rejected with `ERR_PSYCH_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/only_the_owning_psychologist_may_post_scores
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    context = fixtures.evaluation_in_testing(
        school_overrides={
            "name": "Oakcrest Middle",
            "building_code": "OC66",
            "grade_band": "MIDDLE",
            "concurrent_meeting_capacity": 2,
            "enrollment_count": 520,
        },
        psychologist_overrides={
            "full_name": "Perry Iyer",
            "employee_number": "E-2036",
            "credential_type": "SSP",
        },
        referral_overrides={"student_local_id": "STU-56"},
        instrument_overrides={"name": "WIAT-4", "instrument_code": "WIAT4"},
    )
    owner = context["psychologist"]
    evaluation = context["evaluation"]
    colleague = fixtures.create_psychologist(
        [context["school"]["id"]],
        full_name="Rosa Quill",
        employee_number="E-2037",
        credential_type="SSP",
    )
    colleague_headers = make_school_psychologist_headers(colleague["id"])

    response = api_client.record_scores(
        evaluation["id"], scores_payload("Composite 101, fluency 96"), colleague_headers
    )

    validate_error(response, ApiErrorId.ERR_PSYCH_NOT_OWNER.value, 403)
    still_testing = fixtures.get_evaluation(evaluation["id"])
    assert still_testing["assessment_status"] == AssessmentStatus.IN_TESTING.value
    assert still_testing["score_summary"] is None
    assert still_testing["psychologist_id"] == owner["id"]

    # The same ownership rule governs an exclusion claim on somebody else's case.
    claim = api_client.claim_timeline_exclusion(
        timeline_exclusion_payload(
            evaluation["id"],
            ExclusionType.PARENT_UNAVAILABLE.value,
            "2026-08-05",
            "2026-08-07",
            "Parent travelling out of district",
        ),
        colleague_headers,
    )
    validate_error(claim, ApiErrorId.ERR_PSYCH_NOT_OWNER.value, 403)
    assert fixtures.evaluation_exclusions(evaluation["id"]) == []

    scored = fixtures.record_scores(evaluation["id"], owner["id"], "Composite 101")
    assert scored["assessment_status"] == AssessmentStatus.SCORED.value
    assert scored["score_summary"] == "Composite 101"


def test_seating_a_licence_is_open_to_two_roles_and_closed_to_three():
    """Both permitted roles seat a psychologist; the other three never reach the pool.

    "A `DistrictAdmin` or a `PsychServicesSupervisor` assigns a seat of a given instrument to a psychologist by naming the `psychologist_id`; the seat records the owning `instrument_id` from the path, opens in `ASSIGNED` status with `assigned_at` set to the current clock instant and `released_at` null, and reduces the instrument's free-seat count by one."

    Design: Corner/rbac/license_seating_is_shared_by_admin_and_supervisor
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Yorkshire Middle",
        building_code="YK68",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=505,
    )
    first = fixtures.create_psychologist(
        [school["id"]],
        full_name="Zoe Marek",
        employee_number="E-2039",
        credential_type="SSP",
    )
    second = fixtures.create_psychologist(
        [school["id"]],
        full_name="Adi Kwon",
        employee_number="E-2040",
        credential_type="SSP",
    )
    instrument = fixtures.create_instrument(
        name="BRIEF-2",
        instrument_code="BRIEF2",
        protocol_stock_count=4,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1050,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )

    by_admin = fixtures.assign_license_seat(
        instrument["id"], first["id"], headers=ADMIN
    )
    by_supervisor = fixtures.assign_license_seat(instrument["id"], second["id"])

    assert_scoring_license_seat(by_admin)
    assert_scoring_license_seat(by_supervisor)
    assert by_admin["status"] == SeatStatus.ASSIGNED.value
    assert by_admin["instrument_id"] == instrument["id"]
    assert by_admin["released_at"] is None
    assert by_supervisor["status"] == SeatStatus.ASSIGNED.value
    assert fixtures.get_instrument(instrument["id"])["license_seats_free"] == 0

    # Role authorization is settled long before the seat pool is consulted.
    for refused_headers in (
        make_school_psychologist_headers(first["id"]),
        INTAKE,
        COMPLIANCE,
    ):
        refused = api_client.assign_license_seat(
            instrument["id"], license_seat_payload(first["id"]), refused_headers
        )
        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    seats = {row["id"]: row for row in fixtures.instrument_seats(instrument["id"])}
    assert len(seats) == 2
    assert seats[by_admin["id"]]["psychologist_id"] == first["id"]
    assert seats[by_supervisor["id"]]["psychologist_id"] == second["id"]


def test_a_re_route_carrying_the_pre_assignment_version_is_refused():
    """The first assignment moved the version, so the held guard is one behind.

    "If the supplied value does not equal the evaluation's current `version`, the request is rejected with `ERR_STALE_EVALUATION_VERSION` (HTTP 412), and nothing is written."

    Design: Corner/cross_cutting_layers/assign_with_stale_evaluation_version_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Ashcombe Elementary",
        building_code="AC69",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=330,
    )
    incumbent = fixtures.create_psychologist(
        [school["id"]],
        full_name="Bea Yarrow",
        employee_number="E-2041",
        credential_type="SSP",
    )
    successor = fixtures.create_psychologist(
        [school["id"]],
        full_name="Cal Ivers",
        employee_number="E-2042",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-57", requested_domains=["COGNITIVE"]
    )
    stale_version = fixtures.evaluation_version(evaluation["id"])
    fixtures.assign_evaluator(evaluation["id"], incumbent["id"])

    response = api_client.assign_evaluator(
        evaluation["id"],
        assign_evaluator_payload(stale_version, successor["id"]),
        SUPERVISOR,
    )

    validate_error(response, ApiErrorId.ERR_STALE_EVALUATION_VERSION.value, 412)
    fresh_version = fixtures.evaluation_version(evaluation["id"])
    assert fresh_version == stale_version + 1
    held = fixtures.get_evaluation(evaluation["id"])
    assert held["psychologist_id"] == incumbent["id"]
    assert held["reassignment_count"] == 0
    assert fixtures.get_psychologist(incumbent["id"])["open_case_points"] == 5
    assert fixtures.get_psychologist(successor["id"])["open_case_points"] == 0

    rerouted = fixtures.assign_evaluator(
        evaluation["id"], successor["id"], expected_version=fresh_version
    )
    assert rerouted["psychologist_id"] == successor["id"]
    assert rerouted["reassignment_count"] == 1
    assert rerouted["version"] == fresh_version + 1
    assert fixtures.get_psychologist(incumbent["id"])["open_case_points"] == 0
    assert fixtures.get_psychologist(successor["id"])["open_case_points"] == 5


def test_a_meeting_proposed_on_the_pre_assignment_version_writes_nothing():
    """The routing cascade invalidated the coordinator's guard before they proposed.

    "Creating a meeting increments the parent evaluation's `version` by one, which is exactly why the guard is needed: a client holding an older version is refused with `ERR_STALE_EVALUATION_VERSION`."

    Design: Corner/cross_cutting_layers/meeting_creation_with_stale_evaluation_version_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Brookvale Middle",
        building_code="BV70",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=490,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Dot Ellery",
        employee_number="E-2043",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-58", requested_domains=["COGNITIVE"]
    )
    stale_version = fixtures.evaluation_version(evaluation["id"])
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    response = api_client.create_eligibility_meeting(
        eligibility_meeting_payload(
            evaluation["id"],
            school["id"],
            "2026-09-20T15:00:00Z",
            "2026-09-20T16:00:00Z",
            stale_version,
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_STALE_EVALUATION_VERSION.value, 412)
    _, meta = validate_paginated(
        api_client.list_eligibility_meetings(
            INTAKE, {"evaluation_id": evaluation["id"]}
        )
    )
    assert meta["total_count"] == 0
    fresh_version = fixtures.evaluation_version(evaluation["id"])
    assert fresh_version == stale_version + 1

    meeting = fixtures.create_meeting(
        evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
        expected_version=fresh_version,
    )
    assert_eligibility_meeting(meeting)
    assert meeting["status"] == MeetingStatus.PROPOSED.value
    assert meeting["reschedule_count"] == 0
    assert meeting["parent_notice_sent_at"] is None
    assert meeting["notice_lead_days"] is None
    assert meeting["held_at"] is None
    assert fixtures.evaluation_version(evaluation["id"]) == fresh_version + 1


def test_the_routing_response_already_carries_the_whole_cascade():
    """No read is needed to see the assignment, and none is needed to see the load.

    "The rule is that a cascade is part of the request that triggered it: it is applied immediately, in the same request, before the response is written, and each record it touches has its `updated_at` refreshed and its `version` incremented."

    "Whichever mode resolved the target, the successful routing sets `psychologist_id` on the evaluation, increments the evaluation's `version` by one, and re-derives the newly assigned psychologist's `open_case_points`, `caseload_status`, `pressure_index_assigned_basis` and `pressure_index_clock_weighted`."

    Design: Corner/consistency_model/assignment_cascade_visible_in_the_same_response
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Cliffside High",
        building_code="CS71",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=700,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Eve Larkin",
        employee_number="E-2044",
        credential_type="SSP",
        weekly_capacity_points=20,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-59",
        requested_domains=["COGNITIVE", "ACADEMIC"],
    )
    version_before = evaluation["version"]
    assert evaluation["caseload_points"] == 6

    assigned = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    assert_evaluation(assigned)
    assert assigned["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert assigned["psychologist_id"] == psychologist["id"]
    assert assigned["version"] == version_before + 1

    # The very next read of the other record already shows the re-derived figures.
    loaded = fixtures.get_psychologist(psychologist["id"])
    assert_psychologist(loaded)
    assert loaded["open_case_points"] == 6
    assert loaded["caseload_status"] == CaseloadStatus.BALANCED.value
    assert loaded["pressure_index_assigned_basis"] == 0.30
    assert loaded["pressure_index_clock_weighted"] == 0.30

    rows, meta = validate_paginated(
        api_client.list_evaluations(
            SUPERVISOR, {"psychologist_id": psychologist["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [evaluation["id"]]
