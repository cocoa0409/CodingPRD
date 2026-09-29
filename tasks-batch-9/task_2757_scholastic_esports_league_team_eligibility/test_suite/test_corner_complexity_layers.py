"""Breadth tests for the ``complexity_layers`` design section.

The two optimistic-concurrency guards of PRD §2.6 — one on ``Match``, one on
``Student`` — and the reconciliation of the team roll-ups as a source row
appears, changes and leaves.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    ELIGIBILITY_OFFICER_ID_2,
    ELIGIBILITY_OFFICER_ID_3,
    eligibility_officer_headers,
    league_admin_headers,
    make_coach_headers,
)


# ==========================================================================
# Instance: result_report_optimistic_concurrency_rejects_every_stale_expected_
#           match_version
# ==========================================================================
def _build_server_ready_match(api):
    """A REGULAR_SEASON match at `SERVER_READY`, so the match's version has been
    moved twice — once by creation, once by the server configuration."""
    world = fx.build_ready_match(api, scheduled_start_at="2026-10-01T18:00:00.000Z")
    assert world["match"]["version"] == 2, (
        "creation then server configuration are two mutations of §2.5's counter"
    )
    return world


def _report(api, world, side, expected_version, home_games_won=2, away_games_won=1):
    """A raw result report from the coach who owns the ``side`` team ("a" or
    "b"), so PRD §2.1's ownership rung is satisfied and rung 11 is reachable."""
    return api.report_result(
        world["match"]["id"],
        {
            "reporting_team_id": world[f"team_{side}"]["id"],
            "home_games_won": home_games_won,
            "away_games_won": away_games_won,
            "expected_match_version": expected_version,
        },
        make_coach_headers(world[f"coach_{side}"]["id"]),
    )


def test_every_stale_expected_match_version_is_refused_and_writes_nothing(api):
    """The guard catches a version staled by someone else's write, by the
    reporter's own write and by the opponent's, and it outranks the state rung.

    PRD §2.6: "A result report submitted to `POST
    /matches/{matchId}/result-reports` must carry `expected_match_version` as a
    non-optional field holding the client's last observed `version` of the target
    `Match` ... If the supplied `expected_match_version` does not equal the
    match's current `version`, the report is written against a stale view of the
    match and would silently overwrite a supersession the reporter never saw; it
    is therefore rejected with `ERR_STALE_VERSION` (HTTP 412)."  And: "Both
    checks run after the path and body have been validated but **before** any
    state precondition on the target is evaluated."  PRD §2.7 rung 11:
    "**Optimistic concurrency,** as §2.6 describes, reported as
    `ERR_STALE_VERSION` on result reports and academic postings"; rung 17:
    "**Match play and result state,** otherwise `ERR_INVALID_MATCH_STATE` ...
    result reporting requires `SERVER_READY`".

    Design: Corner/complexity_layers/result_report_optimistic_concurrency_rejects_every_stale_expected_match_version
    """
    world = _build_server_ready_match(api)
    match_id = world["match"]["id"]
    home, away = world["team_a"], world["team_b"]

    validate_error(_report(api, world, "a", 1), ApiErrorId.ERR_STALE_VERSION.value, 412)
    untouched = fx.get_match(api, match_id)
    assert untouched["version"] == 2
    assert untouched["home_reported_home_games_won"] is None

    first_response = _report(api, world, "a", 2)
    validate_success(first_response)
    first = A.data_of(first_response)
    A.assert_match_state(first, result_status="PARTIALLY_REPORTED")
    assert first["home_reported_home_games_won"] == 2
    assert first["home_reported_away_games_won"] == 1
    assert first["version"] == 3

    validate_error(_report(api, world, "b", 2), ApiErrorId.ERR_STALE_VERSION.value, 412)
    assert fx.get_match(api, match_id)["version"] == 3

    second_response = _report(api, world, "b", 3)
    validate_success(second_response)
    second = A.data_of(second_response)
    A.assert_match_state(second, play_status="PLAYED", result_status="CONFIRMED")
    assert second["home_games_won"] == 2
    assert second["away_games_won"] == 1
    assert second["winner_team_id"] == home["id"]
    assert second["home_points_awarded"] == 3
    assert second["away_points_awarded"] == 0
    assert second["version"] == 4

    finalize_response = api.finalize_match(match_id, {}, league_admin_headers())
    validate_success(finalize_response)
    finalized = A.data_of(finalize_response)
    A.assert_match_state(finalized, play_status="FINALIZED", result_status="CONFIRMED")
    assert finalized["version"] == 5

    validate_error(
        _report(api, world, "a", 3, home_games_won=3, away_games_won=0),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )
    validate_error(
        _report(api, world, "a", 5, home_games_won=3, away_games_won=0),
        ApiErrorId.ERR_INVALID_MATCH_STATE.value,
        409,
    )

    assert fx.get_match(api, match_id)["version"] == 5
    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 3)
    assert fx.get_team(api, home["id"])["match_points"] == 3
    assert fx.get_team(api, away["id"])["match_points"] == 0


