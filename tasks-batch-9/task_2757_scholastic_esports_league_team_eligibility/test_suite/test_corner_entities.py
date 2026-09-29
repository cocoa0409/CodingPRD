"""Breadth tests for the entity surface: defaults, system fields, not-found
resolution, body shape, and the flat-topology list filters (PRD §2.3, §2.5, §2.7,
§2.10 and §3.1–§3.5).
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    eligibility_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
)


def test_district_creation_returns_every_declared_policy_default(api):
    """The whole policy envelope materialises from two required inputs.

    PRD §3.1: "Its `max_age_rating` is the highest ESRB rating the district will
    permit ... defaulting to `T` ... Its `academic_standing_basis` selects which
    of the two academic evaluation variants applies to its students, either
    `TERM_SNAPSHOT` (the default) or `ROLLING_CUMULATIVE` ... `min_gpa` ...
    defaulting to 2.000, and `probation_gpa_floor` ... defaulting to 1.750."
    And: "`dispute_window_hours` ... defaults to 48 ... `subsidy_pct` ...
    defaulting to 0.250 ... `subsidy_pool_cents` ... defaulting to 5,000,000
    cents ... the server copies that opening figure into
    `subsidy_pool_initial_cents` ... `recruiting_dead_period_start` and
    `recruiting_dead_period_end` ... are both null when no blackout is
    configured; `recruiting_contact_cap_per_window` ... defaults to 3 ... and
    `recruiting_window_days` ... defaults to 30 ... `broadcast_buffer_minutes`
    ... defaults to 15".

    Design: Corner/entities/district_creation_returns_every_declared_policy_default
    """
    response = api.create_district(
        {"name": "Metro District", "state_code": "CA"}, league_admin_headers()
    )
    validate_success(response, 201)
    district = A.data_of(response, 201)
    A.assert_common_fields(district)

    assert district["max_age_rating"] == "T"
    assert district["academic_standing_basis"] == "TERM_SNAPSHOT"
    A.assert_gpa(district["min_gpa"], 2.000)
    A.assert_gpa(district["probation_gpa_floor"], 1.750)
    assert district["dispute_window_hours"] == 48
    A.assert_gpa(district["subsidy_pct"], 0.250)
    A.assert_cents(district["subsidy_pool_cents"], 5000000)
    A.assert_cents(district["subsidy_pool_initial_cents"], 5000000)
    assert district["recruiting_dead_period_start"] is None
    assert district["recruiting_dead_period_end"] is None
    assert district["recruiting_contact_cap_per_window"] == 3
    assert district["recruiting_window_days"] == 30
    assert district["broadcast_buffer_minutes"] == 15
    assert district["created_at"] == "2026-08-01T00:00:00.000Z"


def test_season_defaults_applied_when_every_optional_field_is_omitted(api):
    """A season built from two inputs pins all four windows and both counters.

    PRD §3.4: "`registration_opens_at` and `registration_closes_at` bracket the
    team registration window, defaulting to `2026-08-01T00:00:00.000Z` and
    `2026-09-15T23:59:59.999Z` and both inclusive. `roster_lock_at` is the
    inclusive deadline by which a coach must lock the roster, defaulting to
    `2026-09-20T00:00:00.000Z`. `regular_season_end_at` is the inclusive end of
    the period in which matches may be played, defaulting to
    `2026-11-30T00:00:00.000Z`."  And:
    "`age_cutoff_date`, in `YYYY-MM-DD` form and defaulting to `2026-09-01`
    ... `max_age` ... defaults to 19 ... `min_starters` ... defaulting to 1 ...
    `max_starters` ... defaulting to 3 ... `base_entry_fee_cents` ... defaulting
    to 12,510 cents, and `per_starter_fee_cents` ... defaulting to 3,335 cents
    ... `seeding_basis`, either `MATCH_POINT_BASIS` (the default) or
    `WIN_PERCENTAGE_BASIS`, and ... `playoff_slots` ... defaulting to 2."  And:
    "`status` begins at `DRAFT` ... `seeding_state` begins at `UNSEEDED` ...
    `seed_order` begins as an empty array ... `registered_team_count` begins at
    0 ... `match_point_pool` begins at 0 ... `seeding_basis_applied`, is null
    until the first seeding run".

    Design: Corner/entities/season_defaults_applied_when_every_optional_field_is_omitted
    """
    title = fx.make_title(api)
    response = api.create_season(
        {"title_id": title["id"], "name": "Fall 2026 Varsity"}, league_admin_headers()
    )
    validate_success(response, 201)
    season = A.data_of(response, 201)

    assert season["division"] == "VARSITY"
    assert season["registration_opens_at"] == "2026-08-01T00:00:00.000Z"
    assert season["registration_closes_at"] == "2026-09-15T23:59:59.999Z"
    assert season["roster_lock_at"] == "2026-09-20T00:00:00.000Z"
    assert season["regular_season_end_at"] == "2026-11-30T00:00:00.000Z"
    assert season["age_cutoff_date"] == "2026-09-01"
    assert season["max_age"] == 19
    assert season["min_starters"] == 1
    assert season["max_starters"] == 3
    assert season["playoff_slots"] == 2
    A.assert_cents(season["base_entry_fee_cents"], 12510)
    A.assert_cents(season["per_starter_fee_cents"], 3335)
    assert season["seeding_basis"] == "MATCH_POINT_BASIS"
    assert season["status"] == "DRAFT"
    assert season["seeding_state"] == "UNSEEDED"
    assert season["seed_order"] == []
    assert season["registered_team_count"] == 0
    A.assert_match_point_pool(season, 0)
    assert season["seeding_basis_applied"] is None


def test_team_creation_ignores_client_supplied_system_extra_field(api):
    """Undeclared body keys are dropped, neither honoured nor rejected.

    PRD §3.5: "A new team's `status` is `DRAFT` ... `active_starter_count`
    starts at 0, `entry_fee_cents`, `subsidy_granted_cents` and
    `net_fee_due_cents` at 0, `integrity_score` at 100.00, and
    `suspension_reason` null."  PRD §3.9: a team's `seed_position` and
    `seed_stale` are server-owned seeding fields.

    Design: Corner/entities/team_creation_ignores_client_supplied_system_extra_field
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])

    response = api.create_team(
        {
            "season_id": season["id"],
            "school_id": school["id"],
            "title_id": title["id"],
            "coach_id": coach["id"],
            "name": "North Nova",
            "status": "COMPETING",
            "match_points": 99,
            "integrity_score": 10.0,
        },
        make_coach_headers(coach["id"]),
    )
    validate_success(response, 201)
    team = A.data_of(response, 201)
    A.assert_common_fields(team)

    assert team["status"] == "DRAFT"
    assert team["match_points"] == 0
    assert team["wins"] == 0
    assert team["losses"] == 0
    assert team["draws"] == 0
    assert team["forfeits_charged"] == 0
    assert team["forfeit_wins"] == 0
    A.assert_integrity_score(team["integrity_score"], 100.00)
    assert team["seed_position"] is None
    assert team["seed_stale"] is False


