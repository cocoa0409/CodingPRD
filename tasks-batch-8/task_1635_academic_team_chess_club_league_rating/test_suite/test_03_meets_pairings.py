"""Meet scheduling, calendar occupation, and pairing handshake claims (PRD §2.7, §3.3, §3.4, §3.9)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_version_incremented,
    create_club,
    create_coach,
    create_meet,
    create_meet_payload,
    create_meet_proctor,
    create_pairing,
    create_pairing_payload,
    create_player,
    create_waived_membership,
    get_club,
    make_club_coach_headers,
    publish_pairings,
    report_and_confirm,
    report_result,
    run_meet,
    schedule_meet,
    setup_two_club_league,
    confirm_pairing,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def _standings_row(api, season_id, club_id, headers):
    data = validate_success(api.get_standings(season_id, headers))
    rows = data["standings"]
    for row in rows:
        if row["club_id"] == club_id:
            return row
    raise AssertionError(f"club {club_id} missing from standings: {rows}")

def test_meet_initial_state_draft(api, federation_admin_headers):
    """PRD §3.3: "The two clubs must differ — a meet pitting a club against itself is
    rejected with `ERR_SAME_CLUB_MEET` — and the meet begins in `DRAFT`."
    PRD §3.3: occupation is checked against "another meet in `SCHEDULED`,
    `PAIRINGS_PUBLISHED`, or `IN_PROGRESS`" — a DRAFT meet occupies no date.

    Design: Corner/state_machines/meet_initial_state_draft
    """
    ctx = setup_two_club_league()
    season_id = ctx["season"]["id"]
    meet1 = validate_success(
        api.create_meet(
            create_meet_payload(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"],
                                scheduled_date="2026-09-05"),
            federation_admin_headers,
        ),
        201,
    )
    assert meet1["status"] == "DRAFT", "a newly created meet is DRAFT, not SCHEDULED"

    # A second meet between the same clubs on the same date schedules fine while the
    # first is still DRAFT: DRAFT holds no calendar slot.
    meet2 = create_meet(season_id, ctx["club_b"]["id"], ctx["club_a"]["id"], "2026-09-05")
    scheduled = validate_success(api.schedule_meet(meet2["id"], federation_admin_headers))
    assert scheduled["status"] == "SCHEDULED"

def test_meet_postpone_reschedule_two_laps(api, federation_admin_headers):
    """PRD §3.3: "A coach of either club or the administrator may postpone a `SCHEDULED`
    meet, moving it to `POSTPONED`; a postponed meet occupies no date at all, releasing
    the calendar slot for both clubs. The administrator may later reschedule a
    `POSTPONED` meet back to `SCHEDULED` by supplying a new `scheduled_date`".

    Design: Difficulty/non_linear_state_machine/meet_postpone_reschedule_cycle
    """
    ctx = setup_two_club_league()
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")

    meet = validate_success(api.schedule_meet(meet["id"], federation_admin_headers))
    assert meet["status"] == "SCHEDULED"
    meet = validate_success(api.postpone_meet(meet["id"], federation_admin_headers))
    assert meet["status"] == "POSTPONED"
    meet = validate_success(
        api.reschedule_meet(meet["id"], {"scheduled_date": "2026-09-06"}, federation_admin_headers)
    )
    assert meet["status"] == "SCHEDULED"
    assert meet["scheduled_date"] == "2026-09-06"
    meet = validate_success(api.postpone_meet(meet["id"], federation_admin_headers))
    assert meet["status"] == "POSTPONED"
    meet = validate_success(
        api.reschedule_meet(meet["id"], {"scheduled_date": "2026-09-07"}, federation_admin_headers)
    )
    assert meet["status"] == "SCHEDULED", "two full postpone/reschedule laps are legal"
    assert meet["scheduled_date"] == "2026-09-07"

def test_meet_cycle_increments_version_each_hop(api, federation_admin_headers):
    """PRD §2.4: "`version` (integer): a system-managed integer that starts at its
    initial value on creation and increments by one with every mutation of the
    resource; it anchors optimistic concurrency control where §2.7 applies."

    Design: Difficulty/non_linear_state_machine/meet_postpone_reschedule_cycle
    """
    ctx = setup_two_club_league()
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    previous = meet["version"]

    hops = [
        api.schedule_meet(meet["id"], federation_admin_headers),
        api.postpone_meet(meet["id"], federation_admin_headers),
        api.reschedule_meet(meet["id"], {"scheduled_date": "2026-09-06"}, federation_admin_headers),
        api.postpone_meet(meet["id"], federation_admin_headers),
        api.reschedule_meet(meet["id"], {"scheduled_date": "2026-09-07"}, federation_admin_headers),
    ]
    for hop in hops:
        current = validate_success(hop)
        assert_version_incremented(current["version"], previous)
        previous = current["version"]
    final = validate_success(api.get_meet(meet["id"], federation_admin_headers))
    assert final["version"] == previous
    assert final["status"] == "SCHEDULED"

def test_meet_whole_day_same_date_conflict(api, federation_admin_headers):
    """PRD §3.3: "neither club may already occupy the `scheduled_date` with another meet
    in `SCHEDULED`, `PAIRINGS_PUBLISHED`, or `IN_PROGRESS` — occupation is whole-day,
    so any same-day overlap conflicts (`ERR_MEET_DATE_CONFLICT`)".

    Design: Difficulty/resource_temporal_overlap/meet_whole_day_occupation
    """
    ctx = setup_two_club_league()
    season_id = ctx["season"]["id"]
    club_c = create_club(season_id, name="Gamma", school_name="Gamma HS")
    meet1 = create_meet(season_id, ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet1["id"])

    # Club A (away side here) already occupies 2026-09-05 -> conflict.
    meet2 = create_meet(season_id, club_c["id"], ctx["club_a"]["id"], "2026-09-05")
    res = api.schedule_meet(meet2["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_MEET_DATE_CONFLICT)
    stayed = validate_success(api.get_meet(meet2["id"], federation_admin_headers))
    assert stayed["status"] == "DRAFT", "rejected schedule changes nothing"

def test_meet_whole_day_adjacent_date_free(api, federation_admin_headers):
    """PRD §3.3: "neither club may already occupy the `scheduled_date` with another meet
    in `SCHEDULED`, `PAIRINGS_PUBLISHED`, or `IN_PROGRESS` — occupation is whole-day,
    so any same-day overlap conflicts (`ERR_MEET_DATE_CONFLICT`)". Occupation is by
    calendar date: the adjacent day is free (no buffer, no time-of-day).

    Design: Difficulty/resource_temporal_overlap/meet_whole_day_occupation
    """
    ctx = setup_two_club_league()
    season_id = ctx["season"]["id"]
    club_c = create_club(season_id, name="Gamma", school_name="Gamma HS")
    meet1 = create_meet(season_id, ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet1["id"])

    meet3 = create_meet(season_id, club_c["id"], ctx["club_a"]["id"], "2026-09-06")
    scheduled = validate_success(api.schedule_meet(meet3["id"], federation_admin_headers))
    assert scheduled["status"] == "SCHEDULED"

def test_meet_integrity_beats_temporal(api, federation_admin_headers):
    """PRD §2.10: "Every request is evaluated against a fixed ladder of checks, and the
    first failing rung determines the error returned." Rung 9 is "Business integrity —
    writes attempted by or for a `SUSPENDED` club yield `ERR_CLUB_SUSPENDED` (HTTP
    403)"; rung 12 is "Business temporal rules — a calendar collision on a meet date
    (`ERR_MEET_DATE_CONFLICT`)".

    Design: Difficulty/priority_pair_validation_conflict/meet_integrity_beats_temporal
    """
    ctx = setup_two_club_league()
    season_id = ctx["season"]["id"]
    club_c = create_club(season_id, name="Gamma", school_name="Gamma HS")
    meet1 = create_meet(season_id, ctx["club_a"]["id"], club_c["id"], "2026-09-05")
    # meet2 must exist BEFORE club B is suspended: creating a meet that touches a
    # SUSPENDED club is itself rejected (PRD §3.1), so the suspension happens
    # between creation and scheduling.
    meet2 = create_meet(season_id, ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet1["id"])
    validate_success(api.suspend_club(ctx["club_b"]["id"], federation_admin_headers))

    # Scheduling meet2 violates BOTH the suspension rule (away club SUSPENDED) and
    # the date occupation rule (host club A already holds 2026-09-05): integrity wins.
    res = api.schedule_meet(meet2["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLUB_SUSPENDED)
    assert res.status_code == 403, "integrity (403) outranks temporal (409)"

def test_meet_integrity_rejection_leaves_meet_draft(api, federation_admin_headers):
    """PRD §3.3: "Moving a meet from `DRAFT` to `SCHEDULED` runs four checks, with the
    meet's own state verified first (a meet not in `DRAFT` fails with
    `ERR_MEET_INVALID_STATE`): neither the host nor the away club may be `SUSPENDED`
    (`ERR_CLUB_SUSPENDED`)".

    Design: Difficulty/priority_pair_validation_conflict/meet_integrity_beats_temporal
    """
    ctx = setup_two_club_league()
    season_id = ctx["season"]["id"]
    club_c = create_club(season_id, name="Gamma", school_name="Gamma HS")
    meet1 = create_meet(season_id, ctx["club_a"]["id"], club_c["id"], "2026-09-05")
    # meet2 is created while club B is still in GOOD_STANDING; the suspension
    # lands between creation and scheduling (PRD §3.1 bans creating meet writes
    # that touch a SUSPENDED club).
    meet2 = create_meet(season_id, ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet1["id"])
    validate_success(api.suspend_club(ctx["club_b"]["id"], federation_admin_headers))

    validate_error(
        api.schedule_meet(meet2["id"], federation_admin_headers),
        ApiErrorId.ERR_CLUB_SUSPENDED,
    )
    stayed = validate_success(api.get_meet(meet2["id"], federation_admin_headers))
    assert stayed["status"] == "DRAFT"

def test_meet_cancel_when_completed_rejected(api, federation_admin_headers):
    """PRD §3.3: "Cancellation is terminal and available from `DRAFT`, `SCHEDULED`, or
    `POSTPONED` (any other state fails with `ERR_MEET_INVALID_STATE`)".
    PRD §3.4: "Completion moves the meet to `COMPLETED`, promotes each of the meet's
    `CONFIRMED` proctor assignments to `COMPLETED`".

    Design: Corner/state_machines/meet_cancel_when_completed_rejected
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
        results=["DRAW"], complete=True,
    )
    meet = out["meet"]
    assert meet["status"] == "COMPLETED"

    res = api.cancel_meet(meet["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_MEET_INVALID_STATE)
    after = validate_success(api.get_meet(meet["id"], federation_admin_headers))
    assert after["status"] == "COMPLETED"

    assignments, _ = validate_paginated(
        api.list_proctor_assignments(federation_admin_headers, params={"meet_id": meet["id"]})
    )
    assert assignments[0]["status"] == "COMPLETED", "completion already promoted the proctor"

def test_publish_incomplete_pairings_rejected(api, federation_admin_headers):
    """PRD §3.4: "The administrator publishes pairings only from `SCHEDULED` (state
    checked first, `ERR_MEET_INVALID_STATE`), and only when every round-and-board slot
    in the full grid — every combination of round 1 through `rounds_count` and board 1
    through `boards_count` — is covered by a pairing still in `SCHEDULED`; an
    incomplete grid fails with `ERR_INCOMPLETE_PAIRINGS`."

    Design: Corner/errors/publish_incomplete_pairings_rejected
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"],
                       "2026-09-05", rounds_count=1, boards_count=2)
    schedule_meet(meet["id"])
    create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])

    res = api.publish_pairings(meet["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_INCOMPLETE_PAIRINGS)

def test_meet_complete_unconfirmed_pairings_rejected(api, federation_admin_headers):
    """PRD §3.4: "Completing the meet is the administrator's final step: the meet must
    be `IN_PROGRESS` (state first), and every pairing not already `REPLACED` or
    `CANCELLED` must be `CONFIRMED`, otherwise the completion fails with
    `ERR_UNCONFIRMED_PAIRINGS`."

    Design: Corner/errors/meet_complete_unconfirmed_pairings_rejected
    """
    ctx = setup_two_club_league(players_a=[{}, {}], players_b=[{}, {}])
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[
            (1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
            (1, 2, ctx["players_a"][1]["id"], ctx["players_b"][1]["id"]),
        ],
    )
    g1, g2 = out["pairings"]
    report_and_confirm(g1["id"], "DRAW", ctx["coach_a"]["id"], ctx["coach_b"]["id"])
    report_result(g2["id"], "DRAW", ctx["coach_a"]["id"])  # board 2 stays REPORTED

    res = api.complete_meet(out["meet"]["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_UNCONFIRMED_PAIRINGS)

def test_pairing_confirm_before_report_rejected(api):
    """PRD §3.4: "Confirmation then requires a coach of the *other* club" — and the
    pairing transitions to CONFIRMED only from REPORTED; from SCHEDULED the confirm
    fails with the pairing state error. PRD §2.10 rung 8 lists
    `ERR_PAIRING_INVALID_STATE` among the per-entity state errors (HTTP 409).

    Design: Corner/state_machines/pairing_confirm_before_report_rejected
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    pairing = create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])

    res = api.confirm_pairing(pairing["id"], make_club_coach_headers(ctx["coach_b"]["id"]))
    validate_error(res, ApiErrorId.ERR_PAIRING_INVALID_STATE)
    stayed = validate_success(api.get_pairing(pairing["id"], ADMIN))
    assert stayed["status"] == "SCHEDULED"

