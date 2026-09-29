"""Refusals: labour ceilings, temporal windows, uniqueness, capacity and money."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_hours,
    assert_cycle_ledgers,
    assert_instant_equals,
    assert_interval_coverage,
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_ratio,
    assert_settlement_fields_null,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ACTION_STATUS_ACCEPTED,
    ACTION_STATUS_EXPIRED,
    ACTION_STATUS_OFFERED,
    ALLOCATION_COMMITTED,
    ALLOCATION_PROPOSED,
    ALLOCATION_SETTLED,
    BID_STATUS_SUBMITTED,
    BID_STATUS_WITHDRAWN,
    BILLING_COMMITMENT_FLOOR,
    BILLING_DELIVERED_ONLY,
    CHANNEL_EMAIL,
    COVERAGE_SHORT,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    EVENT_STATUS_CONFIRMED,
    EVENT_STATUS_REALIZED,
    MAX_LIMIT,
    PARTNER_STATUS_ACTIVE,
    POSTURE_OPEN,
    POSTURE_REQUIREMENTS_LOCKED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    RESPONSE_ACCEPT,
    ROUND_STATUS_AWARDED,
    ROUND_STATUS_SCORING,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    award_round,
    build_open_round_week,
    build_partner_week,
    build_published_week,
    commit_allocation,
    generate_allocations,
    generate_grid,
    lock_requirements,
    make_agent,
    make_bid_round,
    make_forecast_group,
    make_labor_agreement,
    make_marketing_event,
    make_ot_offer,
    make_outsource_partner,
    make_partner_forecast_group,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_bid,
    make_shift_template,
    make_vto_offer,
    open_round,
    propose_allocation,
    publish_shift,
    read_action,
    read_agent,
    read_allocation,
    read_bid,
    read_cycle,
    read_group,
    read_interval,
    read_partner,
    read_round,
    read_shift,
    read_template,
    respond_to_action,
    revert_to_open,
    run_reforecast,
    score_round,
    set_clock,
    set_event_status,
    settle_allocation,
    withdraw_bid,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    INTRADAY_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_HEADERS,
    make_agent_headers,
)


class TestPublicationSafetyRules:
    """The labour ceilings a publication has to clear, and which one answers."""

    def test_an_overlapping_second_shift_is_refused_on_overlap_not_on_rest(self, api):
        """A 12:00-16:00 shift against a published 08:00-16:00 one answers the overlap error.

        "A neighbouring shift whose own half-open span actually overlaps the
        candidate is deliberately **skipped** by the rest rule rather than being
        treated as a zero-hour gap — which is precisely what keeps the next rule
        reachable. The **overlap rule** then requires that the agent holds no
        other non-cancelled shift whose half-open span from `start_at` up to
        `end_at` overlaps the candidate's; a collision is refused with
        `ERR_SHIFT_OVERLAP` (HTTP 409)."

        Design: Corner/validations/overlapping_shift_publication_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        agent = make_agent(api, agreement["id"])
        lock_requirements(api, cycle["id"])
        morning = make_shift_template(api, cycle["id"])
        afternoon = make_shift_template(
            api, cycle["id"], start_time_local="12:00", duration_minutes=240
        )
        first = make_schedule_shift(
            api, cycle["id"], agent["id"], morning["id"], HORIZON_START
        )
        published = publish_shift(api, first["id"])
        # The overlap rule counts every "other non-cancelled shift", so the
        # colliding afternoon draft is only minted once the morning shift is
        # already live — otherwise the morning publication is itself the
        # collision.
        second = make_schedule_shift(
            api, cycle["id"], agent["id"], afternoon["id"], HORIZON_START
        )
        assert_shift_axes(published, publication_status=PUBLICATION_PUBLISHED)
        assert_shift_hours(published, paid_hours=7.50, end_at="2026-09-07T16:00:00Z")
        assert_instant_equals(published["start_at"], "2026-09-07T08:00:00Z", "start_at")
        assert_instant_equals(second["start_at"], "2026-09-07T12:00:00Z", "start_at")

        refused = api.set_shift_publication(
            second["id"], f.publication_payload(), SCHEDULER_HEADERS
        )

        validate_error(refused, ApiErrorId.SHIFT_OVERLAP.value, 409)
        assert_shift_axes(
            read_shift(api, second["id"]), publication_status=PUBLICATION_DRAFT
        )
        assert_agent_hours(read_agent(api, agent["id"]), 7.50)
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), total_scheduled_hours=7.50)
        assert_interval_coverage(
            read_interval(api, intervals[0]["id"]), scheduled_agents=1
        )

    def test_a_third_adjacent_day_breaks_the_consecutive_days_run(self, api):
        """Monday and Tuesday publish under a two-day ceiling; Wednesday is refused.

        "The **consecutive-days rule** requires that the agent's longest run of
        consecutive service dates carrying a non-cancelled shift stays at or
        below the agreement's `max_consecutive_days`; a longer run is refused
        with `ERR_MAX_CONSECUTIVE_DAYS_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/consecutive_days_run_exceeded_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, max_consecutive_days=2)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], HORIZON_START)
        agent = make_agent(api, agreement["id"])
        lock_requirements(api, cycle["id"])
        monday = make_shift_template(api, cycle["id"])
        tuesday = make_shift_template(api, cycle["id"], days_of_week=[1])
        wednesday = make_shift_template(api, cycle["id"], days_of_week=[2])
        # The run counts every consecutive service date the agent carries a
        # "non-cancelled shift" on, drafts included, so each day is
        # minted only once its predecessor is live: minting all three drafts up
        # front would already put the run at three before any publication.
        monday_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], monday["id"], "2026-09-07"
        )
        assert_shift_axes(
            publish_shift(api, monday_shift["id"]),
            publication_status=PUBLICATION_PUBLISHED,
        )
        tuesday_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], tuesday["id"], "2026-09-08"
        )
        assert_shift_axes(
            publish_shift(api, tuesday_shift["id"]),
            publication_status=PUBLICATION_PUBLISHED,
        )
        wednesday_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], wednesday["id"], "2026-09-09"
        )

        refused = api.set_shift_publication(
            wednesday_shift["id"], f.publication_payload(), SCHEDULER_HEADERS
        )

        validate_error(refused, ApiErrorId.MAX_CONSECUTIVE_DAYS_EXCEEDED.value, 422)
        assert_shift_axes(
            read_shift(api, wednesday_shift["id"]),
            publication_status=PUBLICATION_DRAFT,
        )
        assert_agent_hours(read_agent(api, agent["id"]), 15.00)
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), total_scheduled_hours=15.00)


class TestTemporalWindowSanity:
    """Every out-of-window surface answers its own temporal error id."""

    def test_each_out_of_window_surface_answers_its_own_temporal_error(self, api):
        """Grid, shift and reforecast answer the horizon error; a premature realisation answers the window error.

        "The service date must fall inside the cycle horizon, from
        `horizon_start_date` through `horizon_end_date` inclusive; a date outside
        it is refused with `ERR_INTERVAL_OUTSIDE_HORIZON` (HTTP 422)."

        "The `effective_from_interval_start` instant must fall inside the cycle
        horizon; outside it, the run is refused with
        `ERR_INTERVAL_OUTSIDE_HORIZON` (HTTP 422)."

        "Marking a driver `REALIZED` — the `CONFIRMED → REALIZED` move —
        requires that the cycle is not frozen and that the logical clock has
        reached or passed the event's `window_end`; requesting it earlier is
        refused with `ERR_EVENT_WINDOW_INVALID`."

        Design: Corner/validations/temporal_window_sanity_violations_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        agent = make_agent(api, agreement["id"])
        template = make_shift_template(api, cycle["id"])
        opened = read_cycle(api, cycle["id"])

        refused_grid = api.generate_interval_plans(
            group["id"], f.interval_grid_payload("2026-09-14"), ANALYST_HEADERS
        )
        refused_shift = api.create_schedule_shift(
            f.schedule_shift_payload(
                cycle["id"], agent["id"], template["id"], "2026-09-20"
            ),
            SCHEDULER_HEADERS,
        )
        refused_reforecast = api.reforecast(
            cycle["id"],
            f.reforecast_payload(opened["version"], "2026-09-20T09:00:00Z"),
            ANALYST_HEADERS,
        )

        validate_error(refused_grid, ApiErrorId.INTERVAL_OUTSIDE_HORIZON.value, 422)
        validate_error(refused_shift, ApiErrorId.INTERVAL_OUTSIDE_HORIZON.value, 422)
        validate_error(
            refused_reforecast, ApiErrorId.INTERVAL_OUTSIDE_HORIZON.value, 422
        )
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            posture=POSTURE_OPEN,
            reforecast_generation=0,
            version=opened["version"],
        )
        rows, meta = validate_paginated(
            api.list_interval_plans(
                ANALYST_HEADERS, params={"forecast_group_id": group["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused grid minted no interval plans"
        assert rows == []

        event = make_marketing_event(api, cycle["id"], group["id"])
        confirmed = set_event_status(api, event["id"], EVENT_STATUS_CONFIRMED)
        assert confirmed["status"] == EVENT_STATUS_CONFIRMED
        assert_instant_equals(
            confirmed["window_end"], "2026-09-07T10:00:00Z", "window_end"
        )

        refused_realize = api.set_marketing_event_status(
            event["id"],
            f.marketing_event_status_payload(EVENT_STATUS_REALIZED),
            ANALYST_HEADERS,
        )

        validate_error(refused_realize, ApiErrorId.EVENT_WINDOW_INVALID.value, 422)
        still_confirmed = get_success_data(
            api.get_marketing_event(event["id"], ANALYST_HEADERS)
        )
        assert still_confirmed["status"] == EVENT_STATUS_CONFIRMED


class TestGridUniqueness:
    """The grid generator is keyed on the group and the date together."""

    def test_a_repeat_grid_for_the_same_group_and_date_is_refused(self, api):
        """A second grid request for the same pair is refused, while another date still generates.

        "A grid may be generated once per group and date: a repeat attempt for
        the same `forecast_group_id` and `service_date` is refused with
        `ERR_DUPLICATE_INTERVALS` (HTTP 409)."

        Design: Corner/validations/duplicate_interval_grid_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        minted = generate_grid(api, group["id"], HORIZON_START)

        refused = api.generate_interval_plans(
            group["id"], f.interval_grid_payload(HORIZON_START), ANALYST_HEADERS
        )

        validate_error(refused, ApiErrorId.DUPLICATE_INTERVALS.value, 409)
        assert read_group(api, group["id"])["interval_count"] == 4
        rows, meta = validate_paginated(
            api.list_interval_plans(
                ANALYST_HEADERS,
                params={
                    "forecast_group_id": group["id"],
                    "service_date": HORIZON_START,
                },
            )
        )
        assert meta["total_count"] == 4, "the refused repeat minted nothing"
        assert rows[0]["id"] == minted[0]["id"]

        next_day = generate_grid(api, group["id"], "2026-09-08")

        assert len(next_day) == 4
        assert read_group(api, group["id"])["interval_count"] == 8


class TestBidUniqueness:
    """One live bid per agent per round, and withdrawal frees the slot."""

    def test_a_second_live_bid_is_refused_but_a_post_withdrawal_bid_is_not(self, api):
        """A different preference list does not buy a second live bid; withdrawing does.

        "A bidder may hold only one live bid per round: if the agent already
        holds a bid in the same round whose `status` is anything other than
        `WITHDRAWN`, the submission is refused with `ERR_DUPLICATE_BID`
        (HTTP 409)."

        Design: Corner/validations/second_bid_in_same_round_rejected
        """
        world = build_open_round_week(api)
        agent_id = world["agent"]["id"]
        round_id = world["round"]["id"]
        first_template = world["template"]
        second_template = make_shift_template(
            api, world["cycle"]["id"], days_of_week=[1]
        )
        first_bid = make_shift_bid(api, round_id, agent_id, [first_template["id"]])
        assert first_bid["status"] == BID_STATUS_SUBMITTED

        refused = api.create_shift_bid(
            f.shift_bid_payload(
                round_id, agent_id, [second_template["id"], first_template["id"]]
            ),
            make_agent_headers(agent_id),
        )

        validate_error(refused, ApiErrorId.DUPLICATE_BID.value, 409)
        withdrawn = withdraw_bid(api, first_bid["id"], agent_id)
        assert withdrawn["status"] == BID_STATUS_WITHDRAWN

        replacement = make_shift_bid(api, round_id, agent_id, [second_template["id"]])

        assert replacement["status"] == BID_STATUS_SUBMITTED
        assert read_bid(api, first_bid["id"])["status"] == BID_STATUS_WITHDRAWN
        _, meta = validate_paginated(
            api.list_shift_bids(
                SCHEDULER_HEADERS,
                params={"bid_round_id": round_id, "agent_id": agent_id},
            )
        )
        assert meta["total_count"] == 2, "the withdrawn bid is kept alongside the new one"


class TestAwardRunGates:
    """The two legality gates of an award run, and the order they fire in."""

    def test_a_round_that_can_place_nobody_is_refused_before_the_honour_floor(self, api):
        """A later round bidding the one exhausted slot is refused on slots, not on the floor.

        "First, a run that can place nobody is refused outright with
        `ERR_TEMPLATE_SLOTS_EXHAUSTED` (HTTP 409) — because every template
        referenced by the round's submitted bids has already reached its
        `slots_total`, or matches no bidder's skills. Running this gate first is
        also what guarantees the honour rate is never compared while it is null."

        Design: Corner/validations/award_against_exhausted_template_slots_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, preference_honor_floor_pct=0.5000)
        cycle = make_planning_cycle(api)
        senior = make_agent(api, agreement["id"], seniority_rank=1)
        junior = make_agent(api, agreement["id"], seniority_rank=2)
        template = make_shift_template(api, cycle["id"], slots_total=1)
        first_round = make_bid_round(api, cycle["id"])
        open_round(api, first_round["id"])
        make_shift_bid(api, first_round["id"], senior["id"], [template["id"]])
        score_round(api, first_round["id"])
        awarded = award_round(api, first_round["id"])
        assert awarded["status"] == ROUND_STATUS_AWARDED
        assert_ratio(awarded["preference_honor_rate"], 1.0000, "preference_honor_rate")
        assert read_template(api, template["id"])["slots_awarded"] == 1
        second_round = make_bid_round(api, cycle["id"])
        open_round(api, second_round["id"])
        late_bid = make_shift_bid(
            api, second_round["id"], junior["id"], [template["id"]]
        )
        score_round(api, second_round["id"])

        refused = api.award_bid_round(second_round["id"], SCHEDULER_HEADERS)

        validate_error(refused, ApiErrorId.TEMPLATE_SLOTS_EXHAUSTED.value, 409)
        stalled = read_round(api, second_round["id"])
        assert stalled["status"] == ROUND_STATUS_SCORING
        assert stalled["preference_honor_rate"] is None
        assert stalled["awarded_bid_count"] == 0
        assert stalled["unfilled_bid_count"] == 0
        untouched_bid = read_bid(api, late_bid["id"])
        assert untouched_bid["status"] == BID_STATUS_SUBMITTED
        assert untouched_bid["awarded_shift_template_id"] is None
        _, meta = validate_paginated(
            api.list_schedule_shifts(
                SCHEDULER_HEADERS, params={"planning_cycle_id": cycle["id"]}
            )
        )
        assert meta["total_count"] == 1, "only the first round's shift exists"

    def test_a_run_below_the_honour_floor_writes_nothing_at_all(self, api):
        """Two bidders sharing one preference order fall below a 0.75 floor and nothing commits.

        "Second, the honour floor: the system takes the strictest floor among the
        labour agreements of the bidders who would be awarded, which is the
        **smallest** `preference_honor_floor_pct` across those agreements, and
        refuses the run with `ERR_PREFERENCE_FLOOR_NOT_MET` (HTTP 422) when the
        honour rate is strictly below it."

        Design: Corner/validations/award_below_preference_floor_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, preference_honor_floor_pct=0.7500)
        cycle = make_planning_cycle(api)
        senior = make_agent(api, agreement["id"], seniority_rank=1)
        junior = make_agent(api, agreement["id"], seniority_rank=2)
        monday = make_shift_template(api, cycle["id"], slots_total=1)
        tuesday = make_shift_template(
            api, cycle["id"], days_of_week=[1], slots_total=1
        )
        preferences = [monday["id"], tuesday["id"]]
        bid_round = make_bid_round(api, cycle["id"])
        open_round(api, bid_round["id"])
        senior_bid = make_shift_bid(api, bid_round["id"], senior["id"], preferences)
        junior_bid = make_shift_bid(api, bid_round["id"], junior["id"], preferences)
        scored = score_round(api, bid_round["id"])
        assert scored["status"] == ROUND_STATUS_SCORING

        refused = api.award_bid_round(bid_round["id"], SCHEDULER_HEADERS)

        validate_error(refused, ApiErrorId.PREFERENCE_FLOOR_NOT_MET.value, 422)
        stalled = read_round(api, bid_round["id"])
        assert stalled["status"] == ROUND_STATUS_SCORING
        assert stalled["preference_honor_rate"] is None
        assert stalled["awarded_bid_count"] == 0
        assert read_bid(api, senior_bid["id"])["status"] == BID_STATUS_SUBMITTED
        assert read_bid(api, junior_bid["id"])["status"] == BID_STATUS_SUBMITTED
        assert read_template(api, monday["id"])["slots_awarded"] == 0
        assert read_template(api, tuesday["id"])["slots_awarded"] == 0
        _, meta = validate_paginated(
            api.list_schedule_shifts(
                SCHEDULER_HEADERS, params={"planning_cycle_id": cycle["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused run minted no shift"


class TestRoutingFeasibility:
    """Outflow is tested at creation, because a routing adjustment self-accepts."""

    def test_shifting_agents_out_of_an_unstaffed_interval_persists_no_action(self, api):
        """An unstaffed source interval refuses the adjustment and leaves no action row behind.

        "Its one precondition is that `agents_shifted` does not exceed the source
        group's interval's `effective_scheduled_agents` — you cannot reroute
        agents who are not staffed — and a breach is refused with
        `ERR_ROUTING_OUTFLOW_EXCEEDS_STAFFING` (HTTP 422)."

        Design: Corner/validations/routing_outflow_above_staffing_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        source_group = make_forecast_group(api, cycle["id"])
        target_group = make_partner_forecast_group(api, cycle["id"])
        source_intervals = generate_grid(api, source_group["id"], HORIZON_START)
        target_intervals = generate_grid(api, target_group["id"], HORIZON_START)
        assert_interval_coverage(
            read_interval(api, source_intervals[0]["id"]),
            scheduled_agents=0,
            effective_scheduled_agents=0,
        )

        refused = api.create_intraday_action(
            f.routing_adjustment_payload(
                cycle["id"],
                source_group["id"],
                target_group["id"],
                "2026-09-07T08:00:00Z",
                agents_shifted=1,
                expires_at="2026-09-07T09:00:00Z",
            ),
            INTRADAY_HEADERS,
        )

        validate_error(refused, ApiErrorId.ROUTING_OUTFLOW_EXCEEDS_STAFFING.value, 422)
        assert_interval_coverage(
            read_interval(api, target_intervals[0]["id"]), routing_inflow_agents=0
        )
        assert_interval_coverage(
            read_interval(api, source_intervals[0]["id"]), routing_outflow_agents=0
        )
        _, meta = validate_paginated(
            api.list_intraday_actions(
                INTRADAY_HEADERS, params={"planning_cycle_id": cycle["id"]}
            )
        )
        assert meta["total_count"] == 0, "no OFFERED row was persisted"


class TestPartnerAllocationGuards:
    """Eligibility and the two-sided volume band, and which of them answers."""

    def test_volumes_either_side_of_the_band_are_refused_but_the_floor_itself_is_not(
        self, api
    ):
        """Five and sixty are both out of band while ten — the floor exactly — is accepted.

        "`allocated_volume` must be at least the partner's
        `commitment_floor_volume` and at most the partner's applicable interval
        cap, which is `interval_max_volume` while the partner is `ACTIVE` and
        `commitment_floor_volume` while it is on `PROBATION`; a volume outside
        that band is refused with `ERR_PARTNER_VOLUME_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/allocation_volume_outside_partner_range_rejected
        """
        world = build_partner_week(api)
        interval = world["intervals"][0]
        assert_interval_outsourcing(
            read_interval(api, interval["id"]), allocatable_volume=82
        )
        partner = make_outsource_partner(
            api,
            rate_per_contact_millicents=10000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        assert partner["status"] == PARTNER_STATUS_ACTIVE

        below_floor = api.create_partner_allocation(
            f.partner_allocation_payload(partner["id"], interval["id"], 5),
            SOURCING_HEADERS,
        )
        above_cap = api.create_partner_allocation(
            f.partner_allocation_payload(partner["id"], interval["id"], 60),
            SOURCING_HEADERS,
        )

        validate_error(below_floor, ApiErrorId.PARTNER_VOLUME_OUT_OF_RANGE.value, 422)
        validate_error(above_cap, ApiErrorId.PARTNER_VOLUME_OUT_OF_RANGE.value, 422)

        at_the_floor = propose_allocation(api, partner["id"], interval["id"], 10)

        assert at_the_floor["status"] == ALLOCATION_PROPOSED
        assert at_the_floor["allocated_volume"] == 10
        assert_interval_outsourcing(
            read_interval(api, interval["id"]),
            partner_committed_volume=0,
            unserved_volume=82,
        )
        _, meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, params={"interval_plan_id": interval["id"]}
            )
        )
        assert meta["total_count"] == 1, "only the in-band proposal was written"

    def test_a_partner_certified_for_another_skill_never_enters_the_waterfall(self, api):
        """A VOICE_EN-only partner is refused on eligibility and the waterfall returns nothing.

        "A suspended partner is permanently excluded from the waterfall, and any
        write referencing it is refused with `ERR_PARTNER_NOT_ELIGIBLE`
        (HTTP 409) — the same identifier used when a partner's `skill_codes` does
        not contain the interval's group `skill_code`."

        "Candidates are the partners whose `status` is `ACTIVE` or `PROBATION`
        and whose `skill_codes` contains the interval's group `skill_code`"

        Design: Corner/validations/allocation_to_partner_without_skill_rejected
        """
        world = build_partner_week(api)
        interval = world["intervals"][0]
        voice_only = make_outsource_partner(
            api,
            skill_codes=["VOICE_EN"],
            rate_per_contact_millicents=10000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )

        refused = api.create_partner_allocation(
            f.partner_allocation_payload(voice_only["id"], interval["id"], 20),
            SOURCING_HEADERS,
        )

        validate_error(refused, ApiErrorId.PARTNER_NOT_ELIGIBLE.value, 409)
        assert generate_allocations(api, interval["id"]) == []
        assert_interval_outsourcing(
            read_interval(api, interval["id"]),
            partner_committed_volume=0,
            unserved_volume=82,
        )
        _, meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, params={"interval_plan_id": interval["id"]}
            )
        )
        assert meta["total_count"] == 0, "the ineligible partner wrote no allocation"


