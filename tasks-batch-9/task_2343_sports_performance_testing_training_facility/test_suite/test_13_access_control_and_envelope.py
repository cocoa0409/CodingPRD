"""Authentication, role authorisation, ownership scope, and the dedicated not-found codes."""
import pytest

from test_helpers import (
    build_user_headers,
    create_compliant_coach,
    create_staff_member_payload,
    fetch_athlete,
    make_athlete_headers,
    make_guardian_headers,
    register_athlete,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_ROLE_HEADERS = {"X-User-ID": "anonymous-1", "Content-Type": "application/json"}
UNRECOGNISED_ROLE_HEADERS = build_user_headers("mystery-1", "FacilityWizard")
UNKNOWN_ATHLETE_ID = "00000000-0000-4000-8000-0000000000ff"


def test_01_every_lookup_by_unknown_id_names_its_own_entity(
        api, performance_director_headers):
    """Thirteen reads against absent rows produce thirteen distinct codes.

    "Each identifier has its own dedicated code: `athlete_id` yields
    `ERR_ATHLETE_NOT_FOUND`, `injury_record_id` yields `ERR_INJURY_RECORD_NOT_FOUND`,
    `test_session_id` yields `ERR_TEST_SESSION_NOT_FOUND`, `training_program_id`
    yields `ERR_TRAINING_PROGRAM_NOT_FOUND`, `program_block_id` yields
    `ERR_PROGRAM_BLOCK_NOT_FOUND`, `group_session_id` yields
    `ERR_GROUP_SESSION_NOT_FOUND`, `enrollment_id` yields
    `ERR_ENROLLMENT_NOT_FOUND`, `staff_member_id` yields
    `ERR_STAFF_MEMBER_NOT_FOUND`, `certification_id` yields
    `ERR_CERTIFICATION_NOT_FOUND`, `membership_package_id` yields
    `ERR_MEMBERSHIP_PACKAGE_NOT_FOUND`, `team_contract_id` yields
    `ERR_TEAM_CONTRACT_NOT_FOUND`, `rts_plan_id` yields `ERR_RTS_PLAN_NOT_FOUND`, and
    `clearance_document_id` yields `ERR_CLEARANCE_DOCUMENT_NOT_FOUND`."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/every_entity_lookup_with_unknown_id_returns_its_own_not_found_error
    """
    lookups = [
        (api.get_athlete, "00000000-0000-4000-8000-000000000001",
         "ERR_ATHLETE_NOT_FOUND"),
        (api.get_injury_record, "00000000-0000-4000-8000-000000000002",
         "ERR_INJURY_RECORD_NOT_FOUND"),
        (api.get_test_session, "00000000-0000-4000-8000-000000000003",
         "ERR_TEST_SESSION_NOT_FOUND"),
        (api.get_training_program, "00000000-0000-4000-8000-000000000004",
         "ERR_TRAINING_PROGRAM_NOT_FOUND"),
        (api.get_program_block, "00000000-0000-4000-8000-000000000005",
         "ERR_PROGRAM_BLOCK_NOT_FOUND"),
        (api.get_group_session, "00000000-0000-4000-8000-000000000006",
         "ERR_GROUP_SESSION_NOT_FOUND"),
        (api.get_enrollment, "00000000-0000-4000-8000-000000000007",
         "ERR_ENROLLMENT_NOT_FOUND"),
        (api.get_staff_member, "00000000-0000-4000-8000-000000000008",
         "ERR_STAFF_MEMBER_NOT_FOUND"),
        (api.get_certification, "00000000-0000-4000-8000-000000000009",
         "ERR_CERTIFICATION_NOT_FOUND"),
        (api.get_membership_package, "00000000-0000-4000-8000-00000000000a",
         "ERR_MEMBERSHIP_PACKAGE_NOT_FOUND"),
        (api.get_team_contract, "00000000-0000-4000-8000-00000000000b",
         "ERR_TEAM_CONTRACT_NOT_FOUND"),
        (api.get_rts_plan, "00000000-0000-4000-8000-00000000000c",
         "ERR_RTS_PLAN_NOT_FOUND"),
        (api.get_clearance_document, "00000000-0000-4000-8000-00000000000d",
         "ERR_CLEARANCE_DOCUMENT_NOT_FOUND"),
    ]

    for read, unknown_id, expected_error in lookups:
        error = validate_error(read(unknown_id, performance_director_headers),
                              expected_error, expected_status=404)
        assert error["error_id"] == expected_error
        assert error["message"].strip() != ""


def test_02_only_the_performance_director_registers_staff_members(
        api, front_desk_headers, performance_director_headers):
    """Two other roles are refused, and a malformed body does not change the answer.

    "Each endpoint in §4 lists the roles permitted to invoke it; a caller whose role
    is absent from that list is rejected with `ERR_UNAUTHORIZED`."

    "**Authorization.** The caller's role is not among the endpoint's permitted roles →
    `ERR_UNAUTHORIZED`. Evaluated before any path identifier is resolved."

    "When one request violates two rules, the rule that appears earlier in the ladder
    produces the response and the later violation is never reported."

    Design: Corner/rbac/front_desk_cannot_create_staff_members
    """
    validate_error(
        api.create_staff_member(create_staff_member_payload(
            full_name="Should Not Exist", role_title="PERFORMANCE_COACH",
            liability_insurance_expires_on="2027-12-31"), front_desk_headers),
        "ERR_UNAUTHORIZED", expected_status=403)

    error = validate_error(
        api.create_staff_member({"full_name": "", "role_title": "SUPREME_LEADER",
                                 "liability_insurance_expires_on": "not-a-date"},
                                front_desk_headers),
        "ERR_UNAUTHORIZED", expected_status=403)
    assert error["error_id"] != "ERR_INVALID_REQUEST", \
        "the role check sits three rungs above schema validation"

    _rows, meta = validate_paginated(api.list_staff_members(
        performance_director_headers))
    assert meta["total_count"] == 0, "neither refused call registered anyone"

    coach, _cert, coach_headers = create_compliant_coach(full_name="Real Coach")

    validate_error(
        api.create_staff_member(create_staff_member_payload(
            full_name="Should Not Exist Either", role_title="PERFORMANCE_COACH",
            liability_insurance_expires_on="2027-12-31"), coach_headers),
        "ERR_UNAUTHORIZED", expected_status=403)

    rows, meta_after = validate_paginated(api.list_staff_members(
        performance_director_headers))
    assert meta_after["total_count"] == 1
    assert rows[0]["id"] == coach["id"], \
        "only the director's own registration survives"


def test_03_an_athlete_reads_only_their_own_progress_report(
        api, performance_director_headers):
    """The same endpoint answers for the caller's own id and refuses a peer's.

    "Ownership scoping for the two athlete-facing roles is enforced on exactly these
    operations: reading a single athlete, reading an athlete's progress report,
    creating an enrollment, cancelling an enrollment, reading a single test session,
    reading a single membership package, reading a single return-to-sport plan, and
    reading a single clearance document. A violation on any of them returns
    `ERR_ATHLETE_SCOPE_VIOLATION`."

    "The athlete's `last_composite_percentile`, or 50.0 when no battery has ever been
    finalized."

    Design: Corner/rbac/athlete_cannot_read_another_athletes_progress_report
    """
    reader = register_athlete(full_name="Self Reader", date_of_birth="2005-01-15")
    peer = register_athlete(full_name="Other Athlete", date_of_birth="2005-02-15")
    reader_headers = make_athlete_headers(reader["id"])

    validate_error(api.get_progress_report(peer["id"], reader_headers),
                   "ERR_ATHLETE_SCOPE_VIOLATION", expected_status=403)

    own = validate_success(api.get_progress_report(reader["id"], reader_headers))
    assert own["athlete_id"] == reader["id"]
    assert own["readiness_index"] == pytest.approx(50.00, abs=0.01)
    assert own["tests_included_count"] == 0
    assert own["composite_percentile_current"] is None

    for athlete in (reader, peer):
        by_director = validate_success(api.get_progress_report(
            athlete["id"], performance_director_headers))
        assert by_director["athlete_id"] == athlete["id"], \
            "the restriction belongs to the ownership-scoped roles alone"


def test_04_a_guardian_may_act_only_for_a_minor_with_a_contact_on_file(
        api, front_desk_headers):
    """The delegated grant depends on the athlete's age and guardian contact.

    "A `Guardian` call additionally requires that the target athlete's `age_years` is
    under 18 and that the athlete has a non-null `guardian_email` on file. A `Guardian`
    acting for an adult athlete, or for a minor with no guardian contact recorded, is
    therefore a scope violation rather than a plain authorization failure."

    Design: Corner/rbac/guardian_acting_for_an_adult_athlete_is_rejected
    """
    adult = validate_success(api.create_athlete(
        {"full_name": "Adult Athlete", "date_of_birth": "2005-01-15",
         "sport": "BASKETBALL", "position": "GUARD"}, front_desk_headers),
        expected_status=201)
    assert adult["age_years"] == 21
    assert adult["guardian_email"] is None
    minor = register_athlete(full_name="Minor Athlete",
                             date_of_birth="2012-01-15",
                             guardian_email="g.minor@example.com")
    assert minor["age_years"] < 18

    validate_error(api.get_athlete(adult["id"], make_guardian_headers(adult["id"])),
                   "ERR_ATHLETE_SCOPE_VIOLATION", expected_status=403)

    permitted = validate_success(api.get_athlete(
        minor["id"], make_guardian_headers(minor["id"])))

    assert permitted["id"] == minor["id"]
    assert permitted["guardian_email"] == "g.minor@example.com"
    assert fetch_athlete(adult["id"])["id"] == adult["id"], \
        "the refusal is about the acting role's grant, not about the row"


def test_05_a_request_without_a_role_header_never_reaches_any_other_check(api):
    """A malformed body and an unknown id are both invisible behind the missing header.

    "**Authentication.** A missing or unrecognised `X-User-Role` →
    `ERR_UNAUTHENTICATED`. Applies to every endpoint except the logical-clock advance."

    "Validation is a **single global ladder**, total and strictly ordered."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    write_error = validate_error(
        api.create_athlete({"full_name": "No Header Athlete",
                            "date_of_birth": "not-a-date", "sport": "QUIDDITCH",
                            "position": "SEEKER"}, NO_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED", expected_status=401)
    assert write_error["error_id"] != "ERR_INVALID_REQUEST", \
        "the malformed date and unknown enums are never evaluated"

    read_error = validate_error(
        api.get_athlete(UNKNOWN_ATHLETE_ID, NO_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED", expected_status=401)
    assert read_error["error_id"] != "ERR_ATHLETE_NOT_FOUND", \
        "the unknown identifier is never resolved"

    unrecognised = validate_error(
        api.get_athlete(UNKNOWN_ATHLETE_ID, UNRECOGNISED_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED", expected_status=401)
    assert unrecognised["error_id"] != "ERR_UNAUTHORIZED", \
        "an unknown role fails authentication rather than authorisation"