def test_pairing_report_requires_meet_in_progress(api, federation_admin_headers):
    """PRD §3.4: "A `ClubCoach` of either the host or the away club reports the outcome
    of a board — the pairing must be in `SCHEDULED` (state checked first,
    `ERR_PAIRING_INVALID_STATE`) and the meet must be `IN_PROGRESS`
    (`ERR_MEET_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/pairing_report_requires_meet_in_progress
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    pairing = create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])
    publish_pairings(meet["id"])  # PAIRINGS_PUBLISHED, not IN_PROGRESS

    res = api.report_result(
        pairing["id"], {"result": "WHITE_WIN"}, make_club_coach_headers(ctx["coach_a"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_MEET_INVALID_STATE)

def test_pairing_report_rejection_keeps_pairing_scheduled(api, federation_admin_headers):
    """PRD §3.4: "the pairing must be in `SCHEDULED` (state checked first,
    `ERR_PAIRING_INVALID_STATE`) and the meet must be `IN_PROGRESS`
    (`ERR_MEET_INVALID_STATE`)". A rejected report mutates nothing.

    Design: Difficulty/cross_entity_state_dependency/pairing_report_requires_meet_in_progress
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    pairing = create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])
    publish_pairings(meet["id"])

    validate_error(
        api.report_result(
            pairing["id"], {"result": "WHITE_WIN"}, make_club_coach_headers(ctx["coach_a"]["id"])
        ),
        ApiErrorId.ERR_MEET_INVALID_STATE,
    )
    stayed = validate_success(api.get_pairing(pairing["id"], federation_admin_headers))
    assert stayed["status"] == "SCHEDULED"

