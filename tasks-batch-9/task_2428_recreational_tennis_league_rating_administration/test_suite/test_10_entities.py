"""Field-level contracts of the resource kinds: shape, defaults, counters, lookups."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_DUPLICATE_VOTE,
    ERR_FACILITY_SECTION_MISMATCH,
    ERR_INVALID_RATING_LEVEL,
    ERR_LEAGUE_LADDER_INVALID,
    ERR_MATCH_SCHEDULE_STATE_INVALID,
    ERR_NOT_FOUND,
    ERR_SECTION_SCOPE_MISMATCH,
    ERR_VALIDATION,
)
from test_helpers.constants import (
    AGE_18_OVER,
    APPEAL_UP,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    GENDER_F,
    GENDER_M,
    LEAGUE_DRAFT,
    RATING_PERIOD_OPEN_SEASON,
    RATING_SOURCE_COMPUTER,
    RATING_UNRATED,
    SPOT_ACTIVE,
    SPOT_PENDING,
    SUBJECT_RATING_APPEAL,
    TEAM_DRAFT,
    TIER_DISTRICT,
    TIER_SECTION,
    VOTE_OPPOSE,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import Scenario
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_captain_headers,
    make_player_headers,
)

LADDER_LEAGUE_KWARGS = {
    "tier": TIER_SECTION,
    "ntrp_level": 3.5,
    "age_group": AGE_18_OVER,
    "format": FORMAT_MENS_DOUBLES,
    "lines_per_match": 3,
    "min_active_roster_size": 2,
    "max_roster_size": 14,
    "min_playoff_eligible_players": 1,
    "max_teams": 8,
    "advancement_slots": 1,
    "match_duration_minutes": 180,
    "allow_same_day_doubleheader": False,
    "registration_opens_at": "2026-08-01T00:00:00Z",
    "registration_closes_at": "2026-12-01T00:00:00Z",
    "roster_lock_at": "2026-12-01T00:00:00Z",
    "season_end_at": "2026-12-31T00:00:00Z",
}


def _section_and_open_parent_league(api):
    """A section plus a SECTION-tier league at REGISTRATION_OPEN to hang a child on."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(
        min_matches_for_playoff_eligibility=1,
        strike_limit=3,
        disqualification_strike_limit=6,
        scorecard_submission_window_hours=48,
        scorecard_dispute_window_hours=24,
        grievance_window_hours=72,
    )
    parent = s.create_league(**LADDER_LEAGUE_KWARGS)
    s.open_registration(parent)
    return s, parent


# ---------------------------------------------------------------------------
def test_a_section_created_with_every_dial_supplied_echoes_them_all_back(api):
    """Nine supplied inputs round-trip unclamped alongside four zeroed system fields.

    PRD 3.1: "Two further counters are maintained by the service rather than
    supplied: `recalculated_player_count` records how many players had a proposed
    level written by the most recent year-end recalculation run, and
    `published_level_change_count` records how many players' `rating_level`
    actually changed when that run was published. Both start at 0."

    Design: Corner/entities/section_create_with_every_input_field_returns_full_config_and_zero_counters
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    response = api.create_section(
        f.section_payload(
            code="SOCAL-2026",
            name="Southern California Section",
            season_year=2026,
            min_matches_for_playoff_eligibility=1,
            strike_limit=3,
            disqualification_strike_limit=6,
            scorecard_submission_window_hours=48,
            scorecard_dispute_window_hours=24,
            grievance_window_hours=72,
        ),
        SECTION_ADMIN,
    )
    data = get_success_data(response, 201)
    assert response.json()["response_type"] == "object"

    assert data["code"] == "SOCAL-2026"
    assert data["name"] == "Southern California Section"
    assert data["season_year"] == 2026
    assert data["min_matches_for_playoff_eligibility"] == 1
    assert data["strike_limit"] == 3
    assert data["disqualification_strike_limit"] == 6
    assert data["scorecard_submission_window_hours"] == 48
    assert data["scorecard_dispute_window_hours"] == 24
    assert data["grievance_window_hours"] == 72

    assert data["rating_period_status"] == RATING_PERIOD_OPEN_SEASON
    assert data["recalc_run_index"] == 0
    assert data["recalculated_player_count"] == 0
    assert data["published_level_change_count"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_a_section_omitting_all_six_optional_dials_takes_the_declared_defaults(api):
    """3 / 3 / 6 / 48 / 24 / 72 are independent field-level defaults.

    PRD 3.1: "`min_matches_for_playoff_eligibility` is the number of verified team
    matches a roster spot must accumulate before it counts toward playoff
    eligibility; it defaults to 3 and must be at least 1."

    Design: Corner/entities/section_create_omitting_all_six_optional_fields_applies_declared_defaults
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    data = get_success_data(
        api.create_section(
            {
                "code": "NORCAL-2026",
                "name": "Northern California Section",
                "season_year": 2026,
            },
            SECTION_ADMIN,
        ),
        201,
    )
    assert data["min_matches_for_playoff_eligibility"] == 3
    assert data["strike_limit"] == 3
    assert data["disqualification_strike_limit"] == 6
    assert data["scorecard_submission_window_hours"] == 48
    assert data["scorecard_dispute_window_hours"] == 24
    assert data["grievance_window_hours"] == 72
    assert data["rating_period_status"] == RATING_PERIOD_OPEN_SEASON
    assert data["recalc_run_index"] == 0


