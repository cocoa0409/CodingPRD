"""State guards on the two writes that a carrier's own standing turns on.

Publishing a scorecard is what makes a period count, and applying a mini-bid is
what makes a rate adjustment real; both have neighbours that look similar and must
be refused. Each guard is driven twice — once refused on state, once allowed once
the missing step has been taken — so a run that accepts either write early is
caught rather than merely mis-scored.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CLOCK_GO_LIVE,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    api_client,
    assert_same_instant,
    create_qualified_carrier,
    draft_scorecard,
    make_carrier_rep_headers,
    mini_bid_denial_payload,
    mini_bid_proposal_payload,
    mini_bid_revert_payload,
    read_carrier,
    read_contract,
    read_mini_bid,
    read_rate_record,
    request_mini_bid,
    scorecard_dispute_payload,
    set_clock,
    setup_live_rate_record,
    validate_error,
    validate_paginated,
    validate_success,
)

# A period scoring 0.45 x 92.00 + 0.35 x 100.00 + 0.20 x 90.00, the last from a
# claims ratio of 0.0100.
STRONG_PERIOD = {"on_time_pct": 92.00, "claims_ratio": 0.0100}
STRONG_PERIOD_SCORE = 94.40

# A period scoring 0.45 x 55.00 + 0.35 x 100.00 + 0.20 x 20.00.
WEAK_PERIOD = {"on_time_pct": 55.00, "claims_ratio": 0.0800}
WEAK_PERIOD_SCORE = 63.75

# The carrier's composite before any scorecard is published, and after the strong
# one is: 0.70 x 94.40 + 0.20 x 88.00 + 0.10 x 100.00.
PROVISIONAL_COMPOSITE = 90.60
COMPOSITE_AFTER_STRONG_PERIOD = 93.68

# The committed value of the single-lane contract: 1147 miles x 2.0000 x 550
# loads, less the 1.5% volume discount, plus the 2.0% accessorial allowance.
CONTRACT_VALUE_USD = 1267629.99

# A window that is already open at the go-live instant, so the clock cannot be
# what refuses a proposal inside it.
MANUAL_WINDOW = {
    "window_open_at": CLOCK_GO_LIVE,
    "window_close_at": "2026-09-11T00:00:00Z",
}
DENIAL_REASON = "Market index reversed; no adjustment warranted"
REVERT_REASON = "Requested in error"
PROPOSED_RATE_PER_MILE = 2.1000


def _publish(scorecard_id):
    """Attempts a scorecard publication without asserting the outcome."""
    return api_client.publish_scorecard(scorecard_id, CATEGORY_MANAGER)


def _dispute(scorecard_id, carrier_id, **overrides):
    """Attempts a dispute as the scorecard's own carrier."""
    return api_client.dispute_scorecard(
        scorecard_id,
        scorecard_dispute_payload(**overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _read_scorecard(carrier_id, scorecard_id):
    """Reads one scorecard back through its carrier's collection."""
    rows, _meta = validate_paginated(
        api_client.list_carrier_scorecards(carrier_id, ANALYST)
    )
    matching = [row for row in rows if row["id"] == scorecard_id]
    assert matching, f"scorecard {scorecard_id} is missing from its carrier's list"
    return matching[0]


def _count_scorecards(carrier_id):
    _rows, meta = validate_paginated(
        api_client.list_carrier_scorecards(carrier_id, ANALYST)
    )
    return meta["total_count"]


def _propose(mini_bid_id, carrier_id, **overrides):
    """Attempts a carrier proposal without asserting the outcome."""
    return api_client.propose_mini_bid_rate(
        mini_bid_id,
        mini_bid_proposal_payload(carrier_id, **overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _deny(mini_bid_id, **overrides):
    return api_client.deny_mini_bid(
        mini_bid_id, mini_bid_denial_payload(**overrides), CATEGORY_MANAGER
    )


def _revert(mini_bid_id, **overrides):
    return api_client.revert_mini_bid(
        mini_bid_id, mini_bid_revert_payload(**overrides), CONTRACT_ADMIN
    )


class TestScorecardPublicationIsNotReplayable:
    """Publication is the write that admits a period into the lookback."""

    def test_the_first_publish_scores_the_period_and_re_scores_the_carrier(self):
        """One published period, so the performance component is that period's score.

        PRD §3.2: "A category manager publishes a `DRAFT` scorecard; the scorecard moves
        from `DRAFT` to `PUBLISHED` and `published_at` is set to the logical clock."
        PRD §3.2: "Multiply `on_time_pct` by `0.45`, `tender_acceptance_pct` by `0.35`
        and the claims subscore by `0.20`, add the three products, and round to 2 decimal
        places."
        PRD §3.2: "When `period_tender_count` is zero, `tender_acceptance_pct` is
        `100.00` — a carrier that was never tendered in the period is not penalised for
        it."
        PRD §3.2: "with one it is `0.50`, which makes a single-scorecard carrier's
        performance component equal to that scorecard's own score"
        PRD §3.2: "Multiply the performance component by `0.70`, the carrier's
        `capability_score` by `0.20` and the insurance component by `0.10`, add the three
        products, and round to 2 decimal places."

        Design: Corner/state_machines/scorecard_publish_replayed_returns_scorecard_already_published
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        assert float(carrier["composite_score"]) == PROVISIONAL_COMPOSITE
        assert carrier["composite_score_variant"] == "PROVISIONAL_SCREENING"

        scorecard = draft_scorecard(carrier["id"], **STRONG_PERIOD)
        published = validate_success(_publish(scorecard["id"]))
        assert published["status"] == "PUBLISHED"
        assert_same_instant(published["published_at"], DEFAULT_CLOCK, "published_at")
        assert published["period_tender_count"] == 0
        assert float(published["tender_acceptance_pct"]) == 100.00
        assert float(published["composite_score"]) == STRONG_PERIOD_SCORE

        rescored = read_carrier(carrier["id"])
        assert rescored["published_scorecard_count"] == 1
        assert rescored["composite_score_variant"] == "FINAL_PERFORMANCE"
        assert float(rescored["composite_score"]) == COMPOSITE_AFTER_STRONG_PERIOD
        assert rescored["status"] == "QUALIFIED"

    def test_the_replay_is_refused_and_cannot_inflate_the_lookback(self):
        """A second publish would count one period twice toward the composite.

        PRD §3.2: "A scorecard that is already `PUBLISHED`, or that has since been
        `DISPUTED`, cannot be published again and is rejected with
        `ERR_SCORECARD_ALREADY_PUBLISHED` (409)."
        PRD §3.2: "The carrier's `published_scorecard_count` is recomputed as the number
        of that carrier's scorecards that participate in the composite lookback — that
        is, the count of its `PUBLISHED` and `DISPUTED` scorecards, capped at three,
        since only the three most recent participate."
        PRD §2.9: "no later check is evaluated and no partial write is retained"

        Design: Corner/state_machines/scorecard_publish_replayed_returns_scorecard_already_published
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        scorecard = draft_scorecard(carrier["id"], **STRONG_PERIOD)
        validate_success(_publish(scorecard["id"]))

        validate_error(
            _publish(scorecard["id"]), "ERR_SCORECARD_ALREADY_PUBLISHED", 409
        )

        replayed = _read_scorecard(carrier["id"], scorecard["id"])
        assert replayed["status"] == "PUBLISHED"
        assert_same_instant(replayed["published_at"], DEFAULT_CLOCK, "published_at")
        assert _count_scorecards(carrier["id"]) == 1

        unchanged = read_carrier(carrier["id"])
        assert unchanged["published_scorecard_count"] == 1, (
            "the refused replay may not admit the same period a second time"
        )
        assert float(unchanged["composite_score"]) == COMPOSITE_AFTER_STRONG_PERIOD
        assert unchanged["composite_score_variant"] == "FINAL_PERFORMANCE"
        assert unchanged["status"] == "QUALIFIED"


class TestDraftScorecardCannotBeDisputed:
    """A carrier may only object to a period it has actually been shown."""

    def test_disputing_a_draft_is_refused_and_the_draft_stays_invisible(self):
        """The owning carrier is acting, so ownership cannot be what refuses it.

        PRD §3.2: "A carrier representative may dispute a scorecard belonging to its own
        carrier, supplying a `disputed_reason`. The scorecard must be `PUBLISHED`; a
        scorecard still in `DRAFT` cannot be disputed and the attempt is rejected with
        `ERR_SCORECARD_NOT_PUBLISHED` (409)."
        PRD §3.2: "Drafting a scorecard does not touch the carrier in any way. A `DRAFT`
        scorecard is invisible to the carrier's own composite score."
        PRD §3.2: "Multiply `claims_ratio` by 1000, subtract that product from `100.00`,
        round to 2 decimal places, and then floor the result at `0.00` so it never goes
        negative."

        Design: Corner/state_machines/dispute_of_a_draft_scorecard_returns_scorecard_not_published
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        scorecard = draft_scorecard(carrier["id"], **WEAK_PERIOD)
        assert scorecard["status"] == "DRAFT"
        assert float(scorecard["composite_score"]) == WEAK_PERIOD_SCORE

        validate_error(
            _dispute(scorecard["id"], carrier["id"]), "ERR_SCORECARD_NOT_PUBLISHED", 409
        )

        untouched = _read_scorecard(carrier["id"], scorecard["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["disputed_reason"] is None
        assert untouched["published_at"] is None

        carrier_after = read_carrier(carrier["id"])
        assert carrier_after["published_scorecard_count"] == 0
        assert float(carrier_after["composite_score"]) == PROVISIONAL_COMPOSITE, (
            "a DRAFT scorecard never feeds the composite, whatever it scores"
        )
        assert carrier_after["composite_score_variant"] == "PROVISIONAL_SCREENING"

    def test_the_same_dispute_succeeds_once_the_scorecard_is_published(self):
        """Publication was the only thing missing, and the dispute moves no score.

        PRD §3.2: "The scorecard moves from `PUBLISHED` to `DISPUTED`, which is
        terminal."
        PRD §3.2: "Disputing changes no score: the carrier's `composite_score` is
        deliberately **not** recomputed, and a `DISPUTED` scorecard remains inside the
        composite lookback exactly as it was."

        Design: Corner/state_machines/dispute_of_a_draft_scorecard_returns_scorecard_not_published
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        scorecard = draft_scorecard(carrier["id"], **WEAK_PERIOD)
        validate_error(
            _dispute(scorecard["id"], carrier["id"]), "ERR_SCORECARD_NOT_PUBLISHED", 409
        )

        validate_success(_publish(scorecard["id"]))
        before = read_carrier(carrier["id"])
        assert before["published_scorecard_count"] == 1

        disputed = validate_success(_dispute(scorecard["id"], carrier["id"]))
        assert disputed["status"] == "DISPUTED"
        assert disputed["disputed_reason"] == (
            "On-time data disputed by the carrier"
        )

        after = read_carrier(carrier["id"])
        assert float(after["composite_score"]) == float(before["composite_score"]), (
            "the dispute may not re-score the carrier in either direction"
        )
        assert after["published_scorecard_count"] == 1, (
            "a DISPUTED scorecard stays inside the lookback"
        )


class TestDeniedMiniBidRefusesProposals:
    """`DENIED` is terminal, so a window that was closed by hand stays closed."""

    def test_a_proposal_inside_a_denied_window_is_refused_and_writes_nothing(self):
        """The clock is inside the window and the carrier is routed on the lane.

        PRD §3.9: "A carrier representative proposes a replacement rate on a mini-bid
        whose `status` is `REQUESTED`; against any other status the attempt is rejected
        with `ERR_MINI_BID_NOT_OPEN` (409)."
        PRD §3.9: "A category manager may close a mini-bid without adjusting anything,
        from either `REQUESTED` or `OPEN`, supplying a mandatory `denial_reason`. The
        mini-bid moves to the terminal `DENIED`. No rate record is created or changed, no
        contract value moves, and no lane or allocation status changes"
        PRD §3.9: "The mini-bid is created with `status` `REQUESTED` and `origin`
        `MANUAL`, distinguishing it from the automatically generated ones, and with
        `proposed_rate_per_mile`, `proposed_by_carrier_id`, `adjustment_pct`,
        `applied_rate_record_id`, `applied_at`, `contract_value_before_usd`,
        `contract_value_after_usd`, `denial_reason`, `revert_reason` and `reverted_at`
        all null."

        Design: Corner/state_machines/proposal_on_a_denied_mini_bid_returns_mini_bid_not_open
        """
        ctx = setup_live_rate_record()
        mini_bid = request_mini_bid(
            ctx["event"]["id"],
            ctx["lane"]["id"],
            ctx["rate_record"]["id"],
            **MANUAL_WINDOW,
        )
        assert mini_bid["status"] == "REQUESTED"
        assert mini_bid["origin"] == "MANUAL"
        assert mini_bid["proposed_rate_per_mile"] is None
        assert mini_bid["adjustment_pct"] is None
        assert_same_instant(mini_bid["window_open_at"], CLOCK_GO_LIVE, "window_open_at")

        denied = validate_success(_deny(mini_bid["id"], denial_reason=DENIAL_REASON))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == DENIAL_REASON

        # The clock is still the go-live instant, which is the window's own open
        # endpoint, so the closed-interval window check cannot be the refusal.
        validate_error(
            _propose(
                mini_bid["id"],
                ctx["carrier"]["id"],
                proposed_rate_per_mile=PROPOSED_RATE_PER_MILE,
            ),
            "ERR_MINI_BID_NOT_OPEN",
            409,
        )

        after = read_mini_bid(mini_bid["id"])
        assert after["status"] == "DENIED"
        assert after["proposed_rate_per_mile"] is None
        assert after["proposed_by_carrier_id"] is None
        assert after["adjustment_pct"] is None
        assert float(read_contract(ctx["contract"]["id"])["total_committed_value_usd"]) == (
            CONTRACT_VALUE_USD
        )
        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "LIVE"
        assert record["superseded_by_rate_record_id"] is None


class TestRevertRequiresAnAppliedMiniBid:
    """The compensating transition exists only for an adjustment that moved money."""

    def test_reverting_a_requested_mini_bid_is_refused_and_compensates_nothing(self):
        """There is no `applied_rate_record_id` to unwind, so the revert is refused.

        PRD §3.9: "The mini-bid's `status` must be `APPLIED`, otherwise
        `ERR_MINI_BID_NOT_APPLIED` (409), and the replacement record identified by
        `applied_rate_record_id` must still be `LIVE`"
        PRD §3.9: "The contract's `amendment_count` decreases by one, its committed value
        is re-evaluated over the restored basis, and its `version` increases by one."
        PRD §3.9: "The replacement rate record moves from `LIVE` to the terminal
        `ROLLED_BACK`. The record it had superseded moves from `SUPERSEDED` back to
        `LIVE`, and its `superseded_by_rate_record_id` is cleared to null."
        PRD §3.9: "The mini-bid records `revert_reason` and sets `reverted_at` from the
        logical clock, then moves from `APPLIED` to the terminal `REVERTED`."

        Design: Corner/state_machines/revert_of_a_mini_bid_that_was_never_applied_returns_mini_bid_not_applied
        """
        ctx = setup_live_rate_record()
        assert ctx["contract"]["status"] == "EXECUTED"
        assert ctx["contract"]["amendment_count"] == 0
        mini_bid = request_mini_bid(
            ctx["event"]["id"],
            ctx["lane"]["id"],
            ctx["rate_record"]["id"],
            **MANUAL_WINDOW,
        )
        assert mini_bid["applied_rate_record_id"] is None

        validate_error(
            _revert(mini_bid["id"], revert_reason=REVERT_REASON),
            "ERR_MINI_BID_NOT_APPLIED",
            409,
        )

        after = read_mini_bid(mini_bid["id"])
        assert after["status"] == "REQUESTED"
        assert after["applied_rate_record_id"] is None
        assert after["applied_at"] is None
        assert after["reverted_at"] is None
        assert after["revert_reason"] is None

        contract = read_contract(ctx["contract"]["id"])
        assert contract["amendment_count"] == 0, (
            "the compensating link may not run against an unapplied window"
        )
        assert contract["status"] == "EXECUTED"
        assert float(contract["total_committed_value_usd"]) == CONTRACT_VALUE_USD

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "LIVE"
        assert record["superseded_by_rate_record_id"] is None