class TestSettlementCommitmentFloor:
    """A commitment-floor partner may be billed its floor but may not settle below it."""

    def test_delivering_below_the_floor_leaves_the_line_committed_and_unbilled(self, api):
        """Fifteen against a floor of twenty is refused; twenty exactly settles.

        "For a partner whose `billing_basis` is `COMMITMENT_FLOOR`,
        `delivered_volume` must be at least that partner's
        `commitment_floor_volume`, and shortfalls are refused with
        `ERR_COMMITMENT_FLOOR_BREACH` (HTTP 409)."

        Design: Corner/validations/commitment_floor_partner_settled_short_rejected
        """
        world = build_partner_week(api)
        interval = world["intervals"][0]
        partner = make_outsource_partner(
            api,
            rate_per_contact_millicents=12500,
            interval_max_volume=50,
            commitment_floor_volume=20,
            billing_basis=BILLING_COMMITMENT_FLOOR,
        )
        allocation = propose_allocation(api, partner["id"], interval["id"], 40)
        committed = commit_allocation(
            api, allocation["id"], read_partner(api, partner["id"])["version"]
        )
        assert committed["status"] == ALLOCATION_COMMITTED

        refused = api.settle_partner_allocation(
            allocation["id"], f.settle_allocation_payload(15), SOURCING_HEADERS
        )

        validate_error(refused, ApiErrorId.COMMITMENT_FLOOR_BREACH.value, 409)
        unsettled = read_allocation(api, allocation["id"])
        assert unsettled["status"] == ALLOCATION_COMMITTED
        assert_settlement_fields_null(unsettled)
        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=40,
            invoice_total_cents=0,
        )
        assert_interval_outsourcing(
            read_interval(api, interval["id"]),
            partner_committed_volume=40,
            unserved_volume=42,
        )

        settled = settle_allocation(api, allocation["id"], 20)

        assert settled["status"] == ALLOCATION_SETTLED
        assert settled["delivered_volume"] == 20


