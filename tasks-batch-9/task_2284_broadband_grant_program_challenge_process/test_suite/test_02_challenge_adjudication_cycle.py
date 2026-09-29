"""The rebuttal negotiation cycle and the cascade a sustained challenge fires."""

from test_helpers import (
    ApiErrorId,
    advance_program_to_scoring,
    api_client,
    close_rebuttal,
    read_application,
    read_challenge,
    read_location,
    read_program,
    score_application,
    set_clock,
    setup_challenge_open_program,
    setup_community_challenge_meeting_standard,
    setup_qualified_subgrantee,
    setup_submitted_application,
    triage_challenge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, ANALYST_OTHER


def _challenge_under_review_at_round_one():
    """A triaged community challenge whose first rebuttal window has been closed
    on the deadline branch, leaving it UNDER_REVIEW at rebuttal_round 1."""
    ctx = setup_challenge_open_program(("L3",))
    challenge = setup_community_challenge_meeting_standard(
        ctx["program_id"], ctx["location_ids"]["L3"]
    )
    triage_challenge(challenge["id"])
    set_clock("2026-09-09T00:00:00Z")
    close_rebuttal(challenge["id"])
    ctx["challenge"] = read_challenge(challenge["id"])
    ctx["challenge_id"] = challenge["id"]
    return ctx


def test_rebuttal_cycle_runs_twice_then_refuses_a_third_round():
    """UNDER_REVIEW and REBUTTAL_OPEN form a cycle bounded by a ceiling of two
    rounds, and the round counter never resets on the way round.

    PRD 3.3: "Reopening requires `rebuttal_round` to be strictly below the
    ceiling of two rounds and requires the program to be `CHALLENGE_OPEN` or
    `CHALLENGE_CLOSED`, so the negotiation cycle cannot be restarted once
    scoring has opened."
    PRD 3.3: "Attempting a third round, once `rebuttal_round` has reached two,
    is refused with `ERR_REBUTTAL_ROUND_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/challenge_rebuttal_round_cycle_exhaustion
    """
    ctx = _challenge_under_review_at_round_one()
    challenge_id = ctx["challenge_id"]
    assert ctx["challenge"]["challenge_state"] == "UNDER_REVIEW"
    assert ctx["challenge"]["rebuttal_round"] == 1

    reopened = validate_success(
        api_client.request_additional_evidence(
            challenge_id, {"reason": "Provider asked for more time."}, ANALYST
        )
    )
    assert reopened["challenge_state"] == "REBUTTAL_OPEN"
    assert reopened["rebuttal_round"] == 2

    set_clock("2026-10-09T00:00:00Z")
    closed_again = close_rebuttal(challenge_id)
    assert closed_again["challenge_state"] == "UNDER_REVIEW"
    assert closed_again["rebuttal_round"] == 2, (
        "Traversing the cycle a second time leaves the counter at the ceiling "
        "rather than resetting it"
    )

    third = api_client.request_additional_evidence(
        challenge_id, {"reason": "One more round."}, ANALYST
    )
    validate_error(third, ApiErrorId.ERR_REBUTTAL_ROUND_EXHAUSTED)

    unchanged = read_challenge(challenge_id)
    assert unchanged["challenge_state"] == "UNDER_REVIEW"
    assert unchanged["rebuttal_round"] == 2


def test_reopening_restamps_the_rebuttal_deadline_thirty_days_from_the_reopen():
    """Each pass through the cycle re-stamps the deadline against the instant of
    that pass, not against the original triage.

    PRD 3.3: "Triage sets `rebuttal_round` to 1, stamps `rebuttal_deadline` at
    thirty days after the current logical instant, records the acting analyst as
    `triaged_by_user_id`, and on the eligibility axis moves the contested
    location `MAPPED → CHALLENGED` while re-deriving that location's
    `challenge_count`."
    PRD 3.3: "It increments `rebuttal_round` and re-stamps `rebuttal_deadline`
    at thirty days past the current instant."

    Design: Difficulty/non_linear_state_machine/challenge_rebuttal_round_cycle_exhaustion
    """
    ctx = setup_challenge_open_program(("L3",))
    challenge = setup_community_challenge_meeting_standard(
        ctx["program_id"], ctx["location_ids"]["L3"]
    )

    triaged = triage_challenge(challenge["id"])
    assert triaged["rebuttal_round"] == 1
    assert triaged["rebuttal_deadline"].startswith("2026-09-09T00:00:00")

    set_clock("2026-09-09T00:00:00Z")
    close_rebuttal(challenge["id"])
    reopened = validate_success(
        api_client.request_additional_evidence(
            challenge["id"], {"reason": "Second round requested."}, ANALYST
        )
    )
    assert reopened["rebuttal_deadline"].startswith("2026-10-09T00:00:00"), (
        "The reopen instant, not the triage instant, anchors the second window"
    )


def _scored_application_with_a_live_challenge():
    """A SCORED application whose claim on the contested location is
    CLAIMED_INELIGIBLE, with the challenge parked UNDER_REVIEW in a SCORING
    program so a determination lands on a live scoring phase.

    The contested location L1 classifies SERVED, so its claim is ineligible; the
    two other claims are eligible at 900002 cents each.
    """
    ctx = setup_challenge_open_program(("L1", "L2", "L3"))
    contested = ctx["location_ids"]["L1"]

    challenge = setup_community_challenge_meeting_standard(ctx["program_id"], contested)
    triage_challenge(challenge["id"])

    subgrantee = setup_qualified_subgrantee(ctx["program_id"])
    application, claims = setup_submitted_application(
        ctx["program_id"],
        subgrantee["id"],
        [
            (contested, 600000),
            (ctx["location_ids"]["L2"], 900002),
            (ctx["location_ids"]["L3"], 900002),
        ],
    )
    advance_program_to_scoring(ctx["program_id"])
    score_sheet = score_application(application["id"])

    ctx.update(
        {
            "challenge_id": challenge["id"],
            "contested_location_id": contested,
            "subgrantee_id": subgrantee["id"],
            "application_id": application["id"],
            "claims": claims,
            "score_sheet": score_sheet,
        }
    )
    return ctx


def test_sustained_determination_reclassifies_location_and_flips_the_claim():
    """The first two hops of the sustain cascade: the location is re-stamped
    from the asserted classification and the ineligible claim on it flips,
    lifting the owning application's eligible aggregates in the same request.

    PRD 3.3: "The location's `classification_status` is re-stamped from the
    challenge's `asserted_classification`, its `classification_source` becomes
    `CHALLENGE_DETERMINATION`, and on the eligibility axis it moves
    `CHALLENGED → RECLASSIFIED`."
    PRD 3.3: "Because the location's classification is now `UNSERVED` or
    `UNDERSERVED`, every location claim on that location sitting in
    `CLAIMED_INELIGIBLE` flips to `CLAIMED_ELIGIBLE`."

    Design: Difficulty/transitive_cascade/sustained_challenge_four_hop_rescore_cascade
    """
    ctx = _scored_application_with_a_live_challenge()

    before = read_application(ctx["application_id"])
    assert before["claim_count"] == 3
    assert before["confirmed_location_count"] == 2
    assert before["eligible_project_cost_cents"] == 1800004
    assert before["final_cost_per_location_cents"] == 900002

    sustained = validate_success(
        api_client.determine_challenge(
            ctx["challenge_id"],
            {"outcome": "SUSTAINED", "determination_note": "Field survey agreed."},
            ANALYST_OTHER,
        )
    )
    assert sustained["challenge_state"] == "SUSTAINED"

    location = read_location(ctx["contested_location_id"])
    assert location["classification_status"] == "UNSERVED"
    assert location["classification_source"] == "CHALLENGE_DETERMINATION"
    assert location["eligibility_state"] == "RECLASSIFIED"

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    flipped = [c for c in claims if c["location_id"] == ctx["contested_location_id"]]
    assert len(flipped) == 1
    assert flipped[0]["claim_state"] == "CLAIMED_ELIGIBLE"

    after = read_application(ctx["application_id"])
    assert after["claim_count"] == 3
    assert after["confirmed_location_count"] == 3
    assert after["eligible_project_cost_cents"] == 2400004
    assert after["final_cost_per_location_cents"] == 800001, (
        "2400004 over three confirmed locations is 800001.33, rounded half up "
        "to a whole cent"
    )


def test_sustained_determination_stales_the_sheet_and_restricts_the_program():
    """The last two hops of the sustain cascade: the FINAL sheet goes STALE, the
    application is pushed back for rescoring with its version incremented, and
    the program's posture drops from OPEN to RESTRICTED.

    PRD 3.3: "Because that application's confirmed location count changed, each
    of its score sheets in `score_state` `FINAL` moves to `STALE`, the
    application moves `SCORED → RESCORE_REQUIRED` with `rescore_required_reason`
    set to `CHALLENGE_RECLASSIFICATION`, and the application's `version`
    increments by one."
    PRD 3.3: "Because the program's `stale_score_sheet_count` has now reached at
    least one, the program's `scoring_posture` moves `OPEN → RESTRICTED`, which
    blocks award obligation across the entire program until every stale sheet
    has been superseded."

    Design: Difficulty/transitive_cascade/sustained_challenge_four_hop_rescore_cascade
    """
    ctx = _scored_application_with_a_live_challenge()

    before_app = read_application(ctx["application_id"])
    assert before_app["application_state"] == "SCORED"
    assert read_program(ctx["program_id"])["scoring_posture"] == "OPEN"

    validate_success(
        api_client.determine_challenge(
            ctx["challenge_id"], {"outcome": "SUSTAINED"}, ANALYST_OTHER
        )
    )

    sheets, _ = validate_paginated(
        api_client.list_application_score_sheets(ctx["application_id"], ADMIN)
    )
    assert [s["score_state"] for s in sheets] == ["STALE"]

    after_app = read_application(ctx["application_id"])
    assert after_app["application_state"] == "RESCORE_REQUIRED"
    assert after_app["rescore_required_reason"] == "CHALLENGE_RECLASSIFICATION"
    assert after_app["version"] == before_app["version"] + 1

    program = read_program(ctx["program_id"])
    assert program["program_state"] == "SCORING"
    assert program["stale_score_sheet_count"] == 1
    assert program["scoring_posture"] == "RESTRICTED"
