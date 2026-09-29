"""Replay-safety and ordering along the award-to-go-live spine.

Every write in this stretch either mints rows or moves volume, so each one is
driven twice: once to land its effect and once to prove the replay is refused on
state rather than silently repeated. The file also pins the shape of a contract at
the instant the award cascade mints it, and the two orderings that cannot be
skipped — load before go-live, go-live before the first tender.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CATEGORY_MANAGER_USER_ID,
    CLOCK_GO_LIVE,
    CONTRACT_ADMIN,
    CONTRACT_EFFECTIVE_FROM,
    CONTRACT_EFFECTIVE_TO,
    DEFAULT_CLOCK,
    api_client,
    approve_allocation,
    assert_lane_volume_conservation,
    assert_same_instant,
    fully_sign_contract,
    get_success_data,
    go_live,
    load_rate_record,
    read_allocation,
    read_contract,
    read_event,
    read_lane,
    read_rate_record,
    set_clock,
    setup_awarded_event,
    setup_published_routing_guide,
    setup_staged_rate_record,
    tender_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The single lane under test: all 550 planned loads granted to the one bidder.
LANE_PLAN_LOADS = 550
FULL_COVERAGE_PCT = 100.00

FIRST_LOAD_REFERENCE = "LD-1001"


def _publish_guide(run_id):
    """Attempts a routing-guide publication without asserting the outcome."""
    return api_client.publish_routing_guide(run_id, ANALYST)


def _approve(allocation_id):
    """Attempts an allocation approval without asserting the outcome."""
    return api_client.approve_award_allocation(allocation_id, CATEGORY_MANAGER)


def _append_tender(rate_record_id, load_reference, **overrides):
    """Attempts a tender append without asserting the outcome."""
    return api_client.create_tender_event(
        rate_record_id, tender_event_payload(load_reference, **overrides), ANALYST
    )


def _list_allocations(**params):
    return api_client.list_award_allocations(ANALYST, params or None)


def _list_contracts(**params):
    return api_client.list_contracts(CONTRACT_ADMIN, params or None)


def _list_tenders(rate_record_id):
    return api_client.list_tender_events(rate_record_id, ANALYST)


def _read_run(run_id):
    return get_success_data(api_client.get_optimization_run(run_id, ANALYST))


class TestRoutingGuidePublicationIsNotReplayable:
    """Publication mints the proposed allocations, so it may happen once."""

    def test_a_second_publish_is_refused_and_mints_no_duplicate_allocation(self):
        """The guard is the event's own state, which the first publish moved.

        PRD §3.6: "The analyst publishes a run whose `status` is `COMPLETED`, while the
        event's `status` is `OPTIMIZING`; publishing against an event in any other state
        is rejected with `ERR_EVENT_NOT_OPTIMIZING` (409)."
        PRD §3.6: "The run moves from `COMPLETED` to `PUBLISHED`, `published_at` is set
        to the logical clock, the event moves from `OPTIMIZING` to `AWARDING`, and the
        event's `version` increases by one."
        PRD §3.6: "An `AwardAllocation` row is created for each pick with `status`
        `PROPOSED`, carrying its `routing_position`, `allocated_volume_loads`,
        `allocated_pct` and `allocated_cost_usd`, its `promoted_from_position` null, and
        `approved_by_user_id`, `approved_at` and `rejection_reason` all null."
        PRD §2.9: "publishing a routing guide while the event is not `OPTIMIZING` raises
        `ERR_EVENT_NOT_OPTIMIZING`"

        Design: Corner/state_machines/second_routing_guide_publish_returns_event_not_optimizing
        """
        ctx = setup_published_routing_guide()
        run = ctx["run"]
        assert run["status"] == "PUBLISHED"
        assert_same_instant(run["published_at"], DEFAULT_CLOCK, "published_at")
        assert float(run["coverage_pct"]) == FULL_COVERAGE_PCT
        assert ctx["event"]["status"] == "AWARDING"
        assert ctx["allocation"]["status"] == "PROPOSED"
        assert ctx["allocation"]["promoted_from_position"] is None
        assert ctx["allocation"]["approved_by_user_id"] is None
        assert ctx["allocation"]["approved_at"] is None
        assert ctx["allocation"]["rejection_reason"] is None

        validate_error(
            _publish_guide(run["id"]), "ERR_EVENT_NOT_OPTIMIZING", 409
        )

        _rows, meta = validate_paginated(
            _list_allocations(bid_event_id=ctx["event"]["id"])
        )
        assert meta["total_count"] == 1, "the replay may not mint a second PROPOSED row"
        replayed_run = _read_run(run["id"])
        assert_same_instant(replayed_run["published_at"], DEFAULT_CLOCK, "published_at")
        assert replayed_run["status"] == "PUBLISHED"
        assert read_event(ctx["event"]["id"])["status"] == "AWARDING"


class TestAllocationApprovalTakesExactlyOneDebit:
    """Approval is where volume is reserved, so a replay would break conservation."""

    def test_the_first_approval_records_the_operator_and_debits_the_lane_once(self):
        """One debit of 550 loads, and the identity the signature rule will read.

        PRD §3.7: "The allocation moves from `PROPOSED` to `APPROVED`,
        `approved_by_user_id` is set to the acting `X-User-ID` — the value the
        segregation-of-duties rule of §2.11 will later compare against — and
        `approved_at` is set to the logical clock."
        PRD §3.7: "The lane's `unallocated_volume_loads` is reduced by the allocation's
        `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as
        `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`,
        divided by `annual_volume_loads`, and rounded to 2 decimal places."
        PRD §2.12: "A `PROPOSED` allocation reserves nothing at all: the debit against
        `unallocated_volume_loads` is taken when the allocation is approved and credited
        back exactly when it is rejected or superseded."

        Design: Corner/state_machines/allocation_approve_replayed_returns_allocation_not_proposed_without_double_debit
        """
        ctx = setup_published_routing_guide()
        assert read_lane(ctx["lane"]["id"])["unallocated_volume_loads"] == (
            LANE_PLAN_LOADS
        ), "a PROPOSED allocation holds no volume"

        approved = validate_success(_approve(ctx["allocation"]["id"]))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CATEGORY_MANAGER_USER_ID
        assert_same_instant(approved["approved_at"], DEFAULT_CLOCK, "approved_at")
        assert approved["allocated_volume_loads"] == LANE_PLAN_LOADS
        assert float(approved["allocated_pct"]) == FULL_COVERAGE_PCT

        lane = read_lane(ctx["lane"]["id"])
        assert lane["unallocated_volume_loads"] == 0
        assert float(lane["awarded_coverage_pct"]) == FULL_COVERAGE_PCT
        assert float(read_event(ctx["event"]["id"])["coverage_pct"]) == (
            FULL_COVERAGE_PCT
        )

    def test_the_replayed_approval_is_refused_without_a_second_debit(self):
        """A second debit would drive the lane negative while every field looks sane.

        PRD §3.7: "The category manager approves an allocation whose `status` is
        `PROPOSED`; an attempt against any other status is rejected with
        `ERR_ALLOCATION_NOT_PROPOSED` (409)."
        PRD §2.9: "approving an allocation that is not `PROPOSED` raises
        `ERR_ALLOCATION_NOT_PROPOSED`"
        PRD §2.12: "For every lane, the sum of `unallocated_volume_loads` and the
        `allocated_volume_loads` of that lane's award allocations whose status is
        `APPROVED`, `EXECUTED`, `ACTIVE` or `SUSPENDED_ROUTING` always equals the lane's
        `annual_volume_loads`."

        Design: Corner/state_machines/allocation_approve_replayed_returns_allocation_not_proposed_without_double_debit
        """
        ctx = setup_published_routing_guide()
        approve_allocation(ctx["allocation"]["id"])

        validate_error(
            _approve(ctx["allocation"]["id"]), "ERR_ALLOCATION_NOT_PROPOSED", 409
        )

        lane = read_lane(ctx["lane"]["id"])
        assert lane["unallocated_volume_loads"] == 0, (
            "the refused replay must not debit the lane a second time"
        )
        assert_lane_volume_conservation(lane, [read_allocation(ctx["allocation"]["id"])])
        assert float(read_event(ctx["event"]["id"])["coverage_pct"]) == (
            FULL_COVERAGE_PCT
        )
        replayed = read_allocation(ctx["allocation"]["id"])
        assert replayed["status"] == "APPROVED"
        assert_same_instant(replayed["approved_at"], DEFAULT_CLOCK, "approved_at")


class TestFreshlyMintedContractSitsAtEveryOrigin:
    """Contracts are never posted; the award cascade is the only thing that mints them."""

    def test_the_award_cascade_mints_one_contract_at_all_three_origins(self):
        """Three independent dimensions, each at its own starting value.

        PRD §3.7: "One contract is created for each distinct pairing of `bid_event_id`
        and `carrier_id` appearing among those executed allocations — one contract per
        carrier per event, however many lanes that carrier won."
        PRD §3.7: "Each contract is created with `status` `DRAFT`, `signature_status`
        `PENDING_BOTH`, `rate_load_status` `NOT_STAGED`, `amendment_count` `0`,
        `rate_record_count` `0`, its `effective_from` and `effective_to` copied from the
        event's `contract_effective_from` and `contract_effective_to`, its four signature
        fields — `carrier_signed_by_user_id`, `carrier_signed_at`,
        `shipper_signed_by_user_id`, `shipper_signed_at` — null, and its committed value
        evaluated by the rule in §3.8."
        PRD §3.8: "Only rate records whose `status` is `STAGED`, `LOADED`, `LIVE` or
        `AT_RISK` are in the basis."
        PRD §2.12: "`Contract.rate_record_count` counts the contract's rate records whose
        status is `STAGED`, `LOADED`, `LIVE` or `AT_RISK`."

        Design: Corner/state_machines/contract_minted_by_the_award_cascade_starts_draft_pending_both_not_staged
        """
        ctx = setup_awarded_event()
        rows, meta = validate_paginated(_list_contracts(bid_event_id=ctx["event"]["id"]))
        assert meta["total_count"] == 1
        contract = rows[0]
        assert contract["bid_event_id"] == ctx["event"]["id"]
        assert contract["carrier_id"] == ctx["carrier"]["id"]

        assert contract["status"] == "DRAFT"
        assert contract["signature_status"] == "PENDING_BOTH"
        assert contract["rate_load_status"] == "NOT_STAGED"
        assert contract["amendment_count"] == 0
        assert contract["rate_record_count"] == 0
        assert contract["version"] == 1

        assert_same_instant(
            contract["effective_from"], CONTRACT_EFFECTIVE_FROM, "effective_from"
        )
        assert_same_instant(
            contract["effective_to"], CONTRACT_EFFECTIVE_TO, "effective_to"
        )
        for field in (
            "carrier_signed_by_user_id",
            "carrier_signed_at",
            "shipper_signed_by_user_id",
            "shipper_signed_at",
        ):
            assert contract[field] is None, f"{field} must be null before any signature"

        # The committed-value rule of §3.8 runs over an empty basis: no rate record
        # has been staged, so every figure it derives is zero rather than absent.
        assert float(contract["base_committed_value_usd"]) == 0.00
        assert float(contract["volume_discount_pct"]) == 0.000
        assert float(contract["volume_discount_usd"]) == 0.00
        assert float(contract["accessorial_allowance_pct"]) == 0.000
        assert float(contract["accessorial_allowance_usd"]) == 0.00
        assert float(contract["total_committed_value_usd"]) == 0.00


class TestRateLoadIsNotReplayable:
    """The load is the write that advances the contract's rate-load dimension."""

    def test_a_second_load_is_refused_and_does_not_re_stamp_loaded_at(self):
        """A replay would look like a no-op yet re-stamp a timestamp downstream reads.

        PRD §3.8: "A contract administrator loads a rate record whose `status` is
        `STAGED`; against any other status the attempt is rejected with
        `ERR_RATE_RECORD_NOT_LOADED` (409)."
        PRD §3.8: "On success the record moves from `STAGED` to `LOADED`, `loaded_at` is
        set to the logical clock, and on the contract's first loaded record the
        contract's `rate_load_status` moves from `STAGED` to `LOADED`."
        PRD §2.5: "Every instant the system writes or compares is read from a
        server-side **logical clock**, never from the host wall clock. That covers
        `created_at` and `updated_at`, every field whose name ends in `_at`"

        Design: Corner/state_machines/rate_record_load_replayed_returns_rate_record_not_loaded
        """
        ctx = setup_staged_rate_record()
        assert ctx["rate_record"]["status"] == "STAGED"
        assert ctx["contract"]["rate_load_status"] == "STAGED"

        loaded = load_rate_record(ctx["rate_record"]["id"])
        assert loaded["status"] == "LOADED"
        assert_same_instant(loaded["loaded_at"], DEFAULT_CLOCK, "loaded_at")
        assert loaded["live_at"] is None

        validate_error(
            api_client.load_rate_record(ctx["rate_record"]["id"], CONTRACT_ADMIN),
            "ERR_RATE_RECORD_NOT_LOADED",
            409,
        )

        replayed = read_rate_record(ctx["rate_record"]["id"])
        assert replayed["status"] == "LOADED"
        assert_same_instant(replayed["loaded_at"], DEFAULT_CLOCK, "loaded_at")
        assert replayed["live_at"] is None
        contract = read_contract(ctx["contract"]["id"])
        assert contract["rate_load_status"] == "LOADED", (
            "the refused replay may not push the dimension on to LIVE"
        )
        assert contract["rate_record_count"] == 1


class TestGoLiveCannotSkipTheLoadStep:
    """Of go-live's four preconditions, only the record's own state is left failing."""

    def test_go_live_on_a_staged_record_reports_the_load_and_runs_no_cascade(self):
        """Signed contract, clock inside the window, so the state check is the one left.

        PRD §3.8: "A contract administrator takes a `LOADED` record live; against any
        other status the attempt is rejected with `ERR_RATE_RECORD_NOT_LOADED` (409)."
        PRD §3.8: "The contract's `signature_status` must be `FULLY_SIGNED`, otherwise
        `ERR_CONTRACT_NOT_FULLY_SIGNED` (409) — this is the single coupling point between
        the two contract dimensions."
        PRD §3.8: "The current logical clock instant must fall inside the record's own
        half-open effective interval, at or after `effective_from` and strictly before
        `effective_to`, otherwise `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW` (409)"
        PRD §2.9: "no later check is evaluated and no partial write is retained"

        Design: Corner/state_machines/go_live_before_the_record_is_loaded_returns_rate_record_not_loaded
        """
        ctx = setup_staged_rate_record()
        signed = fully_sign_contract(ctx["contract"]["id"], ctx["carrier"]["id"])
        assert signed["signature_status"] == "FULLY_SIGNED"
        # CLOCK_GO_LIVE is the record's own effective_from, so it is inside the
        # half-open interval and the window check cannot be the failing one.
        set_clock(CLOCK_GO_LIVE)

        response = api_client.go_live_rate_record(
            ctx["rate_record"]["id"], CONTRACT_ADMIN
        )
        validate_error(response, "ERR_RATE_RECORD_NOT_LOADED", 409)
        reported = response.json()["data"]["error_id"]
        assert reported != "ERR_CONTRACT_NOT_FULLY_SIGNED"
        assert reported != "ERR_RATE_NOT_IN_EFFECTIVE_WINDOW"

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "STAGED"
        assert record["loaded_at"] is None
        assert record["live_at"] is None
        assert read_allocation(ctx["allocation"]["id"])["status"] == "EXECUTED", (
            "none of the four-link cutover cascade may have run"
        )
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "STAGED"
        assert read_event(ctx["event"]["id"])["status"] == "AWARDED"

    def test_loading_first_lets_the_same_go_live_complete_the_cutover(self):
        """The refusal was purely about ordering, and the cascade proves it.

        PRD §3.8: "The record moves from `LOADED` to `LIVE` and `live_at` is set to the
        logical clock."
        PRD §3.8: "The award allocation the record implements moves from `EXECUTED` to
        `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed."
        PRD §3.8: "The contract's `rate_load_status` moves from `LOADED` to `LIVE`."
        PRD §3.8: "On the **first** rate record of the whole event to go live, the event
        moves from `AWARDED` to the terminal `LIVE` and its `coverage_pct` is recomputed
        over the allocations now `ACTIVE`."

        Design: Corner/state_machines/go_live_before_the_record_is_loaded_returns_rate_record_not_loaded
        """
        ctx = setup_staged_rate_record()
        fully_sign_contract(ctx["contract"]["id"], ctx["carrier"]["id"])
        set_clock(CLOCK_GO_LIVE)
        validate_error(
            api_client.go_live_rate_record(ctx["rate_record"]["id"], CONTRACT_ADMIN),
            "ERR_RATE_RECORD_NOT_LOADED",
            409,
        )

        load_rate_record(ctx["rate_record"]["id"])
        live = go_live(ctx["rate_record"]["id"])
        assert live["status"] == "LIVE"
        assert_same_instant(live["live_at"], CLOCK_GO_LIVE, "live_at")

        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LIVE"
        event = read_event(ctx["event"]["id"])
        assert event["status"] == "LIVE"
        assert float(event["coverage_pct"]) == FULL_COVERAGE_PCT
        lane = read_lane(ctx["lane"]["id"])
        assert_lane_volume_conservation(lane, [read_allocation(ctx["allocation"]["id"])])


class TestTenderRequiresRoutingAuthority:
    """A LOADED record has rates in the TMS but no authority to move freight."""

    def test_appending_to_a_loaded_record_is_refused_and_starts_no_counters(self):
        """The acceptance metrics must stay at their neutral defaults.

        PRD §3.9: "A procurement analyst or contract administrator appends a tender
        outcome against a rate record whose `status` is `LIVE` or `AT_RISK`; against any
        other status the attempt is rejected with `ERR_RATE_RECORD_NOT_LIVE` (409)."
        PRD §3.8: "The record is created with `status` `STAGED`; `acceptance_pct`
        `100.00` and `rejection_pct` `0.00`, the neutral starting position of a lane that
        has never been tendered; `tender_count` `0`"
        PRD §3.9: "`rejection_pct` is `0.00` when `tender_count` is zero"

        Design: Corner/state_machines/tender_event_against_a_merely_loaded_record_returns_rate_record_not_live
        """
        ctx = setup_staged_rate_record()
        fully_sign_contract(ctx["contract"]["id"], ctx["carrier"]["id"])
        loaded = load_rate_record(ctx["rate_record"]["id"])
        assert loaded["status"] == "LOADED"

        validate_error(
            _append_tender(ctx["rate_record"]["id"], FIRST_LOAD_REFERENCE),
            "ERR_RATE_RECORD_NOT_LIVE",
            409,
        )

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 0
        assert record["rejection_count"] == 0
        assert float(record["rejection_pct"]) == 0.00
        assert float(record["acceptance_pct"]) == 100.00
        _rows, meta = validate_paginated(_list_tenders(ctx["rate_record"]["id"]))
        assert meta["total_count"] == 0, "the refused append may leave no log entry"

    def test_the_same_append_succeeds_once_the_record_is_live(self):
        """Go-live is the only thing that was missing, and the log then opens.

        PRD §3.9: "The tender event records `tendered_at` from the logical clock and
        freezes `position_used` from the rate record's `routing_position` as it stands at
        append time"
        PRD §3.9: "`tender_count` is the number of tender events on the record, counting
        every outcome."
        PRD §3.9: "`acceptance_pct` is `100.00` minus `rejection_pct`, rounded to 2
        decimal places, so the two always sum to exactly `100.00`."

        Design: Corner/state_machines/tender_event_against_a_merely_loaded_record_returns_rate_record_not_live
        """
        ctx = setup_staged_rate_record()
        fully_sign_contract(ctx["contract"]["id"], ctx["carrier"]["id"])
        load_rate_record(ctx["rate_record"]["id"])
        validate_error(
            _append_tender(ctx["rate_record"]["id"], FIRST_LOAD_REFERENCE),
            "ERR_RATE_RECORD_NOT_LIVE",
            409,
        )

        set_clock(CLOCK_GO_LIVE)
        go_live(ctx["rate_record"]["id"])

        tender = validate_success(
            _append_tender(ctx["rate_record"]["id"], FIRST_LOAD_REFERENCE), 201
        )
        assert tender["outcome"] == "ACCEPTED"
        assert tender["load_reference"] == FIRST_LOAD_REFERENCE
        assert tender["position_used"] == "PRIMARY"
        assert_same_instant(tender["tendered_at"], CLOCK_GO_LIVE, "tendered_at")

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 1
        assert record["rejection_count"] == 0
        assert float(record["acceptance_pct"]) == 100.00
        assert record["status"] == "LIVE"
