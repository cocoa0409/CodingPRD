"""Who may act, on whose records, and never twice on the same claim: the exclusive operations
each opaque role keeps to itself, the two hops that bound an entity-backed caller, the
recorder who may not bless their own outcome, and the header check that runs before all of it.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_instructor_headers,
    make_program_coordinator_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_state_authority_headers,
    make_student_headers,
)
from test_helpers.types import (
    AccommodationStatus,
    CenterDecision,
    IdentityStatus,
    OutcomeDecision,
    OutcomeStatus,
    ProgramTrack,
    Role,
    RoomStatus,
    SessionStatus,
    TestEventStatus,
    TestForm,
    TestFormat,
)

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"

PRE_TEST_AT = "2026-08-02T09:00:00Z"
PLACEMENT_SCORE = 205
DENIED_PERIOD = {
    "label": "FY27-X",
    "start_date": "2026-08-01",
    "end_date": "2026-12-01",
    "rate_cents_per_weight": 9000,
    "total_cents": 200000,
}
INSTRUCTOR_SECTION = {
    "title": "Instructor Section",
    "instructor_user_id": "instructor-40",
    "min_efl_level": 1,
    "max_efl_level": 6,
    "seats_total": 10,
    "weekly_hours": 6.00,
}

SCOPE_SITTING = ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z")
SCOPE_SEATS = 5
USABLE_EXPIRY = "2027-01-01T00:00:00Z"

SOD_PERIOD = {
    "label": "FY27-SOD",
    "start_date": "2026-08-01",
    "end_date": "2026-12-01",
    "rate_cents_per_weight": 10000,
    "total_cents": 100000,
}
OPENING_AUTHORITY = "state-9"
RECORDING_COORDINATOR = "coord-7"
DECIDING_COORDINATOR = "coord-8"


def _oriented_learner_with_scheduled_pre_test():
    student = fixtures.create_oriented_student(
        full_name="Cleo Barnes",
        email="cleo.barnes@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    event = fixtures.schedule_test_event(
        student["id"], PRE_TEST_AT, test_form=TestForm.CASAS_R_900
    )
    fixtures.set_clock(PRE_TEST_AT)
    return student, event


def _score(event_id, headers):
    return api_client.score_test_event(
        event_id, factories.score_test_event_payload(PLACEMENT_SCORE), headers=headers
    )


def _two_authorized_centers():
    first = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Scope Center One", state_code="KS"
    )
    second = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Scope Center Two", state_code="KS"
    )
    room = fixtures.create_room(first["id"], room_code="ONE-1", seat_capacity=10)
    return first, second, room


def _open_a_sitting(room_id, headers):
    return api_client.create_exam_session(
        factories.create_exam_session_payload(
            room_id, SCOPE_SITTING[0], SCOPE_SITTING[1], requested_seats=SCOPE_SEATS
        ),
        headers=headers,
    )


def _headers_without_user_id(role):
    return {"X-User-Role": role}


def test_01_an_adjacent_role_still_cannot_reach_another_roles_exclusive_write():
    """"They alone register testing centres, decide centre authorisation, suspend centres, decide
    proctor certification, issue credentials, create funding periods, run funding allocation and
    close funding periods" and "they alone create class sections, transition section status,
    create enrollments and void attendance entries"

    Design: Corner/rbac/opaque_roles_cannot_perform_another_roles_exclusive_operations
    """
    student, _event = _oriented_learner_with_scheduled_pre_test()
    coordinator = make_program_coordinator_headers()

    validate_error(
        api_client.create_testing_center(
            factories.create_testing_center_payload(
                name="Coordinator Center", state_code="IA"
            ),
            headers=coordinator,
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api_client.create_funding_period(
            factories.create_funding_period_payload(**DENIED_PERIOD),
            headers=make_registrar_headers(),
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api_client.issue_credential(
            factories.create_credential_issuance_payload(student["id"]), headers=coordinator
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api_client.create_class_section(
            factories.create_class_section_payload(
                program_track=ProgramTrack.HSE_PREP, **INSTRUCTOR_SECTION
            ),
            headers=make_instructor_headers(),
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )

    _centers, center_meta = validate_paginated(
        api_client.list_testing_centers(
            headers=make_state_authority_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert center_meta["total_count"] == 0

    _sections, section_meta = validate_paginated(
        api_client.list_class_sections(headers=coordinator, params={"limit": 10, "offset": 0})
    )
    assert section_meta["total_count"] == 0


def test_02_the_registrar_who_booked_the_test_may_not_score_it():
    """"An `Instructor` alone scores test events, and additionally posts attendance entries and
    withdraws enrollments for the classes they teach." and "A `Registrar` has no exclusive
    operation; they run orientation completion, test-event scheduling, exam registration and
    cancellation, accommodation submission and resubmission, transcript ordering on a learner's
    behalf, and transcript fulfilment."

    Design: Corner/rbac/opaque_roles_cannot_perform_another_roles_exclusive_operations
    """
    _student, event = _oriented_learner_with_scheduled_pre_test()

    validate_error(
        _score(event["id"], make_registrar_headers()),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )
    assert fixtures.read_test_event(event["id"])["status"] == TestEventStatus.SCHEDULED

    scored = validate_success(_score(event["id"], make_instructor_headers()))
    assert scored["status"] == TestEventStatus.SCORED
    assert scored["scale_score"] == PLACEMENT_SCORE


def test_03_an_administrator_reaching_into_another_centre_is_out_of_scope():
    """"An entity-backed role that reaches outside its own scope — the wrong centre, a session it
    is not assigned to, another learner's record — is rejected with `ERR_FORBIDDEN_SCOPE` (403).
    This is distinct from `ERR_UNAUTHORIZED`: the role is permitted to perform the operation in
    general, but not on that particular record."

    Design: Corner/rbac/center_administrator_cannot_act_outside_its_own_center
    """
    first, second, room = _two_authorized_centers()
    intruder = make_center_administrator_headers(second["id"])

    validate_error(
        api_client.create_testing_room(
            first["id"],
            factories.create_testing_room_payload(room_code="INTRUDER-1", seat_capacity=10),
            headers=intruder,
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )
    validate_error(
        api_client.create_proctor(
            first["id"],
            factories.create_proctor_payload(full_name="Intruder Proctor"),
            headers=intruder,
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )
    validate_error(
        api_client.take_room_out_of_service(
            room["id"],
            factories.out_of_service_payload(service_note="not my room"),
            headers=intruder,
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )

    assert fixtures.read_testing_room(room["id"])["status"] == RoomStatus.ACTIVE

    _rooms, room_meta = validate_paginated(
        api_client.list_testing_rooms(
            headers=make_state_authority_headers(),
            params={"testing_center_id": first["id"], "limit": 10, "offset": 0},
        )
    )
    assert room_meta["total_count"] == 1

    _proctors, proctor_meta = validate_paginated(
        api_client.list_proctors(
            headers=make_state_authority_headers(),
            params={"testing_center_id": first["id"], "limit": 10, "offset": 0},
        )
    )
    assert proctor_meta["total_count"] == 0


def test_04_scope_on_a_sitting_is_derived_through_the_room_that_hosts_it():
    """"When `X-User-Role` is `CenterAdministrator`, `X-User-ID` is the `id` of the acting
    `TestingCenter`; ownership checks compare it to the testing centre in the path, or to the
    `testing_center_id` of the addressed room, or to the `testing_center_id` of the room that
    hosts the addressed session or registration."

    Design: Corner/rbac/center_administrator_cannot_act_outside_its_own_center
    """
    first, second, room = _two_authorized_centers()

    validate_error(
        _open_a_sitting(room["id"], make_center_administrator_headers(second["id"])),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )

    owned = validate_success(
        _open_a_sitting(room["id"], make_center_administrator_headers(first["id"])),
        expected_status=201,
    )
    assert owned["status"] == SessionStatus.DRAFT
    assert owned["testing_room_id"] == room["id"]


def test_05_a_learner_reads_their_own_file_and_nobody_elses():
    """"When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`;
    ownership checks compare it to the addressed student's `id`, or to the `student_id` of the
    addressed enrollment, test event, registration, accommodation request, credential or
    transcript order."

    Design: Corner/rbac/student_cannot_read_another_students_records
    """
    owner = fixtures.create_student(
        full_name="Dara Quinn", email="dara.quinn@example.org", primary_track=ProgramTrack.ESL
    )
    stranger = fixtures.create_student(
        full_name="Elan Reyes", email="elan.reyes@example.org", primary_track=ProgramTrack.ESL
    )
    request = validate_success(
        api_client.create_accommodation_request(
            factories.create_accommodation_request_payload(
                owner["id"],
                requested_format=TestFormat.LARGE_PRINT,
                documentation_ref="doc-dara-1",
            ),
            headers=make_registrar_headers(),
        ),
        expected_status=201,
    )

    stranger_headers = make_student_headers(stranger["id"])
    validate_error(
        api_client.get_student(owner["id"], headers=stranger_headers),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )
    validate_error(
        api_client.get_accommodation_request(request["id"], headers=stranger_headers),
        ApiErrorId.FORBIDDEN_SCOPE,
        expected_status=403,
    )

    owner_headers = make_student_headers(owner["id"])
    assert fixtures.read_student(owner["id"], headers=owner_headers)["id"] == owner["id"]
    own_request = fixtures.read_accommodation(request["id"], headers=owner_headers)
    assert own_request["id"] == request["id"]
    assert own_request["status"] == AccommodationStatus.SUBMITTED

    staff_view = fixtures.read_accommodation(request["id"], headers=make_registrar_headers())
    assert staff_view["id"] == request["id"]


def test_06_only_the_assigned_proctor_may_sign_off_a_candidates_identity():
    """"When `X-User-Role` is `Proctor`, `X-User-ID` is the `id` of the acting `Proctor`;
    ownership checks compare it to the `proctor_id` of the exam session that hosts the addressed
    registration."

    Design: Corner/rbac/proctor_cannot_verify_identity_on_another_proctors_session
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Two Proctor Center", state_code="ND"
    )
    room = fixtures.create_room(center["id"], room_code="TWOP-1", seat_capacity=10)
    assigned = fixtures.create_certified_proctor(
        center["id"], certification_expires_at=USABLE_EXPIRY, full_name="Pia One"
    )
    unassigned = fixtures.create_certified_proctor(
        center["id"], certification_expires_at=USABLE_EXPIRY, full_name="Pat Two"
    )
    session = fixtures.create_session(
        center["id"], room["id"], SCOPE_SITTING[0], SCOPE_SITTING[1],
        requested_seats=SCOPE_SEATS,
    )
    fixtures.assign_session_proctor(center["id"], session["id"], assigned["id"])

    placed = fixtures.create_placed_student(
        scale_score=227,
        test_form=TestForm.CASAS_M_900,
        pre_test_at=PRE_TEST_AT,
        full_name="Yara Cruz",
        email="yara.cruz@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    registration = fixtures.register_candidate(placed["student_id"], session["id"])

    def _verify(proctor_id):
        return api_client.verify_identity(
            registration["id"],
            factories.identity_verification_payload(),
            headers=make_proctor_headers(proctor_id),
        )

    validate_error(
        _verify(unassigned["id"]), ApiErrorId.FORBIDDEN_SCOPE, expected_status=403
    )
    untouched = fixtures.read_registration(registration["id"])
    assert untouched["identity_status"] == IdentityStatus.UNVERIFIED
    assert untouched["identity_verified_by_proctor_id"] is None

    verified = validate_success(_verify(assigned["id"]))
    assert verified["identity_status"] == IdentityStatus.VERIFIED
    assert verified["identity_verified_by_proctor_id"] == assigned["id"]


def test_07_the_operator_who_claimed_an_outcome_may_neither_bless_nor_bin_it():
    """"The `X-User-ID` that creates an outcome record is stored as `recorded_by_user_id`; the
    `X-User-ID` that later decides it is stored as `certified_by_user_id`. When those two values
    would be equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (403), regardless of
    whether the decision was a certification or a rejection, and regardless of which of the two
    roles permitted to decide is acting."

    Design: Corner/rbac/the_same_user_must_not_record_and_certify_one_outcome
    """
    period = validate_success(
        api_client.create_funding_period(
            factories.create_funding_period_payload(**SOD_PERIOD),
            headers=make_state_authority_headers(OPENING_AUTHORITY),
        ),
        expected_status=201,
    )
    recorder = make_program_coordinator_headers(RECORDING_COORDINATOR)
    student = validate_success(
        api_client.create_student(
            factories.create_student_payload(
                full_name="Gus Halden",
                email="gus.halden@example.org",
                primary_track=ProgramTrack.HSE_PREP,
            ),
            headers=recorder,
        ),
        expected_status=201,
    )
    claim = fixtures.record_outcome(
        student["id"], period["id"], evidence_ref="ev-gus-q2", headers=recorder
    )
    assert claim["recorded_by_user_id"] == RECORDING_COORDINATOR

    def _decide(decision, headers):
        return api_client.decide_outcome_certification(
            claim["id"], factories.outcome_certification_payload(decision), headers=headers
        )

    validate_error(
        _decide(OutcomeDecision.CERTIFY, recorder),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    validate_error(
        _decide(OutcomeDecision.REJECT, recorder),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    assert fixtures.read_outcome(claim["id"])["status"] == OutcomeStatus.RECORDED

    decided = validate_success(
        _decide(
            OutcomeDecision.CERTIFY,
            make_program_coordinator_headers(DECIDING_COORDINATOR),
        )
    )
    assert decided["status"] == OutcomeStatus.CERTIFIED
    assert decided["certified_by_user_id"] == DECIDING_COORDINATOR


def test_08_a_missing_identity_header_answers_before_every_later_defect():
    """"Every request, without exception, must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the capacity that user is acting in. When either
    header is absent, or when `X-User-Role` holds a value that is not one of the seven declared
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/requests_missing_auth_headers_are_unauthenticated_before_any_other_check
    """
    unknown_read = api_client.get_student(
        UNKNOWN_ID, headers=_headers_without_user_id(Role.REGISTRAR)
    )
    validate_error(unknown_read, ApiErrorId.UNAUTHENTICATED, expected_status=401)
    assert unknown_read.json()["data"]["error_id"] != ApiErrorId.STUDENT_NOT_FOUND

    out_of_role_write = api_client.create_student(
        factories.create_student_payload(
            full_name="Ghost User",
            email="ghost@example.org",
            primary_track=ProgramTrack.HSE_PREP,
        ),
        headers=_headers_without_user_id(Role.INSTRUCTOR),
    )
    validate_error(out_of_role_write, ApiErrorId.UNAUTHENTICATED, expected_status=401)
    assert out_of_role_write.json()["data"]["error_id"] != ApiErrorId.UNAUTHORIZED

    malformed_write = api_client.create_class_section(
        {"program_track": "NOT_A_TRACK", "title": "Bad Body"},
        headers=_headers_without_user_id(Role.PROGRAM_COORDINATOR),
    )
    validate_error(malformed_write, ApiErrorId.UNAUTHENTICATED, expected_status=401)
    assert malformed_write.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST

    bad_window = api_client.list_students(
        headers=_headers_without_user_id(Role.REGISTRAR), params={"limit": 0, "offset": 0}
    )
    validate_error(bad_window, ApiErrorId.UNAUTHENTICATED, expected_status=401)
    assert bad_window.json()["data"]["error_id"] != ApiErrorId.INVALID_PAGINATION

    _rows, meta = validate_paginated(
        api_client.list_students(
            headers=make_registrar_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
