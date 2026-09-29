"""Endpoint-level contracts: filtered collection reads, the close write, rollups.

Three endpoints are read as contracts rather than as steps of a chain. The lane
listing has to apply its filters before its page window, so the envelope's
`total_count` describes the filtered population. The round-close endpoint is
where the optimiser's input ordering is finalised, and it must refuse a replay
without touching anything. The carrier read is a pure rollup of writes that
happen three entities away from it.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CLOCK_GO_LIVE,
    DEFAULT_CLOCK,
    LANE_B_REEFER,
    add_lane,
    add_validated_lane,
    api_client,
    assert_same_instant,
    create_bid_event,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    make_carrier_rep_headers,
    open_round,
    read_carrier,
    read_event,
    read_lane_bid,
    second_carrier_overrides,
    set_clock,
    setup_awarded_event,
    setup_live_rate_record,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

# Event A's four dry-van lanes; the first two are validated, the last two stay DRAFT.
VALIDATED_LANE_CODES = ("L-A1", "L-A2")
DRAFT_LANE_CODES = ("L-A3", "L-A4")

# The two bids placed on one lane: 2.1152 with 300 loads committed against 2.2000
# with 400. Both quote three transit days, so the tie-breakers never engage.
CHEAP_BID = {"rate_per_mile": 2.1152, "committed_volume_loads": 300}
DEAR_BID = {"rate_per_mile": 2.2000, "committed_volume_loads": 400}

# 1147 x 2.1152 = 2426.13 linehaul, plus 137.55 x 1.15 = 158.18 accessorial, on
# min(300, 550 x 1.20) loads; then the 5% service credit of a 90.60 carrier.
CHEAP_EVALUATED_TOTAL_USD = 775293.00
CHEAP_RANK_SCORE = 736528.35

# 1147 x 2.2000 = 2523.40 linehaul plus the same 158.18, on min(400, 660) loads.
DEAR_EVALUATED_TOTAL_USD = 1072632.00
DEAR_RANK_SCORE = 1019000.40

# The single-lane award: the lane's own 550 planned loads, not the 600 the bid
# offered to commit.
AWARDED_VOLUME_LOADS = 550
QUALIFICATION_COMPOSITE_SCORE = 90.60


def _list_lanes(headers=ANALYST, **params):
    """Reads the lane collection and returns its (rows, meta) pair."""
    return validate_paginated(api_client.list_lanes(headers, params or None))


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


def _close(round_id):
    """Attempts to close a round without asserting the outcome."""
    return api_client.close_bid_round(round_id, ANALYST)


def _two_carrier_open_round():
    """One locked lane, two accepted bidders, one OPEN round holding both bids."""
    set_clock(DEFAULT_CLOCK)
    cheap_carrier = create_qualified_carrier()
    dear_carrier = create_qualified_carrier(
        carrier_overrides=second_carrier_overrides()
    )
    event, lanes = create_event_with_locked_lanes()
    invite_and_accept(event["id"], cheap_carrier["id"])
    invite_and_accept(event["id"], dear_carrier["id"])
    bid_round = open_round(event["id"])
    return {
        "event": read_event(event["id"]),
        "lane": lanes[0],
        "bid_round": bid_round,
        "cheap_bid": submit_bid(
            bid_round["id"], lanes[0]["id"], cheap_carrier["id"], **CHEAP_BID
        ),
        "dear_bid": submit_bid(
            bid_round["id"], lanes[0]["id"], dear_carrier["id"], **DEAR_BID
        ),
    }


def _two_event_lane_population():
    """Four lanes under event A (two validated) and one REEFER lane under event B."""
    set_clock(DEFAULT_CLOCK)
    event_a = create_bid_event()
    validated = [
        add_validated_lane(event_a["id"], lane_code=code)
        for code in VALIDATED_LANE_CODES
    ]
    drafts = [add_lane(event_a["id"], lane_code=code) for code in DRAFT_LANE_CODES]
    event_b = create_bid_event()
    reefer = add_validated_lane(event_b["id"], **LANE_B_REEFER)
    return {
        "event_a": event_a,
        "event_b": event_b,
        "validated": validated,
        "drafts": drafts,
        "reefer": reefer,
    }


class TestLaneListingCombinesFiltersWithPaging:
    """The filters shrink the population first; the page window applies after."""

    def test_the_status_filter_decides_the_total_count_the_page_window_reports(self):
        """Two pages of one, both reporting the filtered total of 2, not 4 or 5.

        PRD §2.4: "Lanes may be filtered by `bid_event_id`, `incumbent_carrier_id`,
        `status` and `equipment_type`, and are ordered by `created_at` ascending."
        PRD §2.3: "List endpoints accept two query parameters. `limit` bounds the number
        of items returned; when omitted it defaults to 10, its minimum accepted value is
        1 and its maximum accepted value is 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope."

        Design: Corner/endpoints/lane_listing_combines_event_filter_status_filter_and_offset_paging
        """
        ctx = _two_event_lane_population()
        validated_ids = {lane["id"] for lane in ctx["validated"]}

        rows, meta = _list_lanes(bid_event_id=ctx["event_a"]["id"])
        assert meta["total_count"] == 4, "event B's lane is outside the event filter"
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 4

        page_one, meta_one = _list_lanes(
            bid_event_id=ctx["event_a"]["id"], status="VALIDATED", limit=1, offset=0
        )
        assert len(page_one) == 1
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True

        page_two, meta_two = _list_lanes(
            CATEGORY_MANAGER,
            bid_event_id=ctx["event_a"]["id"],
            status="VALIDATED",
            limit=1,
            offset=1,
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert page_two[0]["id"] != page_one[0]["id"], "the two pages are disjoint"
        assert {page_one[0]["id"], page_two[0]["id"]} == validated_ids
        for row in page_one + page_two:
            assert row["status"] == "VALIDATED"
            assert row["bid_event_id"] == ctx["event_a"]["id"]

    def test_the_equipment_filter_stands_alone_and_an_empty_page_is_not_a_404(self):
        """`equipment_type` filters without an event, and offset past the end is 200.

        PRD §2.4: "Because the entity graph here is flat — foreign keys travel in
        request bodies and query strings rather than in deep URL paths — the filtered
        list endpoints are the primary way to walk a relationship backwards. Each
        collection therefore declares its filter set explicitly, and every filter is
        optional"
        PRD §2.3: "`offset` is the number of items to skip before the first returned
        item and defaults to 0."

        Design: Corner/endpoints/lane_listing_combines_event_filter_status_filter_and_offset_paging
        """
        ctx = _two_event_lane_population()

        reefers, reefer_meta = _list_lanes(equipment_type="REEFER")
        assert reefer_meta["total_count"] == 1
        assert [row["id"] for row in reefers] == [ctx["reefer"]["id"]]
        assert reefers[0]["bid_event_id"] == ctx["event_b"]["id"]
        assert reefers[0]["equipment_type"] == "REEFER"

        drafts, draft_meta = _list_lanes(
            bid_event_id=ctx["event_a"]["id"], status="DRAFT"
        )
        assert draft_meta["total_count"] == 2
        assert {row["id"] for row in drafts} == {lane["id"] for lane in ctx["drafts"]}

        response = api_client.list_lanes(
            ANALYST,
            {
                "bid_event_id": ctx["event_a"]["id"],
                "status": "VALIDATED",
                "limit": 1,
                "offset": 5,
            },
        )
        assert response.status_code == 200, "an empty page is not a not-found"
        beyond, beyond_meta = validate_paginated(response)
        assert beyond == []
        assert beyond_meta["total_count"] == 2
        assert beyond_meta["has_more"] is False


class TestClosingARoundRanksOnceAndRefusesAReplay:
    """The close finalises the ordering the optimiser reads, and only once."""

    def test_the_close_re_evaluates_every_submitted_bid_and_flips_the_event(self):
        """The ranking survives the recomputation, and the event advances with it.

        PRD §3.4: "The analyst closes a round whose `status` is `OPEN` while the event is
        in `ROUND_OPEN`. The round moves to the terminal `CLOSED` and `closed_at` is set
        to the logical clock."
        PRD §3.4: "Closing re-evaluates every bid: each lane bid on the round whose
        `status` is `SUBMITTED` has its evaluated cost and its cost-rank score recomputed
        and its `rank_in_lane` rewritten, so the ranking that the optimiser will read
        reflects final, post-withdrawal reality rather than the ordering that happened to
        exist when each bid arrived."
        PRD §3.4: "The event moves from `ROUND_OPEN` to `ROUND_CLOSED` and its `version`
        increases by one."
        PRD §3.5: "Subtract `service_credit_pct` from 1, multiply
        `evaluated_total_cost_usd` by that factor, and round to 2 decimal places."

        Design: Corner/endpoints/closing_a_round_writes_ranks_once_and_refuses_a_replay
        """
        ctx = _two_carrier_open_round()
        before = read_event(ctx["event"]["id"])
        assert before["status"] == "ROUND_OPEN"

        closed = validate_success(_close(ctx["bid_round"]["id"]))
        assert closed["status"] == "CLOSED"
        assert_same_instant(closed["closed_at"], DEFAULT_CLOCK, "closed_at")
        assert closed["submitted_bid_count"] == 2

        cheap = read_lane_bid(ctx["cheap_bid"]["id"])
        dear = read_lane_bid(ctx["dear_bid"]["id"])
        assert float(cheap["evaluated_total_cost_usd"]) == CHEAP_EVALUATED_TOTAL_USD
        assert float(cheap["cost_rank_score"]) == CHEAP_RANK_SCORE
        assert cheap["rank_in_lane"] == 1
        assert float(dear["evaluated_total_cost_usd"]) == DEAR_EVALUATED_TOTAL_USD
        assert float(dear["cost_rank_score"]) == DEAR_RANK_SCORE
        assert dear["rank_in_lane"] == 2

        after = read_event(ctx["event"]["id"])
        assert after["status"] == "ROUND_CLOSED"
        assert after["version"] == before["version"] + 1

    def test_the_second_close_is_refused_and_rewrites_nothing(self):
        """Closure is one-way: the replay must not re-rank or re-flip anything.

        PRD §3.4: "Rounds carry only the two statuses `OPEN` and `CLOSED`, and closure is
        one-way."
        PRD §2.9: "**State preconditions.** The target row and its governing parents are
        in states that permit the operation."
        PRD §2.9: "submitting or withdrawing a bid on a round that is not `OPEN` raises
        `ERR_ROUND_NOT_OPEN`"
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and no
        partial write is retained."

        Design: Corner/endpoints/closing_a_round_writes_ranks_once_and_refuses_a_replay
        """
        ctx = _two_carrier_open_round()
        first = validate_success(_close(ctx["bid_round"]["id"]))
        event_after_first = read_event(ctx["event"]["id"])

        validate_error(_close(ctx["bid_round"]["id"]), "ERR_ROUND_NOT_OPEN", 409)

        replayed = _read_round(ctx["bid_round"]["id"])
        assert replayed["status"] == "CLOSED"
        assert replayed["closed_at"] == first["closed_at"]
        assert read_lane_bid(ctx["cheap_bid"]["id"])["rank_in_lane"] == 1
        assert read_lane_bid(ctx["dear_bid"]["id"])["rank_in_lane"] == 2

        event_after_replay = read_event(ctx["event"]["id"])
        assert event_after_replay["status"] == "ROUND_CLOSED"
        assert event_after_replay["version"] == event_after_first["version"], (
            "a refused close may not advance the event's version a second time"
        )


class TestCarrierReadIsARollupOfDistantWrites:
    """The carrier row shows commitments made three entities away from it."""

    def test_the_rollups_are_empty_at_qualification_and_filled_by_the_award(self):
        """Both rollups are zero at qualification and arrive with the award.

        PRD §3.7: "Each carrier that now holds a contract has its
        `committed_volume_loads` and `active_primary_lane_count` recomputed from its
        executed allocations, per the status sets in §2.12."
        PRD §2.12: "`Carrier.committed_volume_loads` sums `allocated_volume_loads` over
        that carrier's allocations whose status is `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`."
        PRD §2.12: "`Carrier.active_primary_lane_count` counts that carrier's award
        allocations whose `routing_position` is `PRIMARY` and whose status is `EXECUTED`
        or `ACTIVE`."

        Design: Corner/endpoints/carrier_read_reflects_the_commitments_derived_from_its_executed_awards
        """
        set_clock(DEFAULT_CLOCK)
        # `scac_code` is unique across all carriers, so this bystander takes the
        # second carrier's SCAC and leaves the default one for the awarded chain.
        fresh = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
        assert fresh["committed_volume_loads"] == 0
        assert fresh["active_primary_lane_count"] == 0
        assert float(fresh["composite_score"]) == QUALIFICATION_COMPOSITE_SCORE

        ctx = setup_awarded_event()
        assert ctx["allocation"]["status"] == "EXECUTED"
        assert ctx["allocation"]["routing_position"] == "PRIMARY"
        assert ctx["allocation"]["allocated_volume_loads"] == AWARDED_VOLUME_LOADS

        awarded = read_carrier(ctx["carrier"]["id"])
        assert awarded["committed_volume_loads"] == AWARDED_VOLUME_LOADS
        assert awarded["active_primary_lane_count"] == 1, (
            "the count spans allocations whose status is EXECUTED or ACTIVE, so the "
            "committed award already counts"
        )
        assert float(awarded["composite_score"]) == QUALIFICATION_COMPOSITE_SCORE

    def test_the_primary_count_arrives_with_the_go_live_and_every_role_may_read_it(self):
        """The cutover is what activates the routing, and the read is not owner-scoped.

        PRD §3.8: "The award allocation the record implements moves from `EXECUTED` to
        `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed."
        PRD §4: "Retrieves a single carrier with its standing, scores and commitment
        rollups. | ProcurementAnalyst, ComplianceOfficer, CategoryManager, ContractAdmin,
        CarrierRep |"
        PRD §2.9: "**Resource ownership.** When the acting role is `CarrierRep`,
        `X-User-ID` must equal the carrier that owns the target, as enumerated in §2.1,
        otherwise `ERR_NOT_RESOURCE_OWNER` (403). This applies to lane-bid withdrawal,
        invitation response, carrier signature, scorecard dispute, mini-bid proposal and
        lane-bid submission."

        Design: Corner/endpoints/carrier_read_reflects_the_commitments_derived_from_its_executed_awards
        """
        set_clock(DEFAULT_CLOCK)
        bystander = create_qualified_carrier(
            carrier_overrides=second_carrier_overrides()
        )
        ctx = setup_live_rate_record()
        assert ctx["rate_record"]["status"] == "LIVE"
        assert_same_instant(ctx["rate_record"]["live_at"], CLOCK_GO_LIVE, "live_at")
        assert ctx["allocation"]["status"] == "ACTIVE"

        analyst_view = read_carrier(ctx["carrier"]["id"])
        assert analyst_view["committed_volume_loads"] == AWARDED_VOLUME_LOADS
        assert analyst_view["active_primary_lane_count"] == 1
        assert float(analyst_view["composite_score"]) == QUALIFICATION_COMPOSITE_SCORE

        own_headers = make_carrier_rep_headers(ctx["carrier"]["id"])
        own_view = validate_success(
            api_client.get_carrier(ctx["carrier"]["id"], own_headers)
        )
        assert own_view["committed_volume_loads"] == AWARDED_VOLUME_LOADS
        assert own_view["active_primary_lane_count"] == 1
        assert float(own_view["composite_score"]) == QUALIFICATION_COMPOSITE_SCORE

        # The read endpoint lists every role and is not in the ownership rung's list.
        other_view = validate_success(
            api_client.get_carrier(bystander["id"], own_headers)
        )
        assert other_view["id"] == bystander["id"]
        assert other_view["committed_volume_loads"] == 0
