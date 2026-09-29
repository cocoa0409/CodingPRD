"""Operations that read a state on a different entity than the one they write.

The invitation writes an invitation but reads the carrier's qualification standing;
the go-live writes a rate record but reads the contract's signature dimension. In
both cases the same request is issued repeatedly, byte-identical, and only the
other entity's state changes between the refusal and the success.
"""

from test_helpers import (
    ANALYST,
    api_client,
    assert_same_instant,
    CLOCK_GO_LIVE,
    COMPLIANCE,
    CONTRACT_ADMIN,
    create_carrier,
    create_event_with_locked_lanes,
    decision_payload,
    get_success_data,
    invitation_payload,
    load_rate_record,
    open_qualification_review,
    read_allocation,
    read_carrier,
    read_contract,
    read_event,
    read_rate_record,
    screen_review,
    set_clock,
    setup_staged_rate_record,
    sign_as_carrier,
    sign_as_shipper,
    validate_error,
)

# The provisional composite a freshly approved carrier carries, and the figure the
# invitation freezes as its qualification snapshot.
PROVISIONAL_COMPOSITE = 90.60


def _attempt_invitation(event_id, carrier_id, **overrides):
    """Issues an invitation without asserting success."""
    return api_client.create_invitation(
        event_id, invitation_payload(carrier_id, **overrides), ANALYST
    )


def _attempt_go_live(rate_record_id):
    """Attempts the cutover without asserting success."""
    return api_client.go_live_rate_record(rate_record_id, CONTRACT_ADMIN)


def _invitations(**params):
    body = get_success_data(api_client.list_invitations(ANALYST, params or None))
    return body["data"] if isinstance(body, dict) and "data" in body else body