# ==========================================================================
# Instance: academic_posting_optimistic_concurrency_guards_a_version_that_other_
#           endpoints_also_move
# ==========================================================================
def _build_draft_team_and_one_student(api):
    """A DRAFT team and one freshly enrolled student at version 1, born on the
    date the enrollment document will name."""
    world = fx.build_draft_team(api)
    student = fx.make_student(api, world["school"]["id"], birthdate="2009-05-10")
    assert student["version"] == 1, "PRD §2.5 starts the counter at one"
    return {"coach": world["coach"], "team": world["team"], "student": student}


def _post_term(api, student_id, term_label, term_gpa, expected_version):
    return api.post_academic_term(
        student_id,
        {
            "term_label": term_label,
            "term_gpa": term_gpa,
            "term_credits": 6.0,
            "expected_student_version": expected_version,
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_3),
    )


def test_the_student_guard_catches_a_version_moved_by_a_slot_verification(api):
    """`version` is a whole-entity counter, and a refused posting never performs
    the depth-two shift.

    PRD §2.6: "An academic posting submitted to `POST
    /students/{studentId}/academic-postings` must carry
    `expected_student_version` ... A posting shifts the student's latest term into
    the prior-term register and rewrites the derived standing, so a posting
    written against a stale view would push an already-superseded term back into
    the shift register. If `expected_student_version` does not equal the student's
    current `version`, the posting is rejected with `ERR_STALE_VERSION` (HTTP
    412)."  PRD §2.5: "`version` (integer): a counter that increments by exactly
    one on every mutation of that record."  PRD §3.5 on the academics axis: "the
    evaluation of §3.2 runs afresh on the student's current register, writing the
    student's `effective_gpa`, `academic_standing` and `standing_basis_applied`".

    Design: Corner/complexity_layers/academic_posting_optimistic_concurrency_guards_a_version_that_other_endpoints_also_move
    """
    world = _build_draft_team_and_one_student(api)
    student_id = world["student"]["id"]

    first_response = _post_term(api, student_id, "2026-SPRING", 3.200, 1)
    validate_success(first_response)
    first = A.data_of(first_response)
    assert first["version"] == 2
    assert first["latest_term_label"] == "2026-SPRING"
    A.assert_gpa(first["latest_term_gpa"], 3.200)
    assert first["prior_term_gpa"] is None

    validate_error(
        _post_term(api, student_id, "2026-FALL", 2.800, 1),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )
    unshifted = fx.get_student(api, student_id)
    assert unshifted["version"] == 2
    assert unshifted["latest_term_label"] == "2026-SPRING"
    A.assert_gpa(unshifted["latest_term_gpa"], 3.200)
    assert unshifted["prior_term_gpa"] is None

    second_response = _post_term(api, student_id, "2026-FALL", 2.800, 2)
    validate_success(second_response)
    second = A.data_of(second_response)
    assert second["version"] == 3
    assert second["latest_term_label"] == "2026-FALL"
    A.assert_gpa(second["latest_term_gpa"], 2.800)
    A.assert_gpa(second["prior_term_gpa"], 3.200)

    slot = fx.add_slot(
        api, world["team"]["id"], student_id, world["coach"]["id"], "STARTER"
    )
    fx.verify_slot_enrollment(
        api, slot["id"], "2009-05-10", officer_id=ELIGIBILITY_OFFICER_ID
    )
    cleared = fx.verify_slot_academics(
        api, slot["id"], officer_id=ELIGIBILITY_OFFICER_ID_2
    )
    A.assert_slot_axes(cleared, academic_status="CLEARED")
    assert fx.get_student(api, student_id)["version"] == 4

    validate_error(
        _post_term(api, student_id, "2027-SPRING", 3.900, 3),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )
    preserved = fx.get_student(api, student_id)
    assert preserved["latest_term_label"] == "2026-FALL"
    A.assert_gpa(preserved["prior_term_gpa"], 3.200)
    assert preserved["version"] == 4

    third_response = _post_term(api, student_id, "2027-SPRING", 3.900, 4)
    validate_success(third_response)
    third = A.data_of(third_response)
    assert third["version"] == 5
    assert third["latest_term_label"] == "2027-SPRING"
    A.assert_gpa(third["latest_term_gpa"], 3.900)
    A.assert_gpa(third["prior_term_gpa"], 2.800)

    pinned = fx.get_slot(api, slot["id"])
    assert pinned["standing_at_verification"] == cleared["standing_at_verification"]
    A.assert_gpa(
        pinned["effective_gpa_at_verification"],
        cleared["effective_gpa_at_verification"],
    )