class TestOfferExpiry:
    """Equality with the expiry instant is late, and it moves the row."""

    def test_a_response_at_exactly_the_expiry_instant_expires_the_action(self, api):
        """The refusal and the OFFERED to EXPIRED move land in the same request, moving no money.

        "Both answers require the logical clock to be strictly before
        `expires_at`; equality already counts as expired. If the clock has
        reached or passed `expires_at`, the response is refused and the action is
        moved `OFFERED → EXPIRED` in the very same request, returning
        `ERR_ACTION_EXPIRED` (HTTP 409) with no ledger field moved anywhere."

        "`ERR_ACTION_NOT_OFFERED` when a response targets an intraday action
        that is no longer open or a revocation targets an already-terminal one"

        Design: Corner/validations/expired_intraday_action_response_rejected
        """
        world = build_published_week(api)
        agent_id = world["agent"]["id"]
        shift = world["shift"]
        assert_shift_axes(shift, publication_status=PUBLICATION_PUBLISHED)
        assert_shift_hours(shift, paid_hours=7.50, end_at="2026-09-07T16:00:00Z")
        action = make_ot_offer(
            api,
            world["cycle"]["id"],
            agent_id,
            shift["id"],
            world["group"]["id"],
            hours=1.0,
            expires_at="2026-09-06T12:00:00Z",
        )
        assert action["status"] == ACTION_STATUS_OFFERED
        set_clock(api, "2026-09-06T12:00:00Z")

        refused = api.respond_to_intraday_action(
            action["id"],
            f.action_response_payload(RESPONSE_ACCEPT),
            make_agent_headers(agent_id),
        )

        validate_error(refused, ApiErrorId.ACTION_EXPIRED.value, 409)
        expired = read_action(api, action["id"])
        assert expired["status"] == ACTION_STATUS_EXPIRED
        assert expired["cost_cents"] == 0
        assert expired["ot_multiplier_applied"] is None
        assert expired["responded_by_user_id"] is None
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            ot_spend_committed_cents=0,
            ot_hours_committed=0.00,
        )
        assert_shift_hours(
            read_shift(api, shift["id"]),
            paid_hours=7.50,
            ot_hours=0.00,
            end_at="2026-09-07T16:00:00Z",
        )

        again = api.respond_to_intraday_action(
            action["id"],
            f.action_response_payload(RESPONSE_ACCEPT),
            make_agent_headers(agent_id),
        )

        validate_error(again, ApiErrorId.ACTION_NOT_OFFERED.value, 409)