def test_meet_start_requires_confirmed_proctor(api, federation_admin_headers):
    """PRD §3.4: "Starting the meet requires `PAIRINGS_PUBLISHED` (again state first)
    and at least one proctor assignment for the meet in `CONFIRMED`; without one, the
    start fails with `ERR_NO_CONFIRMED_PROCTOR`."

    Design: Difficulty/cross_entity_state_dependency/meet_start_requires_confirmed_proctor
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])
    publish_pairings(meet["id"])
    create_meet_proctor(ctx["coach_a"]["id"], meet["id"], confirm=False)  # ASSIGNED only

    res = api.start_meet(meet["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_NO_CONFIRMED_PROCTOR)

def test_meet_start_rejection_keeps_meet_published(api, federation_admin_headers):
    """PRD §3.4: "Starting the meet requires `PAIRINGS_PUBLISHED` (again state first)
    and at least one proctor assignment for the meet in `CONFIRMED`; without one, the
    start fails with `ERR_NO_CONFIRMED_PROCTOR`."

    Design: Difficulty/cross_entity_state_dependency/meet_start_requires_confirmed_proctor
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    create_pairing(meet["id"], 1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])
    publish_pairings(meet["id"])
    create_meet_proctor(ctx["coach_a"]["id"], meet["id"], confirm=False)

    validate_error(api.start_meet(meet["id"], federation_admin_headers),
                   ApiErrorId.ERR_NO_CONFIRMED_PROCTOR)
    stayed = validate_success(api.get_meet(meet["id"], federation_admin_headers))
    assert stayed["status"] == "PAIRINGS_PUBLISHED"

