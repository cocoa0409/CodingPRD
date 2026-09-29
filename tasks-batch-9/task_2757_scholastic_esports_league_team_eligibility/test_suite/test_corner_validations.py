"""Breadth tests for the ``validations`` design section.

Every test below translates exactly one non-stub instance of the breadth index.
The subjects are the field-level and cross-entity guards of PRD §2.7's global
rejection ladder: cross-field semantics on a single body, polymorphic
discriminators, the five differently-scoped uniqueness rules, the enrollment and
academics gate ladders, the two segregation-of-duties rules, the inclusive
temporal windows, the compound guards over children, and the satisfaction side
of the starter cap.
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
    INTEGRITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID_3,
    eligibility_officer_headers,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
    make_district_admin_headers,
    recruiter_headers,
)


def _count(response):
    """``total_count`` from a §2.5 paginated envelope."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# ==========================================================================
# Instance: probation_floor_above_min_gpa_is_rejected_and_equality_clears
# ==========================================================================
def test_an_inverted_threshold_pair_is_refused_but_equal_thresholds_clear(api):
    """Both numbers are in range, so this is a semantic pair check, not a shape
    check — and the comparison is "not greater than", so equality clears.

    PRD §2.7 rung 6: "**District GPA thresholds.** A district's
    `probation_gpa_floor` is not greater than its `min_gpa` — otherwise
    `ERR_INVALID_GPA_THRESHOLDS`. This rung applies only to district creation."
    PRD §3.1: "Two GPA thresholds follow: `min_gpa` ... defaulting to 2.000, and
    `probation_gpa_floor` ... defaulting to 1.750. Both live in the closed range
    0.000 through 4.000 with three decimals, and a district whose
    `probation_gpa_floor` is greater than its `min_gpa` is nonsensical and is
    refused with `ERR_INVALID_GPA_THRESHOLDS`."

    Design: Corner/validations/probation_floor_above_min_gpa_is_rejected_and_equality_clears
    """
    inverted = api.create_district(
        {
            "name": "Inverted District",
            "state_code": "NV",
            "min_gpa": 1.500,
            "probation_gpa_floor": 2.000,
        },
        league_admin_headers(),
    )
    validate_error(inverted, ApiErrorId.ERR_INVALID_GPA_THRESHOLDS.value, 422)
    assert _count(api.list_districts({}, league_admin_headers())) == 0

    equal = api.create_district(
        {
            "name": "Equal District",
            "state_code": "NV",
            "min_gpa": 2.000,
            "probation_gpa_floor": 2.000,
        },
        league_admin_headers(),
    )
    validate_success(equal, 201)
    district = A.data_of(equal, 201)
    A.assert_gpa(district["min_gpa"], 2.000)
    A.assert_gpa(district["probation_gpa_floor"], 2.000)
    assert _count(api.list_districts({}, league_admin_headers())) == 1


# ==========================================================================
# Instance: match_creation_rejects_a_self_match_and_a_cross_season_participant
# ==========================================================================
def _build_two_seasons_of_one_title(api):
    """Two seasons on the same title: teams A and B in the first, C in the
    second, so a cross-season pairing is available with every id resolvable."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api, server_pool_id="POOL-A", match_duration_minutes=60)
    season_one = fx.make_season(api, title["id"], name="Autumn One")
    season_two = fx.make_season(api, title["id"], name="Autumn Two")
    team_a = fx.make_team(
        api, season_one["id"], school["id"], title["id"], coach["id"], name="Alpha"
    )
    team_b = fx.make_team(
        api, season_one["id"], school["id"], title["id"], coach["id"], name="Bravo"
    )
    team_c = fx.make_team(
        api, season_two["id"], school["id"], title["id"], coach["id"], name="Charlie"
    )
    return {
        "season_one": season_one,
        "season_two": season_two,
        "team_a": team_a,
        "team_b": team_b,
        "team_c": team_c,
    }


def test_a_team_may_not_play_itself_nor_a_team_from_another_season(api):
    """Both defects resolve every identifier, so neither is a 404.

    PRD §2.7 rung 7: "**Distinct match participants.** A match's `home_team_id`
    differs from its `away_team_id` — otherwise `ERR_SELF_MATCH_FORBIDDEN`."
    Rung 39: "**Both participants belong to the match's season** — otherwise
    `ERR_TEAM_SEASON_MISMATCH`, on match scheduling."  PRD §3.7: "The server
    derives `scheduled_end_at` by adding the season's title's
    `match_duration_minutes` to `scheduled_start_at`, and copies that title's
    `server_pool_id` onto the match ... A newly scheduled match sits at
    `SCHEDULED`, `AWAITING_REPORTS`, `NONE` and `NONE` respectively."

    Design: Corner/validations/match_creation_rejects_a_self_match_and_a_cross_season_participant
    """
    world = _build_two_seasons_of_one_title(api)
    season_id = world["season_one"]["id"]

    self_match = api.create_match(
        {
            "season_id": season_id,
            "home_team_id": world["team_a"]["id"],
            "away_team_id": world["team_a"]["id"],
            "scheduled_start_at": "2026-10-01T18:00:00.000Z",
        },
        league_admin_headers(),
    )
    validate_error(self_match, ApiErrorId.ERR_SELF_MATCH_FORBIDDEN.value, 422)

    foreign = api.create_match(
        {
            "season_id": season_id,
            "home_team_id": world["team_a"]["id"],
            "away_team_id": world["team_c"]["id"],
            "scheduled_start_at": "2026-10-01T18:00:00.000Z",
        },
        league_admin_headers(),
    )
    validate_error(foreign, ApiErrorId.ERR_TEAM_SEASON_MISMATCH.value, 422)

    accepted = api.create_match(
        {
            "season_id": season_id,
            "home_team_id": world["team_a"]["id"],
            "away_team_id": world["team_b"]["id"],
            "scheduled_start_at": "2026-10-01T18:00:00.000Z",
        },
        league_admin_headers(),
    )
    validate_success(accepted, 201)
    match = A.data_of(accepted, 201)
    A.assert_match_state(
        match,
        play_status="SCHEDULED",
        result_status="AWAITING_REPORTS",
        dispute_status="NONE",
        broadcast_status="NONE",
    )
    assert match["server_pool_id"] == "POOL-A"
    assert match["scheduled_end_at"] == "2026-10-01T19:00:00.000Z"

    assert _count(api.list_matches({}, league_admin_headers())) == 1


# ==========================================================================
# Instance: fair_play_case_subject_reference_must_agree_with_the_declared_
#           subject_type
# ==========================================================================
def _build_docket_with_one_rostered_student(api):
    """Team A carries a slot for the first student; the second student holds no
    slot at all, and a match exists so a MATCH_BROADCAST id is available."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student_on = fx.make_student(api, school["id"], full_name="Ada Rostered")
    student_off = fx.make_student(api, school["id"], full_name="Beau Unrostered")
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="Bravo"
    )
    fx.add_slot(api, team_a["id"], student_on["id"], coach["id"], "STARTER")
    match = fx.schedule_match(
        api, season["id"], team_a["id"], team_b["id"], "2026-10-01T18:00:00.000Z"
    )
    return {
        "team_a": team_a,
        "student_on": student_on,
        "student_off": student_off,
        "match": match,
    }


def test_the_case_discriminator_is_checked_in_both_directions_before_membership(api):
    """A wrong-shaped subject pair outranks the subject-belongs-to-team check.

    PRD §2.7 rung 10: "On fair-play case creation, a `subject_type` of `STUDENT`
    requires `subject_student_id` present and `subject_match_id` absent, while a
    `subject_type` of `MATCH_BROADCAST` requires `subject_match_id` present and
    `subject_student_id` absent — otherwise `ERR_SUBJECT_REFERENCE_MISMATCH`."
    Rung 42: "**Case subject belongs to the charged team** — otherwise
    `ERR_SUBJECT_TEAM_MISMATCH`."  PRD §3.8: "The subject must also actually
    belong to the charged team: a named student must hold a non-released roster
    slot on that team ... A new case opens in `REPORTED` with
    `reported_by_user_id` taken from `X-User-ID`, `severity` null,
    `sanction_type` `NONE`, `severity_weight` 0, `applied_penalty` 0,
    `repeat_index` null".

    Design: Corner/validations/fair_play_case_subject_reference_must_agree_with_the_declared_subject_type
    """
    world = _build_docket_with_one_rostered_student(api)
    officer = integrity_officer_headers(INTEGRITY_OFFICER_ID)
    team_id = world["team_a"]["id"]

    student_with_match_id = api.create_fair_play_case(
        {
            "team_id": team_id,
            "subject_type": "STUDENT",
            "subject_match_id": world["match"]["id"],
            "case_type": "SMURFING",
            "evidence_ref": "vod-0001",
        },
        officer,
    )
    validate_error(
        student_with_match_id, ApiErrorId.ERR_SUBJECT_REFERENCE_MISMATCH.value, 422
    )

    broadcast_with_student_id = api.create_fair_play_case(
        {
            "team_id": team_id,
            "subject_type": "MATCH_BROADCAST",
            "subject_student_id": world["student_on"]["id"],
            "case_type": "SPECTATOR_CONDUCT",
            "evidence_ref": "clip-0001",
        },
        officer,
    )
    validate_error(
        broadcast_with_student_id, ApiErrorId.ERR_SUBJECT_REFERENCE_MISMATCH.value, 422
    )

    stranger = api.create_fair_play_case(
        {
            "team_id": team_id,
            "subject_type": "STUDENT",
            "subject_student_id": world["student_off"]["id"],
            "case_type": "ACCOUNT_SHARING",
            "evidence_ref": "log-0001",
        },
        officer,
    )
    validate_error(stranger, ApiErrorId.ERR_SUBJECT_TEAM_MISMATCH.value, 422)

    accepted = api.create_fair_play_case(
        {
            "team_id": team_id,
            "subject_type": "STUDENT",
            "subject_student_id": world["student_on"]["id"],
            "case_type": "ACCOUNT_SHARING",
            "evidence_ref": "log-0002",
        },
        officer,
    )
    validate_success(accepted, 201)
    case = A.data_of(accepted, 201)
    assert case["status"] == "REPORTED"
    assert case["severity"] is None
    assert case["severity_weight"] == 0
    assert case["repeat_index"] is None
    A.assert_integrity_score(case["applied_penalty"], 0.00)
    assert case["sanction_type"] == "NONE"
    assert case["reported_by_user_id"] == INTEGRITY_OFFICER_ID

    student = fx.get_student(api, world["student_on"]["id"])
    assert student["fair_play_status"] == "CLEAR"
    assert _count(api.list_fair_play_cases({}, league_admin_headers())) == 1


