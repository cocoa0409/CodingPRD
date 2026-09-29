"""Two counters that cap two loops, each at its own declared ceiling.

`rounds_allowed` is per event and configurable, so the cap must be read from the
event rather than assumed; the remediation ceiling is a fixed constant of the
specification. In both cases the interesting boundary is the same shape: the last
permitted iteration succeeds, only the one after it is refused, and the counter is
frozen at the cap rather than advanced by the refusal.
"""

from test_helpers import (
    ANALYST,
    COMPLIANCE,
    COMPLIANCE_USER_ID,
    api_client,
    bid_round_payload,
    close_round,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    create_screened_review,
    decision_payload,
    invite_and_accept,
    open_round,
    read_carrier,
    read_event,
    screen_review,
    second_carrier_overrides,
    validate_error,
    validate_paginated,
    validate_success,
)

# The two event configurations under test, and the fixed remediation ceiling.
ROUNDS_ALLOWED_TWO = 2
ROUNDS_ALLOWED_THREE = 3
REMEDIATION_CEILING = 2

REJECTION_NOTE = "Capability never cleared the floor after two remediations"


def _open_round(event_id, **overrides):
    """Attempts to open the next round without asserting the outcome."""
    return api_client.create_bid_round(event_id, bid_round_payload(**overrides), ANALYST)


def _decide(review_id, outcome, note):
    """Attempts a qualification decision without asserting the outcome."""
    return api_client.decide_qualification_review(
        review_id, decision_payload(outcome=outcome, decision_note=note), COMPLIANCE
    )


def _read_review(carrier_id, review_id):
    """Re-reads one review out of its carrier's review collection."""
    rows, _meta = validate_paginated(
        api_client.list_qualification_reviews(carrier_id, COMPLIANCE)
    )
    matches = [row for row in rows if row["id"] == review_id]
    assert len(matches) == 1, "the review must be readable exactly once"
    return matches[0]


def _event_walked_to_round(rounds_allowed, walk_to=None, carrier_overrides=None):
    """An event configured for `rounds_allowed` rounds, walked up to `walk_to`.

    `walk_to` defaults to `rounds_allowed`, which leaves the event sitting on its
    own cap. `scac_code` is unique across all carriers, so a test that builds two
    events must register the second event's bidder under its own SCAC.
    """
    walk_to = rounds_allowed if walk_to is None else walk_to
    carrier = create_qualified_carrier(carrier_overrides=carrier_overrides)
    event, lanes = create_event_with_locked_lanes(rounds_allowed=rounds_allowed)
    invite_and_accept(event["id"], carrier["id"])
    assert read_event(event["id"])["accepted_invitation_count"] == 1

    rounds = []
    for expected_round_no in range(1, walk_to + 1):
        opened = open_round(event["id"])
        assert opened["round_no"] == expected_round_no
        assert opened["status"] == "OPEN"
        assert opened["submitted_bid_count"] == 0
        assert opened["lowest_rate_per_mile"] is None
        assert read_event(event["id"])["status"] == "ROUND_OPEN"
        close_round(opened["id"])
        rounds.append(opened)

    at_cap = read_event(event["id"])
    assert at_cap["current_round_no"] == walk_to
    assert at_cap["status"] == "ROUND_CLOSED"
    return {"event": at_cap, "lanes": lanes, "carrier": carrier, "rounds": rounds}


def _screened_review_after_remediations(remediations):
    """A `SCREENED` review that has already been sent back `remediations` times."""
    carrier, review = create_screened_review()
    assert review["status"] == "SCREENED"
    assert review["remediation_count"] == 0

    for expected_count in range(1, remediations + 1):
        sent_back = validate_success(
            _decide(review["id"], "REMEDIATE", "Documents incomplete")
        )
        assert sent_back["status"] == "REMEDIATION"
        assert sent_back["remediation_count"] == expected_count
        assert sent_back["insurance_result"] == "PENDING"
        assert sent_back["capability_result"] == "PENDING"
        assert read_carrier(carrier["id"])["status"] == "SCREENING"
        review = screen_review(review["id"])
        assert review["status"] == "SCREENED"
        assert review["remediation_count"] == expected_count

    return carrier, review