class TestPaginationBand:
    """The pagination band is rejected at its edges, never clamped."""

    def test_out_of_band_pagination_is_refused_rather_than_clamped(self, api):
        """101, 0 and -1 are refused with their own 400 while 100 and 0 are honoured.

        "A `limit` outside the range 1 through 100 inclusive, a negative
        `offset`, or a non-integer value for either is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        "`limit` controls page size: it defaults to 10 when omitted, may not be
        smaller than 1 and may not be larger than 100. `offset` controls the
        starting position: it defaults to 0 and may not be negative."

        Design: Corner/validations/pagination_params_outside_range_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        make_planning_cycle(api)
        make_planning_cycle(
            api, horizon_start_date="2026-09-14", horizon_end_date="2026-09-20"
        )

        over_maximum = api.list_planning_cycles(PLANNER_HEADERS, params={"limit": 101})
        under_minimum = api.list_planning_cycles(PLANNER_HEADERS, params={"limit": 0})
        negative_offset = api.list_planning_cycles(
            PLANNER_HEADERS, params={"offset": -1}
        )

        validate_error(over_maximum, ApiErrorId.INVALID_PAGINATION.value, 400)
        validate_error(under_minimum, ApiErrorId.INVALID_PAGINATION.value, 400)
        validate_error(negative_offset, ApiErrorId.INVALID_PAGINATION.value, 400)

        rows, meta = validate_paginated(
            api.list_planning_cycles(
                PLANNER_HEADERS, params={"limit": MAX_LIMIT, "offset": 0}
            )
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2

        defaulted_rows, defaulted_meta = validate_paginated(
            api.list_planning_cycles(PLANNER_HEADERS)
        )

        assert defaulted_meta["limit"] == DEFAULT_LIMIT
        assert defaulted_meta["offset"] == DEFAULT_OFFSET
        assert len(defaulted_rows) == 2


class TestPostureGateOnDemandDefinition:
    """Locking the requirements closes demand definition but not reforecasting."""

    def test_locked_requirements_refuse_group_and_grid_writes_yet_allow_a_reforecast(
        self, api
    ):
        """Both demand-definition writes are refused while locked, and reopening restores them.

        "Conversely, both demand-definition operations — creating a forecast
        group and generating an interval grid for a forecast group — require the
        cycle to be in `OPEN`; attempting either once the posture has moved past
        `OPEN` is refused with `ERR_CYCLE_NOT_OPEN` (HTTP 409)."

        Design: Corner/validations/forecast_work_after_requirements_lock_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], HORIZON_START)
        locked = lock_requirements(api, cycle["id"])
        assert locked["posture"] == POSTURE_REQUIREMENTS_LOCKED
        email_overrides = {
            "channel": CHANNEL_EMAIL,
            "skill_code": "EMAIL_EN",
            "base_daily_volume": 100,
            "base_aht_seconds": 240,
            "operating_end_minute": 540,
            "intraday_curve": [0.5, 0.5],
        }

        refused_group = api.create_forecast_group(
            f.forecast_group_payload(cycle["id"], **email_overrides), ANALYST_HEADERS
        )
        refused_grid = api.generate_interval_plans(
            group["id"], f.interval_grid_payload("2026-09-08"), ANALYST_HEADERS
        )

        validate_error(refused_group, ApiErrorId.CYCLE_NOT_OPEN.value, 409)
        validate_error(refused_grid, ApiErrorId.CYCLE_NOT_OPEN.value, 409)

        reforecasted = run_reforecast(
            api, cycle["id"], locked["version"], "2026-09-07T09:00:00Z"
        )

        assert reforecasted["posture"] == POSTURE_REQUIREMENTS_LOCKED
        assert reforecasted["reforecast_generation"] == 1
        _, meta = validate_paginated(
            api.list_forecast_groups(
                ANALYST_HEADERS, params={"planning_cycle_id": cycle["id"]}
            )
        )
        assert meta["total_count"] == 1, "the refused group was never written"

        reopened = revert_to_open(api, cycle["id"])

        assert reopened["posture"] == POSTURE_OPEN
        second_group = make_forecast_group(api, cycle["id"], **email_overrides)
        assert second_group["skill_code"] == "EMAIL_EN"
        assert len(generate_grid(api, group["id"], "2026-09-08")) == 4


