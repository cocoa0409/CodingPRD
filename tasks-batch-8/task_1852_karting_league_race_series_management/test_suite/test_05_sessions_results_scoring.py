"""Sessions, result batches and scoring: submission windows, scoring
preconditions, fastest-lap and points computation, optimistic concurrency on
the event/session versions, and immediate read consistency after scoring."""
from test_helpers import (
    ApiErrorId,
    assert_session,
    assert_session_result,
    create_result_row,
    create_results_payload,
    create_session,
    create_session_payload,
    get_entry,
    get_event,
    run_scored_session,
    setup_grid_locked_event,
    setup_open_event,
    setup_scored_event,
    start_event,
    lock_grid,
    enter_driver,
    register_active_driver,
    transition_session,
    validate_error,
    validate_success,
)


def test_results_submission_while_session_open_rejected(
    api, race_director_headers
):
    """PRD 3.5: "Results are submitted only against a `CLOSED` session, as one full
    batch: the `results` array carries one row per finisher with the `entry_id` — which
    must be a `GRID_LOCKED` entry of the session's event — the recorded
    `finish_position` (a positive integer), and `best_lap_ms` and `total_time_ms` (both
    positive integer milliseconds)."
    PRD 3.5: "The submission carries `expected_session_version` (§2.6) and advances the
    session's `version` by one; submitting against a session that is not `CLOSED` fails
    with `ERR_INVALID_STATE`."

    Design: Corner/validations/results_while_session_open_rejected
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    session = transition_session(session["id"], "OPEN")
    entry = ctx["entries"][0]

    response = api.submit_results(
        session["id"],
        create_results_payload(
            [create_result_row(entry["id"], 1, 45000, 600000)],
            expected_session_version=session["version"],
        ),
        race_director_headers,
    )
    # The presented version is current, so the rejection comes from the
    # session-state rule, not the stale-version guard.
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_score_from_open_session_rejected(api, race_director_headers):
    """PRD 3.5: "Attempting it from any state other than `CLOSED` fails with
    `ERR_SESSION_NOT_CLOSED`, and it is refused with `ERR_RESULTS_INCOMPLETE` until
    every `GRID_LOCKED` entry of the parent event holds a result row in the session."

    Design: Corner/validations/score_from_open_session_rejected
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    session = transition_session(session["id"], "OPEN")

    response = api.score_session(session["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_CLOSED.value, 409)

    after = validate_success(api.get_session(session["id"], race_director_headers), 200)
    assert after["status"] == "OPEN"


def test_score_requires_results_for_every_grid_locked_entry(
    api, race_director_headers
):
    """PRD 3.5: "Attempting it from any state other than `CLOSED` fails with
    `ERR_SESSION_NOT_CLOSED`, and it is refused with `ERR_RESULTS_INCOMPLETE` until
    every `GRID_LOCKED` entry of the parent event holds a result row in the session."

    Design: Corner/validations/score_requires_all_grid_locked_results
    """
    ctx = setup_grid_locked_event(num_drivers=2)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    transition_session(session["id"], "OPEN")
    session = transition_session(session["id"], "CLOSED")
    entry_a = ctx["entries"][0]

    validate_success(
        api.submit_results(
            session["id"],
            create_results_payload(
                [create_result_row(entry_a["id"], 1, 45000, 600000)],
                expected_session_version=session["version"],
            ),
            race_director_headers,
        ),
        201,
    )

    response = api.score_session(session["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_RESULTS_INCOMPLETE.value, 409)

    after = validate_success(api.get_session(session["id"], race_director_headers), 200)
    assert after["status"] == "CLOSED", "a refused score leaves the session CLOSED"


def test_duplicate_result_rows_in_batch_rejected(api, race_director_headers):
    """PRD 3.5: "Two rows for the same entry in one submission are refused with
    `ERR_DUPLICATE_RESULT`."

    Design: Corner/validations/duplicate_result_rows_in_batch_rejected
    """
    ctx = setup_grid_locked_event(num_drivers=2)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    transition_session(session["id"], "OPEN")
    session = transition_session(session["id"], "CLOSED")
    entry_a = ctx["entries"][0]

    response = api.submit_results(
        session["id"],
        create_results_payload(
            [
                create_result_row(entry_a["id"], 1, 45000, 600000),
                create_result_row(entry_a["id"], 2, 45100, 601000),
            ],
            expected_session_version=session["version"],
        ),
        race_director_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESULT.value, 409)

    listing = validate_success(
        api.list_session_results(session["id"], race_director_headers), 200
    )
    assert listing == [], "a refused batch records no result rows"


def test_fastest_lap_tie_broken_by_finish_position(api, race_director_headers):
    """PRD 3.5: "The session's fastest lap goes to the result with the lowest
    `best_lap_ms`, a tie broken in favor of the better `finish_position`, and that
    result's `is_fastest_lap` flag is set; when the fastest finisher also placed tenth
    or better (`FASTEST_LAP_MAX_POSITION`), the season's `fastest_lap_bonus_points` are
    added to that result's base as a bonus."

    Design: Corner/calculations/fastest_lap_tie_broken_by_finish_position
    """
    ctx = setup_scored_event(
        [("A", 1, 45000, 600000), ("B", 2, 45000, 601000)],
        season_overrides={"fastest_lap_bonus_points": 2},
    )
    results = ctx["results"]
    result_a = results[ctx["entries_by_label"]["A"]["id"]]
    result_b = results[ctx["entries_by_label"]["B"]["id"]]

    assert result_a["is_fastest_lap"] is True, (
        "tie on best_lap_ms 45000 broken by the better finish_position"
    )
    assert result_b["is_fastest_lap"] is False
    assert result_a["points_awarded"] == 27, "25 base + 2 bonus"
    assert result_b["points_awarded"] == 22


def test_qualifying_session_awards_zero_points(api, race_director_headers):
    """PRD 3.5: "Results in `PRACTICE` and `QUALIFYING` sessions never earn points."
    PRD 3.5: "Each entry's `event_points` is then recomputed as the sum of its
    `points_awarded` across the event's `HEAT` and `MAIN` sessions, and scoring
    advances the session's `version` by one."

    Design: Corner/calculations/qualifying_session_awards_zero_points
    """
    ctx = setup_grid_locked_event(
        num_drivers=2, season_overrides={"fastest_lap_bonus_points": 2}
    )
    session, results = run_scored_session(
        ctx,
        [
            (ctx["entries"][0], 1, 45000, 600000),
            (ctx["entries"][1], 2, 45100, 601000),
        ],
        session_type="QUALIFYING",
    )
    for result in results.values():
        assert result["points_awarded"] == 0, (
            "QUALIFYING results earn no points regardless of position"
        )
    for entry in ctx["entries"]:
        assert get_entry(entry["id"])["event_points"] == 0


def test_scoring_assigns_fastest_lap_flag(api, race_director_headers):
    """PRD 3.5: "The session's fastest lap goes to the result with the lowest
    `best_lap_ms`, a tie broken in favor of the better `finish_position`, and that
    result's `is_fastest_lap` flag is set; when the fastest finisher also placed tenth
    or better (`FASTEST_LAP_MAX_POSITION`), the season's `fastest_lap_bonus_points` are
    added to that result's base as a bonus."

    Design: Difficulty/combinatorial_formula/session_points_position_bonus_conditionals
    """
    ctx = setup_scored_event(
        [("A", 1, 45300, 600000), ("B", 2, 45100, 601000), ("C", 3, 45500, 604000)],
        season_overrides={"fastest_lap_bonus_points": 2},
    )
    results = ctx["results"]
    result_a = results[ctx["entries_by_label"]["A"]["id"]]
    result_b = results[ctx["entries_by_label"]["B"]["id"]]
    result_c = results[ctx["entries_by_label"]["C"]["id"]]
    for result in results.values():
        assert_session_result(result)

    assert result_b["is_fastest_lap"] is True, "lowest best_lap_ms (45100) in the session"
    assert result_a["is_fastest_lap"] is False
    assert result_c["is_fastest_lap"] is False


def test_scoring_combines_base_and_conditional_bonus(api, race_director_headers):
    """PRD 3.5: "In `HEAT` and `MAIN` sessions, each result's base points come from the
    season's `points_scheme` by finishing position — first place takes the array's
    first element, second place the second, and positions past the array's end take
    zero."
    PRD 3.5: "The session's fastest lap goes to the result with the lowest
    `best_lap_ms`, a tie broken in favor of the better `finish_position`, and that
    result's `is_fastest_lap` flag is set; when the fastest finisher also placed tenth
    or better (`FASTEST_LAP_MAX_POSITION`), the season's `fastest_lap_bonus_points` are
    added to that result's base as a bonus."
    PRD 3.5: "Each entry's `event_points` is then recomputed as the sum of its
    `points_awarded` across the event's `HEAT` and `MAIN` sessions, and scoring
    advances the session's `version` by one."

    Design: Difficulty/combinatorial_formula/session_points_position_bonus_conditionals
    """
    ctx = setup_scored_event(
        [("A", 1, 45300, 600000), ("B", 2, 45100, 601000), ("C", 3, 45500, 604000)],
        season_overrides={"fastest_lap_bonus_points": 2},
    )
    results = ctx["results"]
    result_a = results[ctx["entries_by_label"]["A"]["id"]]
    result_b = results[ctx["entries_by_label"]["B"]["id"]]
    result_c = results[ctx["entries_by_label"]["C"]["id"]]

    assert result_a["points_awarded"] == 25, "position-1 base, no fastest lap"
    assert result_b["points_awarded"] == 24, (
        "position-2 base 22 + bonus 2 (fastest lap at position 2, tenth or better)"
    )
    assert result_c["points_awarded"] == 20

    entry_b = get_entry(ctx["entries_by_label"]["B"]["id"])
    assert entry_b["event_points"] == 24


def test_score_immediately_visible_on_entry_read(api, race_director_headers):
    """PRD 1: "The API serves four acting roles and is built around immediate
    consistency: every computed figure — fees collected, points, standings — reflects
    the latest committed change on the next read."
    PRD 3.5: "Each entry's `event_points` is then recomputed as the sum of its
    `points_awarded` across the event's `HEAT` and `MAIN` sessions, and scoring
    advances the session's `version` by one."

    Design: Corner/consistency_model/score_immediately_visible_in_entry_read
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    transition_session(session["id"], "OPEN")
    session = transition_session(session["id"], "CLOSED")
    entry = ctx["entries"][0]
    validate_success(
        api.submit_results(
            session["id"],
            create_results_payload(
                [create_result_row(entry["id"], 1, 45000, 600000)],
                expected_session_version=session["version"],
            ),
            race_director_headers,
        ),
        201,
    )

    scored = validate_success(api.score_session(session["id"], race_director_headers), 200)
    assert_session(scored)
    assert scored["status"] == "SCORED", "the score call itself reports SCORED"

    after = get_entry(entry["id"])
    assert after["event_points"] == 25, (
        "a plain read immediately after scoring shows the recomputed event_points"
    )


def test_session_creation_with_stale_event_version_rejected(
    api, race_director_headers, league_admin_headers
):
    """PRD 2.6: "Creating a session under an event requires the request to carry
    `expected_event_version` holding the event `version` the client last observed."
    PRD 2.6: "If the presented value does not equal the parent resource's current
    `version` — because another write, such as an earlier session creation or result
    submission, has advanced it since the client last read — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 2.6: "Both of these writes themselves advance the parent's `version` by one, so
    a client that has just written must re-read the parent before writing again."

    Design: Corner/complexity_layers/session_create_stale_event_version
    """
    ctx = setup_open_event()
    enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True, inspect_weight=171.0,
    )
    started = start_event(ctx["event"]["id"])
    locked = lock_grid(ctx["event"]["id"])

    stale = api.create_session(
        ctx["event"]["id"],
        create_session_payload(
            "QUALIFYING", 1, expected_event_version=started["version"]
        ),
        race_director_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh = api.create_session(
        ctx["event"]["id"],
        create_session_payload(
            "QUALIFYING", 1, expected_event_version=locked["version"]
        ),
        race_director_headers,
    )
    session = validate_success(fresh, 201)
    assert_session(session)
    assert session["status"] == "SCHEDULED"

    event = get_event(ctx["event"]["id"])
    assert event["version"] == locked["version"] + 1, (
        "session creation advances the parent event's version by one"
    )


def test_result_batch_supersede_requires_fresh_session_version(
    api, race_director_headers
):
    """PRD 3.5: "A batch submitted while an earlier batch exists supersedes it: the
    previous rows are discarded and the new rows are recorded `PROVISIONAL`."
    PRD 2.6: "Submitting a result batch to a session requires `expected_session_version`
    holding the session `version` the client last observed."
    PRD 2.6: "If the presented value does not equal the parent resource's current
    `version` — because another write, such as an earlier session creation or result
    submission, has advanced it since the client last read — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/results_resubmit_supersede_with_fresh_version
    """
    ctx = setup_grid_locked_event(num_drivers=2)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    transition_session(session["id"], "OPEN")
    session = transition_session(session["id"], "CLOSED")
    entry_a, entry_b = ctx["entries"]

    closed_version = session["version"]
    validate_success(
        api.submit_results(
            session["id"],
            create_results_payload(
                [
                    create_result_row(entry_a["id"], 1, 45000, 600000),
                    create_result_row(entry_b["id"], 2, 45100, 601000),
                ],
                expected_session_version=closed_version,
            ),
            race_director_headers,
        ),
        201,
    )
    current = validate_success(
        api.get_session(session["id"], race_director_headers), 200
    )

    corrected_rows = [
        create_result_row(entry_b["id"], 1, 44900, 599000),
        create_result_row(entry_a["id"], 2, 45000, 600500),
    ]
    stale = api.submit_results(
        session["id"],
        create_results_payload(corrected_rows, expected_session_version=closed_version),
        race_director_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh = api.submit_results(
        session["id"],
        create_results_payload(
            corrected_rows, expected_session_version=current["version"]
        ),
        race_director_headers,
    )
    validate_success(fresh, 201)

    validate_success(api.score_session(session["id"], race_director_headers), 200)
    entry_a = get_entry(entry_a["id"])
    entry_b = get_entry(entry_b["id"])
    assert entry_b["event_points"] == 25, (
        "the corrected batch supersedes: B's position-1 finish wins"
    )
    assert entry_a["event_points"] == 22
