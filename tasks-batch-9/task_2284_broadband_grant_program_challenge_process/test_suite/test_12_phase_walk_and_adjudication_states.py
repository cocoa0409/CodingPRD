"""Program phase advancement, its bulk effects, and the challenge state guards."""

from test_helpers import (
    ApiErrorId,
    api_client,
    close_allocation,
    close_challenge_window,
    create_program,
    ingest_canonical_location,
    open_challenge_window,
    open_scoring,
    read_application,
    read_challenge,
    read_location,
    read_program,
    set_clock,
    setup_challenge_open_program,
    setup_community_challenge_meeting_standard,
    setup_scored_application,
    setup_under_review_challenge,
    triage_challenge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST


def test_triage_is_refused_once_the_record_has_reached_review():
    """Triage is the single hop out of `SUBMITTED`, so a record already carrying a
    closed rebuttal round cannot be triaged a second time, and the refusal leaves
    the round counter and the analyst of record untouched.

    PRD 2.12: "9. **Priority 41 — challenge state** →
    `ERR_CHALLENGE_STATE_INVALID`. Evidence append requires `SUBMITTED`,
    `REBUTTAL_OPEN`, `UNDER_REVIEW` or `DEFICIENT`; triage requires `SUBMITTED`;
    close-rebuttal requires `REBUTTAL_OPEN`; request-additional-evidence and
    determine require `UNDER_REVIEW`; resubmit requires `DEFICIENT`."
    PRD 3.3: "Triage sets `rebuttal_round` to 1, stamps `rebuttal_deadline` at
    thirty days after the current logical instant, records the acting analyst as
    `triaged_by_user_id`, and on the eligibility axis moves the contested location
    `MAPPED → CHALLENGED` while re-deriving that location's `challenge_count`."

    Design: Corner/state_machines/challenge_triage_from_under_review_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    challenge = setup_under_review_challenge(ctx["program_id"], contested)
    assert challenge["challenge_state"] == "UNDER_REVIEW"
    assert challenge["rebuttal_round"] == 1
    assert challenge["triaged_by_user_id"] == "analyst-1"

    refused = api_client.triage_challenge(challenge["id"], ANALYST)
    validate_error(refused, ApiErrorId.ERR_CHALLENGE_STATE_INVALID)

    after = read_challenge(challenge["id"])
    assert after["challenge_state"] == "UNDER_REVIEW"
    assert after["rebuttal_round"] == 1
    assert after["triaged_by_user_id"] == "analyst-1"
    assert after["version"] == challenge["version"], "A refusal is not a mutation"

    location = read_location(contested)
    assert location["eligibility_state"] == "CHALLENGED"
    assert location["challenge_count"] == 1


def test_closing_the_rebuttal_early_with_an_empty_record_is_refused():
    """Closing has two independent gates: with no rebuttal evidence on the record
    the only route is the deadline, so a close one day early is refused and the same
    call succeeds the moment the clock reaches the deadline.

    PRD 3.3: "Closing is permitted either once the logical clock has reached
    `rebuttal_deadline` or, earlier, as soon as `rebuttal_strength_score` is
    greater than zero — a rebuttal on the record makes waiting pointless."
    PRD 3.3: "Closing before the deadline with no rebuttal evidence at all is
    refused with `ERR_REBUTTAL_DEADLINE_NOT_REACHED`."
    PRD 3.3: "Triage sets `rebuttal_round` to 1, stamps `rebuttal_deadline` at
    thirty days after the current logical instant, records the acting analyst as
    `triaged_by_user_id`, and on the eligibility axis moves the contested location
    `MAPPED → CHALLENGED` while re-deriving that location's `challenge_count`."

    Design: Corner/state_machines/challenge_close_rebuttal_before_deadline_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    challenge = setup_community_challenge_meeting_standard(
        ctx["program_id"], ctx["location_ids"]["L3"]
    )
    triaged = triage_challenge(challenge["id"])
    assert triaged["challenge_state"] == "REBUTTAL_OPEN"
    assert triaged["rebuttal_deadline"].startswith("2026-09-09T00:00:00"), (
        "Thirty days after the 2026-08-10 triage instant"
    )
    assert triaged["rebuttal_strength_score"] == 0.00

    set_clock("2026-09-08T00:00:00Z")
    too_early = api_client.close_rebuttal(challenge["id"], ANALYST)
    validate_error(too_early, ApiErrorId.ERR_REBUTTAL_DEADLINE_NOT_REACHED)
    assert read_challenge(challenge["id"])["challenge_state"] == "REBUTTAL_OPEN"

    set_clock("2026-09-09T00:00:00Z")
    closed = validate_success(api_client.close_rebuttal(challenge["id"], ANALYST))
    assert closed["challenge_state"] == "UNDER_REVIEW", (
        "The deadline instant itself is enough to close"
    )
    assert closed["rebuttal_round"] == 1
    assert closed["rebuttal_strength_score"] == 0.00


def test_closing_the_challenge_window_advances_and_affirms_in_one_call():
    """One administrative call does three things at once: it advances the phase,
    pulls the live rebuttal into review with its deadline collapsed to now, and
    affirms every location the challenge process never touched — while the contested
    location keeps its challenged standing.

    PRD 3.1: "Closing the challenge window moves it
    `CHALLENGE_OPEN → CHALLENGE_CLOSED` and requires that the clock have reached
    `challenge_window_end` and that no challenge of this program still sit in
    `SUBMITTED`."
    PRD 3.1: "That close does three things: every challenge of the program still in
    `REBUTTAL_OPEN` is advanced to `UNDER_REVIEW` with its `rebuttal_deadline`
    forced to the current instant; every location of the program still in `MAPPED`
    moves on the eligibility axis `MAPPED → AFFIRMED` with its
    `classification_source` left as `NATIONAL_MAP`; and the posture is recomputed to
    `RESTRICTED` if at least one score sheet of the program is `STALE`, otherwise to
    `OPEN`."

    Design: Corner/state_machines/program_close_challenge_window_affirms_and_advances_in_one_call
    """
    ctx = setup_challenge_open_program(("L1", "L2", "L3"))
    contested = ctx["location_ids"]["L3"]
    untouched = [ctx["location_ids"]["L1"], ctx["location_ids"]["L2"]]

    challenge = setup_community_challenge_meeting_standard(ctx["program_id"], contested)
    triage_challenge(challenge["id"])
    for location_id in untouched:
        assert read_location(location_id)["eligibility_state"] == "MAPPED"

    set_clock("2026-09-06T00:00:00Z")
    closed = close_challenge_window(ctx["program_id"])
    assert closed["program_state"] == "CHALLENGE_CLOSED"
    assert closed["stale_score_sheet_count"] == 0
    assert closed["scoring_posture"] == "OPEN", (
        "No score sheet is STALE, so the posture opens rather than restricting"
    )

    pulled_in = read_challenge(challenge["id"])
    assert pulled_in["challenge_state"] == "UNDER_REVIEW"
    assert pulled_in["rebuttal_deadline"].startswith("2026-09-06T00:00:00"), (
        "The deadline is forced to the current instant"
    )
    assert pulled_in["rebuttal_round"] == 1

    for location_id in untouched:
        affirmed = read_location(location_id)
        assert affirmed["eligibility_state"] == "AFFIRMED"
        assert affirmed["classification_source"] == "NATIONAL_MAP"

    still_contested = read_location(contested)
    assert still_contested["eligibility_state"] == "CHALLENGED"
    assert still_contested["classification_source"] == "NATIONAL_MAP"


def test_closing_allocation_releases_every_application_left_open():
    """A scored but never selected application is swept to its terminal state when
    allocation closes, each of its claims is released, and the posture freezes
    program-wide with the appropriation untouched.

    PRD 3.1: "Closing allocation moves the program `SCORING → ALLOCATION_CLOSED`,
    requires that no application of the program still sit in `SELECTED`, then moves
    every application of the program still open to `NOT_SELECTED` —
    `DRAFT → NOT_SELECTED`, `SUBMITTED → NOT_SELECTED`,
    `RETURNED_FOR_CURE → NOT_SELECTED`, `SCORED → NOT_SELECTED` and
    `RESCORE_REQUIRED → NOT_SELECTED`, releases each of those applications' claims
    from `CLAIMED_ELIGIBLE` or `CLAIMED_INELIGIBLE` to `RELEASED`, and recomputes
    the posture to `FROZEN`."
    PRD 2.5: "Then the posture is `FROZEN` when `program_state` is `DRAFT`,
    `CHALLENGE_OPEN` or `ALLOCATION_CLOSED`; it is `RESTRICTED` when `program_state`
    is `CHALLENGE_CLOSED` or `SCORING` **and** `stale_score_sheet_count` is at least
    1; and it is `OPEN` in every other case."

    Design: Corner/state_machines/program_close_allocation_releases_unselected_claims
    """
    ctx = setup_scored_application()
    assert read_application(ctx["application_id"])["application_state"] == "SCORED"
    before_claims, before_meta = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert before_meta["total_count"] == 3
    assert {c["claim_state"] for c in before_claims} == {"CLAIMED_ELIGIBLE"}

    closed = close_allocation(ctx["program_id"])
    assert closed["program_state"] == "ALLOCATION_CLOSED"
    assert closed["scoring_posture"] == "FROZEN"
    assert closed["uncommitted_balance_cents"] == 100000000
    assert closed["obligated_balance_cents"] == 0

    assert read_application(ctx["application_id"])["application_state"] == "NOT_SELECTED"
    after_claims, after_meta = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert after_meta["total_count"] == 3
    assert {c["claim_state"] for c in after_claims} == {"RELEASED"}

    sheets, sheet_meta = validate_paginated(
        api_client.list_application_score_sheets(ctx["application_id"], ADMIN)
    )
    assert sheet_meta["total_count"] == 1
    assert sheets[0]["score_state"] == "FINAL", (
        "Closing allocation sweeps applications and claims, not score sheets"
    )


def test_the_posture_projects_from_the_phase_alone_while_no_sheet_is_stale():
    """Walked end to end with no score sheet ever going stale, the posture is a
    pure function of the phase: frozen at both ends of the walk, open across the two
    middle phases, and never restricted.

    PRD 2.5: "The recomputation first counts `stale_score_sheet_count`: the number
    of score sheets whose application belongs to this program and whose
    `score_state` is `STALE`, with no time window applied."
    PRD 2.5: "Then the posture is `FROZEN` when `program_state` is `DRAFT`,
    `CHALLENGE_OPEN` or `ALLOCATION_CLOSED`; it is `RESTRICTED` when `program_state`
    is `CHALLENGE_CLOSED` or `SCORING` **and** `stale_score_sheet_count` is at least
    1; and it is `OPEN` in every other case."
    PRD 2.5: "A `GrantProgram` moves through `program_state` values `DRAFT`,
    `CHALLENGE_OPEN`, `CHALLENGE_CLOSED`, `SCORING` and the terminal
    `ALLOCATION_CLOSED`, always in that order and only forwards."

    Design: Corner/calculations/scoring_posture_projection_across_program_phases
    """
    program = create_program()
    ingest_canonical_location(program["id"], "L3")
    assert program["program_state"] == "DRAFT"
    assert program["scoring_posture"] == "FROZEN"

    set_clock("2026-08-10T00:00:00Z")
    opened = open_challenge_window(program["id"])
    assert opened["program_state"] == "CHALLENGE_OPEN"
    assert opened["scoring_posture"] == "FROZEN", (
        "An open challenge window is still frozen for allocation"
    )

    set_clock("2026-09-06T00:00:00Z")
    challenge_closed = close_challenge_window(program["id"])
    assert challenge_closed["program_state"] == "CHALLENGE_CLOSED"
    assert challenge_closed["scoring_posture"] == "OPEN"

    scoring = open_scoring(program["id"])
    assert scoring["program_state"] == "SCORING"
    assert scoring["scoring_posture"] == "OPEN"

    allocation_closed = close_allocation(program["id"])
    assert allocation_closed["program_state"] == "ALLOCATION_CLOSED"
    assert allocation_closed["scoring_posture"] == "FROZEN"

    for snapshot in (opened, challenge_closed, scoring, allocation_closed):
        assert snapshot["stale_score_sheet_count"] == 0
        assert snapshot["scoring_posture"] != "RESTRICTED", (
            "RESTRICTED needs at least one stale score sheet"
        )
    assert read_program(program["id"])["scoring_posture"] == "FROZEN"