def test_student_creation_ignores_client_supplied_computed_extra_field(api):
    """No calculation has run, so every computed academic field stays empty.

    PRD §3.1: "A fresh student record has `academic_standing` `UNEVALUATED`,
    `fair_play_status` `CLEAR`, `showcase_status` `NONE`, and an empty
    `recruiting_contact_log`."  And: "`enrollment_status` is what the registrar
    reports and defaults to `ENROLLED` ... `credits_completed` records
    cumulative credits earned and defaults to 0".  PRD §3.9: showcase and
    scholarship figures are written only by a nomination run.

    Design: Corner/entities/student_creation_ignores_client_supplied_computed_extra_field
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])

    response = api.create_student(
        {
            "school_id": school["id"],
            "full_name": "Rosa Nova",
            "birthdate": "2009-05-10",
            "grade_level": 11,
            "academic_standing": "GOOD",
            "effective_gpa": 4.0,
            "scholarship_award_cents": 500000,
        },
        make_athletic_director_headers(school["id"]),
    )
    validate_success(response, 201)
    student = A.data_of(response, 201)

    assert student["academic_standing"] == "UNEVALUATED"
    assert student["effective_gpa"] is None
    assert student["standing_basis_applied"] is None
    assert student["award_tier"] == "NONE"
    A.assert_cents(student["provisional_award_cents"], 0)
    A.assert_cents(student["scholarship_award_cents"], 0)
    assert student["scholarship_award_state"] == "NONE"
    assert student["enrollment_status"] == "ENROLLED"
    assert student["credits_completed"] == 0
    assert student["fair_play_status"] == "CLEAR"
    assert student["showcase_status"] == "NONE"
    assert student["nominating_team_id"] is None
    assert student["recruiting_contact_log"] == []


def test_every_path_parameter_id_that_does_not_resolve_returns_not_found(api):
    """Each of the eleven entities owns its own not-found error id.

    PRD §2.7: "**Path existence.** Every identifier embedded in the URL path
    resolves to a live record, validated left to right. The first unresolvable
    segment decides the error, drawn from `ERR_DISTRICT_NOT_FOUND`,
    `ERR_SCHOOL_NOT_FOUND`, `ERR_COACH_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_TITLE_APPROVAL_NOT_FOUND`,
    `ERR_SEASON_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_ROSTER_SLOT_NOT_FOUND`,
    `ERR_MATCH_NOT_FOUND` and `ERR_FAIR_PLAY_CASE_NOT_FOUND` — each HTTP 404."

    Design: Corner/entities/every_path_parameter_id_that_does_not_resolve_returns_not_found
    """
    probes = [
        (api.get_district, ApiErrorId.ERR_DISTRICT_NOT_FOUND),
        (api.get_school, ApiErrorId.ERR_SCHOOL_NOT_FOUND),
        (api.get_coach, ApiErrorId.ERR_COACH_NOT_FOUND),
        (api.get_student, ApiErrorId.ERR_STUDENT_NOT_FOUND),
        (api.get_title, ApiErrorId.ERR_TITLE_NOT_FOUND),
        (api.get_title_approval, ApiErrorId.ERR_TITLE_APPROVAL_NOT_FOUND),
        (api.get_season, ApiErrorId.ERR_SEASON_NOT_FOUND),
        (api.get_team, ApiErrorId.ERR_TEAM_NOT_FOUND),
        (api.get_roster_slot, ApiErrorId.ERR_ROSTER_SLOT_NOT_FOUND),
        (api.get_match, ApiErrorId.ERR_MATCH_NOT_FOUND),
        (api.get_fair_play_case, ApiErrorId.ERR_FAIR_PLAY_CASE_NOT_FOUND),
    ]
    for getter, error_id in probes:
        response = getter(NON_EXISTENT_UUID, league_admin_headers())
        validate_error(response, error_id.value, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"]


def test_team_creation_missing_required_fields_returns_invalid_request(api):
    """A missing required input is a body-shape failure, never a 404.

    PRD §2.7: "**Body shape.** Every required field present, every enumerated
    value inside its declared set, every number inside its declared range ... —
    otherwise `ERR_INVALID_REQUEST`."  PRD §3.5: a team is created "naming the
    `season_id` it will compete in, the `school_id` fielding it, the `title_id`
    it plays, the `coach_id` designated to run it, and a `name` of 1 to 120
    characters".

    Design: Corner/entities/team_creation_missing_required_fields_returns_invalid_request
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    headers = make_coach_headers(coach["id"])
    complete = {
        "season_id": season["id"],
        "school_id": school["id"],
        "title_id": title["id"],
        "coach_id": coach["id"],
        "name": "North Nova",
    }

    for omitted in ("name", "coach_id", "title_id"):
        payload = {k: v for k, v in complete.items() if k != omitted}
        validate_error(
            api.create_team(payload, headers),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    _rows, meta = validate_paginated(
        api.list_teams({"season_id": season["id"]}, league_admin_headers())
    )
    assert meta["total_count"] == 0
    assert fx.get_season(api, season["id"])["registered_team_count"] == 0


def test_entity_field_type_constraints_are_rejected_as_invalid_request(api):
    """Out-of-range, wrong-shape and off-enum values are refused, not clamped.

    PRD §2.7: "**Body shape.** Every required field present, every enumerated
    value inside its declared set, every number inside its declared range ... —
    otherwise `ERR_INVALID_REQUEST`."  PRD §3.1: a student carries "a
    `grade_level` between 9 and 12 inclusive" and a district "a `state_code` of
    exactly two uppercase letters".  PRD §3.3: a title's "`age_rating` is one of
    `E`, `E10`, `T` or `M`".

    Design: Corner/entities/entity_field_type_constraints_are_rejected_as_invalid_request
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    director = make_athletic_director_headers(school["id"])

    for birthdate, grade_level in (("2013-05-10", 8), ("2007-05-10", 13)):
        validate_error(
            api.create_student(
                {
                    "school_id": school["id"],
                    "full_name": "Out Of Range",
                    "birthdate": birthdate,
                    "grade_level": grade_level,
                },
                director,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    validate_error(
        api.create_district(
            {"name": "Bad State District", "state_code": "CAL"}, league_admin_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_title(
            {
                "name": "Bad Rating Title",
                "publisher": "Nova Interactive",
                "age_rating": "X",
            },
            league_admin_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _students, student_meta = validate_paginated(
        api.list_students({"school_id": school["id"]}, league_admin_headers())
    )
    assert student_meta["total_count"] == 0

    _districts, district_meta = validate_paginated(
        api.list_districts(None, league_admin_headers())
    )
    assert district_meta["total_count"] == 1

    _titles, title_meta = validate_paginated(
        api.list_titles(None, league_admin_headers())
    )
    assert title_meta["total_count"] == 0


def test_pagination_limit_outside_one_to_one_hundred_returns_invalid_request(api):
    """The bounds are enforced, and the inclusive ceiling of 100 is legal.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10,
    its minimum accepted value is 1 and its maximum accepted value is 100.
    `offset` skips a number of records from the front of the result set; it
    defaults to 0 and its minimum accepted value is 0. A `limit` outside the
    range 1 through 100, or a negative `offset`, is a malformed request and is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."  And: "`has_more` is true
    exactly when records remain beyond the returned page."

    Design: Corner/entities/pagination_limit_outside_one_to_one_hundred_returns_invalid_request
    """
    fx.make_district(api)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_districts(params, league_admin_headers()),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    _rows, meta = validate_paginated(api.list_districts(None, league_admin_headers()))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    _rows, wide = validate_paginated(
        api.list_districts({"limit": 100}, league_admin_headers())
    )
    assert wide["limit"] == 100


def test_roster_slot_get_by_id_returns_the_stored_slot(api):
    """The derived third axis is materialised at creation, not left null.

    PRD §3.5: "A fresh slot begins with `verification_status` `UNVERIFIED`,
    `academic_status` `PENDING`, `participation_status` `PROSPECTIVE`,
    `released_at` and `ineligibility_reason` null, and both verifier identifiers
    null".  And the derivation: "In every other case the slot is `PROSPECTIVE`."

    Design: Corner/entities/roster_slot_get_by_id_returns_the_stored_slot
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    created = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")

    response = api.get_roster_slot(
        created["id"], eligibility_officer_headers(ELIGIBILITY_OFFICER_ID)
    )
    validate_success(response)
    body = response.json()
    assert body["response_type"] == "object"

    slot = A.data_of(response)
    assert slot["team_id"] == team["id"]
    assert slot["student_id"] == student["id"]
    assert slot["slot_role"] == "STARTER"
    A.assert_slot_axes(
        slot,
        verification_status="UNVERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )
    assert slot["age_at_cutoff"] is None
    assert slot["standing_at_verification"] is None
    assert slot["ineligibility_reason"] is None
    assert slot["released_at"] is None
    assert slot["created_at"] == "2026-08-01T00:00:00.000Z"


def test_teams_listing_paginates_with_total_count_and_has_more(api):
    """``total_count`` is the unpaginated size on both pages.

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object. `total_count` reports the
    size of the full filtered result set before the limit and offset are
    applied, and `has_more` is true exactly when records remain beyond the
    returned page."

    Design: Corner/entities/teams_listing_paginates_with_total_count_and_has_more
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team_ids = set()
    for label in ("Alpha", "Bravo", "Charlie"):
        coach = fx.make_coach(api, school["id"])
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )
        team_ids.add(team["id"])

    first_response = api.list_teams(
        {"season_id": season["id"], "limit": 2, "offset": 0}, league_admin_headers()
    )
    assert first_response.json()["response_type"] == "array"
    first_rows, first_meta = validate_paginated(first_response)
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_teams(
            {"season_id": season["id"], "limit": 2, "offset": 2}, league_admin_headers()
        )
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    paged = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(paged)) == 3
    assert set(paged) == team_ids
    for row in first_rows + second_rows:
        A.assert_common_fields(row)


def test_foreign_key_reverse_lookup_lists_children_for_every_declared_filter(api):
    """A flat topology navigates parentage only through filtered lists.

    PRD §2.10: "Parentage is carried by foreign-key fields inside request bodies,
    and each such field is offered back as an optional list filter so that the
    children of a parent remain discoverable — schools by `district_id`; coaches
    by `school_id`; students by `school_id` or `nominating_team_id`; ... teams by
    `season_id`, `school_id`, `title_id` or `coach_id`; roster slots by `team_id`
    or `student_id`".  PRD §2.3: "`total_count` reports the size of the full
    filtered result set before the limit and offset are applied".

    Design: Corner/entities/foreign_key_reverse_lookup_lists_children_for_every_declared_filter
    """
    district = fx.make_district(api)
    other_district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    admin = league_admin_headers()

    expected = [
        (api.list_schools, {"district_id": district["id"]}, school["id"]),
        (api.list_coaches, {"school_id": school["id"]}, coach["id"]),
        (api.list_students, {"school_id": school["id"]}, student["id"]),
        (api.list_teams, {"season_id": season["id"]}, team["id"]),
        (api.list_roster_slots, {"team_id": team["id"]}, slot["id"]),
    ]
    for lister, params, child_id in expected:
        rows, meta = validate_paginated(lister(params, admin))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [child_id]

    slot_rows, _meta = validate_paginated(
        api.list_roster_slots({"team_id": team["id"]}, admin)
    )
    assert slot_rows[0]["student_id"] == student["id"]

    empty_rows, empty_meta = validate_paginated(
        api.list_schools({"district_id": other_district["id"]}, admin)
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 0


def test_body_foreign_key_that_does_not_resolve_returns_not_found(api):
    """A phantom body reference yields the referent's own 404, not a 400.

    PRD §2.7 rung 9: "**Body foreign-key existence.** Every foreign-key
    identifier supplied in the request body resolves to a live record, reported
    with the same 404 codes as rung 4. It applies to school creation, coach
    designation, student enrolment, title-approval creation, season creation,
    team creation, roster-slot creation, match scheduling, fair-play case
    creation and showcase nomination."  It sits below rung 5, "**Body shape.**
    ... otherwise `ERR_INVALID_REQUEST`".

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_not_found
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    coach_headers = make_coach_headers(coach["id"])

    validate_error(
        api.create_team(
            {
                "season_id": NON_EXISTENT_UUID,
                "school_id": school["id"],
                "title_id": title["id"],
                "coach_id": coach["id"],
                "name": "Phantom Season Team",
            },
            coach_headers,
        ),
        ApiErrorId.ERR_SEASON_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_roster_slot(
            {
                "team_id": team["id"],
                "student_id": NON_EXISTENT_UUID,
                "slot_role": "STARTER",
            },
            coach_headers,
        ),
        ApiErrorId.ERR_STUDENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_match(
            {
                "season_id": season["id"],
                "home_team_id": NON_EXISTENT_UUID,
                "away_team_id": team["id"],
                "scheduled_start_at": "2026-10-01T18:00:00.000Z",
            },
            league_admin_headers(),
        ),
        ApiErrorId.ERR_TEAM_NOT_FOUND.value,
        404,
    )

    _teams, team_meta = validate_paginated(
        api.list_teams({"season_id": season["id"]}, league_admin_headers())
    )
    assert team_meta["total_count"] == 1
    _slots, slot_meta = validate_paginated(
        api.list_roster_slots({"team_id": team["id"]}, league_admin_headers())
    )
    assert slot_meta["total_count"] == 0

    unchanged = fx.get_team(api, team["id"])
    assert unchanged["starter_slots_used"] == 0
    assert unchanged["starter_slots_available"] == 3