# ==========================================================================
# Instance: team_and_slot_creation_are_refused_when_the_related_entity_belongs_
#           elsewhere
# ==========================================================================
def _build_two_schools_two_titles_and_one_team(api):
    """One district, schools North and Valley with a certified coach each, two
    titles, a season on the first title, a student at each school, and a North
    team already in DRAFT."""
    district = fx.make_district(api)
    school_a = fx.make_school(api, district["id"], name="North High")
    school_b = fx.make_school(api, district["id"], name="Valley High")
    coach_a = fx.make_certified_coach(api, school_a["id"], full_name="Coach North")
    coach_b = fx.make_certified_coach(api, school_b["id"], full_name="Coach Valley")
    title_one = fx.make_title(api, name="Rocket Clash")
    title_two = fx.make_title(api, name="Tactics Prime")
    season = fx.make_season(api, title_one["id"])
    student_a = fx.make_student(api, school_a["id"], full_name="Ada North")
    student_b = fx.make_student(api, school_b["id"], full_name="Beau Valley")
    team_a = fx.make_team(
        api,
        season["id"],
        school_a["id"],
        title_one["id"],
        coach_a["id"],
        name="North Alpha",
    )
    return {
        "school_a": school_a,
        "coach_a": coach_a,
        "coach_b": coach_b,
        "title_one": title_one,
        "title_two": title_two,
        "season": season,
        "student_a": student_a,
        "student_b": student_b,
        "team_a": team_a,
    }


