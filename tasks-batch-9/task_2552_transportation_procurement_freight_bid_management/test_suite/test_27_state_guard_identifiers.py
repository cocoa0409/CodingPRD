"""One workflow, stopped one step short at each gate, answering with eight ids.

The state-precondition rung is a table of pair-specific identifiers rather than a
single generic conflict, and each identifier names the *missing precondition*
rather than the attempted action. So the same workflow paused just before each
gate must produce a different id at every pause, none of the refusals may write
anything, and every call must succeed the moment its own gate is satisfied.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CLOCK_GO_LIVE,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    add_lane,
    api_client,
    bid_round_payload,
    close_round,
    create_bid_event,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    load_rate_record,
    make_carrier_rep_headers,
    mini_bid_denial_payload,
    mini_bid_proposal_payload,
    mini_bid_revert_payload,
    open_round,
    optimization_run_payload,
    read_contract,
    read_event,
    read_mini_bid,
    read_rate_record,
    run_optimization,
    set_clock,
    setup_open_mini_bid,
    setup_staged_rate_record,
    sign_as_carrier,
    sign_as_shipper,
    tender_event_payload,
    validate_error,
    validate_success,
)

EARLY_LOAD_REFERENCE = "LD-EARLY"
STAGED_RECORD_COUNT = 1


def _error_id(response):
    """The `error_id` of a refusal, for cross-comparing two refusals."""
    return response.json()["data"]["error_id"]


def _lock_lanes(event_id):
    return api_client.lock_lanes(event_id, ANALYST)


def _open_round(event_id):
    return api_client.create_bid_round(event_id, bid_round_payload(), ANALYST)


def _create_run(event_id, version):
    return api_client.create_optimization_run(
        optimization_run_payload(event_id, version, scenario_label="TOO_EARLY"), ANALYST
    )


def _go_live(rate_record_id):
    return api_client.go_live_rate_record(rate_record_id, CONTRACT_ADMIN)


def _append_tender(rate_record_id, load_reference):
    return api_client.create_tender_event(
        rate_record_id, tender_event_payload(load_reference), ANALYST
    )


def _revert(mini_bid_id):
    return api_client.revert_mini_bid(
        mini_bid_id, mini_bid_revert_payload(), CONTRACT_ADMIN
    )


def _deny(mini_bid_id):
    return api_client.deny_mini_bid(
        mini_bid_id, mini_bid_denial_payload(), CATEGORY_MANAGER
    )


def _propose(mini_bid_id, carrier_id):
    return api_client.propose_mini_bid_rate(
        mini_bid_id,
        mini_bid_proposal_payload(carrier_id, proposed_rate_per_mile=2.1000),
        make_carrier_rep_headers(carrier_id),
    )


def _validate_lane(lane_id):
    return get_success_data(api_client.validate_lane(lane_id, ANALYST))


class TestTheScopeGatesNameTheirOwnMissingPrecondition:
    """Three pauses on the way from a draft lane to a scenario, three ids."""

    def test_lock_then_invite_then_optimise_each_refuse_differently(self):
        """The same event, one step short at each gate, and nothing written.

        PRD §2.9: "a lane still in `DRAFT` when the event's lanes are locked raises
        `ERR_LANE_NOT_VALIDATED`; inviting carriers or opening the first round before the
        lane scope is locked raises `ERR_LANES_NOT_LOCKED`; submitting or withdrawing a
        bid on a round that is not `OPEN` raises `ERR_ROUND_NOT_OPEN`; creating an
        optimization run while a round of the event is still `OPEN` raises
        `ERR_ROUND_STILL_OPEN`"
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and no
        partial write is retained."

        Design: Corner/errors/not_ready_state_guards_each_answer_with_their_own_id
        """
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event()
        lane = add_lane(event["id"])
        assert lane["status"] == "DRAFT"

        first = _lock_lanes(event["id"])
        validate_error(first, "ERR_LANE_NOT_VALIDATED", 409)

        assert _validate_lane(lane["id"])["status"] == "VALIDATED"
        second = _open_round(event["id"])
        validate_error(second, "ERR_LANES_NOT_LOCKED", 409)

        locked = validate_success(_lock_lanes(event["id"]))
        assert locked["status"] == "LANES_LOCKED"
        carrier = create_qualified_carrier()
        invite_and_accept(event["id"], carrier["id"])
        bid_round = open_round(event["id"])
        opened = read_event(event["id"])
        third = _create_run(opened["id"], opened["version"])
        validate_error(third, "ERR_ROUND_STILL_OPEN", 409)

        assert len({_error_id(first), _error_id(second), _error_id(third)}) == 3, (
            "three different missing preconditions must not share one identifier"
        )
        paused = read_event(event["id"])
        assert paused["lane_count"] == 1
        assert paused["current_round_no"] == 1
        assert paused["status"] == "ROUND_OPEN"

        close_round(bid_round["id"])
        run = run_optimization(event["id"])
        assert run["status"] == "FAILED", "no bid was ever submitted into the round"
        assert read_event(event["id"])["status"] == "OPTIMIZING"


class TestTheRateGatesNameTheirOwnMissingPrecondition:
    """Staged, loaded and live are three different answers on one record."""

    def test_go_live_and_tendering_each_report_the_precondition_they_lack(self):
        """`NOT_LOADED`, then `NOT_FULLY_SIGNED`, then `NOT_LIVE`, then success.

        PRD §3.8: "**Going live.** A contract administrator takes a `LOADED` record
        live; against any other status the attempt is rejected with
        `ERR_RATE_RECORD_NOT_LOADED` (409). Three further conditions apply. The
        contract's `signature_status` must be `FULLY_SIGNED`, otherwise
        `ERR_CONTRACT_NOT_FULLY_SIGNED` (409) — this is the single coupling point between
        the two contract dimensions."
        PRD §2.9: "appending a tender to, or applying a mini-bid against, a record that
        is neither `LIVE` nor `AT_RISK` raises `ERR_RATE_RECORD_NOT_LIVE`"
        PRD §3.8: "On success the record moves from `STAGED` to `LOADED`, `loaded_at` is
        set to the logical clock, and on the contract's first loaded record the
        contract's `rate_load_status` moves from `STAGED` to `LOADED`."

        Design: Corner/errors/not_ready_state_guards_each_answer_with_their_own_id
        """
        ctx = setup_staged_rate_record()
        record_id = ctx["rate_record"]["id"]
        assert ctx["rate_record"]["status"] == "STAGED"
        assert ctx["contract"]["signature_status"] == "PENDING_BOTH"

        first = _go_live(record_id)
        validate_error(first, "ERR_RATE_RECORD_NOT_LOADED", 409)

        half_signed = sign_as_carrier(ctx["contract"]["id"], ctx["carrier"]["id"])
        assert half_signed["signature_status"] == "PENDING_SHIPPER"
        loaded = load_rate_record(record_id)
        assert loaded["status"] == "LOADED"

        second = _go_live(record_id)
        validate_error(second, "ERR_CONTRACT_NOT_FULLY_SIGNED", 409)
        third = _append_tender(record_id, EARLY_LOAD_REFERENCE)
        validate_error(third, "ERR_RATE_RECORD_NOT_LIVE", 409)

        assert len({_error_id(first), _error_id(second), _error_id(third)}) == 3
        untouched = read_rate_record(record_id)
        assert untouched["status"] == "LOADED"
        assert untouched["tender_count"] == 0
        assert untouched["live_at"] is None
        assert read_contract(ctx["contract"]["id"])["rate_record_count"] == (
            STAGED_RECORD_COUNT
        )

        assert sign_as_shipper(ctx["contract"]["id"])["signature_status"] == (
            "FULLY_SIGNED"
        )
        set_clock(CLOCK_GO_LIVE)
        assert validate_success(_go_live(record_id))["status"] == "LIVE"
        validate_success(_append_tender(record_id, EARLY_LOAD_REFERENCE), 201)
        assert read_rate_record(record_id)["tender_count"] == 1


class TestTheMiniBidGatesSeparateNotOpenFromNotApplied:
    """A window that was never applied and one that can no longer be proposed on."""

    def test_reverting_an_open_window_and_proposing_on_a_denied_one_differ(self):
        """Two 409s on one mini-bid, and neither of them touches a rate.

        PRD §3.10: "**Reverting an applied mini-bid.** A contract administrator may
        unwind an applied adjustment, supplying a mandatory `revert_reason`. The
        mini-bid's `status` must be `APPLIED`, otherwise `ERR_MINI_BID_NOT_APPLIED`
        (409)"
        PRD §3.10: "**Proposing a rate.** A carrier representative proposes a
        replacement rate on a mini-bid whose `status` is `REQUESTED`; against any other
        status the attempt is rejected with `ERR_MINI_BID_NOT_OPEN` (409)."
        PRD §2.9: "proposing on a mini-bid that is not `REQUESTED`, or applying or
        denying one that is not `OPEN`, raises `ERR_MINI_BID_NOT_OPEN`; reverting a
        mini-bid that is not `APPLIED` raises `ERR_MINI_BID_NOT_APPLIED`"

        Design: Corner/errors/not_ready_state_guards_each_answer_with_their_own_id
        """
        ctx = setup_open_mini_bid()
        mini_bid_id = ctx["mini_bid"]["id"]
        assert ctx["mini_bid"]["status"] == "OPEN"
        assert ctx["mini_bid"]["applied_rate_record_id"] is None
        value_before = float(ctx["contract"]["total_committed_value_usd"])

        first = _revert(mini_bid_id)
        validate_error(first, "ERR_MINI_BID_NOT_APPLIED", 409)
        assert read_mini_bid(mini_bid_id)["status"] == "OPEN"

        denied = validate_success(_deny(mini_bid_id))
        assert denied["status"] == "DENIED"

        second = _propose(mini_bid_id, ctx["carrier"]["id"])
        validate_error(second, "ERR_MINI_BID_NOT_OPEN", 409)

        assert _error_id(first) != _error_id(second), (
            "a never-applied window and a closed window are different refusals"
        )
        assert read_mini_bid(mini_bid_id)["status"] == "DENIED"
        assert read_rate_record(ctx["rate_record"]["id"])["status"] == "LIVE"
        assert float(
            read_contract(ctx["contract"]["id"])["total_committed_value_usd"]
        ) == value_before