# ==========================================================================
# Instance: derived_fields_reconcile_after_create_update_and_removal_of_their_
#           source_rows
# ==========================================================================
def _build_team_and_one_good_standing_student(api):
    """A DRAFT team with no slots and one student already carrying a 3.200 term,
    so their standing is `GOOD` before any verification."""
    world = fx.build_draft_team(api)
    student = fx.make_student(api, world["school"]["id"], birthdate="2009-05-10")
    student = fx.post_term(api, student, 3.200, 6.0, term_label="2026-SPRING")
    return {"coach": world["coach"], "team": world["team"], "student": student}


def test_the_roll_ups_reconcile_while_the_pinned_snapshot_never_moves(api):
    """A source row appears, changes on both axes and leaves; the seat identity
    holds at every step and a later INELIGIBLE posting rewrites nothing pinned.

    PRD §3.5: "`starter_slots_used` is the count of the team's slots whose
    `slot_role` is `STARTER` and whose `participation_status` is `PROSPECTIVE`,
    `ACTIVE` or `INELIGIBLE` — released slots are excluded ... The third axis,
    `participation_status`, is derived rather than commanded ... A slot is
    `ACTIVE` when both axes have cleared".  And on the academics axis: "the
    slot's `standing_at_verification` and `effective_gpa_at_verification` pin the
    figures that cleared it".  PRD §3.2: "When the recomputed standing lands on
    `INELIGIBLE`, every roster slot belonging to that student whose academics
    axis is still `PENDING` ... moves its academics axis from `PENDING` to
    `BLOCKED`".  PRD §2.9: "For every team, `starter_slots_used` plus
    `starter_slots_available` always equals the season's `max_starters`."

    Design: Corner/complexity_layers/derived_fields_reconcile_after_create_update_and_removal_of_their_source_rows
    """
    world = _build_team_and_one_good_standing_student(api)
    coach_headers = make_coach_headers(world["coach"]["id"])
    team_id = world["team"]["id"]
    student = world["student"]

    empty = A.data_of(api.get_team(team_id, coach_headers))
    assert empty["starter_slots_used"] == 0
    assert empty["starter_slots_available"] == 3
    assert empty["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(empty, 3)

    slot = fx.add_slot(api, team_id, student["id"], world["coach"]["id"], "STARTER")
    appeared = fx.get_team(api, team_id)
    assert appeared["starter_slots_used"] == 1
    assert appeared["starter_slots_available"] == 2
    assert appeared["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(appeared, 3)

    half_verified = fx.verify_slot_enrollment(
        api, slot["id"], "2009-05-10", officer_id=ELIGIBILITY_OFFICER_ID
    )
    A.assert_slot_axes(
        half_verified,
        verification_status="ENROLLMENT_VERIFIED",
        participation_status="PROSPECTIVE",
    )
    assert fx.get_team(api, team_id)["active_starter_count"] == 0

    activated = fx.verify_slot_academics(
        api, slot["id"], officer_id=ELIGIBILITY_OFFICER_ID_2
    )
    A.assert_slot_axes(
        activated, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert activated["standing_at_verification"] == "GOOD"
    A.assert_gpa(activated["effective_gpa_at_verification"], 3.200)

    reconciled = A.data_of(api.get_team(team_id, coach_headers))
    assert reconciled["starter_slots_used"] == 1
    assert reconciled["starter_slots_available"] == 2
    assert reconciled["active_starter_count"] == 1
    A.assert_starter_capacity_conserved(reconciled, 3)

    current = fx.get_student(api, student["id"])
    demoting = _post_term(api, student["id"], "2026-FALL", 1.400, current["version"])
    validate_success(demoting)
    demoted_student = A.data_of(demoting)
    A.assert_gpa(demoted_student["effective_gpa"], 1.400)
    assert demoted_student["academic_standing"] == "INELIGIBLE"

    still_pinned = fx.get_slot(api, slot["id"])
    A.assert_slot_axes(
        still_pinned, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert still_pinned["standing_at_verification"] == "GOOD"
    A.assert_gpa(still_pinned["effective_gpa_at_verification"], 3.200)
    assert fx.get_team(api, team_id)["active_starter_count"] == 1

    released_response = api.release_roster_slot(
        slot["id"], {"release_note": "transferred out"}, coach_headers
    )
    validate_success(released_response)
    released = A.data_of(released_response)
    A.assert_slot_axes(released, participation_status="RELEASED")
    assert released["released_at"] == "2026-08-01T00:00:00.000Z"

    final = A.data_of(api.get_team(team_id, coach_headers))
    assert final["starter_slots_used"] == 0
    assert final["starter_slots_available"] == 3
    assert final["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(final, 3)