def test_a_freshly_created_child_league_reads_back_every_dial_and_four_zeros(api):
    """A DISTRICT league echoes its eighteen inputs and all four counters at zero.

    PRD 3.1: "Those counters are `registered_team_count` (teams of this league in
    the registered, roster-locked, in-play, eliminated or advanced states),
    `noncompliant_team_count` (teams of this league in the roster-locked or in-play
    states whose `roster_compliant` is false), `finalized_match_count` (matches of
    this league whose `result_status` is `FINALIZED`) and `seeded_team_count`
    (teams of this league whose `playoff_seed` is not null)."

    Design: Corner/entities/league_get_returns_stored_ladder_config_and_four_zeroed_counters
    """
    s, parent = _section_and_open_parent_league(api)
    child = s.create_league(
        **dict(
            LADDER_LEAGUE_KWARGS,
            parent_league_id=parent["id"],
            tier=TIER_DISTRICT,
            max_teams=4,
            registration_closes_at="2026-08-10T00:00:00Z",
            roster_lock_at="2026-08-10T00:00:00Z",
            season_end_at="2026-09-30T00:00:00Z",
        )
    )

    data = get_success_data(api.get_league(child["id"], LEAGUE_COORDINATOR))
    assert data["id"] == child["id"]
    assert data["section_id"] == s.section["id"]
    assert data["parent_league_id"] == parent["id"]
    assert data["tier"] == TIER_DISTRICT
    assert data["ntrp_level"] == 3.5
    assert data["age_group"] == AGE_18_OVER
    assert data["format"] == FORMAT_MENS_DOUBLES
    assert data["lines_per_match"] == 3
    assert data["min_active_roster_size"] == 2
    assert data["max_roster_size"] == 14
    assert data["min_playoff_eligible_players"] == 1
    assert data["max_teams"] == 4
    assert data["advancement_slots"] == 1
    assert data["match_duration_minutes"] == 180
    assert data["allow_same_day_doubleheader"] is False
    assert_instant_equals(data["roster_lock_at"], "2026-08-10T00:00:00Z")
    assert_instant_equals(data["season_end_at"], "2026-09-30T00:00:00Z")

    assert data["status"] == LEAGUE_DRAFT
    assert data["registered_team_count"] == 0
    assert data["noncompliant_team_count"] == 0
    assert data["finalized_match_count"] == 0
    assert data["seeded_team_count"] == 0
    assert data["version"] == 1


def test_an_unknown_match_identifier_is_a_not_found_before_any_state_gate(api):
    """A well-formed UUID that resolves to nothing answers 404, not a state error.

    PRD 2.10: "Path identifiers are always resolved **left to right**, and the
    first identifier that fails to resolve is the one reported: a request naming a
    section that does not exist is refused with `ERR_NOT_FOUND` (HTTP 404) before
    anything nested beneath it is examined."

    Design: Corner/entities/match_get_with_unresolvable_path_id_returns_not_found
    """
    _s, _parent = _section_and_open_parent_league(api)
    response = api.get_match(NON_EXISTENT_UUID, LEAGUE_COORDINATOR)
    validate_error(response, ERR_NOT_FOUND, 404)

    body = response.json()["data"]
    assert body["error_id"] != ERR_MATCH_SCHEDULE_STATE_INVALID
    assert isinstance(body["message"], str)
    assert body["message"] != ""


