"""Role-based access control, the identity mapping and the two write gates."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_participant,
    create_caregiver,
    create_confirmed_enrollment,
    create_fee_band,
    create_open_session,
    create_participant,
    create_period,
    create_staff,
    funding_source_payload,
    headers_without_role,
    headers_without_user_id,
    lock_staffing,
    make_activity_lead_headers,
    make_caregiver_headers,
    move_posture,
    participant_payload,
    propose_assignment,
    read_enrollment,
    read_session,
    request_enrollment,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD, OFFICER
from test_helpers.test_users import (
    TEST_USERS,
    make_funding_officer_headers,
    OFFICER_ONE_USER_ID,
)
from prd_bench_local_runner.testing import build_user_headers


def test_missing_or_unknown_role_headers_return_unauthenticated():
    """PRD §2.1: "A request missing or carrying an empty `X-User-Role` is rejected
    with `ERR_MISSING_ROLE_HEADER` (401); a request missing or carrying an empty
    `X-User-ID` is rejected with `ERR_MISSING_USER_ID_HEADER` (401); the role
    header is checked before the id header."
    PRD §2.1: "A role string that is not one of the six names below is rejected
    with `ERR_UNKNOWN_ROLE` (401), and a syntactically valid role that is not
    authorised for the endpoint being called is rejected with
    `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/missing_or_unknown_role_headers_return_unauthenticated
    """
    create_participant()

    validate_error(
        api_client.list_participants(headers_without_role()),
        ApiErrorId.ERR_MISSING_ROLE_HEADER.value,
        expected_status=401,
    )
    validate_error(
        api_client.list_participants(headers_without_user_id("IntakeCoordinator")),
        ApiErrorId.ERR_MISSING_USER_ID_HEADER.value,
        expected_status=401,
    )
    validate_error(
        api_client.list_participants(build_user_headers("someone", "SuperUser")),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
        expected_status=401,
    )


def test_program_admin_cannot_confirm_an_enrollment():
    """PRD §2.1: "A `ProgramAdmin` deliberately may not enrol a participant, sign
    a consent, or move a single cent."
    PRD §2.10 rung 4: "The named role appears in the called endpoint's
    authorised-role set — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/program_admin_cannot_confirm_an_enrollment
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    validate_error(
        api_client.confirm_enrollment(enrollment["id"], ADMIN, {}),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )

    assert read_enrollment(enrollment["id"])["enrollment_status"] == "REQUESTED"
    assert read_session(session["id"])["slots_committed"] == 0


def test_caregiver_cannot_withdraw_another_participants_enrollment():
    """PRD §2.1: "A `CaregiverUser` that reaches for a resource belonging to any
    participant other than the one named on its own caregiver row is rejected
    with `ERR_CAREGIVER_SCOPE_VIOLATION` (403)."
    PRD §2.10 rung 6: "A `CaregiverUser` touches only resources belonging to the
    participant named on its own caregiver row, on every endpoint called as
    `CaregiverUser` that names a participant, an enrolment, a consent or a goal —
    otherwise `ERR_CAREGIVER_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/caregiver_cannot_withdraw_another_participants_enrollment
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=3)
    own = create_active_participant()
    caregiver = create_caregiver(own["participant"]["id"])
    other = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    own_enrollment = request_enrollment(own["participant"]["id"], session["id"])
    other_enrollment = request_enrollment(other["participant"]["id"], session["id"])

    validate_error(
        api_client.withdraw_enrollment(
            other_enrollment["id"], make_caregiver_headers(caregiver["id"])
        ),
        ApiErrorId.ERR_CAREGIVER_SCOPE_VIOLATION.value,
        expected_status=403,
    )
    assert read_enrollment(other_enrollment["id"])["enrollment_status"] == "REQUESTED"

    withdrawn = validate_success(
        api_client.withdraw_enrollment(
            own_enrollment["id"], make_caregiver_headers(caregiver["id"])
        )
    )
    assert withdrawn["enrollment_status"] == "WITHDRAWN"