class TestTheRoundCapIsReadFromItsOwnEvent:
    """Two rounds on a two-round event, three on a three-round event."""

    def test_the_round_after_the_cap_is_refused_and_the_counter_holds(self):
        """Rounds 1 and 2 open normally; only the third is a limit violation.

        PRD §3.4: "Round 1 may be opened from `INVITING` and requires that
        `accepted_invitation_count` is at least 1 — there is no point opening a round
        nobody can bid into — and that `current_round_no` is strictly less than the
        event's `rounds_allowed`. Subsequent rounds are opened from `ROUND_CLOSED` under
        the same round-count condition. An attempt to open a round when
        `current_round_no` has already reached `rounds_allowed` is rejected with
        `ERR_ROUND_LIMIT_EXCEEDED` (409)"
        PRD §3.4: "The event's `current_round_no` increases by one, the event moves to
        `ROUND_OPEN`, and its `version` increases by one."

        Design: Corner/errors/round_and_remediation_counters_stop_at_their_declared_limits
        """
        ctx = _event_walked_to_round(ROUNDS_ALLOWED_TWO)
        before = ctx["event"]
        assert before["current_round_no"] == ROUNDS_ALLOWED_TWO

        validate_error(
            _open_round(before["id"]), "ERR_ROUND_LIMIT_EXCEEDED", 409
        )

        after = read_event(before["id"])
        assert after["current_round_no"] == ROUNDS_ALLOWED_TWO, (
            "a refused round must not advance the counter"
        )
        assert after["status"] == "ROUND_CLOSED"
        assert after["version"] == before["version"]

        rows, meta = validate_paginated(
            api_client.list_bid_rounds(before["id"], ANALYST)
        )
        assert meta["total_count"] == ROUNDS_ALLOWED_TWO
        assert [row["status"] for row in rows] == ["CLOSED", "CLOSED"]

    def test_a_three_round_event_accepts_the_identical_third_round(self):
        """The cap is the event's own field, not a constant of the system.

        PRD §3.3: "Optionally it may state `fuel_index_per_mile`, a non-negative
        per-mile fuel adder defaulting to `0.4500`; `accessorial_inflation_factor`,
        between `1.00` and `2.00` and defaulting to `1.15`; `rounds_allowed`, an integer
        between 1 and 4 defaulting to 2"
        PRD §3.4: "The round is created with `round_no` set to the event's
        `current_round_no` plus one, `status` `OPEN`, `opens_at` set to the logical
        clock, `closed_at` null, `submitted_bid_count` `0` and `lowest_rate_per_mile`
        null."

        Design: Corner/errors/round_and_remediation_counters_stop_at_their_declared_limits
        """
        capped = _event_walked_to_round(ROUNDS_ALLOWED_TWO)
        validate_error(_open_round(capped["event"]["id"]), "ERR_ROUND_LIMIT_EXCEEDED", 409)

        # The identical two-round history, but on an event permitting three, so the
        # third round is inside the cap rather than past it.
        roomier = _event_walked_to_round(
            ROUNDS_ALLOWED_THREE,
            walk_to=ROUNDS_ALLOWED_TWO,
            carrier_overrides=second_carrier_overrides(),
        )
        third = validate_success(_open_round(roomier["event"]["id"]), 201)
        assert third["round_no"] == ROUNDS_ALLOWED_THREE
        assert third["status"] == "OPEN"

        opened = read_event(roomier["event"]["id"])
        assert opened["current_round_no"] == ROUNDS_ALLOWED_THREE
        assert opened["status"] == "ROUND_OPEN"
        assert opened["version"] > roomier["event"]["version"]


class TestTheRemediationCeilingIsFixedAtTwo:
    """The loop reopens twice and refuses a third, without deadlocking the review."""

    def test_the_third_remediation_is_refused_with_the_counter_at_the_ceiling(self):
        """Two round trips through `REMEDIATION`, then a 409 on the third.

        PRD §3.1: "**`REMEDIATE`** requires that the review's `remediation_count` is
        strictly less than the remediation ceiling of 2; a third attempt to send the same
        review back is rejected with `ERR_REMEDIATION_LIMIT_EXCEEDED` (409). The review
        moves from `SCREENED` to `REMEDIATION`, `remediation_count` increases by one, and
        **both** arm results are reset to `PENDING`, reopening the fork."
        PRD §3.1: "Re-running either arm on a review in `REMEDIATION` returns it to
        `SUBMITTED`, from which the ordinary fork-and-join behaviour resumes: the second
        arm to complete moves it to `SCREENED` again."

        Design: Corner/errors/round_and_remediation_counters_stop_at_their_declared_limits
        """
        carrier, review = _screened_review_after_remediations(REMEDIATION_CEILING)
        assert review["remediation_count"] == REMEDIATION_CEILING

        validate_error(
            _decide(review["id"], "REMEDIATE", "Third attempt"),
            "ERR_REMEDIATION_LIMIT_EXCEEDED",
            409,
        )

        unchanged = _read_review(carrier["id"], review["id"])
        assert unchanged["remediation_count"] == REMEDIATION_CEILING, (
            "the refused decision must not advance the counter"
        )
        assert unchanged["status"] == "SCREENED"
        # "In every branch the review records `decision_outcome`" — the second
        # remediation recorded itself, and nothing in the reopened fork clears it.
        assert unchanged["decision_outcome"] == "REMEDIATE"
        assert unchanged["insurance_result"] == "PASS"
        assert unchanged["capability_result"] == "PASS"
        assert read_carrier(carrier["id"])["status"] == "SCREENING"

    def test_only_the_remediation_loop_is_capped_not_the_review_itself(self):
        """A capped review still decides: `REJECT` carries it to its terminal state.

        PRD §3.1: "**`REJECT`** has no result precondition beyond the review being
        `SCREENED`. The review moves from `SCREENED` to `REJECTED`. The carrier moves
        from `SCREENING` straight to the terminal `DISQUALIFIED`, and its
        `status_reason` is set to the `decision_note` supplied with the decision."
        PRD §3.1: "In every branch the review records `decision_outcome`,
        `decision_note` and `decision_by_user_id` set to the acting `X-User-ID`."

        Design: Corner/errors/round_and_remediation_counters_stop_at_their_declared_limits
        """
        carrier, review = _screened_review_after_remediations(REMEDIATION_CEILING)
        validate_error(
            _decide(review["id"], "REMEDIATE", "Third attempt"),
            "ERR_REMEDIATION_LIMIT_EXCEEDED",
            409,
        )

        rejected = validate_success(_decide(review["id"], "REJECT", REJECTION_NOTE))
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_outcome"] == "REJECT"
        assert rejected["decision_note"] == REJECTION_NOTE
        assert rejected["decision_by_user_id"] == COMPLIANCE_USER_ID
        assert rejected["remediation_count"] == REMEDIATION_CEILING

        disqualified = read_carrier(carrier["id"])
        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["status_reason"] == REJECTION_NOTE
