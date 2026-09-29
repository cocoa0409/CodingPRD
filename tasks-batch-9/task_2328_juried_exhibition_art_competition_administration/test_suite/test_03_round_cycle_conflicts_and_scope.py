"""The cyclic round machine, retroactive conflict voiding, and the scope check
that outranks the scoring window."""

import pytest

from test_helpers import (
    JURY_CHAIR_A,
    ApiErrorId,
    create_score_payload,
    fixtures,
    make_juror_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

WORK_RIDGE_LINE = {
    "title": "Ridge Line", "medium_category": "PAINTING",
    "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
}


# ─── Reopen cycle bounded at two ──────────────────────

def _completed_single_work_round():
    exhibition = fixtures.open_call(jury_quorum=1)
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, [WORK_RIDGE_LINE]
    )
    jury_round, juror = fixtures.setup_open_round(
        exhibition["id"], round_overrides={"quorum_required": 1}
    )
    fixtures.submit_score(jury_round["id"], juror, artworks[0]["id"], 8, 8, 8)
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")
    return exhibition, entry, artworks[0], jury_round


def test_reopening_a_completed_round_undoes_the_shortlist_fork(api):
    """PRD §3.5: "On `SCORING_COMPLETE → OPEN` the round's `reopen_count`
    increases by one, every work of the exhibition whose `status` is
    `SHORTLISTED` or `DECLINED` reverts to `SUBMITTED` with its
    `certified_mean_score` cleared to null, and the exhibition's
    `shortlisted_count` is recomputed."

    Design: Difficulty/non_linear_state_machine/jury_round_reopen_cycle_bounded_at_two
    """
    exhibition, _, artwork, jury_round = _completed_single_work_round()

    shortlisted = fixtures.read_artwork(artwork["id"])
    assert shortlisted["status"] == "SHORTLISTED"
    assert shortlisted["certified_mean_score"] == pytest.approx(8.00, abs=0.01)

    reopened = fixtures.set_round_status(jury_round["id"], "OPEN")
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1

    reverted = fixtures.read_artwork(artwork["id"])
    assert reverted["status"] == "SUBMITTED"
    assert reverted["certified_mean_score"] is None
    assert fixtures.read_exhibition(exhibition["id"])["shortlisted_count"] == 0


def test_third_reopen_attempt_is_refused_once_the_budget_is_spent(api):
    """PRD §3.5: "`SCORING_COMPLETE → OPEN` reopens the round for more scoring,
    and is permitted only while `reopen_count` is below 2 and the exhibition is
    still `JURYING`; a third reopen attempt is refused with
    `ERR_ROUND_REOPEN_LIMIT`."

    Design: Difficulty/non_linear_state_machine/jury_round_reopen_cycle_bounded_at_two
    """
    _, _, artwork, jury_round = _completed_single_work_round()

    fixtures.set_round_status(jury_round["id"], "OPEN")
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")
    second = fixtures.set_round_status(jury_round["id"], "OPEN")
    assert second["reopen_count"] == 2
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")

    response = api.set_jury_round_status(
        jury_round["id"], {"target_status": "OPEN"}, JURY_CHAIR_A
    )
    validate_error(response, ApiErrorId.ERR_ROUND_REOPEN_LIMIT.value)

    after = fixtures.read_jury_round(jury_round["id"])
    assert after["reopen_count"] == 2
    assert after["status"] == "SCORING_COMPLETE"

    refork = fixtures.read_artwork(artwork["id"])
    assert refork["status"] == "SHORTLISTED"
    assert refork["certified_mean_score"] == pytest.approx(8.00, abs=0.01)


# ─── Retroactive conflict voiding ─────────────────────

def _two_juror_scored_round():
    exhibition = fixtures.open_call(jury_quorum=2)
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, [WORK_RIDGE_LINE]
    )
    fixtures.enter_jurying(exhibition["id"])

    first = fixtures.invite_and_confirm_juror(
        display_name="Iris Vega", expertise_categories=["PAINTING"]
    )
    second = fixtures.invite_and_confirm_juror(
        display_name="Omar Diaz", expertise_categories=["PAINTING"]
    )
    jury_round = fixtures.create_jury_round(exhibition["id"], quorum_required=2)
    fixtures.book_session(jury_round["id"], first)
    fixtures.book_session(jury_round["id"], second)
    jury_round = fixtures.set_round_status(jury_round["id"], "OPEN")
    fixtures.set_clock(fixtures.CLOCK_SCORING)

    score_first = fixtures.submit_score(
        jury_round["id"], first, artworks[0]["id"], 8, 8, 8
    )
    score_second = fixtures.submit_score(
        jury_round["id"], second, artworks[0]["id"], 6, 6, 6
    )
    return {
        "exhibition": exhibition,
        "artist": artist,
        "artwork": artworks[0],
        "jury_round": jury_round,
        "first_juror": first,
        "second_juror": second,
        "score_first": score_first,
        "score_second": score_second,
    }