def test_a_league_missing_roster_lock_at_fails_the_schema_gate(api):
    """One of the nine no-default league inputs is omitted and nothing is stored.

    PRD 3.1: "Four instants complete the league definition and they must be
    supplied in a consistent order: `registration_opens_at` and
    `registration_closes_at` bracket the registration window, with the close
    strictly after the open; `roster_lock_at` is the earliest instant from which
    rosters may be locked and must be at or after `registration_closes_at`"

    Design: Corner/entities/league_create_missing_roster_lock_at_returns_422_validation
    """
    s, parent = _section_and_open_parent_league(api)
    payload = {
        "section_id": s.section["id"],
        "parent_league_id": parent["id"],
        "tier": TIER_DISTRICT,
        "ntrp_level": 3.5,
        "age_group": AGE_18_OVER,
        "format": FORMAT_MENS_DOUBLES,
        "lines_per_match": 3,
        "registration_opens_at": "2026-08-01T00:00:00Z",
        "registration_closes_at": "2026-08-10T00:00:00Z",
        "season_end_at": "2026-09-30T00:00:00Z",
    }
    response = api.create_league(payload, SECTION_ADMIN)
    validate_error(response, ERR_VALIDATION, 422)
    assert response.json()["data"]["error_id"] != ERR_LEAGUE_LADDER_INVALID

    children, _meta = validate_paginated(
        api.list_leagues(
            SECTION_ADMIN,
            {"parent_league_id": parent["id"], "limit": 100, "offset": 0},
        )
    )
    assert children == []


def test_a_rating_off_the_half_step_lattice_is_refused_by_its_own_rule(api):
    """3.7 is a well-typed number and still fails the dedicated level rule.

    PRD 2.9: "`ERR_INVALID_RATING_LEVEL` - any supplied or requested level is a
    multiple of 0.5 within 2.5 to 5.0."

    Design: Corner/entities/rating_assign_with_level_off_the_half_step_returns_invalid_rating_level
    """
    s, _parent = _section_and_open_parent_league(api)
    s.add_player("p1", full_name="Adam Ace")
    assert s.refresh_player("p1")["rating_type"] == RATING_UNRATED

    response = api.assign_rating(
        s.player_id("p1"),
        f.rating_payload(3.7, RATING_SOURCE_COMPUTER),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_INVALID_RATING_LEVEL, 422)
    assert response.json()["data"]["error_id"] != ERR_VALIDATION

    stored = s.refresh_player("p1")
    assert stored["rating_type"] == RATING_UNRATED
    assert stored["rating_level"] is None
    assert stored["rating_history"] == []


def test_an_unknown_payload_key_is_refused_rather_than_silently_dropped(api):
    """Seeding a system field is a hard failure and enrols nobody.

    PRD 2.9: "`ERR_VALIDATION` - required fields present, no unknown fields, every
    enum value a declared member."

    Design: Corner/entities/player_create_with_unknown_payload_field_returns_422_validation_and_stores_nothing
    """
    s, _parent = _section_and_open_parent_league(api)
    response = api.create_player(
        {
            "section_id": s.section["id"],
            "full_name": "Ghost Player",
            "birth_year": 1990,
            "gender": GENDER_M,
            "rating_level": 5.0,
        },
        SECTION_ADMIN,
    )
    validate_error(response, ERR_VALIDATION, 422)

    players, meta = validate_paginated(
        api.list_players(
            SECTION_ADMIN,
            {"section_id": s.section["id"], "limit": 100, "offset": 0},
        )
    )
    assert players == []
    assert meta["total_count"] == 0