def test_three_cross_entity_agreements_each_raise_their_own_error_id(api):
    """Coach-school, team-title and student-school each have a distinct error.

    PRD §3.5: "Two referential agreements are checked at creation: the
    designated coach must belong to the same school as the team, otherwise
    `ERR_COACH_SCHOOL_MISMATCH`, and the team's `title_id` must be exactly the
    `title_id` of the season it is joining, otherwise `ERR_TEAM_TITLE_MISMATCH`."
    And on rostering: "The student must be enrolled at the same school as the
    team, otherwise `ERR_STUDENT_SCHOOL_MISMATCH`.  ... A fresh slot begins with
    `verification_status` `UNVERIFIED`, `academic_status` `PENDING`,
    `participation_status` `PROSPECTIVE`".

    Design: Corner/validations/team_and_slot_creation_are_refused_when_the_related_entity_belongs_elsewhere
    """
    world = _build_two_schools_two_titles_and_one_team(api)

    foreign_coach = api.create_team(
        {
            "season_id": world["season"]["id"],
            "school_id": world["school_a"]["id"],
            "title_id": world["title_one"]["id"],
            "coach_id": world["coach_b"]["id"],
            "name": "North Bravo",
        },
        make_coach_headers(world["coach_b"]["id"]),
    )
    validate_error(foreign_coach, ApiErrorId.ERR_COACH_SCHOOL_MISMATCH.value, 422)

    foreign_title = api.create_team(
        {
            "season_id": world["season"]["id"],
            "school_id": world["school_a"]["id"],
            "title_id": world["title_two"]["id"],
            "coach_id": world["coach_a"]["id"],
            "name": "North Charlie",
        },
        make_coach_headers(world["coach_a"]["id"]),
    )
    validate_error(foreign_title, ApiErrorId.ERR_TEAM_TITLE_MISMATCH.value, 422)

    foreign_student = api.create_roster_slot(
        {
            "team_id": world["team_a"]["id"],
            "student_id": world["student_b"]["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(world["coach_a"]["id"]),
    )
    validate_error(foreign_student, ApiErrorId.ERR_STUDENT_SCHOOL_MISMATCH.value, 422)

    accepted = api.create_roster_slot(
        {
            "team_id": world["team_a"]["id"],
            "student_id": world["student_a"]["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(world["coach_a"]["id"]),
    )
    validate_success(accepted, 201)
    A.assert_slot_axes(
        A.data_of(accepted, 201),
        verification_status="UNVERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )

    team = fx.get_team(api, world["team_a"]["id"])
    assert team["starter_slots_used"] == 1
    assert team["starter_slots_available"] == 2
    assert team["active_starter_count"] == 0

    assert _count(api.list_teams({}, league_admin_headers())) == 1
    assert _count(api.list_roster_slots({}, league_admin_headers())) == 1


# ==========================================================================
# Instance: every_uniqueness_constraint_is_enforced_inside_its_declared_scope_
#           only
# ==========================================================================
def _build_one_incumbent_of_every_uniqueness_scope(api):
    """One school code, one title name, one team name, one live approval and one
    live roster slot — each paired with an out-of-scope twin to come."""
    district_one = fx.make_district(api, name="North District")
    district_two = fx.make_district(api, name="Valley District")
    school = fx.make_school(api, district_one["id"], nces_code="NCES-001")
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api, name="Rocket Clash", publisher="Example Publisher")
    season_one = fx.make_season(api, title["id"], name="Autumn One")
    season_two = fx.make_season(api, title["id"], name="Autumn Two")
    approval = fx.request_title_approval(
        api, district_one["id"], title["id"], school["id"]
    )
    student = fx.make_student(api, school["id"])
    team = fx.make_team(
        api,
        season_one["id"],
        school["id"],
        title["id"],
        coach["id"],
        name="North Alpha",
    )
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    return {
        "district_one": district_one,
        "district_two": district_two,
        "school": school,
        "coach": coach,
        "title": title,
        "season_one": season_one,
        "season_two": season_two,
        "approval": approval,
        "student": student,
        "team": team,
        "slot": slot,
    }


def test_each_uniqueness_rule_binds_only_inside_its_own_declared_scope(api):
    """Five scopes, five twins: an over-broad index fails as loudly as none.

    PRD §3.1: an `nces_code` "must be unique among the schools of the same
    district; a collision is refused with `ERR_DUPLICATE_NCES_CODE`."  PRD §3.3:
    a title "carries a `name` ... that must be unique across the whole catalogue
    — a repeat is refused with `ERR_DUPLICATE_TITLE_NAME`"; and "At most one
    approval per district-and-title pair may sit in `PENDING` or `APPROVED` at a
    time; a second live request for the same pair is refused with
    `ERR_DUPLICATE_TITLE_APPROVAL`."  PRD §3.5: a team's name "must be unique
    among the teams of that same season — a collision is refused with
    `ERR_DUPLICATE_TEAM_NAME`"; and "The student must not already hold a slot on
    this team that has not been released, otherwise
    `ERR_DUPLICATE_ROSTER_SLOT`."

    Design: Corner/validations/every_uniqueness_constraint_is_enforced_inside_its_declared_scope_only
    """
    world = _build_one_incumbent_of_every_uniqueness_scope(api)
    coach_headers = make_coach_headers(world["coach"]["id"])

    same_district = api.create_school(
        {
            "district_id": world["district_one"]["id"],
            "name": "North Annex",
            "nces_code": "NCES-001",
        },
        league_admin_headers(),
    )
    validate_error(same_district, ApiErrorId.ERR_DUPLICATE_NCES_CODE.value, 409)

    other_district = api.create_school(
        {
            "district_id": world["district_two"]["id"],
            "name": "Valley Annex",
            "nces_code": "NCES-001",
        },
        league_admin_headers(),
    )
    validate_success(other_district, 201)

    repeated_title = api.create_title(
        {"name": "Rocket Clash", "publisher": "Other Publisher"},
        league_admin_headers(),
    )
    validate_error(repeated_title, ApiErrorId.ERR_DUPLICATE_TITLE_NAME.value, 409)

    same_season = api.create_team(
        {
            "season_id": world["season_one"]["id"],
            "school_id": world["school"]["id"],
            "title_id": world["title"]["id"],
            "coach_id": world["coach"]["id"],
            "name": "North Alpha",
        },
        coach_headers,
    )
    validate_error(same_season, ApiErrorId.ERR_DUPLICATE_TEAM_NAME.value, 409)

    other_season = api.create_team(
        {
            "season_id": world["season_two"]["id"],
            "school_id": world["school"]["id"],
            "title_id": world["title"]["id"],
            "coach_id": world["coach"]["id"],
            "name": "North Alpha",
        },
        coach_headers,
    )
    validate_success(other_season, 201)

    live_pair = api.create_title_approval(
        {
            "district_id": world["district_one"]["id"],
            "title_id": world["title"]["id"],
            "requested_by_school_id": world["school"]["id"],
        },
        make_athletic_director_headers(world["school"]["id"]),
    )
    validate_error(live_pair, ApiErrorId.ERR_DUPLICATE_TITLE_APPROVAL.value, 409)
    assert fx.get_title_approval(api, world["approval"]["id"])["status"] == "PENDING"

    duplicate_slot = api.create_roster_slot(
        {
            "team_id": world["team"]["id"],
            "student_id": world["student"]["id"],
            "slot_role": "SUB",
        },
        coach_headers,
    )
    validate_error(duplicate_slot, ApiErrorId.ERR_DUPLICATE_ROSTER_SLOT.value, 409)

    released = api.release_roster_slot(
        world["slot"]["id"], {"release_note": "moved to another title"}, coach_headers
    )
    validate_success(released)
    freed = A.data_of(released)
    A.assert_slot_axes(freed, participation_status="RELEASED")
    assert freed["released_at"] == "2026-08-01T00:00:00.000Z"

    emptied = fx.get_team(api, world["team"]["id"])
    assert emptied["starter_slots_used"] == 0
    assert emptied["starter_slots_available"] == 3

    reinstated = api.create_roster_slot(
        {
            "team_id": world["team"]["id"],
            "student_id": world["student"]["id"],
            "slot_role": "SUB",
        },
        coach_headers,
    )
    validate_success(reinstated, 201)

    unchanged = fx.get_team(api, world["team"]["id"])
    assert unchanged["starter_slots_used"] == 0
    assert unchanged["starter_slots_available"] == 3

    admin = league_admin_headers()
    assert _count(
        api.list_schools({"district_id": world["district_one"]["id"]}, admin)
    ) == 1
    assert _count(
        api.list_schools({"district_id": world["district_two"]["id"]}, admin)
    ) == 1


# ==========================================================================
# Instance: enrollment_verification_gate_ladder_refuses_each_precondition_in_
#           priority_order
# ==========================================================================
def _build_enrollment_gate_ladder(api):
    """North High is certified through 2027; Valley High's certification ran out
    the day before the clock's date.  North fields three starters: one whose
    document will disagree, one who is exactly 19 at the cutoff, and one clean."""
    district = fx.make_district(api)
    school_a = fx.make_school(api, district["id"], name="North High")
    school_b = fx.make_school(
        api,
        district["id"],
        name="Valley High",
        enrollment_verified_through="2026-07-31",
    )
    coach_a = fx.make_certified_coach(api, school_a["id"], full_name="Coach North")
    coach_b = fx.make_certified_coach(api, school_b["id"], full_name="Coach Valley")
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    withdrawn = fx.make_student(
        api,
        school_a["id"],
        full_name="Wanda Withdrawn",
        birthdate="2009-05-10",
        enrollment_status="WITHDRAWN",
    )
    lapsed = fx.make_student(
        api, school_b["id"], full_name="Lena Lapsed", birthdate="2009-05-10"
    )
    mismatched = fx.make_student(
        api, school_a["id"], full_name="Mona Document", birthdate="2009-05-10"
    )
    over_age = fx.make_student(
        api, school_a["id"], full_name="Oren Overage", birthdate="2007-08-31"
    )
    clean = fx.make_student(
        api, school_a["id"], full_name="Cleo Clean", birthdate="2009-05-10"
    )
    team_a = fx.make_team(
        api, season["id"], school_a["id"], title["id"], coach_a["id"], name="North Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school_b["id"], title["id"], coach_b["id"], name="Valley Alpha"
    )
    return {
        "coach_a": coach_a,
        "team_a": team_a,
        "withdrawn": withdrawn,
        "slot_lapsed": fx.add_slot(
            api, team_b["id"], lapsed["id"], coach_b["id"], "STARTER"
        ),
        "slot_mismatched": fx.add_slot(
            api, team_a["id"], mismatched["id"], coach_a["id"], "STARTER"
        ),
        "slot_over_age": fx.add_slot(
            api, team_a["id"], over_age["id"], coach_a["id"], "STARTER"
        ),
        "slot_clean": fx.add_slot(
            api, team_a["id"], clean["id"], coach_a["id"], "STARTER"
        ),
    }


def _verify(api, slot_id, verified_birthdate, document_ref):
    return api.verify_enrollment(
        slot_id,
        {
            "enrollment_document_ref": document_ref,
            "verified_birthdate": verified_birthdate,
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )


def test_the_document_check_runs_before_the_age_it_would_otherwise_derive(api):
    """A document birthdate of 2001-01-01 would read as 25 at the cutoff, so an
    implementation that ages first reports the wrong error.

    PRD §3.5: "The student's `enrollment_status` must be `ENROLLED`, otherwise
    `ERR_STUDENT_NOT_ENROLLED`. The supplied `verified_birthdate` must equal the
    student's `birthdate` exactly, otherwise `ERR_BIRTHDATE_DOCUMENT_MISMATCH`.
    The student's school must still have `enrollment_verified_through` on or
    after the logical clock's date, otherwise
    `ERR_ENROLLMENT_CERTIFICATION_LAPSED`. ... Finally the two age bounds are
    applied to `age_at_cutoff`, the number of completed years from the
    `verified_birthdate` to the season's `age_cutoff_date`: it must be at or
    above the title's `min_player_age`, otherwise
    `ERR_STUDENT_BELOW_TITLE_MIN_AGE`, and strictly below the season's
    `max_age`, otherwise `ERR_STUDENT_OVER_AGE_LIMIT`. The publisher floor is
    inclusive and the league ceiling is exclusive: a student whose age at the
    cutoff equals `max_age` is over-age."

    Design: Corner/validations/enrollment_verification_gate_ladder_refuses_each_precondition_in_priority_order
    """
    world = _build_enrollment_gate_ladder(api)

    withdrawn_slot = api.create_roster_slot(
        {
            "team_id": world["team_a"]["id"],
            "student_id": world["withdrawn"]["id"],
            "slot_role": "SUB",
        },
        make_coach_headers(world["coach_a"]["id"]),
    )
    validate_error(withdrawn_slot, ApiErrorId.ERR_STUDENT_NOT_ENROLLED.value, 422)
    assert _count(
        api.list_roster_slots(
            {"student_id": world["withdrawn"]["id"]}, league_admin_headers()
        )
    ) == 0

    lapsed = _verify(api, world["slot_lapsed"]["id"], "2009-05-10", "REG-2026-0001")
    validate_error(lapsed, ApiErrorId.ERR_ENROLLMENT_CERTIFICATION_LAPSED.value, 422)

    document = _verify(
        api, world["slot_mismatched"]["id"], "2001-01-01", "REG-2026-0002"
    )
    validate_error(document, ApiErrorId.ERR_BIRTHDATE_DOCUMENT_MISMATCH.value, 422)

    ceiling = _verify(api, world["slot_over_age"]["id"], "2007-08-31", "REG-2026-0003")
    validate_error(ceiling, ApiErrorId.ERR_STUDENT_OVER_AGE_LIMIT.value, 422)

    for untouched_id in (
        world["slot_mismatched"]["id"],
        world["slot_over_age"]["id"],
    ):
        untouched = fx.get_slot(api, untouched_id)
        A.assert_slot_axes(untouched, verification_status="UNVERIFIED")
        assert untouched["age_at_cutoff"] is None
        assert untouched["enrollment_verified_by_user_id"] is None

    accepted = _verify(api, world["slot_clean"]["id"], "2009-05-10", "REG-2026-0004")
    validate_success(accepted)
    slot = A.data_of(accepted)
    A.assert_slot_axes(
        slot,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )
    assert slot["age_at_cutoff"] == 17
    assert slot["enrollment_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID

    team = fx.get_team(api, world["team_a"]["id"])
    assert team["starter_slots_used"] == 3
    assert team["starter_slots_available"] == 0
    assert team["active_starter_count"] == 0


# ==========================================================================
# Instance: academic_verification_refuses_an_unposted_and_an_ineligible_
#           standing_and_clears_a_probation_sub
# ==========================================================================
def _build_four_enrollment_verified_slots(api):
    """Four slots past axis one: one student with no posted term, one at 1.500,
    one at 1.800 on a SUB seat, and one at 3.200 on a STARTER seat."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    unposted = fx.make_student(api, school["id"], full_name="Nora Unposted")
    ineligible = fx.make_student_with_term(
        api, school["id"], term_gpa=1.500, term_credits=6.0, full_name="Ida Ineligible"
    )
    probation = fx.make_student_with_term(
        api, school["id"], term_gpa=1.800, term_credits=6.0, full_name="Pia Probation"
    )
    good = fx.make_student_with_term(
        api, school["id"], term_gpa=3.200, term_credits=6.0, full_name="Gil Good"
    )
    slots = {}
    for key, student, role in (
        ("unposted", unposted, "STARTER"),
        ("ineligible", ineligible, "STARTER"),
        ("probation", probation, "SUB"),
        ("good", good, "STARTER"),
    ):
        slot = fx.add_slot(api, team["id"], student["id"], coach["id"], role)
        slots[key] = fx.verify_slot_enrollment(
            api, slot["id"], student["birthdate"], officer_id=ELIGIBILITY_OFFICER_ID
        )
    return {
        "team": team,
        "unposted": unposted,
        "good": good,
        "slots": slots,
    }


def test_one_error_id_covers_both_no_posted_term_and_a_sub_floor_average(api):
    """The PROBATION clearance on a SUB seat proves the starter restriction is
    role-conditional rather than a blanket ban.

    PRD §3.5 axis two: "The student must have at least one posted term, meaning
    `latest_term_gpa` is not null, otherwise
    `ERR_ACADEMIC_STANDING_INELIGIBLE`. The standing evaluation of §3.2 then runs
    afresh against the district's basis ... if it yields `INELIGIBLE`, the
    verification is refused with `ERR_ACADEMIC_STANDING_INELIGIBLE`. If it yields
    `PROBATION` and the slot's `slot_role` is `STARTER`, the verification is
    refused with `ERR_PROBATION_STARTER_RESTRICTED` — a student on probation may
    occupy a `SUB` slot but never a starting one. A `PROBATION` result on a `SUB`
    slot, and any `GOOD` result, clear the axis. ... On success the slot's
    `academic_status` moves `PENDING → CLEARED`, the slot snapshots
    `standing_at_verification` ... and `effective_gpa_at_verification` (three
    decimals)".

    Design: Corner/validations/academic_verification_refuses_an_unposted_and_an_ineligible_standing_and_clears_a_probation_sub
    """
    world = _build_four_enrollment_verified_slots(api)
    officer = eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2)

    unposted = api.verify_academics(world["slots"]["unposted"]["id"], {}, officer)
    validate_error(unposted, ApiErrorId.ERR_ACADEMIC_STANDING_INELIGIBLE.value, 422)
    assert (
        fx.get_student(api, world["unposted"]["id"])["academic_standing"]
        == "UNEVALUATED"
    )

    below_floor = api.verify_academics(world["slots"]["ineligible"]["id"], {}, officer)
    validate_error(below_floor, ApiErrorId.ERR_ACADEMIC_STANDING_INELIGIBLE.value, 422)
    refused = fx.get_slot(api, world["slots"]["ineligible"]["id"])
    A.assert_slot_axes(refused, academic_status="PENDING")
    assert refused["standing_at_verification"] is None

    sub = api.verify_academics(world["slots"]["probation"]["id"], {}, officer)
    validate_success(sub)
    cleared_sub = A.data_of(sub)
    A.assert_slot_axes(
        cleared_sub, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert cleared_sub["standing_at_verification"] == "PROBATION"
    A.assert_gpa(cleared_sub["effective_gpa_at_verification"], 1.800)

    starter = api.verify_academics(world["slots"]["good"]["id"], {}, officer)
    validate_success(starter)
    cleared_starter = A.data_of(starter)
    A.assert_slot_axes(
        cleared_starter, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert cleared_starter["standing_at_verification"] == "GOOD"
    A.assert_gpa(cleared_starter["effective_gpa_at_verification"], 3.200)
    assert cleared_starter["academics_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID_2

    student = fx.get_student(api, world["good"]["id"])
    assert student["academic_standing"] == "GOOD"
    assert student["standing_basis_applied"] == "TERM_SNAPSHOT"

    team = fx.get_team(api, world["team"]["id"])
    assert team["starter_slots_used"] == 3
    assert team["active_starter_count"] == 1


# ==========================================================================
# Instance: a_sanctioned_student_is_barred_from_slots_academics_and_the_
#           showcase_pathway
# ==========================================================================
def _build_one_sanctioned_and_one_clean_team_mate(api):
    """Two team-mates on North Alpha.  The first is sustained at MINOR for
    account sharing while his academics are still unverified; the second is fully
    cleared and stays untouched."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Bravo"
    )
    charged = fx.make_student_with_term(
        api, school["id"], term_gpa=3.200, term_credits=6.0, full_name="Xan Charged"
    )
    clean = fx.make_student_with_term(
        api, school["id"], term_gpa=3.200, term_credits=6.0, full_name="Yara Clean"
    )
    slot_x = fx.add_slot(api, team_a["id"], charged["id"], coach["id"], "STARTER")
    slot_y = fx.add_slot(api, team_a["id"], clean["id"], coach["id"], "STARTER")
    fx.verify_slot_enrollment(api, slot_x["id"], charged["birthdate"])
    fx.verify_slot_enrollment(api, slot_y["id"], clean["birthdate"])
    fx.verify_slot_academics(api, slot_y["id"], officer_id=ELIGIBILITY_OFFICER_ID_2)
    case = fx.open_student_case(
        api, team_a["id"], charged["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)
    case = fx.decide_case(
        api,
        case["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    return {
        "coach": coach,
        "team_a": team_a,
        "team_b": team_b,
        "charged": charged,
        "clean": clean,
        "slot_x": slot_x,
        "case": case,
    }


def test_the_sanction_flag_closes_three_endpoints_on_three_different_entities(api):
    """One flag on the student shuts rostering, academics and the showcase.

    PRD §2.7 rung 33: "**Student fair-play standing** is `CLEAR` — otherwise
    `ERR_STUDENT_FAIR_PLAY_SANCTIONED`. It guards three operations: roster-slot
    creation, academics verification and showcase nomination."  PRD §3.8: "Each
    case's `severity_weight` is the sum of two constants: a severity component
    worth 5 for `MINOR` ... and a case-type surcharge worth 5 for
    `ACCOUNT_SHARING` ... The repeat multiplier is 1.0 for the first case in the
    set ... Otherwise the selection is `STUDENT_SUSPENSION`."  And: "The third
    link, caused by the second, moves every roster slot of that student whose
    `participation_status` is `ACTIVE` to `INELIGIBLE`".

    Design: Corner/validations/a_sanctioned_student_is_barred_from_slots_academics_and_the_showcase_pathway
    """
    world = _build_one_sanctioned_and_one_clean_team_mate(api)
    case = world["case"]
    assert case["status"] == "SUSTAINED"
    assert case["severity_weight"] == 10
    assert case["repeat_index"] == 1
    A.assert_integrity_score(case["applied_penalty"], 10.00)
    assert case["sanction_type"] == "STUDENT_SUSPENSION"

    charged_team = fx.get_team(api, world["team_a"]["id"])
    A.assert_integrity_score(charged_team["integrity_score"], 90.00)
    assert charged_team["status"] == "DRAFT"

    assert fx.get_student(api, world["charged"]["id"])["fair_play_status"] == "SANCTIONED"
    assert fx.get_student(api, world["clean"]["id"])["fair_play_status"] == "CLEAR"

    prospective = fx.get_slot(api, world["slot_x"]["id"])
    A.assert_slot_axes(prospective, participation_status="PROSPECTIVE")
    assert prospective["ineligibility_reason"] is None

    new_slot = api.create_roster_slot(
        {
            "team_id": world["team_b"]["id"],
            "student_id": world["charged"]["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(world["coach"]["id"]),
    )
    validate_error(new_slot, ApiErrorId.ERR_STUDENT_FAIR_PLAY_SANCTIONED.value, 409)
    assert _count(
        api.list_roster_slots(
            {"team_id": world["team_b"]["id"]}, league_admin_headers()
        )
    ) == 0

    academics = api.verify_academics(
        world["slot_x"]["id"], {}, eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2)
    )
    validate_error(academics, ApiErrorId.ERR_STUDENT_FAIR_PLAY_SANCTIONED.value, 409)

    barred = api.nominate_showcase(
        world["charged"]["id"],
        {"nominating_team_id": world["team_a"]["id"]},
        league_admin_headers(),
    )
    validate_error(barred, ApiErrorId.ERR_STUDENT_FAIR_PLAY_SANCTIONED.value, 409)
    assert fx.get_student(api, world["charged"]["id"])["showcase_status"] == "NONE"

    nominated = api.nominate_showcase(
        world["clean"]["id"],
        {"nominating_team_id": world["team_a"]["id"]},
        league_admin_headers(),
    )
    validate_success(nominated)
    student = A.data_of(nominated)
    assert student["showcase_status"] == "NOMINATED"
    assert student["nominating_team_id"] == world["team_a"]["id"]


# ==========================================================================
# Instance: title_approval_ceiling_applies_only_to_the_approve_branch_and_only_
#           above_the_districts_rating
# ==========================================================================
def _build_one_m_rated_title_asked_of_two_districts(api):
    """The same `M`-rated title is pending in a district capped at the default
    `T` and in a district capped at `M`."""
    district_t = fx.make_district(api, name="Tee District")
    district_m = fx.make_district(api, name="Emm District", max_age_rating="M")
    school_t = fx.make_school(api, district_t["id"], name="North High")
    school_m = fx.make_school(api, district_m["id"], name="Mesa High")
    title = fx.make_title(api, name="Siege Protocol", age_rating="M")
    return {
        "district_t": district_t,
        "district_m": district_m,
        "approval_t": fx.request_title_approval(
            api, district_t["id"], title["id"], school_t["id"]
        ),
        "approval_m": fx.request_title_approval(
            api, district_m["id"], title["id"], school_m["id"]
        ),
    }


def test_the_rating_ceiling_blocks_an_approval_but_never_a_denial(api):
    """The ordinal comparison is scoped to the APPROVE branch alone.

    PRD §3.3: "An `action` of `APPROVE` moves a `PENDING` approval to `APPROVED`,
    but only if the title is permissible in that district: the title's
    `age_rating` must sit at or below the district's `max_age_rating` on the
    ordinal scale where `E` is 0, `E10` is 1, `T` is 2 and `M` is 3. A title
    rated above the district's ceiling — an `M`-rated title in a district capped
    at `T`, for example — is refused with
    `ERR_TITLE_AGE_RATING_EXCEEDS_DISTRICT_CEILING`. An `action` of `DENY` moves a
    `PENDING` approval to the terminal `DENIED` state and applies no rating test,
    since denial is always permissible. ... All three actions write
    `decided_by_user_id` from `X-User-ID` ... stamp `decided_at` from the logical
    clock, and advance the approval's `version` by one."

    Design: Corner/validations/title_approval_ceiling_applies_only_to_the_approve_branch_and_only_above_the_districts_rating
    """
    world = _build_one_m_rated_title_asked_of_two_districts(api)
    approval_t = world["approval_t"]

    above_ceiling = api.decide_title_approval(
        approval_t["id"],
        {"action": "APPROVE", "decision_note": "requested by North High"},
        make_district_admin_headers(world["district_t"]["id"]),
    )
    validate_error(
        above_ceiling,
        ApiErrorId.ERR_TITLE_AGE_RATING_EXCEEDS_DISTRICT_CEILING.value,
        422,
    )
    still_pending = fx.get_title_approval(api, approval_t["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["decided_by_user_id"] is None

    denied_response = api.decide_title_approval(
        approval_t["id"],
        {"action": "DENY", "decision_note": "rating above district policy"},
        make_district_admin_headers(world["district_t"]["id"]),
    )
    validate_success(denied_response)
    denied = A.data_of(denied_response)
    assert denied["status"] == "DENIED"
    assert denied["decided_by_user_id"] == world["district_t"]["id"]
    assert denied["decided_at"] == "2026-08-01T00:00:00.000Z"
    A.assert_version_advanced_by(approval_t, denied, 1)

    approved_response = api.decide_title_approval(
        world["approval_m"]["id"],
        {"action": "APPROVE", "decision_note": "within district policy"},
        make_district_admin_headers(world["district_m"]["id"]),
    )
    validate_success(approved_response)
    approved = A.data_of(approved_response)
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == world["district_m"]["id"]


# ==========================================================================
# Instance: showcase_and_recruiting_preconditions_are_enforced_in_their_
#           declared_order
# ==========================================================================
def _build_one_rostered_and_one_unrostered_prospect(api):
    """Ada holds a slot on North Alpha only; Beau holds none.  North Bravo exists
    so a nomination can name a team the student is not on."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Bravo"
    )
    on_team = fx.make_student(api, school["id"], full_name="Ada Rostered")
    off_team = fx.make_student(api, school["id"], full_name="Beau Unrostered")
    fx.add_slot(api, team_a["id"], on_team["id"], coach["id"], "STARTER")
    return {
        "team_a": team_a,
        "team_b": team_b,
        "on_team": on_team,
        "off_team": off_team,
    }


def test_a_contact_is_refused_until_the_nomination_and_leaves_the_log_empty(api):
    """The funnel is nomination-then-contact, and refusals are never logged.

    PRD §3.9: "Three conditions gate it: the student must hold a roster slot on
    that team that has not been released, otherwise `ERR_STUDENT_NOT_ON_TEAM`
    ... On acceptance `showcase_status` becomes `NOMINATED` and
    `nominating_team_id` is stored on the student."  And: "The student's
    `showcase_status` must be `NOMINATED`, otherwise
    `ERR_SHOWCASE_NOT_NOMINATED`. ... An accepted contact appends one entry to
    `recruiting_contact_log` holding `contacted_at` from the logical clock
    together with the supplied `org_code`, `channel` and `purpose` ... Refused
    attempts are never logged, so a rejected contact leaves the quota exactly
    where it was."  Step four of the projection "sets `scholarship_award_state`
    to `CURRENT`."

    Design: Corner/validations/showcase_and_recruiting_preconditions_are_enforced_in_their_declared_order
    """
    world = _build_one_rostered_and_one_unrostered_prospect(api)
    contact = {"org_code": "STATE-U", "channel": "EMAIL", "purpose": "camp invitation"}

    stranger = api.nominate_showcase(
        world["off_team"]["id"],
        {"nominating_team_id": world["team_a"]["id"]},
        league_admin_headers(),
    )
    validate_error(stranger, ApiErrorId.ERR_STUDENT_NOT_ON_TEAM.value, 422)

    wrong_team = api.nominate_showcase(
        world["on_team"]["id"],
        {"nominating_team_id": world["team_b"]["id"]},
        league_admin_headers(),
    )
    validate_error(wrong_team, ApiErrorId.ERR_STUDENT_NOT_ON_TEAM.value, 422)

    too_early = api.log_recruiting_contact(
        world["on_team"]["id"], dict(contact), recruiter_headers()
    )
    validate_error(too_early, ApiErrorId.ERR_SHOWCASE_NOT_NOMINATED.value, 409)
    assert fx.get_student(api, world["on_team"]["id"])["recruiting_contact_log"] == []

    nominated_response = api.nominate_showcase(
        world["on_team"]["id"],
        {"nominating_team_id": world["team_a"]["id"]},
        league_admin_headers(),
    )
    validate_success(nominated_response)
    nominated = A.data_of(nominated_response)
    assert nominated["showcase_status"] == "NOMINATED"
    assert nominated["nominating_team_id"] == world["team_a"]["id"]
    assert nominated["scholarship_award_state"] == "CURRENT"

    accepted = api.log_recruiting_contact(
        world["on_team"]["id"], dict(contact), recruiter_headers()
    )
    validate_success(accepted)
    log = A.data_of(accepted)["recruiting_contact_log"]
    assert len(log) == 1
    assert log[0]["contacted_at"] == "2026-08-01T00:00:00.000Z"
    assert log[0]["org_code"] == "STATE-U"
    assert log[0]["channel"] == "EMAIL"
    assert log[0]["purpose"] == "camp invitation"


# ==========================================================================
# Instance: registration_window_is_inclusive_at_both_bounds
# ==========================================================================
def _build_three_registerable_teams(api):
    """Three teams whose every register precondition but the clock is already
    satisfied, in a season whose window runs 2026-09-01 to 2026-09-10."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(
        api,
        title["id"],
        registration_opens_at="2026-09-01T00:00:00.000Z",
        registration_closes_at="2026-09-10T00:00:00.000Z",
    )
    teams = []
    for name in ("North Alpha", "North Bravo", "North Charlie"):
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=name
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        teams.append(team)
    season = fx.open_registration(api, season["id"])
    return {"district": district, "coach": coach, "season": season, "teams": teams}


def test_registration_opens_and_closes_on_the_millisecond(api):
    """One millisecond outside either bound is refused; both bounds themselves
    are inclusive.

    PRD §3.6: "The logical clock must fall at or after `registration_opens_at`
    and at or before `registration_closes_at`, both bounds inclusive, otherwise
    `ERR_REGISTRATION_WINDOW_CLOSED`. ... Once the fee is pinned, the district's
    `subsidy_pool_cents` is reduced by exactly the `subsidy_granted_cents` just
    awarded ... The team's `registered_at` is stamped from the logical clock, its
    status becomes `REGISTERED`, the season's `registered_team_count` is
    recomputed".  PRD §3.4: "`registered_team_count` begins at 0 and counts the
    season's teams whose status is anything other than `DRAFT` or `WITHDRAWN`."

    Design: Corner/validations/registration_window_is_inclusive_at_both_bounds
    """
    world = _build_three_registerable_teams(api)
    first, second, third = world["teams"]
    coach_headers = make_coach_headers(world["coach"]["id"])

    fx.set_clock(api, "2026-08-31T23:59:59.999Z")
    too_early = api.register_team(first["id"], {}, coach_headers)
    validate_error(too_early, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED.value, 409)
    assert fx.get_team(api, first["id"])["status"] == "DRAFT"

    fx.set_clock(api, "2026-09-01T00:00:00.000Z")
    on_open = api.register_team(first["id"], {}, coach_headers)
    validate_success(on_open)
    registered = A.data_of(on_open)
    assert registered["status"] == "REGISTERED"
    assert registered["registered_at"] == "2026-09-01T00:00:00.000Z"
    A.assert_cents(registered["entry_fee_cents"], 15845)
    A.assert_cents(registered["subsidy_granted_cents"], 3962)
    A.assert_cents(registered["net_fee_due_cents"], 11883)
    A.assert_cents(
        fx.get_district(api, world["district"]["id"])["subsidy_pool_cents"], 4996038
    )

    fx.set_clock(api, "2026-09-10T00:00:00.000Z")
    on_close = api.register_team(second["id"], {}, coach_headers)
    validate_success(on_close)
    assert A.data_of(on_close)["status"] == "REGISTERED"
    A.assert_cents(
        fx.get_district(api, world["district"]["id"])["subsidy_pool_cents"], 4992076
    )

    fx.set_clock(api, "2026-09-10T00:00:00.001Z")
    too_late = api.register_team(third["id"], {}, coach_headers)
    validate_error(too_late, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED.value, 409)
    assert fx.get_team(api, third["id"])["status"] == "DRAFT"

    assert fx.get_season(api, world["season"]["id"])["registered_team_count"] == 2


# ==========================================================================
# Instance: a_match_must_fit_entirely_between_roster_lock_and_the_regular_
#           season_end
# ==========================================================================
def _build_two_schedulable_teams(api):
    """Two teams in a season keeping every calendar default: roster lock
    2026-09-20 and regular-season end 2026-11-30, on a 60-minute title."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api, match_duration_minutes=60)
    season = fx.make_season(api, title["id"])
    return {
        "season": season,
        "team_a": fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name="Alpha"
        ),
        "team_b": fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name="Bravo"
        ),
    }


def _try_match(api, world, scheduled_start_at):
    return api.create_match(
        {
            "season_id": world["season"]["id"],
            "home_team_id": world["team_a"]["id"],
            "away_team_id": world["team_b"]["id"],
            "scheduled_start_at": scheduled_start_at,
        },
        league_admin_headers(),
    )


def test_the_window_test_is_asymmetric_start_inclusive_and_derived_end_inclusive(api):
    """The end that matters is the derived one, so the last legal start is one
    match duration before the season's end.

    PRD §3.7: "The match must fit inside the season's competitive calendar:
    `scheduled_start_at` must be at or after the season's `roster_lock_at`, and
    the derived end must be at or before the season's `regular_season_end_at`. A
    match falling outside that span is refused with
    `ERR_MATCH_OUTSIDE_SEASON_WINDOW`."  And: "The server derives
    `scheduled_end_at` by adding the season's title's `match_duration_minutes` to
    `scheduled_start_at`".

    Design: Corner/validations/a_match_must_fit_entirely_between_roster_lock_and_the_regular_season_end
    """
    world = _build_two_schedulable_teams(api)

    before_lock = _try_match(api, world, "2026-09-19T23:59:59.999Z")
    validate_error(before_lock, ApiErrorId.ERR_MATCH_OUTSIDE_SEASON_WINDOW.value, 409)

    on_lock = _try_match(api, world, "2026-09-20T00:00:00.000Z")
    validate_success(on_lock, 201)
    assert A.data_of(on_lock, 201)["scheduled_end_at"] == "2026-09-20T01:00:00.000Z"

    end_overruns = _try_match(api, world, "2026-11-29T23:00:00.001Z")
    validate_error(end_overruns, ApiErrorId.ERR_MATCH_OUTSIDE_SEASON_WINDOW.value, 409)

    end_exactly = _try_match(api, world, "2026-11-29T23:00:00.000Z")
    validate_success(end_exactly, 201)
    assert A.data_of(end_exactly, 201)["scheduled_end_at"] == "2026-11-30T00:00:00.000Z"

    assert _count(
        api.list_matches({"season_id": world["season"]["id"]}, league_admin_headers())
    ) == 2


# ==========================================================================
# Instance: the_logical_clock_refuses_to_move_backwards_but_accepts_its_own_
#           value
# ==========================================================================
def test_the_clock_accepts_its_own_value_and_a_refused_rewind_moves_nothing(api):
    """Monotonicity is "at or after", so a re-set to the present instant is not a
    rewind — and the refusal leaves the clock where it stood.

    PRD §2.4: "The clock is monotonic: a requested `current_utc` earlier than the
    clock's present value is refused with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP
    409), while a value equal to the present value is accepted and leaves the
    clock where it is. Once the clock moves, all subsequent temporal evaluations
    read the new value."  And: "whose value at server startup is exactly
    `2026-08-01T00:00:00.000Z`."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_its_own_value
    """
    forward = api.set_clock("2026-09-01T00:00:00.000Z", league_admin_headers())
    validate_success(forward)

    rewind = api.set_clock("2026-08-31T23:59:59.999Z", league_admin_headers())
    validate_error(rewind, ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN.value, 409)

    same_value = api.set_clock("2026-09-01T00:00:00.000Z", league_admin_headers())
    validate_success(same_value)

    witness = api.create_district(
        {"name": "Clock Witness District", "state_code": "OR"}, league_admin_headers()
    )
    validate_success(witness, 201)
    district = A.data_of(witness, 201)
    assert district["created_at"] == "2026-09-01T00:00:00.000Z"
    A.assert_common_fields(district)


# ==========================================================================
# Instance: broadcast_actions_are_refused_from_every_illegal_broadcast_state_
#           and_for_a_foreign_school
# ==========================================================================
def _build_match_between_two_schools(api):
    """North and Valley meet on 2026-10-01, each with its own certified coach, so
    a coach can name the opponent's school by mistake."""
    district = fx.make_district(api)
    school_a = fx.make_school(api, district["id"], name="North High")
    school_b = fx.make_school(api, district["id"], name="Valley High")
    coach_a = fx.make_certified_coach(api, school_a["id"], full_name="Coach North")
    coach_b = fx.make_certified_coach(api, school_b["id"], full_name="Coach Valley")
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team_a = fx.make_team(
        api, season["id"], school_a["id"], title["id"], coach_a["id"], name="North Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school_b["id"], title["id"], coach_b["id"], name="Valley Alpha"
    )
    match = fx.schedule_match(
        api, season["id"], team_a["id"], team_b["id"], "2026-10-01T18:00:00.000Z"
    )
    return {
        "school_a": school_a,
        "school_b": school_b,
        "coach_a": coach_a,
        "match": match,
    }


def test_the_broadcast_dimension_has_its_own_from_state_error_and_school_pin(api):
    """END and RESUME are illegal from NONE or SCHEDULED, a second REGISTER is
    illegal, and the channel must be the acting coach's own school.

    PRD §2.7 rung 19: "**Broadcast from-state,** otherwise
    `ERR_INVALID_BROADCAST_STATE`. `REGISTER` requires `NONE`; `GO_LIVE` requires
    `SCHEDULED`; `RESUME` requires `SUSPENDED` together with fewer than three
    accumulated `spectator_strikes`; `END` requires `LIVE` or `SUSPENDED`."  PRD
    §3.8: "A coach of either participating team claims the channel with an
    `action` of `REGISTER` accompanied by `broadcast_school_id`,
    `broadcast_start_at` and `broadcast_end_at`. The match's `broadcast_status`
    must be `NONE`, otherwise `ERR_INVALID_BROADCAST_STATE`; the acting
    `X-User-ID` must be the coach of the home or the away team; and the supplied
    `broadcast_school_id` must be the school of that coach's own participating
    team, otherwise `ERR_BROADCAST_SCHOOL_MISMATCH`."

    Design: Corner/validations/broadcast_actions_are_refused_from_every_illegal_broadcast_state_and_for_a_foreign_school
    """
    world = _build_match_between_two_schools(api)
    match_id = world["match"]["id"]
    coach_headers = make_coach_headers(world["coach_a"]["id"])
    window = {
        "broadcast_start_at": "2026-10-01T18:00:00.000Z",
        "broadcast_end_at": "2026-10-01T19:00:00.000Z",
    }

    end_from_none = api.broadcast_action(match_id, {"action": "END"}, coach_headers)
    validate_error(end_from_none, ApiErrorId.ERR_INVALID_BROADCAST_STATE.value, 409)

    foreign_school = api.broadcast_action(
        match_id,
        dict(action="REGISTER", broadcast_school_id=world["school_b"]["id"], **window),
        coach_headers,
    )
    validate_error(foreign_school, ApiErrorId.ERR_BROADCAST_SCHOOL_MISMATCH.value, 422)
    assert fx.get_match(api, match_id)["broadcast_status"] == "NONE"

    claimed = api.broadcast_action(
        match_id,
        dict(action="REGISTER", broadcast_school_id=world["school_a"]["id"], **window),
        coach_headers,
    )
    validate_success(claimed)
    scheduled = A.data_of(claimed)
    assert scheduled["broadcast_status"] == "SCHEDULED"
    assert scheduled["broadcast_school_id"] == world["school_a"]["id"]
    assert scheduled["broadcast_start_at"] == "2026-10-01T18:00:00.000Z"
    assert scheduled["broadcast_end_at"] == "2026-10-01T19:00:00.000Z"
    assert scheduled["spectator_strikes"] == 0

    second_claim = api.broadcast_action(
        match_id,
        dict(action="REGISTER", broadcast_school_id=world["school_a"]["id"], **window),
        coach_headers,
    )
    validate_error(second_claim, ApiErrorId.ERR_INVALID_BROADCAST_STATE.value, 409)

    resume_from_scheduled = api.broadcast_action(
        match_id, {"action": "RESUME"}, coach_headers
    )
    validate_error(
        resume_from_scheduled, ApiErrorId.ERR_INVALID_BROADCAST_STATE.value, 409
    )

    final = fx.get_match(api, match_id)
    A.assert_match_state(
        final,
        play_status="SCHEDULED",
        result_status="AWAITING_REPORTS",
        broadcast_status="SCHEDULED",
    )


# ==========================================================================
# Instance: seeding_is_refused_when_no_team_in_the_season_is_still_in_a_
#           seedable_state
# ==========================================================================
def _build_seeded_season_of_two_competing_teams(api):
    """A REGULAR_SEASON season with two COMPETING teams created one day apart, so
    the final `created_at` ascending tie-break is determinate."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    teams = []
    for index, name in enumerate(("North Alpha", "North Bravo")):
        if index == 1:
            fx.set_clock(api, "2026-08-02T00:00:00.000Z")
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=name
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        teams.append(team)
    fx.open_registration(api, season["id"])
    teams = [fx.register_team(api, team) for team in teams]
    teams = [fx.lock_roster(api, team) for team in teams]
    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    fx.advance_season(api, season["id"], "REGULAR_SEASON")
    return {"school": school, "season": season, "teams": teams}


def test_an_empty_seed_set_is_a_fault_rather_than_an_empty_seed_order(api):
    """The same call that seeded two COMPETING teams must fail once both have
    withdrawn out of the eligible set.

    PRD §3.9: "The eligible set is the season's teams whose status is
    `COMPETING`, `PLAYOFF_SEEDED`, `ELIMINATED` or `SUSPENDED`. Teams in `DRAFT`,
    `REGISTERED`, `ROSTER_LOCKED`, `WITHDRAWN` or `DISQUALIFIED` are excluded from
    the seed order entirely and keep a null `seed_position`. If the eligible set
    is empty the run is refused with `ERR_SEED_ORDER_EMPTY`."  PRD §3.6:
    "Withdrawal ... Every roster slot on the team whose `participation_status` is
    not already `RELEASED` transitions to `RELEASED`. ... The season's
    `registered_team_count` is recomputed, and if the season's `seeding_state` was
    `SEEDED` it becomes `STALE`."

    Design: Corner/validations/seeding_is_refused_when_no_team_in_the_season_is_still_in_a_seedable_state
    """
    world = _build_seeded_season_of_two_competing_teams(api)
    first, second = world["teams"]

    seeded_response = api.run_seeding(world["season"]["id"], {}, league_admin_headers())
    validate_success(seeded_response)
    seeded = A.data_of(seeded_response)
    assert seeded["seeding_state"] == "SEEDED"
    assert seeded["seeding_basis_applied"] == "MATCH_POINT_BASIS"
    assert seeded["seed_order"] == [first["id"], second["id"]]

    for expected_position, team in ((1, first), (2, second)):
        seeded_team = fx.get_team(api, team["id"])
        assert seeded_team["status"] == "PLAYOFF_SEEDED"
        assert seeded_team["seed_position"] == expected_position

    for team in (first, second):
        withdrawn_response = api.withdraw_team(
            team["id"],
            {"withdrawal_note": "school closed the program"},
            make_athletic_director_headers(world["school"]["id"]),
        )
        validate_success(withdrawn_response)
        assert A.data_of(withdrawn_response)["status"] == "WITHDRAWN"
        released, _meta = validate_paginated(
            api.list_roster_slots({"team_id": team["id"]}, league_admin_headers())
        )
        for slot in released:
            A.assert_slot_axes(slot, participation_status="RELEASED")

    emptied = fx.get_season(api, world["season"]["id"])
    assert emptied["seeding_state"] == "STALE"
    assert emptied["registered_team_count"] == 0

    refused = api.run_seeding(world["season"]["id"], {}, league_admin_headers())
    validate_error(refused, ApiErrorId.ERR_SEED_ORDER_EMPTY.value, 422)
    unchanged = fx.get_season(api, world["season"]["id"])
    assert unchanged["seeding_state"] == "STALE"
    assert unchanged["seed_order"] == [first["id"], second["id"]]


# ==========================================================================
# Instance: registration_is_refused_when_the_district_subsidy_pool_is_one_cent_
#           short
# ==========================================================================
def _build_two_districts_one_cent_apart(api):
    """Two otherwise identical one-starter teams: one district holds 3,961 cents,
    the figure a sum-then-round subsidy would need, and the other holds 3,962."""
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    built = {}
    for key, pool in (("thin", 3961), ("exact", 3962)):
        district = fx.make_district(api, subsidy_pool_cents=pool, name=f"{key} district")
        school = fx.make_school(api, district["id"])
        coach = fx.make_certified_coach(api, school["id"])
        fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
        team = fx.make_team(
            api,
            season["id"],
            school["id"],
            title["id"],
            coach["id"],
            name=f"{key} alpha",
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        built[key] = {"district": district, "coach": coach, "team": team}
    fx.open_registration(api, season["id"])
    built["season"] = season
    return built


def test_the_fiscal_gate_is_settled_on_the_per_line_rounded_grant(api):
    """One cent short is a 402; exactly enough registers and empties the pool.

    PRD §3.6: "And the district's remaining `subsidy_pool_cents` must be at least
    as large as the subsidy this registration would grant, otherwise
    `ERR_SUBSIDY_POOL_EXHAUSTED` — the last rung on the whole ladder, so any state
    problem is always reported ahead of a budget problem."  PRD §2.8: "Where
    several money line items are each subsidized, each line item is rounded to
    whole cents *before* the line items are summed".  PRD §3.5: a new team's
    "`entry_fee_cents`, `subsidy_granted_cents` and `net_fee_due_cents`" begin
    "at 0" with "`registered_at` and `roster_locked_at` ... null at creation".

    Design: Corner/validations/registration_is_refused_when_the_district_subsidy_pool_is_one_cent_short
    """
    world = _build_two_districts_one_cent_apart(api)
    thin = world["thin"]
    exact = world["exact"]

    refused = api.register_team(
        thin["team"]["id"], {}, make_coach_headers(thin["coach"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_SUBSIDY_POOL_EXHAUSTED.value, 402)

    untouched = fx.get_team(api, thin["team"]["id"])
    assert untouched["status"] == "DRAFT"
    A.assert_cents(untouched["entry_fee_cents"], 0)
    A.assert_cents(untouched["subsidy_granted_cents"], 0)
    A.assert_cents(untouched["net_fee_due_cents"], 0)
    assert untouched["registered_at"] is None

    thin_district = fx.get_district(api, thin["district"]["id"])
    A.assert_cents(thin_district["subsidy_pool_cents"], 3961)
    A.assert_cents(thin_district["subsidy_pool_initial_cents"], 3961)

    accepted = api.register_team(
        exact["team"]["id"], {}, make_coach_headers(exact["coach"]["id"])
    )
    validate_success(accepted)
    registered = A.data_of(accepted)
    assert registered["status"] == "REGISTERED"
    A.assert_cents(registered["entry_fee_cents"], 15845)
    A.assert_cents(registered["subsidy_granted_cents"], 3962)
    A.assert_cents(registered["net_fee_due_cents"], 11883)

    exact_district = fx.get_district(api, exact["district"]["id"])
    A.assert_cents(exact_district["subsidy_pool_cents"], 0)
    A.assert_subsidy_conserved(exact_district, 3962)

    assert fx.get_season(api, world["season"]["id"])["registered_team_count"] == 1


# ==========================================================================
# Instance: verify_academics_roster_locked_beats_segregation_of_duties
# ==========================================================================
def _build_one_locked_team_and_one_draft_team(api):
    """North Alpha is ROSTER_LOCKED on the strength of one cleared starter and
    still carries a second slot whose academics are unverified; North Bravo is
    still DRAFT with an enrollment-verified slot of its own.  Officer A verified
    enrollment on every slot."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Bravo"
    )
    cleared = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
    stranded = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
    draft_side = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
    slot_cleared = fx.add_slot(api, team_a["id"], cleared["id"], coach["id"], "STARTER")
    slot_stranded = fx.add_slot(
        api, team_a["id"], stranded["id"], coach["id"], "STARTER"
    )
    slot_draft = fx.add_slot(api, team_b["id"], draft_side["id"], coach["id"], "STARTER")
    for slot, student in (
        (slot_cleared, cleared),
        (slot_stranded, stranded),
        (slot_draft, draft_side),
    ):
        fx.verify_slot_enrollment(
            api, slot["id"], student["birthdate"], officer_id=ELIGIBILITY_OFFICER_ID
        )
    fx.verify_slot_academics(
        api, slot_cleared["id"], officer_id=ELIGIBILITY_OFFICER_ID_2
    )
    fx.open_registration(api, season["id"])
    team_a = fx.lock_roster(api, fx.register_team(api, team_a))
    return {
        "team_a": team_a,
        "team_b": team_b,
        "slot_stranded": slot_stranded,
        "slot_draft": slot_draft,
    }


def test_a_locked_roster_is_reported_before_the_two_person_rule(api):
    """One request breaks both rules; the state rung must win, and the same
    request on a DRAFT team isolates the segregation failure.

    PRD §3.5 axis two: "The acting `X-User-ID` must differ from the slot's
    `enrollment_verified_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` —
    this is the two-person rule, and note from §2.7 that a locked roster is
    reported before the segregation failure when both apply."  PRD §2.7: "An
    academics clearance attempted by the same officer who verified enrollment, on
    a slot whose team has already locked, reports `ERR_ROSTER_LOCKED`, because
    state precedes segregation of duties."  PRD §3.6: "From this point the roster
    is frozen: slot creation, either verification axis, and release are all
    refused with `ERR_ROSTER_LOCKED`."

    Design: Corner/validations/verify_academics_roster_locked_beats_segregation_of_duties
    """
    world = _build_one_locked_team_and_one_draft_team(api)
    assert world["team_a"]["status"] == "ROSTER_LOCKED"
    assert fx.get_team(api, world["team_b"]["id"])["status"] == "DRAFT"

    tainted_and_locked = api.verify_academics(
        world["slot_stranded"]["id"],
        {},
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_error(tainted_and_locked, ApiErrorId.ERR_ROSTER_LOCKED.value, 409)
    stranded = fx.get_slot(api, world["slot_stranded"]["id"])
    A.assert_slot_axes(stranded, academic_status="PENDING")
    assert stranded["academics_verified_by_user_id"] is None

    tainted_only = api.verify_academics(
        world["slot_draft"]["id"], {}, eligibility_officer_headers(ELIGIBILITY_OFFICER_ID)
    )
    validate_error(tainted_only, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    independent = api.verify_academics(
        world["slot_draft"]["id"],
        {},
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2),
    )
    validate_success(independent)
    cleared = A.data_of(independent)
    A.assert_slot_axes(
        cleared, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert cleared["academics_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID_2
    assert fx.get_team(api, world["team_b"]["id"])["active_starter_count"] == 1


# ==========================================================================
# Instance: season_complete_advance_is_blocked_by_one_unplayed_match
# ==========================================================================
def _build_playoff_season_with_one_outstanding_match(api):
    """A PLAYOFFS season carrying one FORFEITED match and one still SCHEDULED."""
    world = _build_seeded_season_of_two_competing_teams(api)
    first, second = world["teams"]
    world["match_one"] = fx.schedule_match(
        api,
        world["season"]["id"],
        first["id"],
        second["id"],
        "2026-10-01T18:00:00.000Z",
    )
    world["match_two"] = fx.schedule_match(
        api,
        world["season"]["id"],
        first["id"],
        second["id"],
        "2026-10-02T18:00:00.000Z",
    )
    fx.forfeit_match(
        api,
        world["match_one"]["id"],
        second["id"],
        reason_note="no players available",
    )
    fx.run_seeding(api, world["season"]["id"])
    world["season"] = fx.advance_season(api, world["season"]["id"], "PLAYOFFS")
    return world


def test_the_last_stage_advance_waits_on_every_child_match(api):
    """The from-state is right and the blocking fact lives on another entity.

    PRD §3.4: "`PLAYOFFS → COMPLETE` is the second compound condition over
    children: every match in the season must have reached `FINALIZED` or
    `FORFEITED`, and a season with any match still outstanding is refused with
    `ERR_INVALID_SEASON_STAGE`. Every one of the five advances increments the
    season's `version` by one".  PRD §2.9 anchors `match_point_pool` as "the
    running total of match points awarded in the season".

    Design: Corner/validations/season_complete_advance_is_blocked_by_one_unplayed_match
    """
    world = _build_playoff_season_with_one_outstanding_match(api)
    first, second = world["teams"]
    assert world["season"]["status"] == "PLAYOFFS"
    A.assert_match_state(
        fx.get_match(api, world["match_one"]["id"]), play_status="FORFEITED"
    )
    A.assert_match_state(
        fx.get_match(api, world["match_two"]["id"]), play_status="SCHEDULED"
    )

    blocked = api.advance_season(
        world["season"]["id"], {"to_status": "COMPLETE"}, league_admin_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_SEASON_STAGE.value, 409)
    assert fx.get_season(api, world["season"]["id"])["status"] == "PLAYOFFS"

    resolved = api.forfeit_match(
        world["match_two"]["id"],
        {"forfeiting_team_id": first["id"], "reason_note": "roster collapse"},
        league_admin_headers(),
    )
    validate_success(resolved)
    forfeited = A.data_of(resolved)
    A.assert_match_state(
        forfeited, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert forfeited["forfeiting_team_id"] == first["id"]
    assert forfeited["winner_team_id"] == second["id"]

    completed = api.advance_season(
        world["season"]["id"], {"to_status": "COMPLETE"}, league_admin_headers()
    )
    validate_success(completed)
    assert A.data_of(completed)["status"] == "COMPLETE"

    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 6)
    for team in (first, second):
        final = fx.get_team(api, team["id"])
        assert final["forfeit_wins"] == 1
        assert final["forfeits_charged"] == 1


# ==========================================================================
# Instance: appeal_decision_cannot_be_made_by_the_investigator_or_the_decider
# ==========================================================================
def _build_appealed_case_with_two_tainted_officers(api):
    """One SUSTAINED-then-APPEALED case whose investigator is officer one and
    whose decider is officer two, with the sanctioned student's slot demoted."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
    team = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    slot = fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
    case = fx.open_student_case(
        api, team["id"], student["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)
    case = fx.decide_case(
        api,
        case["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    case = fx.appeal_case(
        api,
        case,
        coach["id"],
        appeal_grounds="the login came from the student's own home network",
    )
    return {"team": team, "student": student, "slot": slot, "case": case}


def test_appeal_independence_excludes_two_recorded_officers_before_the_fork(api):
    """Both the investigator and the decider are refused, whichever way they
    would have decided, and the refusal preserves every sanction.

    PRD §2.1: "The officer who decides an appeal must not be the same identifier
    as that case's `investigator_user_id` or its `decider_user_id`."  PRD §2.7
    rung 23: "**Appeal independence** on the appeal decision —
    `ERR_SEGREGATION_OF_DUTIES`."  PRD §3.8: "The third link, caused by the
    second, moves every roster slot of that student whose `participation_status`
    is `ACTIVE` to `INELIGIBLE` with `ineligibility_reason` `FAIR_PLAY`".

    Design: Corner/validations/appeal_decision_cannot_be_made_by_the_investigator_or_the_decider
    """
    world = _build_appealed_case_with_two_tainted_officers(api)
    case_id = world["case"]["id"]
    assert world["case"]["status"] == "APPEALED"
    assert world["case"]["investigator_user_id"] == INTEGRITY_OFFICER_ID
    assert world["case"]["decider_user_id"] == INTEGRITY_OFFICER_ID_2

    by_investigator = api.decide_appeal(
        case_id,
        {"decision": "AFFIRM", "appeal_note": "stands"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID),
    )
    validate_error(by_investigator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    by_decider = api.decide_appeal(
        case_id,
        {"decision": "OVERTURN", "appeal_note": "lab machine accepted"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_2),
    )
    validate_error(by_decider, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    preserved = fx.get_case(api, case_id)
    assert preserved["status"] == "APPEALED"
    assert preserved["appeal_decider_user_id"] is None
    assert fx.get_student(api, world["student"]["id"])["fair_play_status"] == "SANCTIONED"
    A.assert_slot_axes(
        fx.get_slot(api, world["slot"]["id"]), participation_status="INELIGIBLE"
    )

    independent = api.decide_appeal(
        case_id,
        {"decision": "AFFIRM", "appeal_note": "independent review agrees"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_3),
    )
    validate_success(independent)
    affirmed = A.data_of(independent)
    assert affirmed["status"] == "SUSTAINED_FINAL"
    assert affirmed["appeal_decider_user_id"] == INTEGRITY_OFFICER_ID_3

    A.assert_integrity_score(
        fx.get_team(api, world["team"]["id"])["integrity_score"], 90.00
    )
    assert fx.get_student(api, world["student"]["id"])["fair_play_status"] == "SANCTIONED"
    still_ineligible = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(still_ineligible, participation_status="INELIGIBLE")
    assert still_ineligible["ineligibility_reason"] == "FAIR_PLAY"


# ==========================================================================
# Instance: starter_capacity_is_satisfied_up_to_the_cap_and_sub_slots_are_exempt
# ==========================================================================
def _build_empty_team_and_four_students(api):
    """A DRAFT team with all three default starter seats free and four students
    waiting."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    team = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="North Alpha"
    )
    students = [
        fx.make_student(api, school["id"], full_name=f"Prospect {index}")
        for index in range(1, 5)
    ]
    return {"coach": coach, "team": team, "students": students}


def test_the_third_starter_fits_at_the_boundary_and_a_sub_is_exempt(api):
    """The rule is "at least one available", so the third starter is accepted with
    exactly one seat left, and a SUB is accepted with none.

    PRD §3.5: "when the requested role is `STARTER`, the team must still have
    starter capacity — `starter_slots_used` strictly below the season's
    `max_starters`, equivalently at least one `starter_slots_available` —
    otherwise `ERR_STARTER_CAPACITY_EXCEEDED`."  And: "`starter_slots_used` is the
    count of the team's slots whose `slot_role` is `STARTER` and whose
    `participation_status` is `PROSPECTIVE`, `ACTIVE` or `INELIGIBLE` ...
    `active_starter_count` ... counts only slots whose `slot_role` is `STARTER`
    and whose `participation_status` is exactly `ACTIVE`."

    Design: Corner/validations/starter_capacity_is_satisfied_up_to_the_cap_and_sub_slots_are_exempt
    """
    world = _build_empty_team_and_four_students(api)
    coach_headers = make_coach_headers(world["coach"]["id"])
    team_id = world["team"]["id"]

    assert world["team"]["starter_slots_used"] == 0
    assert world["team"]["starter_slots_available"] == 3

    created = []
    for index, expected_used in ((0, 1), (1, 2), (2, 3)):
        response = api.create_roster_slot(
            {
                "team_id": team_id,
                "student_id": world["students"][index]["id"],
                "slot_role": "STARTER",
            },
            coach_headers,
        )
        validate_success(response, 201)
        slot = A.data_of(response, 201)
        assert slot["slot_role"] == "STARTER"
        A.assert_slot_axes(
            slot,
            verification_status="UNVERIFIED",
            academic_status="PENDING",
            participation_status="PROSPECTIVE",
        )
        created.append(slot)
        team = fx.get_team(api, team_id)
        assert team["starter_slots_used"] == expected_used
        assert team["starter_slots_available"] == 3 - expected_used
        A.assert_starter_capacity_conserved(team, 3)

    sub_response = api.create_roster_slot(
        {
            "team_id": team_id,
            "student_id": world["students"][3]["id"],
            "slot_role": "SUB",
        },
        coach_headers,
    )
    validate_success(sub_response, 201)
    sub = A.data_of(sub_response, 201)
    assert sub["slot_role"] == "SUB"
    created.append(sub)

    read_back = fx.get_team(api, team_id)
    assert read_back["starter_slots_used"] == 3
    assert read_back["starter_slots_available"] == 0
    assert read_back["active_starter_count"] == 0

    for slot in created:
        A.assert_slot_axes(
            fx.get_slot(api, slot["id"]), participation_status="PROSPECTIVE"
        )