def test_conflict_declaration_retroactively_voids_that_jurors_score(api):
    """PRD §3.4: "Filing a declaration acts **retroactively**: every existing
    score cast by that juror on any work belonging to that artist has its
    `voided_by_conflict` flag flipped to true, and the declaration reports how
    many it invalidated in `voided_score_count`."

    Design: Difficulty/transitive_cascade/conflict_declaration_voids_score_and_reopens_quorum_shortfall
    """
    ctx = _two_juror_scored_round()

    before = fixtures.read_artwork(ctx["artwork"]["id"])
    assert before["valid_score_count"] == 2
    assert before["provisional_mean_score"] == pytest.approx(7.00, abs=0.01)

    declaration = fixtures.file_conflict_declaration(
        ctx["second_juror"], ctx["artist"], "TEACHER_STUDENT"
    )
    assert declaration["voided_score_count"] == 1

    voided = validate_success(
        api.get_score(ctx["score_second"]["id"], JURY_CHAIR_A)
    )
    assert voided["voided_by_conflict"] is True

    untouched = validate_success(
        api.get_score(ctx["score_first"]["id"], JURY_CHAIR_A)
    )
    assert untouched["voided_by_conflict"] is False

    after = fixtures.read_artwork(ctx["artwork"]["id"])
    assert after["valid_score_count"] == 1
    assert after["provisional_mean_score"] == pytest.approx(8.00, abs=0.01)


def test_conflict_voided_score_reopens_the_quorum_shortfall(api):
    """PRD §3.4: "Voiding scores in turn forces a recompute of each affected
    artwork's `provisional_mean_score` and `valid_score_count`, and of each
    affected round's `quorum_shortfall_count` — a late declaration can therefore
    make a round that appeared complete no longer completable."

    Design: Difficulty/transitive_cascade/conflict_declaration_voids_score_and_reopens_quorum_shortfall
    """
    ctx = _two_juror_scored_round()

    assert fixtures.read_jury_round(ctx["jury_round"]["id"])["quorum_shortfall_count"] == 0

    fixtures.file_conflict_declaration(
        ctx["second_juror"], ctx["artist"], "TEACHER_STUDENT"
    )

    short = fixtures.read_jury_round(ctx["jury_round"]["id"])
    assert short["quorum_shortfall_count"] == 1

    response = api.set_jury_round_status(
        ctx["jury_round"]["id"], {"target_status": "SCORING_COMPLETE"}, JURY_CHAIR_A
    )
    validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET.value)

    assert fixtures.read_jury_round(ctx["jury_round"]["id"])["status"] == "OPEN"
    artwork = fixtures.read_artwork(ctx["artwork"]["id"])
    assert artwork["status"] == "SUBMITTED"
    assert artwork["certified_mean_score"] is None


# ─── Scope coherence outranks the scoring window ──────

CLOCK_AFTER_ROUND_WINDOW = "2026-10-14T00:00:00Z"


def _two_calls_one_open_round():
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)
    juried = fixtures.open_call()
    other = fixtures.open_call(title="Coastal Small Works")

    artist = fixtures.register_artist()
    _, juried_works = fixtures.setup_submitted_entry(
        juried["id"], artist, [WORK_RIDGE_LINE]
    )
    _, other_works = fixtures.setup_submitted_entry(
        other["id"], artist, [dict(WORK_RIDGE_LINE, title="Coastal Ridge")]
    )

    jury_round, juror = fixtures.setup_open_round(
        juried["id"], round_overrides={"quorum_required": 1}
    )
    return juried, other, juror, jury_round, juried_works[0], other_works[0]


def test_score_on_a_foreign_exhibitions_work_reports_scope_mismatch(api):
    """PRD §2.10: "**Cross-exhibition coherence** — the four checks of §2.5,
    else `ERR_EXHIBITION_SCOPE_MISMATCH` (422)." at position 12, ahead of
    "**Scoring window** — the clock lies within the round's closed window, else
    `ERR_SCORING_WINDOW_CLOSED` (409)." at position 23.

    Design: Difficulty/priority_pair_validation_conflict/score_scope_mismatch_before_scoring_window
    """
    _, _, juror, jury_round, own_work, foreign_work = _two_calls_one_open_round()
    fixtures.set_clock(CLOCK_AFTER_ROUND_WINDOW)

    response = api.submit_score(
        jury_round["id"], create_score_payload(foreign_work["id"], 8, 8, 8),
        make_juror_headers(juror["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EXHIBITION_SCOPE_MISMATCH.value)

    assert fixtures.read_artwork(foreign_work["id"])["valid_score_count"] == 0
    assert fixtures.read_artwork(foreign_work["id"])["provisional_mean_score"] is None
    assert fixtures.read_artwork(own_work["id"])["valid_score_count"] == 0

    _, meta = validate_paginated(
        api.list_scores(JURY_CHAIR_A, params={"jury_round_id": jury_round["id"]})
    )
    assert meta["total_count"] == 0


def test_score_outside_the_window_on_an_in_scope_work_reports_the_window(api):
    """PRD §3.5: "Four gates apply beyond the standard ladder: the juror must be
    `CONFIRMED`; the clock must lie inside the round's closed `[opens_at,
    closes_at]` window, else `ERR_SCORING_WINDOW_CLOSED`; the scored work must
    belong to the round's exhibition, else `ERR_EXHIBITION_SCOPE_MISMATCH`; and
    no score may already exist for this combination of round, work and juror,
    else `ERR_DUPLICATE_SCORE`."

    Design: Difficulty/priority_pair_validation_conflict/score_scope_mismatch_before_scoring_window
    """
    _, _, juror, jury_round, own_work, _ = _two_calls_one_open_round()
    fixtures.set_clock(CLOCK_AFTER_ROUND_WINDOW)

    response = api.submit_score(
        jury_round["id"], create_score_payload(own_work["id"], 8, 8, 8),
        make_juror_headers(juror["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SCORING_WINDOW_CLOSED.value)

    assert fixtures.read_artwork(own_work["id"])["valid_score_count"] == 0