class TestVoluntaryTimeOffAcceptance:
    """The satisfied side of the notice and coverage gates on a release."""

    def test_a_release_with_ample_notice_shortens_the_shift_without_double_counting(
        self, api
    ):
        """An hour released 152 hours ahead of an already-short interval lands paid hours on 6.50.

        "For a voluntary-time-off offer it additionally requires that the notice
        period — the shift's `start_at` minus the current logical clock,
        expressed in hours — is greater than or equal to the agreement's
        `vto_min_notice_hours`, with shortfalls refused as
        `ERR_VTO_NOTICE_TOO_SHORT` (HTTP 422); and it requires that releasing the
        hours does not push any interval plan the shift covers from `COVERED` to
        `SHORT`, with breaches refused as `ERR_VTO_WOULD_BREACH_COVERAGE`
        (HTTP 409)."

        "An accepted voluntary-time-off offer instead shortens `end_at` by
        `hours` and recomputes the shift's `scheduled_seconds`, `vto_hours` and
        `paid_hours`, the agent's `scheduled_hours_committed` and the cycle's
        `total_scheduled_hours`."

        Design: Corner/validations/vto_accept_with_sufficient_notice_succeeds
        """
        world = build_published_week(api)
        agent_id = world["agent"]["id"]
        shift = world["shift"]
        first_interval = world["intervals"][0]
        assert_interval_coverage(
            read_interval(api, first_interval["id"]), coverage_state=COVERAGE_SHORT
        )
        assert_instant_equals(shift["start_at"], "2026-09-07T08:00:00Z", "start_at")
        assert_shift_hours(
            shift,
            scheduled_seconds=27000,
            paid_hours=7.50,
            end_at="2026-09-07T16:00:00Z",
        )
        action = make_vto_offer(
            api,
            world["cycle"]["id"],
            agent_id,
            shift["id"],
            hours=1.0,
            expires_at="2026-09-06T00:00:00Z",
        )
        assert action["status"] == ACTION_STATUS_OFFERED

        accepted = respond_to_action(api, action["id"], agent_id, RESPONSE_ACCEPT)

        assert accepted["status"] == ACTION_STATUS_ACCEPTED
        assert accepted["responded_by_user_id"] == agent_id
        assert accepted["cost_cents"] == 0
        shortened = read_shift(api, shift["id"])
        assert_shift_hours(
            shortened,
            scheduled_seconds=23400,
            paid_hours=6.50,
            ot_hours=0.00,
            vto_hours=1.00,
            end_at="2026-09-07T15:00:00Z",
        )
        assert_shift_axes(shortened, publication_status=PUBLICATION_PUBLISHED)
        assert_agent_hours(read_agent(api, agent_id), 6.50)
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            posture=POSTURE_REQUIREMENTS_LOCKED,
            total_scheduled_hours=6.50,
            ot_spend_committed_cents=0,
        )
        assert_interval_coverage(
            read_interval(api, first_interval["id"]), coverage_state=COVERAGE_SHORT
        )