class TestInvitationGatedOnCarrierStanding:
    """The invitation endpoint writes an invitation but reads the carrier."""

    def test_a_registered_carrier_cannot_be_invited(self):
        """No review at all means no standing, so the invitation is refused.

        PRD §3.4: "The carrier must be fit in the sense of §2.10 — not suspended or
        disqualified, insurance not expired, and standing at `QUALIFIED`,
        `CONDITIONALLY_QUALIFIED` or `WATCHLIST`."
        PRD §2.10: "A carrier that has not reached `QUALIFIED`,
        `CONDITIONALLY_QUALIFIED` or `WATCHLIST` standing where the operation requires
        standing is rejected with `ERR_CARRIER_NOT_QUALIFIED`."
        PRD §3.1: "A newly registered carrier is created with `status` set to
        `REGISTERED`, `status_reason` null, `capability_score` `0.00`"

        Design: Difficulty/cross_entity_state_dependency/invitation_creation_gated_on_carrier_qualification_state
        """
        set_clock()
        carrier = create_carrier()
        assert carrier["status"] == "REGISTERED"
        event, _lanes = create_event_with_locked_lanes()
        assert event["status"] == "LANES_LOCKED"

        response = _attempt_invitation(event["id"], carrier["id"], nda_required=True)
        validate_error(response, "ERR_CARRIER_NOT_QUALIFIED", 409)

        assert _invitations(bid_event_id=event["id"]) == []
        unchanged = read_event(event["id"])
        assert unchanged["status"] == "LANES_LOCKED"
        assert unchanged["invited_carrier_count"] == 0

    def test_a_carrier_with_a_review_still_in_flight_has_no_standing(self):
        """SCREENING is not standing: the same call is still refused.

        PRD §2.10: "A carrier's `status` is the system's single expression of whether
        it may be bound to new commercial obligations, and it is re-checked at the
        moment of every such write rather than trusted from an earlier check."
        PRD §2.10: "A carrier that has not reached `QUALIFIED`,
        `CONDITIONALLY_QUALIFIED` or `WATCHLIST` standing where the operation requires
        standing is rejected with `ERR_CARRIER_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/invitation_creation_gated_on_carrier_qualification_state
        """
        set_clock()
        carrier = create_carrier()
        review = open_qualification_review(carrier["id"])
        screen_review(review["id"])
        screening = read_carrier(carrier["id"])
        assert screening["status"] == "SCREENING", (
            "a screened but undecided review leaves the carrier in SCREENING"
        )
        event, _lanes = create_event_with_locked_lanes()

        response = _attempt_invitation(event["id"], carrier["id"], nda_required=True)
        validate_error(response, "ERR_CARRIER_NOT_QUALIFIED", 409)
        assert _invitations(bid_event_id=event["id"]) == []

    def test_the_identical_invitation_succeeds_once_the_review_is_approved(self):
        """Only the carrier's status changed between the refusal and the success.

        PRD §3.1: "The carrier moves from `SCREENING` to `QUALIFIED`, its
        `capability_score` is set from the review's `capability_score`, its
        `qualified_at` is set to the logical clock, and its `composite_score` and
        `composite_score_variant` are recomputed."
        PRD §3.4: "The invitation is created with `status` `SENT`, `nda_signed`
        `false`, `snapshot_stale` `false`, and `responded_at`, `decline_reason` and
        `revoked_reason` null."
        PRD §3.4: "`qualification_snapshot_score` records the carrier's
        `composite_score` as it stood when the invitation went out"
        PRD §3.4: "The event's `invited_carrier_count` is recomputed, and on the first
        invitation the event moves from `LANES_LOCKED` to `INVITING`."

        Design: Difficulty/cross_entity_state_dependency/invitation_creation_gated_on_carrier_qualification_state
        """
        set_clock()
        carrier = create_carrier()
        review = open_qualification_review(carrier["id"])
        screen_review(review["id"])
        event, _lanes = create_event_with_locked_lanes()
        validate_error(
            _attempt_invitation(event["id"], carrier["id"], nda_required=True),
            "ERR_CARRIER_NOT_QUALIFIED",
            409,
        )

        get_success_data(
            api_client.decide_qualification_review(
                review["id"], decision_payload(outcome="APPROVE"), COMPLIANCE
            )
        )
        qualified = read_carrier(carrier["id"])
        assert qualified["status"] == "QUALIFIED"
        assert float(qualified["composite_score"]) == PROVISIONAL_COMPOSITE

        invitation = get_success_data(
            _attempt_invitation(event["id"], carrier["id"], nda_required=True), 201
        )
        assert invitation["status"] == "SENT"
        assert invitation["nda_required"] is True
        assert invitation["nda_signed"] is False
        assert invitation["snapshot_stale"] is False
        assert invitation["responded_at"] is None
        assert float(invitation["qualification_snapshot_score"]) == PROVISIONAL_COMPOSITE

        after = read_event(event["id"])
        assert after["status"] == "INVITING"
        assert after["invited_carrier_count"] == 1
        assert after["accepted_invitation_count"] == 0


