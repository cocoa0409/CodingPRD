"""Incident protocol: reporting rights, segregation of duties, the appeal
cycle with its single-appeal quota, the TIME_SECONDS penalty cascade with
compensating reversal, and the open-incident gate on event finalization."""
from test_helpers import (
    ApiErrorId,
    adjudicate_incident,
    appeal_incident,
    assert_incident,
    complete_event,
    create_adjudication_payload,
    create_incident_payload,
    create_session,
    get_entry,
    get_event,
    get_incident,
    list_session_results,
    make_driver_headers,
    open_incident_review,
    report_incident,
    setup_event_with_reported_incident,
    setup_grid_locked_event,
    setup_scored_event,
    standings_row_for,
    validate_error,
    validate_success,
)


def test_appeal_from_reported_state_rejected(api):
    """PRD 3.6: "The driver of the reported entry — and only that driver, else
    `ERR_NOT_ENTRY_DRIVER` — may appeal an upheld ruling, moving the incident
    `UPHELD → APPEALED`."
    PRD 2.8: "6. **State preconditions** — the target resources sit in states that
    permit the operation: the season `ACTIVE` for event creation and registration
    opening (`ERR_SEASON_NOT_ACTIVE`); the event `REGISTRATION_OPEN` for entry creation
    (`ERR_EVENT_REGISTRATION_CLOSED`); the driver `ACTIVE` for entries and practice
    bookings (`ERR_DRIVER_NOT_ACTIVE`); the kart `AVAILABLE` for entries and bookings
    (`ERR_KART_UNAVAILABLE`); no open incidents at event finalization
    (`ERR_OPEN_INCIDENTS`); no prior appeal on the incident (`ERR_APPEAL_LIMIT`); the
    session `CLOSED` for result submission and for scoring, with scoring from a
    non-closed session surfaced as `ERR_SESSION_NOT_CLOSED`; every `GRID_LOCKED` entry
    holding a result at scoring time (`ERR_RESULTS_INCOMPLETE`); every non-`WITHDRAWN`
    entry in `TECH_PASSED` at grid lock (`ERR_TECH_NOT_PASSED`); and any other invalid
    from-state for a requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/appeal_from_reported_state_rejected
    """
    ctx = setup_event_with_reported_incident([("A", 1, 45000, 600000)])
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]

    response = api.appeal_incident(incident["id"], make_driver_headers(driver_a["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = get_incident(incident["id"])
    assert after["status"] == "REPORTED"
    assert after["appeal_count"] == 0


def test_driver_cannot_report_incident(api):
    """PRD 3.6: "Any on-track official — a `RaceDirector` or a `Steward` — may report
    an incident against an entry in a session of the event, supplying the `entry_id`,
    the `session_id`, and a free-text `description`; the server records the caller's
    identifier as `reporter_user_id`, and the report opens in `REPORTED` status."
    PRD 2.1: "A request whose role is not permitted for the target endpoint is rejected
    with `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/driver_cannot_report_incident
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    session = create_session(ctx["event"]["id"], ctx["event"]["version"])
    entry = ctx["entries"][0]

    response = api.create_incident(
        ctx["event"]["id"],
        create_incident_payload(entry["id"], session["id"], "Self-serving report"),
        make_driver_headers(entry["driver_id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_race_director_cannot_adjudicate(api, race_director_2_headers, steward_headers):
    """PRD 3.6: "Adjudication is the steward's exclusive province and carries the
    segregation-of-duties rule of §2.1: the ruling steward's `X-User-ID` must differ
    from the incident's `reporter_user_id`, on pain of `ERR_SELF_ADJUDICATION`."
    PRD 2.1: "A request whose role is not permitted for the target endpoint is rejected
    with `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/racedirector_cannot_adjudicate
    """
    ctx = setup_event_with_reported_incident([("A", 1, 45000, 600000)])
    incident = ctx["incident"]
    open_incident_review(incident["id"], steward_headers)

    response = api.adjudicate_incident(
        incident["id"], create_adjudication_payload("DISMISSED"), race_director_2_headers
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value, 403)

    after = get_incident(incident["id"])
    assert after["status"] == "UNDER_REVIEW"


def test_steward_cannot_adjudicate_own_report(api, steward_headers, steward_9_headers):
    """PRD 3.6: "Adjudication is the steward's exclusive province and carries the
    segregation-of-duties rule of §2.1: the ruling steward's `X-User-ID` must differ
    from the incident's `reporter_user_id`, on pain of `ERR_SELF_ADJUDICATION`."
    PRD 3.6: "The ruling itself is a `decision` of `UPHELD` or `DISMISSED`, recorded
    along with the steward's identifier as `adjudicator_user_id`."

    Design: Corner/rbac/steward_self_adjudication_rejected
    """
    # The reporting official here is a Steward (st-9), who may also report.
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000)],
        description="Steward-observed contact",
        reporter_headers=steward_9_headers,
    )
    incident = ctx["incident"]
    open_incident_review(incident["id"], steward_headers)

    own = api.adjudicate_incident(
        incident["id"],
        create_adjudication_payload("UPHELD", penalty_kind="NONE"),
        steward_9_headers,
    )
    validate_error(own, ApiErrorId.ERR_SELF_ADJUDICATION.value, 403)
    assert get_incident(incident["id"])["status"] == "UNDER_REVIEW"

    other = adjudicate_incident(incident["id"], "DISMISSED", steward_headers=steward_headers)
    assert_incident(other)
    assert other["status"] == "DISMISSED"
    assert other["adjudicator_user_id"] == "st-1"


def test_second_appeal_rejected(api, steward_headers):
    """PRD 3.6: "Each incident allows at most one appeal: the attempt is refused with
    `ERR_APPEAL_LIMIT` once the incident's `appeal_count` has reached one, and a
    successful appeal adds one to that count."

    Design: Corner/rbac/second_appeal_rejected
    """
    ctx = setup_event_with_reported_incident([("A", 1, 45000, 600000)])
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "UPHELD", penalty_kind="NONE")
    appeal_incident(incident["id"], driver_a["id"])
    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "UPHELD", penalty_kind="NONE")

    response = api.appeal_incident(incident["id"], make_driver_headers(driver_a["id"]))
    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT.value, 409)

    after = get_incident(incident["id"])
    assert after["appeal_count"] == 1
    assert after["status"] == "UPHELD"


def test_appeal_by_other_driver_rejected(api, steward_headers):
    """PRD 3.6: "The driver of the reported entry — and only that driver, else
    `ERR_NOT_ENTRY_DRIVER` — may appeal an upheld ruling, moving the incident
    `UPHELD → APPEALED`."

    Design: Corner/rbac/appeal_by_other_driver_rejected
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 601000)]
    )
    incident = ctx["incident"]
    driver_b = ctx["drivers_by_label"]["B"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "UPHELD", penalty_kind="NONE")

    response = api.appeal_incident(incident["id"], make_driver_headers(driver_b["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_ENTRY_DRIVER.value, 403)

    after = get_incident(incident["id"])
    assert after["status"] == "UPHELD"
    assert after["appeal_count"] == 0


def test_incident_appeal_cycle_returns_to_under_review(api, steward_headers, steward_2_headers):
    """PRD 3.6: "A `Steward` opens review, moving the incident `REPORTED →
    UNDER_REVIEW`; the same open-review action also returns an `APPEALED` incident to
    `UNDER_REVIEW` for a second look."
    PRD 3.6: "The driver of the reported entry — and only that driver, else
    `ERR_NOT_ENTRY_DRIVER` — may appeal an upheld ruling, moving the incident
    `UPHELD → APPEALED`."
    PRD 3.6: "Each incident allows at most one appeal: the attempt is refused with
    `ERR_APPEAL_LIMIT` once the incident's `appeal_count` has reached one, and a
    successful appeal adds one to that count."

    Design: Difficulty/non_linear_state_machine/incident_appeal_review_cycle
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 605000)]
    )
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]

    open_incident_review(incident["id"], steward_headers)
    upheld = adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=10
    )
    assert upheld["status"] == "UPHELD"

    appealed = appeal_incident(incident["id"], driver_a["id"])
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1

    reopened = open_incident_review(incident["id"], steward_headers)
    assert reopened["status"] == "UNDER_REVIEW"

    dismissed = adjudicate_incident(
        incident["id"], "DISMISSED", steward_headers=steward_2_headers
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["appeal_count"] == 1


def test_dismissal_after_appeal_restores_results(api, steward_headers, steward_2_headers):
    """PRD 3.6: "When a previously upheld incident is, after its appeal, re-adjudicated
    as `DISMISSED`, the penalty is reversed as compensation: the `penalty_seconds` are
    subtracted from the affected result's `penalty_seconds_applied`, and the session is
    re-ranked and recomputed exactly as in the upheld cascade, restoring the
    pre-penalty positions and points."

    Design: Difficulty/non_linear_state_machine/incident_appeal_review_cycle
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 605000)]
    )
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]
    entry_a = ctx["entries_by_label"]["A"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=10
    )
    appeal_incident(incident["id"], driver_a["id"])
    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "DISMISSED", steward_headers=steward_2_headers)

    results = {r["entry_id"]: r for r in list_session_results(ctx["session"]["id"])}
    result_a = results[entry_a["id"]]
    assert result_a["penalty_seconds_applied"] == 0, "the penalty is subtracted back"
    assert result_a["finish_position"] == 1, "pre-penalty position restored"
    assert result_a["points_awarded"] == 25, "pre-penalty points restored"
    assert get_entry(entry_a["id"])["event_points"] == 25


def test_time_penalty_reorders_results_and_points(api, steward_headers):
    """PRD 3.6: "An upheld ruling with `penalty_kind` `TIME_SECONDS` triggers the
    penalty cascade. First, the result of the reported entry in the reported session
    has the `penalty_seconds` added to its `penalty_seconds_applied`. Second, every
    result in that session is re-ranked by effective total time — the recorded
    `total_time_ms` plus one thousand milliseconds for each second of
    `penalty_seconds_applied` — ascending, with ties broken in favor of the result that
    held the better `finish_position` before the re-rank; the `finish_position` values
    are then rewritten to the new order, and every result whose position changed moves
    from `PROVISIONAL` to `AMENDED` with its `points_awarded` recomputed after the
    re-rank. Third, `points_awarded` is recomputed for every result of the session
    under the session-points rule of §3.5, each affected entry's `event_points` is
    recomputed, and the standings reflect the change on their next read."

    Design: Difficulty/transitive_cascade/penalty_reorders_results_points_standings
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 603000)]
    )
    incident = ctx["incident"]
    entry_a = ctx["entries_by_label"]["A"]
    entry_b = ctx["entries_by_label"]["B"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=5
    )

    results = {r["entry_id"]: r for r in list_session_results(ctx["session"]["id"])}
    result_a = results[entry_a["id"]]
    result_b = results[entry_b["id"]]

    # Hop 1: penalty applied and the session re-ranked by effective total time
    # (A 600000 + 5000 = 605000 > B 603000).
    assert result_a["penalty_seconds_applied"] == 5
    assert result_a["finish_position"] == 2
    assert result_b["finish_position"] == 1
    assert result_a["status"] == "AMENDED"
    assert result_b["status"] == "AMENDED"

    # Hop 2: points recomputed from the rewritten positions.
    assert result_a["points_awarded"] == 22
    assert result_b["points_awarded"] == 25
    assert get_entry(entry_a["id"])["event_points"] == 22
    assert get_entry(entry_b["id"])["event_points"] == 25
    assert result_a["points_awarded"] + result_b["points_awarded"] == 47


def test_time_penalty_reorders_standings_on_next_read(api, steward_headers, league_admin_headers):
    """PRD 3.6: "Third, `points_awarded` is recomputed for every result of the session
    under the session-points rule of §3.5, each affected entry's `event_points` is
    recomputed, and the standings reflect the change on their next read."
    PRD 3.7: "Only counted events feed the totals — child events in `COMPLETED` or
    `FINALIZED` status; `CANCELLED` events are excluded — and the season's
    `rounds_completed` is exactly the count of those counted events."
    PRD 3.3: "Completion — `IN_PROGRESS → COMPLETED`, by the `RaceDirector` — requires
    every child session to be `SCORED`."

    Design: Difficulty/transitive_cascade/penalty_reorders_results_points_standings
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 603000)]
    )
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]
    driver_b = ctx["drivers_by_label"]["B"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=5
    )

    # The event joins the counted set once completed; the standings read then
    # reflects the penalty without any direct standings write.
    complete_event(ctx["event"]["id"])
    standings = validate_success(
        api.get_standings(
            ctx["season"]["id"],
            league_admin_headers,
            params={"class_id": ctx["race_class"]["id"]},
        ),
        200,
    )
    assert standings["rows"][0]["driver_id"] == driver_b["id"], (
        "hop 3: the penalized driver drops below the rival in the standings"
    )
    assert standings["rows"][1]["driver_id"] == driver_a["id"]
    assert standings_row_for(standings, driver_b["id"])["provisional_points"] == 25
    assert standings_row_for(standings, driver_a["id"])["provisional_points"] == 22


def test_penalty_application_conserves_session_points(api, steward_headers):
    """PRD 3.6: "Second, every result in that session is re-ranked by effective total
    time — the recorded `total_time_ms` plus one thousand milliseconds for each second
    of `penalty_seconds_applied` — ascending, with ties broken in favor of the result
    that held the better `finish_position` before the re-rank; the `finish_position`
    values are then rewritten to the new order, and every result whose position changed
    moves from `PROVISIONAL` to `AMENDED` with its `points_awarded` recomputed after
    the re-rank."
    PRD 3.5: "In `HEAT` and `MAIN` sessions, each result's base points come from the
    season's `points_scheme` by finishing position — first place takes the array's
    first element, second place the second, and positions past the array's end take
    zero."

    Design: Difficulty/compensating_invariant/penalty_apply_reverse_conserves_session_points
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 603000)]
    )
    incident = ctx["incident"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=5
    )

    results = list_session_results(ctx["session"]["id"])
    total = sum(r["points_awarded"] for r in results)
    assert total == 47, (
        "points are permuted by the re-rank, never created or destroyed (22 + 25)"
    )


def test_penalty_reversal_restores_positions_and_conserves_points(
    api, steward_headers, steward_2_headers
):
    """PRD 3.6: "When a previously upheld incident is, after its appeal, re-adjudicated
    as `DISMISSED`, the penalty is reversed as compensation: the `penalty_seconds` are
    subtracted from the affected result's `penalty_seconds_applied`, and the session is
    re-ranked and recomputed exactly as in the upheld cascade, restoring the
    pre-penalty positions and points."

    Design: Difficulty/compensating_invariant/penalty_apply_reverse_conserves_session_points
    """
    ctx = setup_event_with_reported_incident(
        [("A", 1, 45000, 600000), ("B", 2, 45100, 603000)]
    )
    incident = ctx["incident"]
    driver_a = ctx["drivers_by_label"]["A"]
    entry_a = ctx["entries_by_label"]["A"]
    entry_b = ctx["entries_by_label"]["B"]

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(
        incident["id"], "UPHELD", penalty_kind="TIME_SECONDS", penalty_seconds=5
    )
    appeal_incident(incident["id"], driver_a["id"])
    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "DISMISSED", steward_headers=steward_2_headers)

    results = {r["entry_id"]: r for r in list_session_results(ctx["session"]["id"])}
    result_a = results[entry_a["id"]]
    result_b = results[entry_b["id"]]

    assert result_a["penalty_seconds_applied"] == 0
    assert result_a["finish_position"] == 1
    assert result_a["points_awarded"] == 25
    assert result_b["finish_position"] == 2
    assert result_b["points_awarded"] == 22
    assert result_a["points_awarded"] + result_b["points_awarded"] == 47, (
        "the reversal conserves the session points total (25 + 22)"
    )


def test_event_finalize_blocked_while_incident_open(api, race_director_headers):
    """PRD 3.3: "Finalization — `COMPLETED → FINALIZED` — requires that no incident of
    the event remains in `REPORTED`, `UNDER_REVIEW`, or `APPEALED`
    (`ERR_OPEN_INCIDENTS`); on finalization every result of the event's sessions that
    is still `PROVISIONAL` or `AMENDED` becomes `FINAL`, and the event counts toward
    the standings."

    Design: Difficulty/cross_entity_state_dependency/event_finalize_blocked_by_open_incident
    """
    ctx = setup_scored_event([("A", 1, 45000, 600000)])
    incident = report_incident(
        ctx["event"]["id"],
        ctx["entries_by_label"]["A"]["id"],
        ctx["session"]["id"],
        "Unsafe rejoin",
    )
    complete_event(ctx["event"]["id"])

    response = api.finalize_event(ctx["event"]["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_OPEN_INCIDENTS.value, 409)

    event = get_event(ctx["event"]["id"])
    assert event["status"] == "COMPLETED", "the blocked finalize changes nothing"
    assert get_incident(incident["id"])["status"] == "REPORTED"


def test_event_finalize_succeeds_after_incident_dismissed(
    api, race_director_headers, steward_headers
):
    """PRD 3.3: "Finalization — `COMPLETED → FINALIZED` — requires that no incident of
    the event remains in `REPORTED`, `UNDER_REVIEW`, or `APPEALED`
    (`ERR_OPEN_INCIDENTS`); on finalization every result of the event's sessions that
    is still `PROVISIONAL` or `AMENDED` becomes `FINAL`, and the event counts toward
    the standings."

    Design: Difficulty/cross_entity_state_dependency/event_finalize_blocked_by_open_incident
    """
    ctx = setup_scored_event([("A", 1, 45000, 600000)])
    incident = report_incident(
        ctx["event"]["id"],
        ctx["entries_by_label"]["A"]["id"],
        ctx["session"]["id"],
        "Unsafe rejoin",
    )
    complete_event(ctx["event"]["id"])

    open_incident_review(incident["id"], steward_headers)
    adjudicate_incident(incident["id"], "DISMISSED", steward_headers=steward_headers)

    finalized = validate_success(
        api.finalize_event(ctx["event"]["id"], race_director_headers), 200
    )
    assert finalized["status"] == "FINALIZED"

    results = list_session_results(ctx["session"]["id"])
    assert len(results) == 1
    assert results[0]["status"] == "FINAL", (
        "event finalization settles every PROVISIONAL or AMENDED result into FINAL"
    )
