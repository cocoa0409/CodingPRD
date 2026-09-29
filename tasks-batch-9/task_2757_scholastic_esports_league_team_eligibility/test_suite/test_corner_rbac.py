"""Breadth tests for the ``rbac`` design section.

The four access rungs of PRD §2.7 — authentication (1), authorization (2),
ownership (3) — plus the two-person rule of §2.1 and the per-endpoint read
scoping tabulated in §4.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    ELIGIBILITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID,
    LEAGUE_ADMIN_ID,
    eligibility_officer_headers,
    headers_for_role,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
    make_district_admin_headers,
    recruiter_headers,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _forbidden(response, error_id=ApiErrorId.ERR_UNAUTHORIZED):
    """A 403 whose body carries only the two error keys (PRD §2.2)."""
    validate_error(response, error_id.value, 403)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    return body["data"]["error_id"]


def _build_one_of_every_entity(api):
    """A district, school, certified coach, approved title, DRAFT season, DRAFT
    team, student, unverified slot and one REPORTED fair-play case."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    approval = fx.approve_title_for_district(
        api, district["id"], title["id"], school["id"]
    )
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    student = fx.make_student(api, school["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    case = fx.open_student_case(api, team["id"], student["id"])
    return {
        "district": district,
        "school": school,
        "coach": coach,
        "title": title,
        "approval": approval,
        "season": season,
        "team": team,
        "student": student,
        "slot": slot,
        "case": case,
    }


# ==========================================================================
# Instance: each_roles_exclusive_operation_is_refused_to_every_other_role
# ==========================================================================
def test_one_exclusive_operation_per_role_is_refused_to_an_unlisted_role(api):
    """The role rung fires before ownership and before every state check, and
    LeagueAdmin is not a superuser.

    PRD §2.7 rung 2: "**Authorization.** The acting role appears in the target
    operation's role list — otherwise `ERR_UNAUTHORIZED`."  Rung 3:
    "**Ownership.** An entity-backed role acts only on its own resources —
    otherwise `ERR_NOT_RESOURCE_OWNER`."  And: "The ladder is evaluated strictly
    in the order below; a rung is only reached when every earlier rung passed."
    PRD §4 tabulates each operation's authorized roles: season advance
    `LeagueAdmin`; the approval decision `DistrictAdmin`; team withdraw
    `AthleticDirector`; team register `Coach`; enrollment verification
    `EligibilityOfficer`; case investigation `IntegrityOfficer`; recruiting
    contacts `Recruiter`; the clock `LeagueAdmin`.

    Design: Corner/rbac/each_roles_exclusive_operation_is_refused_to_every_other_role
    """
    world = _build_one_of_every_entity(api)
    coach_id = world["coach"]["id"]
    school_id = world["school"]["id"]

    refusals = [
        _forbidden(
            api.advance_season(
                world["season"]["id"],
                {"to_status": "REGISTRATION_OPEN"},
                make_district_admin_headers(world["district"]["id"]),
            )
        ),
        _forbidden(
            api.decide_title_approval(
                world["approval"]["id"],
                {"action": "REVOKE"},
                make_athletic_director_headers(school_id),
            )
        ),
        _forbidden(
            api.withdraw_team(
                world["team"]["id"],
                {"withdrawal_note": "not going ahead"},
                make_coach_headers(coach_id),
            )
        ),
        _forbidden(
            api.register_team(world["team"]["id"], {}, make_athletic_director_headers(school_id))
        ),
        _forbidden(
            api.verify_enrollment(
                world["slot"]["id"],
                {
                    "enrollment_document_ref": "REG-0001",
                    "verified_birthdate": world["student"]["birthdate"],
                },
                make_coach_headers(coach_id),
            )
        ),
        _forbidden(
            api.investigate_case(
                world["case"]["id"],
                {"investigation_note": "let me look"},
                make_coach_headers(coach_id),
            )
        ),
        _forbidden(
            api.log_recruiting_contact(
                world["student"]["id"],
                {
                    "org_code": "STATE-U",
                    "channel": "EMAIL",
                    "purpose": "camp invitation",
                },
                league_admin_headers(),
            )
        ),
        _forbidden(
            api.set_clock(
                "2026-09-01T00:00:00.000Z",
                integrity_officer_headers(INTEGRITY_OFFICER_ID),
            )
        ),
    ]
    assert refusals == [ApiErrorId.ERR_UNAUTHORIZED.value] * 8

    assert fx.get_season(api, world["season"]["id"])["status"] == "DRAFT"
    assert fx.get_title_approval(api, world["approval"]["id"])["status"] == "APPROVED"
    team = fx.get_team(api, world["team"]["id"])
    assert team["status"] == "DRAFT"
    assert team["registered_at"] is None
    A.assert_slot_axes(
        fx.get_slot(api, world["slot"]["id"]), verification_status="UNVERIFIED"
    )
    case = fx.get_case(api, world["case"]["id"])
    assert case["status"] == "REPORTED"
    assert case["investigator_user_id"] is None
    assert fx.get_student(api, world["student"]["id"])["recruiting_contact_log"] == []

    witness = fx.make_district(api)
    assert witness["created_at"] == "2026-08-01T00:00:00.000Z"


# ==========================================================================
# Instance: every_shared_operation_accepts_each_of_its_declared_roles
# ==========================================================================
def test_every_multi_role_operation_succeeds_from_its_non_primary_role(api):
    """Each shared endpoint is driven by its second declared role, with the same
    effects, and the actor is captured from the header.

    PRD §4 lists more than one role for each of these operations — school
    registration (`LeagueAdmin`, `DistrictAdmin`), coach designation
    (`LeagueAdmin`, `AthleticDirector`), certification (`AthleticDirector`,
    `LeagueAdmin`), student enrolment (`LeagueAdmin`, `AthleticDirector`,
    `EligibilityOfficer`), academic postings (`EligibilityOfficer`,
    `LeagueAdmin`), approval requests (`AthleticDirector`, `LeagueAdmin`), team
    creation (`Coach`, `AthleticDirector`) and case opening (`IntegrityOfficer`,
    `LeagueAdmin`, `Coach`).  PRD §3.8: "A new case opens in `REPORTED` with
    `reported_by_user_id` taken from `X-User-ID`".  PRD §2.1: "When
    `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier
    not tied to any persisted entity."

    Design: Corner/rbac/every_shared_operation_accepts_each_of_its_declared_roles
    """
    district = fx.make_district(api)
    district_admin = make_district_admin_headers(district["id"])

    school_response = api.create_school(
        {"district_id": district["id"], "name": "North High", "nces_code": "NCES-001"},
        district_admin,
    )
    validate_success(school_response, 201)
    school = A.data_of(school_response, 201)
    director = make_athletic_director_headers(school["id"])

    coach_response = api.create_coach(
        {"school_id": school["id"], "full_name": "Dana Reed", "email": "dana@north.k12"},
        director,
    )
    validate_success(coach_response, 201)
    coach = A.data_of(coach_response, 201)

    certification = api.certify_coach(
        coach["id"],
        {"action": "CERTIFY", "background_check_expires_on": "2027-06-30"},
        league_admin_headers(),
    )
    validate_success(certification)
    assert A.data_of(certification)["certification_status"] == "CERTIFIED"

    first_student_response = api.create_student(
        {
            "school_id": school["id"],
            "full_name": "Ada Lin",
            "birthdate": "2009-05-10",
            "grade_level": 11,
        },
        director,
    )
    validate_success(first_student_response, 201)
    first_student = A.data_of(first_student_response, 201)

    second_student_response = api.create_student(
        {
            "school_id": school["id"],
            "full_name": "Beau Ng",
            "birthdate": "2009-06-11",
            "grade_level": 11,
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_success(second_student_response, 201)
    second_student = A.data_of(second_student_response, 201)

    posting = api.post_academic_term(
        first_student["id"],
        {
            "term_label": "2026-FALL",
            "term_gpa": 3.200,
            "term_credits": 6.0,
            "expected_student_version": first_student["version"],
        },
        league_admin_headers(),
    )
    validate_success(posting)
    posted = A.data_of(posting)
    A.assert_gpa(posted["latest_term_gpa"], 3.200)
    assert posted["academic_standing"] == "GOOD"

    title_response = api.create_title(
        {
            "name": "Rocket Clash",
            "publisher": "Astro Interactive",
            "age_rating": "E10",
            "min_player_age": 13,
        },
        league_admin_headers(),
    )
    validate_success(title_response, 201)
    title = A.data_of(title_response, 201)

    approval_response = api.create_title_approval(
        {
            "district_id": district["id"],
            "title_id": title["id"],
            "requested_by_school_id": school["id"],
        },
        league_admin_headers(),
    )
    validate_success(approval_response, 201)
    approval = A.data_of(approval_response, 201)

    decision = api.decide_title_approval(
        approval["id"], {"action": "APPROVE"}, district_admin
    )
    validate_success(decision)
    assert A.data_of(decision)["status"] == "APPROVED"

    season_response = api.create_season(
        {"title_id": title["id"], "name": "Fall 2026 Varsity"}, league_admin_headers()
    )
    validate_success(season_response, 201)
    season = A.data_of(season_response, 201)

    team_response = api.create_team(
        {
            "season_id": season["id"],
            "school_id": school["id"],
            "title_id": title["id"],
            "coach_id": coach["id"],
            "name": "North Alpha",
        },
        director,
    )
    validate_success(team_response, 201)
    team = A.data_of(team_response, 201)

    slot_response = api.create_roster_slot(
        {
            "team_id": team["id"],
            "student_id": first_student["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(coach["id"]),
    )
    validate_success(slot_response, 201)

    coach_case_response = api.create_fair_play_case(
        {
            "team_id": team["id"],
            "subject_type": "STUDENT",
            "case_type": "SMURFING",
            "evidence_ref": "EV-1",
            "subject_student_id": first_student["id"],
        },
        make_coach_headers(coach["id"]),
    )
    validate_success(coach_case_response, 201)
    coach_case = A.data_of(coach_case_response, 201)
    assert coach_case["reported_by_user_id"] == coach["id"]

    api.create_roster_slot(
        {
            "team_id": team["id"],
            "student_id": second_student["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(coach["id"]),
    )
    admin_case_response = api.create_fair_play_case(
        {
            "team_id": team["id"],
            "subject_type": "STUDENT",
            "case_type": "SMURFING",
            "evidence_ref": "EV-2",
            "subject_student_id": second_student["id"],
        },
        league_admin_headers(),
    )
    validate_success(admin_case_response, 201)
    assert A.data_of(admin_case_response, 201)["reported_by_user_id"] == LEAGUE_ADMIN_ID


# ==========================================================================
# Instance: a_missing_or_unrecognised_identity_header_is_unauthenticated_before_
#           anything_else
# ==========================================================================
def test_identity_is_checked_before_existence_authorization_and_ownership(api):
    """Both header halves are mandatory, and rung 1 answers even when the path id
    cannot resolve and the role would have been unauthorized anyway.

    PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies the
    acting user and `X-User-Role` declares the capacity in which that user is
    acting. If either header is absent, or if `X-User-Role` is not one of the
    seven role names declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is
    examined."  PRD §2.7 rung 1: "**Authentication.** Both headers present and
    `X-User-Role` one of the seven declared roles — otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/a_missing_or_unrecognised_identity_header_is_unauthenticated_before_anything_else
    """
    district = fx.make_district(api)
    unauthenticated = ApiErrorId.ERR_UNAUTHENTICATED.value

    validate_error(
        api.get_district(district["id"], {"X-User-ID": "someone"}),
        unauthenticated,
        401,
    )
    validate_error(
        api.get_district(district["id"], {"X-User-Role": "LeagueAdmin"}),
        unauthenticated,
        401,
    )
    validate_error(
        api.create_district(
            {"name": "Ghost District", "state_code": "CA"},
            headers_for_role("Superintendent", "ghost"),
        ),
        unauthenticated,
        401,
    )
    validate_error(
        api.get_team(MISSING_ID, headers_for_role("Superintendent", "ghost")),
        unauthenticated,
        401,
    )
    validate_error(
        api.register_team(MISSING_ID, {}, {"X-User-ID": "ghost"}),
        unauthenticated,
        401,
    )

    rows, meta = validate_paginated(api.list_districts(None, league_admin_headers()))
    assert [row["id"] for row in rows] == [district["id"]]
    assert meta["total_count"] == 1

    reachable = api.get_district(district["id"], recruiter_headers())
    validate_success(reachable)
    assert A.data_of(reachable)["id"] == district["id"]


# ==========================================================================
# Instance: entity_backed_roles_must_own_the_resource_they_act_on
# ==========================================================================
def _build_two_schools_with_a_foreign_coach_and_district(api):
    """One team owned by coach one of school one under district one, with a
    complete second district, school and coach standing by as the foreign actor."""
    district_one = fx.make_district(api)
    district_two = fx.make_district(api)
    school_one = fx.make_school(api, district_one["id"])
    school_two = fx.make_school(api, district_two["id"])
    coach_one = fx.make_certified_coach(api, school_one["id"])
    coach_two = fx.make_coach(api, school_two["id"])
    title = fx.make_title(api)
    approval = fx.approve_title_for_district(
        api, district_one["id"], title["id"], school_one["id"]
    )
    season = fx.make_season(api, title["id"])
    team = fx.make_team(
        api, season["id"], school_one["id"], title["id"], coach_one["id"]
    )
    student = fx.make_student(api, school_one["id"])
    return {
        "district_two": district_two,
        "school_one": school_one,
        "school_two": school_two,
        "coach_one": coach_one,
        "coach_two": coach_two,
        "approval": approval,
        "team": team,
        "student": student,
    }


def test_the_wrong_owner_in_the_right_role_is_a_distinct_403(api):
    """Ownership is reached through a different path for each entity-backed role,
    it precedes every state check, and the true owners still succeed.

    PRD §2.1: "An authenticated, authorized caller in an entity-backed role that
    reaches for a resource belonging to someone else is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This applies to team creation, team
    registration, roster lock, team withdrawal, roster-slot creation and release,
    match result reports, dispute filing, broadcast control, fair-play appeals,
    title-approval creation, title-approval decisions, and coach certification."
    And: "ownership checks compare the governing team's `coach_id` to
    `X-User-ID`, resolved through `RosterSlot.team_id`" for `Coach`, "the
    governing school foreign key (a team's `school_id`, for instance)" for
    `AthleticDirector`, and "the resource's district foreign-key field" for
    `DistrictAdmin`.

    Design: Corner/rbac/entity_backed_roles_must_own_the_resource_they_act_on
    """
    world = _build_two_schools_with_a_foreign_coach_and_district(api)
    foreign_coach = make_coach_headers(world["coach_two"]["id"])
    foreign_director = make_athletic_director_headers(world["school_two"]["id"])
    team_id = world["team"]["id"]

    refusals = [
        _forbidden(
            api.create_roster_slot(
                {
                    "team_id": team_id,
                    "student_id": world["student"]["id"],
                    "slot_role": "STARTER",
                },
                foreign_coach,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        ),
        _forbidden(
            api.register_team(team_id, {}, foreign_coach),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        ),
        _forbidden(
            api.withdraw_team(
                team_id, {"withdrawal_note": "not ours to withdraw"}, foreign_director
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        ),
        _forbidden(
            api.certify_coach(
                world["coach_one"]["id"], {"action": "SUSPEND"}, foreign_director
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        ),
        _forbidden(
            api.decide_title_approval(
                world["approval"]["id"],
                {"action": "REVOKE"},
                make_district_admin_headers(world["district_two"]["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        ),
    ]
    assert refusals == [ApiErrorId.ERR_NOT_RESOURCE_OWNER.value] * 5

    frozen_team = fx.get_team(api, team_id)
    assert frozen_team["status"] == "DRAFT"
    assert frozen_team["starter_slots_used"] == 0
    assert (
        fx.get_coach(api, world["coach_one"]["id"])["certification_status"]
        == "CERTIFIED"
    )
    assert fx.get_title_approval(api, world["approval"]["id"])["status"] == "APPROVED"

    owned_slot = api.create_roster_slot(
        {
            "team_id": team_id,
            "student_id": world["student"]["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(world["coach_one"]["id"]),
    )
    validate_success(owned_slot, 201)

    owned_suspension = api.certify_coach(
        world["coach_one"]["id"],
        {"action": "SUSPEND"},
        make_athletic_director_headers(world["school_one"]["id"]),
    )
    validate_success(owned_suspension)
    assert A.data_of(owned_suspension)["certification_status"] == "SUSPENDED"


# ==========================================================================
# Instance: the_two_person_rule_is_scoped_to_the_slot_not_to_the_officer_or_the_
#           team
# ==========================================================================
def _build_two_slots_enrolled_by_opposite_officers(api):
    """Two STARTER slots on one team, the first enrolled by officer one and the
    second by officer two, so each officer is blocked on exactly one slot."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slots = []
    for officer in (ELIGIBILITY_OFFICER_ID, ELIGIBILITY_OFFICER_ID_2):
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
        slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
        fx.verify_slot_enrollment(
            api, slot["id"], student["birthdate"], officer_id=officer
        )
        slots.append(slot)
    return {"team": team, "slots": slots}


def test_the_two_person_rule_is_per_slot_not_per_officer_or_per_team(api):
    """Each officer is locked out of exactly the slot they enrolled and free on
    the sibling slot, in both directions.

    PRD §2.1: "The officer who clears a slot's academics must not be the officer
    already recorded in that slot's `enrollment_verified_by_user_id`."  PRD §3.5:
    "The acting `X-User-ID` must differ from the slot's
    `enrollment_verified_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` —
    this is the two-person rule".  PRD §2.1 also fixes the comparison space: the
    officer identifier is "an opaque officer identifier not tied to any persisted
    entity ... and compares those recorded values against each other rather than
    against any entity's `id`."

    Design: Corner/rbac/the_two_person_rule_is_scoped_to_the_slot_not_to_the_officer_or_the_team
    """
    world = _build_two_slots_enrolled_by_opposite_officers(api)
    first_slot, second_slot = world["slots"]
    officer_one = eligibility_officer_headers(ELIGIBILITY_OFFICER_ID)
    officer_two = eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2)

    validate_error(
        api.verify_academics(first_slot["id"], {}, officer_one),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    first_cleared_response = api.verify_academics(first_slot["id"], {}, officer_two)
    validate_success(first_cleared_response)
    first_cleared = A.data_of(first_cleared_response)
    A.assert_slot_axes(first_cleared, academic_status="CLEARED")
    assert first_cleared["academics_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID_2

    validate_error(
        api.verify_academics(second_slot["id"], {}, officer_two),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    second_cleared_response = api.verify_academics(second_slot["id"], {}, officer_one)
    validate_success(second_cleared_response)
    second_cleared = A.data_of(second_cleared_response)
    A.assert_slot_axes(second_cleared, academic_status="CLEARED")
    assert second_cleared["academics_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID

    for slot in (first_slot, second_slot):
        A.assert_slot_axes(
            fx.get_slot(api, slot["id"]), participation_status="ACTIVE"
        )
    assert fx.get_team(api, world["team"]["id"])["active_starter_count"] == 2

    first_read = fx.get_slot(api, first_slot["id"])
    second_read = fx.get_slot(api, second_slot["id"])
    assert (
        first_read["enrollment_verified_by_user_id"],
        first_read["academics_verified_by_user_id"],
    ) == (ELIGIBILITY_OFFICER_ID, ELIGIBILITY_OFFICER_ID_2)
    assert (
        second_read["enrollment_verified_by_user_id"],
        second_read["academics_verified_by_user_id"],
    ) == (ELIGIBILITY_OFFICER_ID_2, ELIGIBILITY_OFFICER_ID)


# ==========================================================================
# Instance: read_access_is_role_scoped_so_a_recruiter_sees_pathway_data_but_not_
#           competition_integrity_data
# ==========================================================================
def test_read_access_is_scoped_per_endpoint_rather_than_by_a_single_tier(api):
    """The Recruiter reads the recruiting pathway and nothing of the competition
    internals, and the eligibility desk cannot read title approvals.

    PRD §4 gives each read its own role list: `GET /titles/{titleId}`,
    `GET /roster-slots`, `GET /matches`, `GET /fair-play-cases/{caseId}` and
    `GET /coaches/{coachId}` omit `Recruiter`, while `GET /students/{studentId}`,
    `GET /teams/{teamId}`, `GET /seasons/{seasonId}` and `GET /schools/{schoolId}`
    include it; `GET /title-approvals/{approvalId}` is limited to `LeagueAdmin`,
    `DistrictAdmin`, `AthleticDirector` and `Coach`.  PRD §2.7 rung 2:
    "**Authorization.** The acting role appears in the target operation's role
    list — otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/read_access_is_role_scoped_so_a_recruiter_sees_pathway_data_but_not_competition_integrity_data
    """
    world = _build_one_of_every_entity(api)
    recruiter = recruiter_headers()
    before = {
        "district": fx.get_district(api, world["district"]["id"]),
        "school": fx.get_school(api, world["school"]["id"]),
        "coach": fx.get_coach(api, world["coach"]["id"]),
        "title": fx.get_title(api, world["title"]["id"]),
        "approval": fx.get_title_approval(api, world["approval"]["id"]),
        "season": fx.get_season(api, world["season"]["id"]),
        "team": fx.get_team(api, world["team"]["id"]),
        "student": fx.get_student(api, world["student"]["id"]),
        "slot": fx.get_slot(api, world["slot"]["id"]),
        "case": fx.get_case(api, world["case"]["id"]),
    }

    refusals = [
        _forbidden(api.get_title(world["title"]["id"], recruiter)),
        _forbidden(api.list_roster_slots({"team_id": world["team"]["id"]}, recruiter)),
        _forbidden(api.list_matches({"season_id": world["season"]["id"]}, recruiter)),
        _forbidden(api.get_fair_play_case(world["case"]["id"], recruiter)),
        _forbidden(api.get_coach(world["coach"]["id"], recruiter)),
        _forbidden(
            api.get_title_approval(
                world["approval"]["id"],
                eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
            )
        ),
    ]
    assert refusals == [ApiErrorId.ERR_UNAUTHORIZED.value] * 6

    for response, expected_id in (
        (api.get_student(world["student"]["id"], recruiter), world["student"]["id"]),
        (api.get_team(world["team"]["id"], recruiter), world["team"]["id"]),
        (api.get_season(world["season"]["id"], recruiter), world["season"]["id"]),
        (api.get_school(world["school"]["id"], recruiter), world["school"]["id"]),
    ):
        validate_success(response)
        assert A.data_of(response)["id"] == expected_id

    after = {
        "district": fx.get_district(api, world["district"]["id"]),
        "school": fx.get_school(api, world["school"]["id"]),
        "coach": fx.get_coach(api, world["coach"]["id"]),
        "title": fx.get_title(api, world["title"]["id"]),
        "approval": fx.get_title_approval(api, world["approval"]["id"]),
        "season": fx.get_season(api, world["season"]["id"]),
        "team": fx.get_team(api, world["team"]["id"]),
        "student": fx.get_student(api, world["student"]["id"]),
        "slot": fx.get_slot(api, world["slot"]["id"]),
        "case": fx.get_case(api, world["case"]["id"]),
    }
    for name, record in before.items():
        assert after[name]["version"] == record["version"], (
            f"{name} version moved during a read-only sequence"
        )