class TestGoLiveGatedOnContractSignatures:
    """The cutover writes a rate record but reads the contract's signatures."""

    @staticmethod
    def _loaded_at_window_start():
        """A LOADED rate record with the clock on the inclusive start of its window."""
        ctx = setup_staged_rate_record()
        load_rate_record(ctx["rate_record"]["id"])
        set_clock(CLOCK_GO_LIVE)
        ctx["rate_record"] = read_rate_record(ctx["rate_record"]["id"])
        assert ctx["rate_record"]["status"] == "LOADED"
        assert_same_instant(
            ctx["rate_record"]["effective_from"], CLOCK_GO_LIVE, "effective_from"
        )
        return ctx

    def test_go_live_is_refused_while_both_signatures_are_outstanding(self):
        """The record's own preconditions hold; the contract's do not.

        PRD §3.8: "The contract's `signature_status` must be `FULLY_SIGNED`, otherwise
        `ERR_CONTRACT_NOT_FULLY_SIGNED` (409) — this is the single coupling point
        between the two contract dimensions."
        PRD §3.8: "The current logical clock instant must fall inside the record's own
        half-open effective interval, at or after `effective_from` and strictly before
        `effective_to`, otherwise `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW` (409)"
        PRD §2.9: "taking a rate record live while the contract's `signature_status` is
        not `FULLY_SIGNED` raises `ERR_CONTRACT_NOT_FULLY_SIGNED`"

        Design: Difficulty/cross_entity_state_dependency/rate_go_live_gated_on_contract_signature_state
        """
        ctx = self._loaded_at_window_start()
        assert read_contract(ctx["contract"]["id"])["signature_status"] == "PENDING_BOTH"

        response = _attempt_go_live(ctx["rate_record"]["id"])
        validate_error(response, "ERR_CONTRACT_NOT_FULLY_SIGNED", 409)

        unchanged = read_rate_record(ctx["rate_record"]["id"])
        assert unchanged["status"] == "LOADED"
        assert unchanged["live_at"] is None

    def test_one_signature_is_not_enough_for_the_cutover(self):
        """PENDING_SHIPPER is refused exactly as PENDING_BOTH was.

        PRD §3.8: "A carrier representative signs on behalf of its own carrier: from
        `PENDING_BOTH` the `signature_status` becomes `PENDING_SHIPPER`, and from
        `PENDING_CARRIER` it becomes `FULLY_SIGNED` and the contract's `status` moves
        from `DRAFT` to `EXECUTED`."
        PRD §3.8: "The contract's `signature_status` must be `FULLY_SIGNED`, otherwise
        `ERR_CONTRACT_NOT_FULLY_SIGNED` (409) — this is the single coupling point
        between the two contract dimensions."

        Design: Difficulty/cross_entity_state_dependency/rate_go_live_gated_on_contract_signature_state
        """
        ctx = self._loaded_at_window_start()
        signed_once = sign_as_carrier(ctx["contract"]["id"], ctx["carrier"]["id"])
        assert signed_once["signature_status"] == "PENDING_SHIPPER"

        validate_error(
            _attempt_go_live(ctx["rate_record"]["id"]),
            "ERR_CONTRACT_NOT_FULLY_SIGNED",
            409,
        )
        still_loaded = read_rate_record(ctx["rate_record"]["id"])
        assert still_loaded["status"] == "LOADED"
        assert still_loaded["live_at"] is None

    def test_the_identical_cutover_succeeds_once_the_contract_is_fully_signed(self):
        """Nothing about the rate record changed - only the contract did.

        PRD §3.8: "The record moves from `LOADED` to `LIVE` and `live_at` is set to the
        logical clock."
        PRD §3.8: "The award allocation the record implements moves from `EXECUTED` to
        `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed."
        PRD §3.8: "The contract's `rate_load_status` moves from `LOADED` to `LIVE`."
        PRD §3.8: "On the **first** rate record of the whole event to go live, the event
        moves from `AWARDED` to the terminal `LIVE` and its `coverage_pct` is recomputed
        over the allocations now `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/rate_go_live_gated_on_contract_signature_state
        """
        ctx = self._loaded_at_window_start()
        validate_error(
            _attempt_go_live(ctx["rate_record"]["id"]),
            "ERR_CONTRACT_NOT_FULLY_SIGNED",
            409,
        )
        sign_as_carrier(ctx["contract"]["id"], ctx["carrier"]["id"])
        executed = sign_as_shipper(ctx["contract"]["id"])
        assert executed["signature_status"] == "FULLY_SIGNED"
        assert executed["status"] == "EXECUTED"

        record = get_success_data(_attempt_go_live(ctx["rate_record"]["id"]))
        assert record["status"] == "LIVE"
        assert_same_instant(record["live_at"], CLOCK_GO_LIVE, "live_at")
        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LIVE"
        assert read_event(ctx["event"]["id"])["status"] == "LIVE"