def test_validation_same_club_meet(api, federation_admin_headers):
    """PRD §3.3: "The two clubs must differ — a meet pitting a club against itself is
    rejected with `ERR_SAME_CLUB_MEET` — and the meet begins in `DRAFT`."

    Design: Corner/validations/validation_same_club_meet
    """
    ctx = setup_two_club_league()
    res = api.create_meet(
        create_meet_payload(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_a"]["id"]),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_SAME_CLUB_MEET)

def test_validation_player_club_mismatch(api, federation_admin_headers):
    """PRD §3.4: "plus a `white_player_id` drawn from the host club and a
    `black_player_id` drawn from the away club. Putting a player on the wrong side of
    the board fails with `ERR_PLAYER_CLUB_MISMATCH`".

    Design: Corner/validations/validation_player_club_mismatch
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    current = validate_success(api.get_meet(meet["id"], federation_admin_headers))

    # White from the AWAY club, black from the HOST club: wrong sides.
    res = api.create_pairing(
        meet["id"],
        create_pairing_payload(1, 1, ctx["players_b"][0]["id"], ctx["players_a"][0]["id"],
                               current["version"]),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_PLAYER_CLUB_MISMATCH)

def test_suspended_player_pairing_rejected(api, federation_admin_headers):
    """PRD §3.4: "seating a `SUSPENDED` player fails with `ERR_PLAYER_SUSPENDED`."
    PRD §3.1: "a `SUSPENDED` player may not be placed in a pairing or a tournament
    entry — such attempts fail with `ERR_PLAYER_SUSPENDED`."

    Design: Corner/errors/suspended_player_pairing_rejected
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    validate_success(api.suspend_player(ctx["players_a"][0]["id"], federation_admin_headers))
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    schedule_meet(meet["id"])
    current = validate_success(api.get_meet(meet["id"], federation_admin_headers))

    res = api.create_pairing(
        meet["id"],
        create_pairing_payload(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"],
                               current["version"]),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_PLAYER_SUSPENDED)
    assert res.status_code == 403

def test_same_club_confirmation_forbidden(api):
    """PRD §3.4: "Confirmation then requires a coach of the *other* club: the confirmer
    must belong to the host or away club and must not belong to the reporting coach's
    club, or the confirmation fails with `ERR_SAME_CLUB_CONFIRMATION`."

    Design: Corner/errors/same_club_confirmation_forbidden
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    coach_a2 = create_coach(ctx["club_a"]["id"], full_name="Coach A2",
                            email="coach.a2@example.com")
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
    )
    pairing = out["pairings"][0]
    report_result(pairing["id"], "WHITE_WIN", ctx["coach_a"]["id"])

    res = api.confirm_pairing(pairing["id"], make_club_coach_headers(coach_a2["id"]))
    validate_error(res, ApiErrorId.ERR_SAME_CLUB_CONFIRMATION)

def test_occ_pairing_stale_meet_version(api, federation_admin_headers):
    """PRD §2.7: "Creating a pairing within a meet requires the request to carry
    `expected_meet_version` matching the meet's current `version`. Pairing creation
    supersedes any existing non-terminal pairing at the same round-and-board slot and
    is legitimate repeatedly while the meet is being arranged, so the only guard
    against a writer whose view of the meet is outdated is this check: a create whose
    `expected_meet_version` no longer matches because another pairing write has
    advanced the meet since the client observed it is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_pairing_stale_meet_version
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"], "2026-09-05")
    stale_version = meet["version"]
    schedule_meet(meet["id"])  # advances the meet version

    res = api.create_pairing(
        meet["id"],
        create_pairing_payload(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"],
                               stale_version),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    fresh = validate_success(api.get_meet(meet["id"], federation_admin_headers))
    created = validate_success(
        api.create_pairing(
            meet["id"],
            create_pairing_payload(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"],
                                   fresh["version"]),
            federation_admin_headers,
        ),
        201,
    )
    assert created["status"] == "SCHEDULED"
    after = validate_success(api.get_meet(meet["id"], federation_admin_headers))
    assert_version_incremented(after["version"], fresh["version"])

def test_meet_game_points_conservation(api, federation_admin_headers):
    """PRD §3.9: "a `WHITE_WIN` gives the host 1 and the away 0; a `BLACK_WIN` gives
    the host 0 and the away 1; a `DRAW` gives each side one half; a
    `WHITE_FORFEIT_WIN` gives the host 1 and the away 0; a `BLACK_FORFEIT_WIN` gives
    the host 0 and the away 1; and a `DOUBLE_FORFEIT` gives neither side anything."
    PRD §3.9: "A meet's `game_points` are the sum of its board points, and
    `match_points` follow from comparing the two clubs' game points: 2 for more, 1
    for an exact tie, 0 for fewer."

    Design: Difficulty/compensating_invariant/meet_game_points_conservation
    """
    ctx = setup_two_club_league(players_a=[{}, {}], players_b=[{}, {}])
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[
            (1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
            (1, 2, ctx["players_a"][1]["id"], ctx["players_b"][1]["id"]),
        ],
        results=["WHITE_WIN", "DOUBLE_FORFEIT"], complete=True,
    )
    assert out["meet"]["status"] == "COMPLETED"

    host = _standings_row(api, ctx["season"]["id"], ctx["club_a"]["id"], federation_admin_headers)
    away = _standings_row(api, ctx["season"]["id"], ctx["club_b"]["id"], federation_admin_headers)
    # Conservation: points awarded == rounds*boards minus 1 per DOUBLE_FORFEIT game.
    assert host["game_points"] == 1 and away["game_points"] == 0
    assert host["game_points"] + away["game_points"] == 1 * 2 - 1
    assert host["match_points"] == 2 and away["match_points"] == 0

def test_meet_double_forfeit_tallies_and_no_rating_events(api, federation_admin_headers):
    """PRD §3.9: "Each side's `forfeit_losses` grow by one for every game it loses by
    forfeit, with a double forfeit charging both sides."
    PRD §3.4: "For a forfeit result (`WHITE_FORFEIT_WIN`, `BLACK_FORFEIT_WIN`, or
    `DOUBLE_FORFEIT`) no rating events exist at all".

    Design: Difficulty/compensating_invariant/meet_game_points_conservation
    """
    ctx = setup_two_club_league(players_a=[{}, {}], players_b=[{}, {}])
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[
            (1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
            (1, 2, ctx["players_a"][1]["id"], ctx["players_b"][1]["id"]),
        ],
        results=["WHITE_WIN", "DOUBLE_FORFEIT"], complete=True,
    )
    host = _standings_row(api, ctx["season"]["id"], ctx["club_a"]["id"], federation_admin_headers)
    away = _standings_row(api, ctx["season"]["id"], ctx["club_b"]["id"], federation_admin_headers)
    assert host["forfeit_losses"] == 1, "double forfeit charges the host side"
    assert away["forfeit_losses"] == 1, "double forfeit charges the away side"

    g2 = out["pairings"][1]
    events, meta = validate_paginated(
        api.list_rating_events(federation_admin_headers, params={"pairing_id": g2["id"]})
    )
    assert events == [], "DOUBLE_FORFEIT creates no rating events"
    assert meta["total_count"] == 0