def test_unknown_lead_identity_and_unassigned_lead_are_both_refused():
    """PRD §2.1: "An entity-backed role whose `X-User-ID` does not resolve to an
    existing row — no such `StaffMember` for an `ActivityLead`, no such
    `Caregiver` for a `CaregiverUser` — is rejected with `ERR_IDENTITY_NOT_FOUND`
    (403)."
    PRD §2.1: "And an `ActivityLead` performing a delivery-time operation —
    delivering a session, recording attendance, checking equipment out, receiving
    equipment back, or recording a goal rating — must itself be staffed on that
    session: its `StaffMember` id must appear on a `StaffAssignment` for the
    session whose status is `PROPOSED`, `CONFIRMED` or `DELIVERED`, failing which
    the request is rejected with `ERR_STAFF_NOT_ASSIGNED_TO_SESSION` (403)."

    Design: Corner/rbac/unknown_lead_identity_not_found_and_unassigned_lead_cannot_record_attendance
    """
    create_fee_band()
    _program, session = create_open_session()
    assigned = create_staff(full_name="Dana Lead")["id"]
    bystander = create_staff(full_name="Eli Bystander", role_title="Program Aide")["id"]
    who = create_active_participant()
    enrollment = create_confirmed_enrollment(who["participant"]["id"], session["id"])
    propose_assignment(session["id"], assigned)
    lock_staffing(session["id"], assigned)
    set_clock("2026-06-10T15:00:00Z")

    validate_error(
        api_client.record_attendance(
            enrollment["id"], {"outcome": "ATTENDED"},
            TEST_USERS["activity_lead_unknown_headers"],
        ),
        ApiErrorId.ERR_IDENTITY_NOT_FOUND.value,
        expected_status=403,
    )

    validate_error(
        api_client.record_attendance(
            enrollment["id"], {"outcome": "ATTENDED"}, make_activity_lead_headers(bystander)
        ),
        ApiErrorId.ERR_STAFF_NOT_ASSIGNED_TO_SESSION.value,
        expected_status=403,
    )

    attended = validate_success(
        api_client.record_attendance(
            enrollment["id"], {"outcome": "ATTENDED"}, make_activity_lead_headers(assigned)
        )
    )
    assert attended["enrollment_status"] == "ATTENDED"


def test_frozen_period_blocks_every_write_while_restricted_blocks_only_money():
    """PRD §2.5: "**The global write gate.** When the current period's `status` is
    `FROZEN` or `CLOSED`, every mutating endpoint is rejected with
    `ERR_PERIOD_FROZEN` (409). Two mutating endpoints are exempt and continue to
    work: setting the logical clock, and moving a period along its own posture
    axis (`POST /recreation/operating-periods/{period_id}/posture`) — the second
    exemption exists so that a frozen period can always be thawed."
    PRD §2.5: "**The financial-write gate.** When the current period's `status` is
    `RESTRICTED` or `CLOSING`, ordinary programme work continues but seven
    financial endpoints are rejected with `ERR_PERIOD_RESTRICTED` (409): creating
    a funding source, closing a funding source, creating a scholarship award,
    encumbering an award, disbursing an award, releasing an award, and recording
    a family payment against an enrolment charge."
    PRD §2.4: "The value reported in `current_utc` is the string the caller
    supplied, unchanged; before the clock has ever been set it reads exactly
    `2026-05-01T00:00:00Z`."

    Design: Corner/errors/global_write_gate_freezes_everything_then_restricted_blocks_only_money
    """
    period = create_period()

    frozen = move_posture(period["id"], "FROZEN")
    assert frozen["status"] == "FROZEN"

    validate_error(
        api_client.create_participant(
            participant_payload(legal_name="Blocked Person", household_id="HH-9"), COORD
        ),
        ApiErrorId.ERR_PERIOD_FROZEN.value,
        expected_status=409,
    )

    swept = set_clock("2026-05-02T00:00:00Z")
    assert swept["current_utc"] == "2026-05-02T00:00:00Z", (
        "the clock endpoint is exempt from the global write gate"
    )

    move_posture(period["id"], "OPEN")
    restricted = move_posture(period["id"], "RESTRICTED")
    assert restricted["status"] == "RESTRICTED"

    validate_error(
        api_client.create_funding_source(
            funding_source_payload(
                period["id"], name="Blocked Fund", flat_award_cents=1000,
                total_budget_cents=1000,
            ),
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_PERIOD_RESTRICTED.value,
        expected_status=409,
    )

    allowed = validate_success(
        api_client.create_participant(
            participant_payload(legal_name="Allowed Person", household_id="HH-8"), COORD
        ),
        expected_status=201,
    )
    assert allowed["status"] == "INTAKE"
    assert validate_success(
        api_client.get_operating_period(period["id"], OFFICER)
    )["status"] == "RESTRICTED"