def test_pagination_metadata_describes_the_filtered_set_not_the_page(api):
    """Three players over two pages of two report total_count 3 on both pages.

    PRD 2.3: "Players may be listed filtered by `section_id`, by `status`, by
    `rating_type` and by `gender`."

    Design: Corner/entities/player_list_paginated_reports_full_total_count_on_every_page
    """
    s, _parent = _section_and_open_parent_league(api)
    s.add_player("p1", full_name="Adam Ace")
    s.add_player("p2", full_name="Ben Baseline")
    s.add_player("pf", full_name="Fay Forehand", gender=GENDER_F)

    first, first_meta = validate_paginated(
        api.list_players(
            SECTION_ADMIN,
            {"section_id": s.section["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second, second_meta = validate_paginated(
        api.list_players(
            SECTION_ADMIN,
            {"section_id": s.section["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    women, women_meta = validate_paginated(
        api.list_players(
            SECTION_ADMIN,
            {"section_id": s.section["id"], "gender": GENDER_F, "limit": 100, "offset": 0},
        )
    )
    assert women_meta["total_count"] == 1
    assert women[0]["id"] == s.player_id("pf")


def _child_league_open_with_one_active_and_one_pending_spot(api):
    """A DRAFT team holding one ACTIVE and one PENDING spot in an open child league."""
    s, parent = _section_and_open_parent_league(api)
    child = s.create_league(
        **dict(
            LADDER_LEAGUE_KWARGS,
            parent_league_id=parent["id"],
            tier=TIER_DISTRICT,
            max_teams=4,
            registration_closes_at="2026-08-10T00:00:00Z",
            roster_lock_at="2026-08-10T00:00:00Z",
            season_end_at="2026-09-30T00:00:00Z",
        )
    )
    s.open_registration(child)
    s.create_facility()
    s.add_player("p1", level=3.5, full_name="Adam Ace")
    s.add_player("p2", level=3.5, full_name="Ben Baseline")
    s.create_team("th", "p1", "Balboa Aces")
    s.add_spot("th", "p1")
    s.activate_spot("th", "p1")
    s.add_spot("th", "p2")
    return s


def test_the_active_roster_measure_ignores_the_pending_spot_the_cap_counts(api):
    """One activation of two adds leaves active_roster_size at 1 and two spots on file.

    PRD 3.3: "Activation then recomputes the team's `active_roster_size` (its count
    of spots at `ACTIVE`), its `playoff_eligible_roster_size` (its count of spots
    at `ACTIVE` whose `playoff_eligible` is true) and its `roster_compliant` flag,
    which is true exactly when `active_roster_size` is at least the league's
    `min_active_roster_size`."

    Design: Corner/entities/team_roster_counters_count_active_only_while_cap_counts_pending_too
    """
    s = _child_league_open_with_one_active_and_one_pending_spot(api)
    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["playoff_eligible_roster_size"] == 0
    assert team["roster_compliant"] is False
    assert team["status"] == TEAM_DRAFT
    assert team["captain_player_id"] == s.player_id("p1")
    assert team["advanced_from_team_id"] is None
    assert team["playoff_seed"] is None

    activated = s.refresh_spot("p1")
    assert activated["status"] == SPOT_ACTIVE
    assert activated["level_at_add"] == 3.5
    pending = s.refresh_spot("p2")
    assert pending["status"] == SPOT_PENDING
    assert pending["level_at_add"] is None

    spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": team["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert len(spots) == 2


def _one_ballot_cast_on_an_appeal_under_review(api):
    """An UNDER_REVIEW UP appeal carrying exactly one SUPPORT ballot."""
    s, _parent = _section_and_open_parent_league(api)
    s.add_player("p1", level=3.5, full_name="Adam Ace")
    s.add_player("pch", full_name="Chair Coleman")
    s.add_player("pc1", full_name="Mel Member")

    appeal = get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(
                s.player_id("p1"),
                APPEAL_UP,
                4.0,
                reason="Results across the season support a higher level",
            ),
            make_player_headers(s.player_id("p1")),
        ),
        201,
    )
    get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    vote = get_success_data(
        api.create_committee_vote(
            f.vote_payload(
                appeal["id"],
                VOTE_SUPPORT,
                SUBJECT_RATING_APPEAL,
                note="Dynamic rating supports the move.",
            ),
            s.member_headers("pc1"),
        ),
        201,
    )
    return s, appeal, vote


def test_a_committee_ballot_carries_no_version_and_cannot_be_recast(api):
    """The append-only vote exposes neither version nor updated_at.

    PRD 2.2: "`CommitteeVote` is the exception. A committee vote is an append-only
    record: it carries only `id` and `created_at`. It has no `updated_at` field and
    no `version` field, because it is never modified after it is cast."

    Design: Corner/entities/committee_vote_exposes_no_version_and_second_ballot_is_rejected
    """
    s, appeal, vote = _one_ballot_cast_on_an_appeal_under_review(api)
    validate_error(
        api.create_committee_vote(
            f.vote_payload(appeal["id"], VOTE_OPPOSE, SUBJECT_RATING_APPEAL),
            s.member_headers("pc1"),
        ),
        ERR_DUPLICATE_VOTE,
        409,
    )

    stored = get_success_data(api.get_committee_vote(vote["id"], SECTION_ADMIN))
    assert stored["vote"] == VOTE_SUPPORT
    assert stored["note"] == "Dynamic rating supports the move."
    assert "version" not in stored
    assert "updated_at" not in stored
    assert is_iso8601_timestamp(stored["created_at"])

    reread = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert reread["support_vote_count"] == 1
    assert reread["oppose_vote_count"] == 0

    votes, meta = validate_paginated(
        api.list_player_committee_votes(
            s.player_id("pc1"), SECTION_ADMIN, {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert len(votes) == 1


def test_a_district_league_without_a_parent_breaks_the_ladder_rule(api):
    """The parent link is biconditional, so a null on a DISTRICT rung is refused.

    PRD 3.1: "Any violation of that composite rule - wrong tier distance,
    mismatched level, mismatched age group, mismatched format, a null where one is
    required or a value where null is required - is refused with
    `ERR_LEAGUE_LADDER_INVALID`."

    Design: Corner/entities/league_create_district_tier_with_null_parent_returns_league_ladder_invalid
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()

    response = api.create_league(
        {
            "section_id": s.section["id"],
            "parent_league_id": None,
            "tier": TIER_DISTRICT,
            "ntrp_level": 3.5,
            "age_group": AGE_18_OVER,
            "format": FORMAT_MENS_DOUBLES,
            "lines_per_match": 3,
            "registration_opens_at": "2026-08-01T00:00:00Z",
            "registration_closes_at": "2026-08-10T00:00:00Z",
            "roster_lock_at": "2026-08-10T00:00:00Z",
            "season_end_at": "2026-09-30T00:00:00Z",
        },
        SECTION_ADMIN,
    )
    validate_error(response, ERR_LEAGUE_LADDER_INVALID, 422)
    assert response.json()["data"]["error_id"] != ERR_VALIDATION

    _leagues, meta = validate_paginated(
        api.list_leagues(
            SECTION_ADMIN,
            {"section_id": s.section["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_a_home_facility_from_another_section_is_out_of_scope_not_mismatched(api):
    """Two rules could fire on the same foreign key and the scope rule answers.

    PRD 2.10: "A payload foreign key that *does* resolve but belongs to a different
    `Section` than the target resource is refused with `ERR_SECTION_SCOPE_MISMATCH`
    (HTTP 404): players, leagues, facilities and teams never cross section
    boundaries. This scoping rule guards league creation, facility creation, team
    creation, roster-spot creation, fixture creation and strike issuance."

    Design: Corner/entities/team_create_naming_a_facility_of_another_section_returns_section_scope_mismatch
    """
    s, parent = _section_and_open_parent_league(api)
    s.create_facility()
    child = s.create_league(
        **dict(
            LADDER_LEAGUE_KWARGS,
            parent_league_id=parent["id"],
            tier=TIER_DISTRICT,
            max_teams=4,
            registration_closes_at="2026-08-10T00:00:00Z",
            roster_lock_at="2026-08-10T00:00:00Z",
            season_end_at="2026-09-30T00:00:00Z",
        )
    )
    s.open_registration(child)
    s.add_player("p1", level=3.5, full_name="Adam Ace")

    other_section = get_success_data(
        api.create_section(
            f.section_payload(code="NORCAL-2026", name="Northern California Section"),
            SECTION_ADMIN,
        ),
        201,
    )
    foreign_facility = get_success_data(
        api.create_facility(
            f.facility_payload(
                other_section["id"], name="Golden Gate Courts", court_count=4
            ),
            SECTION_ADMIN,
        ),
        201,
    )

    response = api.create_team(
        f.team_payload(child["id"], foreign_facility["id"], name="Cross Section Crew"),
        make_captain_headers(s.player_id("p1")),
    )
    validate_error(response, ERR_SECTION_SCOPE_MISMATCH, 404)
    assert response.json()["data"]["error_id"] != ERR_FACILITY_SECTION_MISMATCH

    _teams, meta = validate_paginated(
        api.list_teams(
            SECTION_ADMIN, {"league_id": child["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert get_success_data(api.get_league(child["id"], LEAGUE_COORDINATOR))[
        "registered_team_count"
    ] == 0
