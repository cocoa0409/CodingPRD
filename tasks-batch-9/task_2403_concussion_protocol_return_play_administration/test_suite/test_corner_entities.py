"""
Entity-level contract tests for the Concussion Protocol & Return-to-Play API.

This module covers the persisted resource types at their edges: the fields the
server derives on creation (clubs, players, games), the uniqueness and range
constraints the PRD attaches to their inputs, the entity-specific not-found
errors, body foreign-key resolution, collection reads with filters and
pagination, and the immediate visibility of a diagnosis' cascaded effects.

The server is restarted before every test, so every test builds the state it
needs from an empty database.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_NOT_FOUND,
    ERR_CLINICIAN_NOT_FOUND,
    ERR_CLUB_NOT_FOUND,
    ERR_EVALUATION_NOT_FOUND,
    ERR_GAME_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PLAYER_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNIQUENESS_VIOLATION,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR_A,
    make_club_physician_headers,
    make_compliance_officer_headers,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_MS = "2026-08-01T00:00:00.000Z"


def test_club_creation_seeds_every_derived_compliance_and_slot_field(api):
    """A club registration returns a fully seeded compliance posture and slot ledger.

    PRD: "Everything else about a club is derived: it opens with `compliance_score` and `adjudicated_compliance_score` both at 100, `escalation_tier` at `TIER_0`, `status` at `ACTIVE`, `outstanding_fine_cents` at 0, `open_violation_count` at 0, `exemption_slots_used` at 0, and `exemption_slots_available` equal to its declared total."

    Design: Corner/entities/club_creation_initialises_compliance_and_slot_fields
    """
    # Arrange: pin the logical clock to the instant the row will be stamped with.
    fx.set_clock(api, DEFAULT_CLOCK)

    # Act: register a club supplying only the three accepted inputs.
    response = api.create_club(
        f.club_payload(
            name="Harbor City Kraken", market_code="HCK", exemption_slots_total=3
        ),
        ADMIN,
    )
    club = validate_success(response, 201)

    # Assert: the stored inputs, the derived posture and the derived slot ledger.
    assert club["name"] == "Harbor City Kraken"
    assert club["market_code"] == "HCK"
    a.assert_club_posture(
        club,
        compliance_score=100,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=0,
        open_violation_count=0,
        adjudicated_compliance_score=100,
    )
    a.assert_exemption_slots(club, used=0, available=3, total=3)
    a.assert_common_fields(club, expected_version=1)
    a.assert_instant(club["created_at"], DEFAULT_CLOCK_MS)
    a.assert_instant(club["updated_at"], DEFAULT_CLOCK_MS)

    # Assert on re-read state: nothing was computed only for the response body.
    stored = fx.read_club(api, club["id"])
    a.assert_club_posture(
        stored,
        compliance_score=100,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=0,
        open_violation_count=0,
        adjudicated_compliance_score=100,
    )
    a.assert_exemption_slots(stored, used=0, available=3, total=3)
    assert stored["version"] == 1


def test_club_duplicate_market_code_is_refused(api):
    """A second club reusing an existing market_code is refused league-wide.

    PRD: "A club is registered with a `name` between 1 and 80 characters and a `market_code` of exactly three uppercase letters that must be unique across all clubs; a collision on that code is refused with `ERR_UNIQUENESS_VIOLATION`."

    Design: Corner/entities/club_duplicate_market_code_rejected
    """
    # Arrange: one club already holds market_code HCK.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act: register a different club reusing that same code.
    response = api.create_club(
        f.club_payload(
            name="Harbor City Krakens B", market_code="HCK", exemption_slots_total=2
        ),
        ADMIN,
    )

    # Assert: refused at 409, and the incumbent row is untouched.
    validate_error(response, ERR_UNIQUENESS_VIOLATION, 409)
    stored = fx.read_club(api, club["id"])
    assert stored["name"] == "Harbor City Kraken"
    assert stored["market_code"] == "HCK"
    assert stored["version"] == 1


def test_club_omitting_exemption_slots_total_applies_the_default_of_three(api):
    """Omitting the optional exemption_slots_total seeds the declared default.

    PRD: "Each club declares `exemption_slots_total`, the number of concussion roster exemptions it may hold simultaneously; the value must lie between 1 and 5 inclusive and defaults to 3 when the club is created without one."

    Design: Corner/entities/club_default_exemption_slots_total_applied
    """
    # Arrange
    fx.set_clock(api, DEFAULT_CLOCK)

    # Act: register a club with the optional slot total left out of the body.
    response = api.create_club(
        f.club_payload(
            name="Ridgeway Sentinels", market_code="RWS", exemption_slots_total=f.OMIT
        ),
        ADMIN,
    )
    club = validate_success(response, 201)

    # Assert: the default total, with the two counters conserved against it.
    a.assert_exemption_slots(club, used=0, available=3, total=3)

    # Assert on re-read state.
    stored = fx.read_club(api, club["id"])
    a.assert_exemption_slots(stored, used=0, available=3, total=3)


def test_player_creation_exposes_computed_readiness_fields(api):
    """A brand-new player's readiness fields are computed, not accepted from input.

    PRD: "A new player starts with `baseline_status` at `NONE`, `availability_status` at `AVAILABLE`, `public_injury_designation` at `NONE`, and `diagnosed_case_count` at 0."

    Design: Corner/entities/player_creation_exposes_computed_readiness_fields
    """
    # Arrange: a club to hold the roster; no baseline test is filed.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act
    response = api.create_player(
        f.player_payload(
            club_id=club["id"], full_name="K Mbeki", jersey_number=24, position="WR"
        ),
        ADMIN,
    )
    player = validate_success(response, 201)

    # Assert: the four derived readiness fields plus the system-managed set.
    assert player["baseline_status"] == "NONE"
    assert player["availability_status"] == "AVAILABLE"
    assert player["public_injury_designation"] == "NONE"
    assert player["diagnosed_case_count"] == 0
    a.assert_common_fields(player, expected_version=1)

    # Assert on re-read state.
    stored = fx.read_player(api, player["id"])
    assert stored["baseline_status"] == "NONE"
    assert stored["availability_status"] == "AVAILABLE"
    assert stored["public_injury_designation"] == "NONE"
    assert stored["diagnosed_case_count"] == 0
    assert stored["version"] == 1


def test_jersey_number_is_unique_per_club_while_license_number_is_league_wide(api):
    """Jersey numbers collide only inside one club; licence numbers collide everywhere.

    PRD: "`ERR_UNIQUENESS_VIOLATION` (409) — a duplicate `market_code` across clubs, a duplicate `license_number` across clinicians, or a duplicate `jersey_number` within one club."

    Design: Corner/entities/jersey_number_and_license_number_uniqueness_enforced
    """
    # Arrange: two clubs, one clinician holding LIC-1001, one player wearing 24.
    fx.set_clock(api, DEFAULT_CLOCK)
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    fx.create_club_physician(api, club_h["id"], "Dr Vance", "LIC-1001")
    fx.create_player(api, club_h["id"], "K Mbeki", 24, "WR")

    # Act 1: reuse jersey 24 inside the club that already wears it.
    same_club = api.create_player(
        f.player_payload(
            club_id=club_h["id"], full_name="R Silva", jersey_number=24, position="DB"
        ),
        ADMIN,
    )

    # Act 2: reuse jersey 24 at the other club.
    other_club = api.create_player(
        f.player_payload(
            club_id=club_r["id"], full_name="R Silva", jersey_number=24, position="DB"
        ),
        ADMIN,
    )

    # Act 3: reuse licence LIC-1001 at the other club.
    duplicate_licence = api.create_clinician(
        f.club_physician_payload(
            club_id=club_r["id"], full_name="Dr Kaur", license_number="LIC-1001"
        ),
        ADMIN,
    )

    # Assert: club-scoped jersey uniqueness, league-wide licence uniqueness.
    validate_error(same_club, ERR_UNIQUENESS_VIOLATION, 409)
    accepted = validate_success(other_club, 201)
    assert accepted["jersey_number"] == 24
    assert accepted["club_id"] == club_r["id"]
    validate_error(duplicate_licence, ERR_UNIQUENESS_VIOLATION, 409)

    # Assert on re-read state: exactly one extra player exists, at Ridgeway.
    rows, meta = validate_paginated(api.list_players(ADMIN, club_id=club_r["id"]))
    a.assert_page_meta(meta, total_count=1)
    a.assert_ids_equal(rows, [accepted["id"]])
    clinicians, clinician_meta = validate_paginated(api.list_clinicians(ADMIN))
    a.assert_page_meta(clinician_meta, total_count=1)
    assert clinicians[0]["license_number"] == "LIC-1001"


def test_out_of_enum_and_out_of_range_inputs_are_refused_as_invalid_request(api):
    """An unknown enum member and out-of-range integers are refused before any write.

    PRD: "Required fields present, JSON types correct, enum members recognised, and integers inside their declared ranges — `symptom_score` from 0 to 20, `composite_score` from 0 to 100, `reaction_time_ms` from 200 to 1500, `stage_index` from 1 to 5, `exposure_days` from 0 to 30, `jersey_number` from 0 to 99, `week_index` from 1 to 18, `season_year` from 2020 to 2100, `exemption_slots_total` from 1 to 5, `limit` from 1 to 100, `offset` at least 0 — all bounds inclusive."

    Design: Corner/entities/enum_and_range_constraints_rejected_as_invalid_request
    """
    # Arrange
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act 1: a position outside the declared enumeration.
    bad_position = api.create_player(
        f.player_payload(
            club_id=club["id"],
            full_name="Bad Position",
            jersey_number=12,
            position="GOALIE",
        ),
        ADMIN,
    )

    # Act 2: a jersey number above the inclusive upper bound of 99.
    bad_jersey = api.create_player(
        f.player_payload(
            club_id=club["id"], full_name="Bad Number", jersey_number=100, position="WR"
        ),
        ADMIN,
    )

    # Act 3: an exemption slot total above the inclusive upper bound of 5.
    bad_slots = api.create_club(
        f.club_payload(
            name="Overslotted FC", market_code="OVS", exemption_slots_total=6
        ),
        ADMIN,
    )

    # Assert: each refusal is the schema-rung error at HTTP 400.
    for response in (bad_position, bad_jersey, bad_slots):
        validate_error(response, ERR_INVALID_REQUEST, 400)

    # Assert on re-read state: no partial row was written by any of the three.
    rows, meta = validate_paginated(api.list_players(ADMIN))
    a.assert_page_meta(meta, total_count=0)
    assert rows == []
    stored = fx.read_club(api, club["id"])
    assert stored["exemption_slots_total"] == 3


def test_baseline_test_without_composite_score_is_refused(api):
    """composite_score is a required baseline input with no default.

    PRD: "A `ClubPhysician` files a pre-season baseline for a player of their own club, supplying the `player_id`, the `season_year` the baseline is filed for, a `composite_score`, a `reaction_time_ms`, a `symptom_score` capturing the player's resting symptom burden, and the `expected_player_version` demanded by §2.6."

    Design: Corner/entities/baseline_test_missing_required_field_rejected
    """
    # Arrange: a club physician and a player of that club with no baseline on file.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    physician = fx.create_club_physician(api, club["id"], "Dr Vance", "LIC-1001")
    player = fx.create_player(api, club["id"], "K Mbeki", 24, "WR")

    # Act: file a baseline with composite_score left out of the body entirely.
    response = api.create_baseline_test(
        f.baseline_payload(
            player_id=player["id"],
            expected_player_version=player["version"],
            season_year=2026,
            composite_score=f.OMIT,
            reaction_time_ms=520,
            symptom_score=0,
        ),
        make_club_physician_headers(physician["id"]),
    )

    # Assert: refused at 400, with no baseline row and no player mutation.
    validate_error(response, ERR_INVALID_REQUEST, 400)
    stored_player = fx.read_player(api, player["id"])
    assert stored_player["baseline_status"] == "NONE"
    assert stored_player["version"] == 1
    rows, meta = validate_paginated(
        api.list_baseline_tests(ADMIN, player_id=player["id"])
    )
    a.assert_page_meta(meta, total_count=0)
    assert rows == []


def test_game_creation_stamps_system_fields_and_opens_scheduled(api):
    """A newly scheduled game is SCHEDULED with server-stamped identity and timestamps.

    PRD: "A game begins `SCHEDULED`."

    Design: Corner/entities/game_system_fields_are_server_assigned
    """
    # Arrange: two clubs, with the logical clock at the stamping instant.
    fx.set_clock(api, DEFAULT_CLOCK)
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)

    # Act
    response = api.create_game(
        f.game_payload(
            home_club_id=club_h["id"],
            away_club_id=club_r["id"],
            season_year=2026,
            week_index=1,
            kickoff_at="2026-09-13T17:00:00Z",
        ),
        ADMIN,
    )
    game = validate_success(response, 201)

    # Assert: the opening status, the server-minted identity and the clock stamps.
    assert game["status"] == "SCHEDULED"
    assert is_valid_uuid(game["id"])
    a.assert_common_fields(game, expected_version=1)
    a.assert_instant(game["created_at"], DEFAULT_CLOCK_MS)
    a.assert_instant(game["updated_at"], DEFAULT_CLOCK_MS)
    a.assert_millisecond_timestamp(game["created_at"])
    assert game["kickoff_at"].startswith("2026-09-13T17:00:00")
    assert game["season_year"] == 2026 and game["week_index"] == 1

    # Assert on re-read state.
    stored = fx.read_game(api, game["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["version"] == 1
    a.assert_instant(stored["created_at"], DEFAULT_CLOCK_MS)


def test_unknown_path_ids_return_the_entity_specific_not_found_error(api):
    """Each resource type refuses an unresolvable path id with its own not-found error.

    PRD: "Every path in this API addresses exactly one resource and names its identifier `{id}`, so path resolution is a single lookup: if the `{id}` does not resolve, the request is refused with the not-found error belonging to that resource type before any body validation, state check or business rule is evaluated."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found_errors
    """
    # Arrange: an empty database, so no id of any type resolves.
    fx.set_clock(api, DEFAULT_CLOCK)

    # Act & Assert: one read per resource type, each with its own error id.
    cases = [
        (api.get_club(NON_EXISTENT_UUID, ADMIN), ERR_CLUB_NOT_FOUND),
        (api.get_player(NON_EXISTENT_UUID, ADMIN), ERR_PLAYER_NOT_FOUND),
        (api.get_clinician(NON_EXISTENT_UUID, ADMIN), ERR_CLINICIAN_NOT_FOUND),
        (api.get_game(NON_EXISTENT_UUID, ADMIN), ERR_GAME_NOT_FOUND),
        (
            api.get_sideline_evaluation(NON_EXISTENT_UUID, ADMIN),
            ERR_EVALUATION_NOT_FOUND,
        ),
        (api.get_concussion_case(NON_EXISTENT_UUID, ADMIN), ERR_CASE_NOT_FOUND),
        (api.get_return_step(NON_EXISTENT_UUID, ADMIN), ERR_RESOURCE_NOT_FOUND),
    ]
    for response, expected_error_id in cases:
        validate_error(response, expected_error_id, 404)
        a.assert_error_envelope(response)


def test_clinician_listing_filters_by_affiliation_and_paginates(api):
    """Filtered listings page over the filtered set and report it in meta.

    PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

    Design: Corner/entities/clinician_listing_filters_and_paginates
    """
    # Arrange: two club-affiliated clinicians and one independent consultant.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    doc_one = fx.create_club_physician(api, club["id"], "Dr Vance", "LIC-1001")
    doc_two = fx.create_club_physician(api, club["id"], "Dr Nakamura", "LIC-1002")
    consultant = fx.create_consultant(api, "Dr Iyer", "LIC-3001")

    # Act: page the CLUB_AFFILIATED subset one row at a time.
    first_rows, first_meta = validate_paginated(
        api.list_clinicians(ADMIN, affiliation="CLUB_AFFILIATED", limit=1, offset=0)
    )
    second_rows, second_meta = validate_paginated(
        api.list_clinicians(ADMIN, affiliation="CLUB_AFFILIATED", limit=1, offset=1)
    )
    club_rows, club_meta = validate_paginated(
        api.list_clinicians(ADMIN, club_id=club["id"])
    )

    # Assert: total_count counts the filtered set, has_more tracks the page edge.
    assert len(first_rows) == 1
    a.assert_page_meta(first_meta, total_count=2, limit=1, offset=0, has_more=True)
    assert len(second_rows) == 1
    a.assert_page_meta(second_meta, total_count=2, limit=1, offset=1, has_more=False)

    # Assert: the two pages are disjoint and together cover the filtered set.
    paged_ids = {first_rows[0]["id"], second_rows[0]["id"]}
    assert paged_ids == {doc_one["id"], doc_two["id"]}
    assert consultant["id"] not in paged_ids

    # Assert: the club_id filter also excludes the consultant, whose club_id is null.
    a.assert_page_meta(club_meta, total_count=2)
    a.assert_only_ids(club_rows, [doc_one["id"], doc_two["id"]])


def test_evaluation_naming_an_unknown_player_is_refused_with_player_not_found(api):
    """A body foreign key that names no row yields the referenced type's not-found error.

    PRD: "Every foreign key supplied in a request body — `club_id`, `player_id`, `game_id`, `inc_clinician_id`, `case_id`, `sideline_evaluation_id` — resolves to an existing row, else the matching not-found error for the referenced type (`ERR_CLUB_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_EVALUATION_NOT_FOUND`), all at HTTP 404."

    Design: Corner/entities/evaluation_with_unknown_player_reference_rejected
    """
    # Arrange: a live week-1 game and an authorised club physician.
    ctx = fx.setup_live_game(api)

    # Act: initiate an evaluation naming a player_id that resolves to nothing.
    response = api.create_sideline_evaluation(
        f.evaluation_payload(
            NON_EXISTENT_UUID, ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
        ),
        ctx["doc_h_headers"],
    )

    # Assert: refused at 404 for the referenced type, and no evaluation exists.
    validate_error(response, ERR_PLAYER_NOT_FOUND, 404)
    rows, meta = validate_paginated(api.list_sideline_evaluations(ADMIN))
    a.assert_page_meta(meta, total_count=0)
    assert rows == []


def test_audit_naming_an_unknown_case_is_refused_with_case_not_found(api):
    """The optional case_id on an audit is still resolved before the audit is opened.

    PRD: "Every foreign key supplied in a request body — `club_id`, `player_id`, `game_id`, `inc_clinician_id`, `case_id`, `sideline_evaluation_id` — resolves to an existing row, else the matching not-found error for the referenced type (`ERR_CLUB_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_EVALUATION_NOT_FOUND`), all at HTTP 404."

    Design: Corner/entities/audit_with_unknown_case_reference_rejected
    """
    # Arrange: a real club, but no concussion case anywhere in the database.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act: open an audit against the real club naming an unknown case.
    response = api.create_protocol_audit(
        f.audit_payload(club_id=club["id"], case_id=NON_EXISTENT_UUID), AUDITOR_A
    )

    # Assert: refused at 404, with no audit row and no club-side accounting.
    validate_error(response, ERR_CASE_NOT_FOUND, 404)
    rows, meta = validate_paginated(
        api.list_protocol_audits(ADMIN, club_id=club["id"])
    )
    a.assert_page_meta(meta, total_count=0)
    assert rows == []
    stored = fx.read_club(api, club["id"])
    assert stored["open_violation_count"] == 0
    assert stored["version"] == 1


def test_player_read_echoes_roster_data_and_appears_in_the_club_sub_listing(api):
    """A player reads back with its roster data and is reachable through its club.

    PRD: "`GET /concussion-program/clubs/{id}/players` filters on `availability_status` and `baseline_status`."

    Design: Corner/entities/player_retrieval_returns_stored_and_linked_data
    """
    # Arrange: one club with one player and no baseline on file.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    player = fx.create_player(api, club["id"], "K Mbeki", 24, "WR")

    # Act: read the player directly, then through the club's filtered sub-listing.
    direct = validate_success(api.get_player(player["id"], ADMIN), 200)
    rows, meta = validate_paginated(
        api.list_club_players(
            club["id"],
            make_compliance_officer_headers(club["id"]),
            availability_status="AVAILABLE",
        )
    )

    # Assert: the stored roster data and the club foreign key are echoed.
    assert direct["id"] == player["id"]
    assert direct["full_name"] == "K Mbeki"
    assert direct["jersey_number"] == 24
    assert direct["position"] == "WR"
    assert direct["club_id"] == club["id"]

    # Assert: the same row is the only AVAILABLE player of that club.
    a.assert_page_meta(meta, total_count=1)
    a.assert_ids_equal(rows, [player["id"]])
    assert rows[0]["availability_status"] == "AVAILABLE"


def test_diagnosis_effects_are_visible_immediately_without_a_sweep(api):
    """The diagnosis cascade is visible to reads issued straight after the write.

    PRD: "The player's `availability_status` becomes `PROTOCOL_RESTRICTED`, `public_injury_designation` becomes `OUT`, and `diagnosed_case_count` increases by 1."

    Design: Corner/consistency model/diagnosis_response_reflects_every_immediate_effect
    """
    # Arrange: the consultant-attended examination under way since 18:10.
    ctx = fx.setup_locker_room_exam(api)
    fx.set_clock(api, fx.DIAGNOSIS_AT)

    # Act: document the concussion nine whole minutes into the examination.
    case = get_success_data(
        api.diagnose_concussion(
            ctx["eval_id"],
            f.diagnose_payload(symptom_score=9, composite_score=70),
            ctx["doc_h_headers"],
        )
    )

    # Assert: the write's own response already carries the computed case figures.
    a.assert_case_dimensions(
        case,
        case_status="MANDATORY_REMOVAL",
        monitoring_status="ACTIVE_SYMPTOM_WATCH",
        roster_exemption_status="NONE",
    )
    a.assert_case_progress(
        case, rtp_stage=0, recurrence_count=0, severity_index=fx.CANONICAL_SEVERITY_INDEX
    )
    a.assert_instant(case["projected_return_at"], fx.CANONICAL_PROJECTED_RETURN_AT)
    a.assert_instant(case["diagnosis_at"], fx.DIAGNOSIS_AT_MS)

    # Assert on re-read state, with no sweep and no second write in between.
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "PROTOCOL_RESTRICTED"
    assert player["public_injury_designation"] == "OUT"
    assert player["baseline_status"] == "RETEST_REQUIRED"
    assert player["diagnosed_case_count"] == 1

    baseline = fx.read_baseline(api, ctx["baseline_id"])
    assert baseline["retest_required_reason"] == "NEW_DIAGNOSIS"
    assert baseline["status"] == "VALID"

    evaluation = fx.read_evaluation(api, ctx["eval_id"])
    assert evaluation["status"] == "DIAGNOSED"
    assert evaluation["diagnosis_outcome"] == "CONCUSSION"
    assert evaluation["exam_duration_minutes"] == 9
    a.assert_instant(evaluation["exam_completed_at"], fx.DIAGNOSIS_AT_MS)
