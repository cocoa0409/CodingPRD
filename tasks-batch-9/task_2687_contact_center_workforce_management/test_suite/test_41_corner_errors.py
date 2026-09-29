"""Error corners: entity-specific not-founds and the four state-specific refusals."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_coaching,
    assert_cycle_ledgers,
    assert_partner_ledgers,
    assert_settlement_fields_null,
    assert_shift_adherence,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ADHERENCE_EXCUSED,
    ADHERENCE_PENDING,
    ALLOCATION_PROPOSED,
    ALLOCATION_REVOKED,
    BID_STATUS_SUBMITTED,
    BILLING_DELIVERED_ONLY,
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_REQUEST_INFO,
    EXCEPTION_STATUS_APPROVED,
    POSTURE_OPEN,
    POSTURE_REQUIREMENTS_LOCKED,
    PUBLICATION_CANCELLED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    ROUND_STATUS_DRAFT,
    ROUND_STATUS_SCORING,
)
from test_helpers.factories import (
    adherence_observation_payload,
    exception_decision_payload,
    exception_resubmit_payload,
    publication_payload,
    settle_allocation_payload,
    shift_bid_payload,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    build_exception_case,
    cancel_shift,
    generate_grid,
    lock_requirements,
    make_agent,
    make_bid_round,
    make_forecast_group,
    make_labor_agreement,
    make_outsource_partner,
    make_partner_forecast_group,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    open_round,
    propose_allocation,
    read_agent,
    read_allocation,
    read_cycle,
    read_exception,
    read_partner,
    read_shift,
    revoke_allocation,
    score_round,
    set_clock,
)
from test_helpers.test_users import (
    COACH_HEADERS,
    INTRADAY_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_ALT_USER_ID,
    make_agent_headers,
    make_sourcing_headers,
)


class TestEntitySpecificNotFound:
    """Fifteen entities, fifteen distinct not-found identifiers."""

    def test_every_unknown_path_id_names_its_own_entity(self, api):
        """Reading fifteen unknown ids gives fifteen different 404 identifiers.

        "The per-entity not-found identifiers are `ERR_PLANNING_CYCLE_NOT_FOUND`,
        `ERR_LABOR_AGREEMENT_NOT_FOUND`, `ERR_FORECAST_GROUP_NOT_FOUND`,
        `ERR_MARKETING_EVENT_NOT_FOUND`, `ERR_INTERVAL_PLAN_NOT_FOUND`,
        `ERR_AGENT_NOT_FOUND`, `ERR_SHIFT_TEMPLATE_NOT_FOUND`,
        `ERR_BID_ROUND_NOT_FOUND`, `ERR_SHIFT_BID_NOT_FOUND`,
        `ERR_SCHEDULE_SHIFT_NOT_FOUND`, `ERR_ADHERENCE_EXCEPTION_NOT_FOUND`,
        `ERR_INTRADAY_ACTION_NOT_FOUND`, `ERR_OUTSOURCE_PARTNER_NOT_FOUND`,
        `ERR_PARTNER_ALLOCATION_NOT_FOUND` and `ERR_HIRING_CLASS_NOT_FOUND`."

        Design: Corner/errors/unknown_path_id_returns_entity_specific_not_found
        """
        set_clock(api, CANONICAL_CLOCK)
        probes = [
            (api.get_planning_cycle, "0001", ApiErrorId.PLANNING_CYCLE_NOT_FOUND),
            (api.get_labor_agreement, "0002", ApiErrorId.LABOR_AGREEMENT_NOT_FOUND),
            (api.get_forecast_group, "0003", ApiErrorId.FORECAST_GROUP_NOT_FOUND),
            (api.get_marketing_event, "0004", ApiErrorId.MARKETING_EVENT_NOT_FOUND),
            (api.get_interval_plan, "0005", ApiErrorId.INTERVAL_PLAN_NOT_FOUND),
            (api.get_agent, "0006", ApiErrorId.AGENT_NOT_FOUND),
            (api.get_shift_template, "0007", ApiErrorId.SHIFT_TEMPLATE_NOT_FOUND),
            (api.get_bid_round, "0008", ApiErrorId.BID_ROUND_NOT_FOUND),
            (api.get_shift_bid, "0009", ApiErrorId.SHIFT_BID_NOT_FOUND),
            (api.get_schedule_shift, "000a", ApiErrorId.SCHEDULE_SHIFT_NOT_FOUND),
            (
                api.get_adherence_exception,
                "000b",
                ApiErrorId.ADHERENCE_EXCEPTION_NOT_FOUND,
            ),
            (api.get_intraday_action, "000c", ApiErrorId.INTRADAY_ACTION_NOT_FOUND),
            (api.get_outsource_partner, "000d", ApiErrorId.OUTSOURCE_PARTNER_NOT_FOUND),
            (
                api.get_partner_allocation,
                "000e",
                ApiErrorId.PARTNER_ALLOCATION_NOT_FOUND,
            ),
            (api.get_hiring_class, "000f", ApiErrorId.HIRING_CLASS_NOT_FOUND),
        ]

        observed = []
        for reader, tail, expected in probes:
            unknown_id = f"00000000-0000-4000-8000-00000000{tail}"
            error = validate_error(reader(unknown_id, PLANNER_HEADERS), expected, 404)
            observed.append(error["error_id"])

        assert len(observed) == 15
        assert len(set(observed)) == 15


class TestBidRoundIntakeWindow:
    """Both edges of the open window, on both bid endpoints."""

    def test_bids_are_refused_on_either_side_of_the_open_window(self, api):
        """A draft round, a scoring round and a post-open withdrawal all name the same refusal.

        "the refusal is HTTP 409 and carries the most specific identifier available
        for that entity family: `ERR_BID_ROUND_NOT_OPEN` when a bid is submitted or
        withdrawn outside an open round"

        Design: Corner/errors/bid_submission_to_unopened_round_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        agreement = make_labor_agreement(api)
        first_agent = make_agent(api, agreement["id"], seniority_rank=1)
        second_agent = make_agent(api, agreement["id"], seniority_rank=2)
        template = make_shift_template(api, cycle["id"], slots_total=2)
        bid_round = make_bid_round(api, cycle["id"])
        assert bid_round["status"] == ROUND_STATUS_DRAFT

        validate_error(
            api.create_shift_bid(
                shift_bid_payload(bid_round["id"], first_agent["id"], [template["id"]]),
                make_agent_headers(first_agent["id"]),
            ),
            ApiErrorId.BID_ROUND_NOT_OPEN,
            409,
        )

        open_round(api, bid_round["id"])
        accepted = validate_success(
            api.create_shift_bid(
                shift_bid_payload(bid_round["id"], first_agent["id"], [template["id"]]),
                make_agent_headers(first_agent["id"]),
            ),
            201,
        )
        assert accepted["status"] == BID_STATUS_SUBMITTED

        assert score_round(api, bid_round["id"])["status"] == ROUND_STATUS_SCORING

        validate_error(
            api.create_shift_bid(
                shift_bid_payload(bid_round["id"], second_agent["id"], [template["id"]]),
                make_agent_headers(second_agent["id"]),
            ),
            ApiErrorId.BID_ROUND_NOT_OPEN,
            409,
        )
        validate_error(
            api.withdraw_shift_bid(
                accepted["id"], make_agent_headers(first_agent["id"])
            ),
            ApiErrorId.BID_ROUND_NOT_OPEN,
            409,
        )

        rows, meta = validate_paginated(
            api.list_shift_bids(SCHEDULER_HEADERS, {"bid_round_id": bid_round["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
        assert rows[0]["status"] == BID_STATUS_SUBMITTED


class TestAdherenceAxisRequiresPublication:
    """The adherence axis is unreachable on a draft or cancelled shift."""

    def test_observations_on_unpublished_shifts_are_refused(self, api):
        """A draft shift and a cancelled shift both refuse the observation and stay pending.

        "Adherence is the second, independent axis of a shift, and it may only be
        traversed while the shift's `publication_status` is `PUBLISHED`; an
        observation or exception aimed at a shift that is not published is refused
        with `ERR_SHIFT_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/errors/adherence_observation_on_unpublished_shift_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        agreement = make_labor_agreement(api)
        agent = make_agent(api, agreement["id"])
        template = make_shift_template(api, cycle["id"], slots_total=2)
        draft_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], "2026-09-07"
        )
        assert_shift_axes(
            draft_shift,
            publication_status=PUBLICATION_DRAFT,
            adherence_status=ADHERENCE_PENDING,
        )
        doomed_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], "2026-09-08"
        )
        cancelled = cancel_shift(api, doomed_shift["id"])
        assert_shift_axes(cancelled, publication_status=PUBLICATION_CANCELLED)

        validate_error(
            api.record_adherence_observation(
                draft_shift["id"], adherence_observation_payload(5400), INTRADAY_HEADERS
            ),
            ApiErrorId.SHIFT_NOT_PUBLISHED,
            409,
        )
        validate_error(
            api.record_adherence_observation(
                doomed_shift["id"], adherence_observation_payload(600), INTRADAY_HEADERS
            ),
            ApiErrorId.SHIFT_NOT_PUBLISHED,
            409,
        )

        after = read_shift(api, draft_shift["id"])
        assert_shift_axes(after, adherence_status=ADHERENCE_PENDING)
        assert_shift_adherence(
            after, out_of_adherence_seconds=0, flagged_by_user_id=None
        )
        assert_agent_coaching(
            read_agent(api, agent["id"]), adherence_pct=1.0000, coaching_flag_count=0
        )


class TestSettlementRequiresCommitment:
    """Settlement is reachable from exactly one allocation status."""

    def test_settling_a_proposed_or_revoked_allocation_bills_nothing(self, api):
        """Both uncommitted statuses refuse settlement and the partner ledgers stay at zero.

        "Settlement is only legal from `COMMITTED`; attempting it from any other
        status is refused with `ERR_ALLOCATION_NOT_COMMITTED` (HTTP 409)."

        Design: Corner/errors/settle_of_uncommitted_allocation_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_partner_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], "2026-09-07")
        partner = make_outsource_partner(
            api,
            rate_per_contact_millicents=10000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        proposed = propose_allocation(api, partner["id"], intervals[0]["id"], 20)
        assert proposed["status"] == ALLOCATION_PROPOSED
        doomed = propose_allocation(api, partner["id"], intervals[0]["id"], 20)
        revoked = revoke_allocation(api, doomed["id"])
        assert revoked["status"] == ALLOCATION_REVOKED

        settler = make_sourcing_headers(SOURCING_ALT_USER_ID)
        validate_error(
            api.settle_partner_allocation(
                proposed["id"], settle_allocation_payload(20), settler
            ),
            ApiErrorId.ALLOCATION_NOT_COMMITTED,
            409,
        )
        validate_error(
            api.settle_partner_allocation(
                doomed["id"], settle_allocation_payload(20), settler
            ),
            ApiErrorId.ALLOCATION_NOT_COMMITTED,
            409,
        )

        untouched = read_allocation(api, proposed["id"])
        assert untouched["status"] == ALLOCATION_PROPOSED
        assert_settlement_fields_null(untouched)

        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=0,
            invoice_total_cents=0,
        )


class TestTerminalExceptionRefusesASecondDecision:
    """An approved exception is terminal on every branch of the fork."""

    def test_a_replayed_decision_never_applies_the_excused_seconds_twice(self, api):
        """Three further decisions and a resubmission are all refused, leaving 2700 excused once.

        "`ERR_EXCEPTION_NOT_PENDING` when a decision targets an exception that is
        not awaiting decision or a resubmission targets one that was not sent back
        for information"

        Design: Corner/errors/second_decision_on_terminal_exception_rejected
        """
        world = build_exception_case(api)
        exception = world["exception"]
        original_narrative = exception["narrative"]

        first = validate_success(
            api.decide_adherence_exception(
                exception["id"],
                exception_decision_payload(DECISION_APPROVE),
                COACH_HEADERS,
            ),
            200,
        )
        assert first["status"] == EXCEPTION_STATUS_APPROVED

        for decision in (DECISION_APPROVE, DECISION_REJECT, DECISION_REQUEST_INFO):
            validate_error(
                api.decide_adherence_exception(
                    exception["id"], exception_decision_payload(decision), COACH_HEADERS
                ),
                ApiErrorId.EXCEPTION_NOT_PENDING,
                409,
            )

        validate_error(
            api.resubmit_adherence_exception(
                exception["id"],
                exception_resubmit_payload(1800),
                make_agent_headers(world["agent"]["id"]),
            ),
            ApiErrorId.EXCEPTION_NOT_PENDING,
            409,
        )

        shift = read_shift(api, world["shift"]["id"])
        assert_shift_adherence(shift, excused_seconds=2700, adherence_pct=0.9000)
        assert_shift_axes(shift, adherence_status=ADHERENCE_EXCUSED)

        stored = read_exception(api, exception["id"])
        assert stored["status"] == EXCEPTION_STATUS_APPROVED
        assert stored["info_requested_count"] == 0
        assert stored["narrative"] == original_narrative


class TestPublicationPostureGate:
    """Publication is gated on the cycle posture, with its own identifier."""

    def test_publishing_from_an_open_cycle_is_refused_then_allowed_once_locked(self, api):
        """The identical publication is refused while the cycle is open and succeeds once locked.

        "Publishing a schedule shift requires the cycle's `posture` to be one of
        `REQUIREMENTS_LOCKED`, `SCHEDULE_PUBLISHED` or `INTRADAY_ALERT`; attempting
        it while the cycle is still `OPEN` (or after it has frozen) is refused with
        `ERR_CYCLE_NOT_LOCKED` (HTTP 409)."

        Design: Corner/errors/publication_before_requirements_lock_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        agreement = make_labor_agreement(api)
        agent = make_agent(api, agreement["id"])
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], "2026-09-07")
        template = make_shift_template(api, cycle["id"])
        shift = make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], "2026-09-07"
        )
        assert_shift_axes(shift, publication_status=PUBLICATION_DRAFT)

        validate_error(
            api.set_shift_publication(
                shift["id"], publication_payload(PUBLICATION_PUBLISHED), SCHEDULER_HEADERS
            ),
            ApiErrorId.CYCLE_NOT_LOCKED,
            409,
        )

        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]), posture=POSTURE_OPEN, total_scheduled_hours=0.00
        )

        locked = lock_requirements(api, cycle["id"])
        assert locked["posture"] == POSTURE_REQUIREMENTS_LOCKED

        published = validate_success(
            api.set_shift_publication(
                shift["id"], publication_payload(PUBLICATION_PUBLISHED), SCHEDULER_HEADERS
            ),
            200,
        )
        assert_shift_axes(published, publication_status=PUBLICATION_PUBLISHED)
        assert_shift_hours(published, paid_hours=7.50)
