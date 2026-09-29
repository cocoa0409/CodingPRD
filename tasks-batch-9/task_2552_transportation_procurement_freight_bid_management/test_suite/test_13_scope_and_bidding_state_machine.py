"""Event scope, invitation and bid-round guards on the way into a negotiation.

Scope is frozen before any carrier sees it, and it is frozen all at once: one
un-validated lane blocks the whole event, and nothing may be invited or optimised
out of order. The second half of the file drives the two compensating edges of
the bid machine — an invitation revoked after acceptance, and a bid withdrawn and
re-submitted inside the same open round.
"""

from test_helpers import (
    ANALYST,
    DEFAULT_CLOCK,
    LANE_B_REEFER,
    add_lane,
    add_validated_lane,
    api_client,
    assert_same_instant,
    close_round,
    create_bid_event,
    create_qualified_carrier,
    get_success_data,
    invitation_payload,
    invitation_revoke_payload,
    lane_bid_payload,
    make_carrier_rep_headers,
    optimization_run_payload,
    read_event,
    read_lane,
    read_lane_bid,
    run_optimization,
    set_clock,
    setup_open_round_with_bidder,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

# Lane A's 550 planned loads plus lane B's 120, counted only once both lanes are
# inside the scope status set.
LOCKED_SCOPE_VOLUME_LOADS = 670

# Neither lane names an incumbent, so both are excluded from the event baseline.
LOCKED_SCOPE_BASELINE_USD = 0.00

# The rate the bidder first quotes, and the lower rate it re-quotes after
# withdrawing.
FIRST_RATE_PER_MILE = 2.0000
SECOND_RATE_PER_MILE = 1.9500
SECOND_COMMITTED_VOLUME_LOADS = 400

REVOKED_REASON = "Carrier withdrew from the program"


def _lock_lanes(event_id):
    """Attempts to lock an event's lane scope without asserting the outcome."""
    return api_client.lock_lanes(event_id, ANALYST)


def _invite(event_id, carrier_id, **overrides):
    """Attempts an invitation without asserting the outcome."""
    return api_client.create_invitation(
        event_id, invitation_payload(carrier_id, **overrides), ANALYST
    )


def _list_invitations(**params):
    return api_client.list_invitations(ANALYST, params or None)


def _list_runs(event_id):
    return api_client.list_event_optimization_runs(event_id, ANALYST)


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


def _attempt_bid(round_id, lane_id, carrier_id, **overrides):
    """Submits a lane bid as its owning carrier, without asserting the outcome."""
    return api_client.create_lane_bid(
        round_id,
        lane_bid_payload(lane_id, carrier_id, **overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _two_lane_draft_event():
    """A DRAFT event whose first lane is VALIDATED and whose second is still DRAFT."""
    set_clock(DEFAULT_CLOCK)
    event = create_bid_event()
    lane_a = add_validated_lane(event["id"])
    lane_b = add_lane(event["id"], **LANE_B_REEFER)
    return event, lane_a, lane_b


class TestLaneScopeLockIsAllOrNothing:
    """One un-validated lane blocks the lock, and the lock leaves no half-state."""

    def test_a_draft_lane_blocks_the_lock_without_locking_its_sibling(self):
        """The refusal is atomic: the validated lane must not be locked anyway.

        PRD §3.3: "Locking requires the event to be in `DRAFT` and to hold at least one
        lane; every lane of the event must be `VALIDATED`, and a lane still in `DRAFT`
        causes rejection with `ERR_LANE_NOT_VALIDATED` (409)"
        PRD §2.9: "a lane still in `DRAFT` when the event's lanes are locked raises
        `ERR_LANE_NOT_VALIDATED`"
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and
        no partial write is retained."

        Design: Corner/state_machines/lock_lanes_with_a_draft_lane_returns_lane_not_validated
        """
        event, lane_a, lane_b = _two_lane_draft_event()
        assert lane_a["status"] == "VALIDATED"
        assert lane_b["status"] == "DRAFT"

        validate_error(_lock_lanes(event["id"]), "ERR_LANE_NOT_VALIDATED", 409)

        unchanged = read_event(event["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["total_scope_volume_loads"] == 0
        assert unchanged["baseline_cost_usd"] is None
        assert unchanged["lane_count"] == 2
        assert read_lane(lane_a["id"])["status"] == "VALIDATED", (
            "the failed lock must not promote the already-validated lane"
        )
        assert read_lane(lane_b["id"])["status"] == "DRAFT"

    def test_validating_the_second_lane_lets_the_same_lock_succeed(self):
        """The lock was armed all along; only the lane's own state was missing.

        PRD §3.3: "The lock then does three things: every `VALIDATED` lane of the event
        moves to `LOCKED`; each locked lane's `baseline_cost_usd` is recomputed so the
        frozen scope carries current figures; and the event's
        `total_scope_volume_loads` and `baseline_cost_usd` are rolled up."
        PRD §3.3: "`total_scope_volume_loads` is the sum of `annual_volume_loads` over
        the event's lanes whose `status` is `VALIDATED`, `LOCKED`, `AWARDED` or
        `UNDER_REBID`. Lanes still in `DRAFT` are outside the scope."
        PRD §3.3: "`baseline_cost_usd` is the sum of `baseline_cost_usd` over those
        same lanes, **excluding any lane whose `data_quality_flags` contain
        `NO_INCUMBENT_BASELINE`**, rounded to 2 decimal places."

        Design: Corner/state_machines/lock_lanes_with_a_draft_lane_returns_lane_not_validated
        """
        event, lane_a, lane_b = _two_lane_draft_event()
        validate_error(_lock_lanes(event["id"]), "ERR_LANE_NOT_VALIDATED", 409)

        validated = validate_success(api_client.validate_lane(lane_b["id"], ANALYST))
        assert validated["status"] == "VALIDATED"

        locked = validate_success(_lock_lanes(event["id"]))
        assert locked["status"] == "LANES_LOCKED"
        assert locked["total_scope_volume_loads"] == LOCKED_SCOPE_VOLUME_LOADS
        assert float(locked["baseline_cost_usd"]) == LOCKED_SCOPE_BASELINE_USD
        assert read_lane(lane_a["id"])["status"] == "LOCKED"
        assert read_lane(lane_b["id"])["status"] == "LOCKED"


class TestInvitationRequiresFrozenScope:
    """No carrier may see a scope that can still change under it."""

    def test_inviting_from_draft_is_refused_even_for_a_qualified_carrier(self):
        """The carrier and the lane are both fine; the event's state is not.

        PRD §3.4: "Inviting before the scope is locked is rejected with
        `ERR_LANES_NOT_LOCKED` (409)."
        PRD §2.9: "inviting carriers or opening the first round before the lane scope
        is locked raises `ERR_LANES_NOT_LOCKED`"
        PRD §3.4: "The event's `invited_carrier_count` is recomputed, and on the first
        invitation the event moves from `LANES_LOCKED` to `INVITING`."

        Design: Corner/state_machines/invitation_before_lanes_are_locked_returns_lanes_not_locked
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        assert carrier["status"] == "QUALIFIED"
        event = create_bid_event()
        lane = add_validated_lane(event["id"])
        assert lane["status"] == "VALIDATED"

        validate_error(
            _invite(event["id"], carrier["id"]), "ERR_LANES_NOT_LOCKED", 409
        )

        unchanged = read_event(event["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["invited_carrier_count"] == 0
        assert unchanged["accepted_invitation_count"] == 0

        _rows, meta = validate_paginated(_list_invitations(bid_event_id=event["id"]))
        assert meta["total_count"] == 0, "no invitation row may survive the refusal"


class TestOptimizationRequiresAClosedRound:
    """A scenario is only defined over a closed round's bid set."""

    def test_a_run_created_while_the_round_is_open_is_a_state_refusal(self):
        """The version guard passes, so the 409 is about the round, not the OCC.

        PRD §3.6: "No round of the event may still be `OPEN`; if one is, the request is
        rejected with `ERR_ROUND_STILL_OPEN` (409)."
        PRD §2.9: "creating an optimization run while a round of the event is still
        `OPEN` raises `ERR_ROUND_STILL_OPEN`"
        PRD §2.8: "If `expected_bid_event_version` does not equal the bid event's
        current `version`, the request is rejected with `ERR_STALE_BID_EVENT_VERSION`
        (HTTP 412) and nothing is created."
        PRD §3.6: "A run may be created while the event's `status` is `ROUND_CLOSED`,
        `OPTIMIZING` or `AWARDING`"

        Design: Corner/state_machines/optimization_run_while_a_round_is_still_open_returns_round_still_open
        """
        ctx = setup_open_round_with_bidder()
        submit_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=FIRST_RATE_PER_MILE,
        )
        before = read_event(ctx["event"]["id"])
        assert before["status"] == "ROUND_OPEN"

        premature = api_client.create_optimization_run(
            optimization_run_payload(
                before["id"], before["version"], scenario_label="PREMATURE"
            ),
            ANALYST,
        )
        validate_error(premature, "ERR_ROUND_STILL_OPEN", 409)
        assert premature.json()["data"]["error_id"] != "ERR_STALE_BID_EVENT_VERSION"
        assert premature.status_code != 412

        after = read_event(ctx["event"]["id"])
        assert after["status"] == "ROUND_OPEN"
        assert after["version"] == before["version"], (
            "a refused run may not advance the event's version"
        )
        _rows, meta = validate_paginated(_list_runs(ctx["event"]["id"]))
        assert meta["total_count"] == 0

        # Closing the round is the only thing that was missing.
        close_round(ctx["bid_round"]["id"])
        run = run_optimization(ctx["event"]["id"], scenario_label="BASE")
        assert run["status"] == "COMPLETED"
        assert read_event(ctx["event"]["id"])["status"] == "OPTIMIZING"


class TestInvitationRevokeUnwindsTheOpenRound:
    """Revoking an accepted invitation is a three-place write."""

    @staticmethod
    def _accepted_bidder_with_one_bid():
        """An OPEN round holding one SUBMITTED bid at the first rate."""
        ctx = setup_open_round_with_bidder()
        ctx["bid"] = submit_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=FIRST_RATE_PER_MILE,
        )
        return ctx

    def test_the_revoke_drops_the_invitation_out_of_the_accepted_count(self):
        """The invitation had reached `ACCEPTED`, so the counter is decremented.

        PRD §3.4: "The analyst may revoke an invitation whose `status` is `SENT` or
        `ACCEPTED`, supplying a mandatory `revoked_reason`. The invitation moves to the
        terminal `REVOKED` and drops out of `invited_carrier_count`. When the
        revocation is from `ACCEPTED`, the event's `accepted_invitation_count` is
        additionally decreased by one."
        PRD §2.12: "`BidEvent.invited_carrier_count` counts invitations whose status is
        `SENT`, `ACCEPTED` or `DECLINED`, so a revoked invitation drops out of it."

        Design: Corner/state_machines/invitation_revoke_after_acceptance_withdraws_the_carriers_open_round_bids
        """
        ctx = self._accepted_bidder_with_one_bid()
        assert ctx["invitation"]["status"] == "ACCEPTED"
        assert read_event(ctx["event"]["id"])["accepted_invitation_count"] == 1

        revoked = validate_success(
            api_client.revoke_invitation(
                ctx["invitation"]["id"],
                invitation_revoke_payload(revoked_reason=REVOKED_REASON),
                ANALYST,
            )
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_reason"] == REVOKED_REASON

        event = read_event(ctx["event"]["id"])
        assert event["accepted_invitation_count"] == 0
        assert event["invited_carrier_count"] == 0
        assert event["status"] == "ROUND_OPEN", "the revoke does not unwind the scope"
        assert read_lane(ctx["lane"]["id"])["status"] == "LOCKED"

    def test_the_revoke_withdraws_the_bid_and_recomputes_the_rounds_rollups(self):
        """`lowest_rate_per_mile` must fall back to null, not stay stale.

        PRD §3.4: "In both cases the withdrawal cascade fires: every lane bid belonging
        to that carrier whose `status` is `SUBMITTED` and whose round is still `OPEN`
        moves to `WITHDRAWN`, and each affected round's `submitted_bid_count` and
        `lowest_rate_per_mile` are recomputed."
        PRD §2.12: "`BidRound.lowest_rate_per_mile` is the minimum `rate_per_mile`
        across the round's bids whose status is `SUBMITTED`, and is null when the
        round holds none."
        PRD §2.12: "`BidRound.submitted_bid_count` counts lane bids on the round whose
        status is `SUBMITTED`, `SHORTLISTED`, `AWARDED_PRIMARY`, `AWARDED_BACKUP` or
        `NOT_AWARDED`, so withdrawal removes a bid from the count while award does not."

        Design: Corner/state_machines/invitation_revoke_after_acceptance_withdraws_the_carriers_open_round_bids
        """
        ctx = self._accepted_bidder_with_one_bid()
        before = _read_round(ctx["bid_round"]["id"])
        assert before["submitted_bid_count"] == 1
        assert float(before["lowest_rate_per_mile"]) == FIRST_RATE_PER_MILE

        validate_success(
            api_client.revoke_invitation(
                ctx["invitation"]["id"],
                invitation_revoke_payload(revoked_reason=REVOKED_REASON),
                ANALYST,
            )
        )

        assert read_lane_bid(ctx["bid"]["id"])["status"] == "WITHDRAWN"
        after = _read_round(ctx["bid_round"]["id"])
        assert after["submitted_bid_count"] == 0
        assert after["lowest_rate_per_mile"] is None, (
            "the derived rate is recomputed, not left stale at the withdrawn bid"
        )
        assert after["status"] == "OPEN"


class TestWithdrawalFreesTheUniquenessSlot:
    """The duplicate key is scoped to non-`WITHDRAWN` bids, so a re-bid is legal."""

    @staticmethod
    def _bidder_with_one_bid():
        ctx = setup_open_round_with_bidder()
        ctx["bid"] = submit_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=FIRST_RATE_PER_MILE,
        )
        return ctx

    def test_the_same_lane_cannot_be_re_bid_until_the_first_bid_is_withdrawn(self):
        """The refusal, then the withdrawal, then the identical submission at 201.

        PRD §3.5: "At most one bid that is not `WITHDRAWN` may exist for a given
        combination of round, lane and carrier; a second is rejected with
        `ERR_DUPLICATE_LANE_BID` (409), while re-bidding after a withdrawal within the
        same open round is permitted."
        PRD §2.9: "at most one non-`WITHDRAWN` lane bid may exist per combination of
        round, lane and carrier (`ERR_DUPLICATE_LANE_BID`)"
        PRD §3.5: "A carrier representative may withdraw its own bid while the bid's
        `status` is `SUBMITTED` and the round is still `OPEN`. The bid moves to the
        terminal `WITHDRAWN` and `withdrawn_at` is set to the logical clock."

        Design: Corner/state_machines/lane_bid_withdraw_frees_the_duplicate_bid_uniqueness_slot
        """
        ctx = self._bidder_with_one_bid()
        rebid_kwargs = {
            "rate_per_mile": SECOND_RATE_PER_MILE,
            "committed_volume_loads": SECOND_COMMITTED_VOLUME_LOADS,
        }

        validate_error(
            _attempt_bid(
                ctx["bid_round"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                **rebid_kwargs,
            ),
            "ERR_DUPLICATE_LANE_BID",
            409,
        )

        withdrawn = validate_success(
            api_client.withdraw_lane_bid(
                ctx["bid"]["id"], make_carrier_rep_headers(ctx["carrier"]["id"])
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_same_instant(withdrawn["withdrawn_at"], DEFAULT_CLOCK, "withdrawn_at")

        replacement = validate_success(
            _attempt_bid(
                ctx["bid_round"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                **rebid_kwargs,
            ),
            201,
        )
        assert replacement["status"] == "SUBMITTED"
        assert float(replacement["rate_per_mile"]) == SECOND_RATE_PER_MILE
        assert replacement["id"] != ctx["bid"]["id"]

    def test_the_rounds_rollups_follow_the_live_bid_not_the_withdrawn_one(self):
        """Zero and null between the two bids, then the new rate, never the old.

        PRD §3.5: "The round's `submitted_bid_count` is recomputed, its
        `lowest_rate_per_mile` is recomputed over the bids that remain `SUBMITTED` —
        becoming null if none remain — and the surviving bids on that lane are
        renumbered so `rank_in_lane` again runs contiguously from 1 with no gap where
        the withdrawn bid sat."
        PRD §3.5: "A bid's `status` travels through `SUBMITTED`, `WITHDRAWN`,
        `SHORTLISTED`, `AWARDED_PRIMARY`, `AWARDED_BACKUP` and `NOT_AWARDED`."

        Design: Corner/state_machines/lane_bid_withdraw_frees_the_duplicate_bid_uniqueness_slot
        """
        ctx = self._bidder_with_one_bid()
        validate_success(
            api_client.withdraw_lane_bid(
                ctx["bid"]["id"], make_carrier_rep_headers(ctx["carrier"]["id"])
            )
        )

        emptied = _read_round(ctx["bid_round"]["id"])
        assert emptied["submitted_bid_count"] == 0
        assert emptied["lowest_rate_per_mile"] is None

        replacement = submit_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=SECOND_RATE_PER_MILE,
            committed_volume_loads=SECOND_COMMITTED_VOLUME_LOADS,
        )
        refilled = _read_round(ctx["bid_round"]["id"])
        assert refilled["submitted_bid_count"] == 1
        assert float(refilled["lowest_rate_per_mile"]) == SECOND_RATE_PER_MILE
        assert replacement["rank_in_lane"] == 1

        # Withdrawal is not deletion: the original row is still readable.
        original = read_lane_bid(ctx["bid"]["id"])
        assert original["status"] == "WITHDRAWN"
        assert float(original["rate_per_mile"]) == FIRST_RATE_PER_MILE
