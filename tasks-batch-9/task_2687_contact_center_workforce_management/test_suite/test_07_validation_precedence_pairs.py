"""Requests that break two rules at once must report the higher-precedence one."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cycle_ledgers,
    assert_agent_hours,
    assert_instant_equals,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ACTION_STATUS_OFFERED,
    COVERAGE_COVERED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    RESPONSE_ACCEPT,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    build_coverage_week,
    build_ot_offer_week,
    build_published_week,
    freeze_cycle,
    lock_requirements,
    make_agent,
    make_labor_agreement,
    make_schedule_shift,
    make_shift_template,
    make_vto_offer,
    publish_shift,
    read_action,
    read_agent,
    read_cycle,
    read_interval,
    read_shift,
    set_clock,
)
from test_helpers.test_users import SCHEDULER_HEADERS, make_agent_headers


def _error_id(response):
    """The error identifier carried by a refusal envelope."""
    return response.json()["data"]["error_id"]


def _accept(api, action_id, agent_id):
    """Raw acceptance so the refusal itself can be inspected."""
    return api.respond_to_intraday_action(
        action_id,
        f.action_response_payload(RESPONSE_ACCEPT),
        make_agent_headers(agent_id),
    )


class TestFrozenCycleBeatsOvertimeBudget:
    """A frozen cycle is reported before the money is even looked at."""

    def test_the_frozen_gate_is_reported_not_the_budget_ceiling(self, api):
        """Accepting a 14400-cent offer against a 1000-cent budget in a frozen cycle reports the freeze.

        "That order is authentication (`ERR_UNAUTHENTICATED`), then endpoint role
        authorisation (`ERR_UNAUTHORIZED`), then request-body shape
        (`ERR_VALIDATION`, HTTP 422 — required fields present, correct types, enum
        members recognised, numeric ranges and array lengths as specified in
        Section 3), then pagination parameter sanity on list endpoints
        (`ERR_INVALID_PAGINATION`), then path-parameter existence, then body
        foreign-key existence, then `Agent` and `PartnerRep` ownership
        (`ERR_OWNERSHIP_VIOLATION`), then segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`), then the optimistic-concurrency version echo
        (`ERR_STALE_CYCLE_VERSION` or `ERR_STALE_PARTNER_VERSION`), then the
        frozen-cycle gate (`ERR_CYCLE_FROZEN`), then the target resource's own
        state-transition legality, then the cross-entity posture gates
        (`ERR_CYCLE_NOT_LOCKED` or `ERR_CYCLE_NOT_OPEN`), and only then the
        business-safety, temporal, referential, capacity and fiscal rules described
        throughout Section 3."

        Design: Difficulty/priority_pair_validation_conflict/frozen_cycle_beats_ot_budget
        """
        world = build_ot_offer_week(
            api, hours=4.0, cycle_overrides={"ot_budget_cents": 1000}
        )
        freeze_cycle(api, world["cycle"]["id"])

        response = _accept(api, world["action"]["id"], world["agent"]["id"])

        validate_error(response, ApiErrorId.CYCLE_FROZEN.value)

    def test_the_refused_acceptance_leaves_the_offer_unpriced(self, api):
        """The offer stays open with no tier multiplier and no cost.

        "Both `ot_multiplier_applied` and `cost_cents` are frozen on the action at
        acceptance and are never recomputed afterwards."

        Design: Difficulty/priority_pair_validation_conflict/frozen_cycle_beats_ot_budget
        """
        world = build_ot_offer_week(
            api, hours=4.0, cycle_overrides={"ot_budget_cents": 1000}
        )
        freeze_cycle(api, world["cycle"]["id"])

        _accept(api, world["action"]["id"], world["agent"]["id"])

        stored = read_action(api, world["action"]["id"])
        assert stored["status"] == ACTION_STATUS_OFFERED
        assert stored["cost_cents"] == 0
        assert stored["ot_multiplier_applied"] is None

    def test_the_refused_acceptance_leaves_the_ledgers_and_the_shift_alone(self, api):
        """No overtime spend is booked and the shift keeps its 16:00 finish.

        "An accepted overtime offer then extends the shift's `end_at` by `hours`
        and recomputes the shift's `scheduled_seconds`, `ot_hours` and `paid_hours`,
        the agent's `scheduled_hours_committed`, the cycle's `ot_hours_committed`
        (the two-decimal sum of `hours` over the cycle's accepted overtime actions),
        the cycle's `ot_spend_committed_cents` (the integer sum of `cost_cents` over
        the same set) and the cycle's `total_scheduled_hours`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_cycle_beats_ot_budget
        """
        world = build_ot_offer_week(
            api, hours=4.0, cycle_overrides={"ot_budget_cents": 1000}
        )
        freeze_cycle(api, world["cycle"]["id"])

        _accept(api, world["action"]["id"], world["agent"]["id"])

        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            ot_spend_committed_cents=0,
            ot_hours_committed=0.00,
        )
        assert_instant_equals(
            read_shift(api, world["shift"]["id"])["end_at"],
            "2026-09-07T16:00:00Z",
            "end_at",
        )


class TestMinimumRestBeatsSkillMismatch:
    """A labour-safety breach outranks a referential skill breach."""

    def _rest_world(self, api):
        """A published morning shift plus a draft evening shift on a foreign skill."""
        world = build_published_week(api)
        evening_template = make_shift_template(
            api,
            world["cycle"]["id"],
            code="T-MON-EVE",
            skill_code="CHAT_EN",
            start_time_local="20:00",
            duration_minutes=240,
            unpaid_break_minutes=0,
        )
        world["evening_shift"] = make_schedule_shift(
            api,
            world["cycle"]["id"],
            world["agent"]["id"],
            evening_template["id"],
            HORIZON_START,
        )
        return world

    def test_the_rest_breach_is_reported_not_the_skill_breach(self, api):
        """A four-hour rest gap and a foreign skill together report the rest violation.

        "Then the four labour-safety checks against an agent's schedule, in this
        order: minimum rest (`ERR_MIN_REST_VIOLATION`), shift overlap
        (`ERR_SHIFT_OVERLAP`), maximum weekly hours
        (`ERR_MAX_WEEKLY_HOURS_EXCEEDED`) and maximum consecutive days
        (`ERR_MAX_CONSECUTIVE_DAYS_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/min_rest_beats_skill_mismatch
        """
        world = self._rest_world(api)

        response = api.set_shift_publication(
            world["evening_shift"]["id"],
            f.publication_payload(PUBLICATION_PUBLISHED),
            SCHEDULER_HEADERS,
        )

        validate_error(response, ApiErrorId.MIN_REST_VIOLATION.value)

    def test_the_skill_rule_is_the_lower_precedence_of_the_pair(self, api):
        """Skill eligibility sits behind the labour-safety band, so it is not the answer here.

        "Then skill eligibility (`ERR_SKILL_MISMATCH`), then partner eligibility
        (`ERR_PARTNER_NOT_ELIGIBLE`)."

        Design: Difficulty/priority_pair_validation_conflict/min_rest_beats_skill_mismatch
        """
        world = self._rest_world(api)

        response = api.set_shift_publication(
            world["evening_shift"]["id"],
            f.publication_payload(PUBLICATION_PUBLISHED),
            SCHEDULER_HEADERS,
        )

        assert _error_id(response) != ApiErrorId.SKILL_MISMATCH.value

    def test_the_refused_publication_leaves_both_shifts_where_they_were(self, api):
        """The evening shift stays draft, the morning shift stays published, hours stay at 7.50.

        "Every shift carries **two independent state axes on one row**, and the
        observable state of a shift is the pair."

        Design: Difficulty/priority_pair_validation_conflict/min_rest_beats_skill_mismatch
        """
        world = self._rest_world(api)

        api.set_shift_publication(
            world["evening_shift"]["id"],
            f.publication_payload(PUBLICATION_PUBLISHED),
            SCHEDULER_HEADERS,
        )

        assert_shift_axes(
            read_shift(api, world["evening_shift"]["id"]),
            publication_status=PUBLICATION_DRAFT,
        )
        assert_shift_axes(
            read_shift(api, world["shift"]["id"]),
            publication_status=PUBLICATION_PUBLISHED,
        )
        assert_agent_hours(read_agent(api, world["agent"]["id"]), 7.50)
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]), total_scheduled_hours=7.50
        )


class TestVoluntaryTimeOffNoticeBeatsCoverageBreach:
    """The notice period is a temporal rule and outranks coverage protection."""

    def _vto_world(self, api):
        """A covered CHAT_EN day carrying a seven-hour release offer, eight hours before the shift."""
        world = build_coverage_week(api, cycle_overrides={"name": "W37-VTO"})
        agreement = make_labor_agreement(api)
        agent = make_agent(api, agreement["id"], skills=["CHAT_EN"])
        template = make_shift_template(
            api, world["cycle"]["id"], code="T-CHAT-MON", skill_code="CHAT_EN"
        )
        shift = make_schedule_shift(
            api, world["cycle"]["id"], agent["id"], template["id"], HORIZON_START
        )
        lock_requirements(api, world["cycle"]["id"])
        shift = publish_shift(api, shift["id"])
        action = make_vto_offer(
            api,
            world["cycle"]["id"],
            agent["id"],
            shift["id"],
            hours=7.0,
            expires_at="2026-09-08T00:00:00Z",
        )
        set_clock(api, "2026-09-07T00:00:00Z")
        world.update({"agent": agent, "shift": shift, "action": action})
        return world

    def test_the_notice_shortfall_is_reported_not_the_coverage_breach(self, api):
        """Eight hours of notice against a twelve-hour floor reports the notice failure.

        "Then the voluntary-time-off notice period (`ERR_VTO_NOTICE_TOO_SHORT`)."

        Design: Difficulty/priority_pair_validation_conflict/vto_notice_beats_coverage_breach
        """
        world = self._vto_world(api)

        response = _accept(api, world["action"]["id"], world["agent"]["id"])

        validate_error(response, ApiErrorId.VTO_NOTICE_TOO_SHORT.value)

    def test_the_coverage_rule_is_the_lower_precedence_of_the_pair(self, api):
        """Coverage protection sits in the capacity band, so it is not the answer here.

        "Then the capacity-conservation checks: coverage protection on a
        voluntary-time-off acceptance (`ERR_VTO_WOULD_BREACH_COVERAGE`), routing
        outflow against staffed agents (`ERR_ROUTING_OUTFLOW_EXCEEDS_STAFFING`),
        interval allocation capacity (`ERR_ALLOCATION_CAPACITY_EXCEEDED`) and
        partner volume bounds (`ERR_PARTNER_VOLUME_OUT_OF_RANGE`)."

        Design: Difficulty/priority_pair_validation_conflict/vto_notice_beats_coverage_breach
        """
        world = self._vto_world(api)

        response = _accept(api, world["action"]["id"], world["agent"]["id"])

        assert _error_id(response) != ApiErrorId.VTO_WOULD_BREACH_COVERAGE.value

    def test_the_refused_release_moves_neither_the_shift_nor_the_coverage(self, api):
        """The shift keeps its full span and every interval stays covered.

        "An accepted voluntary-time-off offer instead shortens `end_at` by `hours`
        and recomputes the shift's `scheduled_seconds`, `vto_hours` and
        `paid_hours`, the agent's `scheduled_hours_committed` and the cycle's
        `total_scheduled_hours`."

        Design: Difficulty/priority_pair_validation_conflict/vto_notice_beats_coverage_breach
        """
        world = self._vto_world(api)

        _accept(api, world["action"]["id"], world["agent"]["id"])

        assert read_action(api, world["action"]["id"])["status"] == ACTION_STATUS_OFFERED
        shift = read_shift(api, world["shift"]["id"])
        assert_instant_equals(shift["end_at"], "2026-09-07T16:00:00Z", "end_at")
        assert_shift_hours(shift, vto_hours=0.00, paid_hours=7.50)
        for interval in world["intervals"][2:]:
            assert (
                read_interval(api, interval["id"])["coverage_state"] == COVERAGE_COVERED
            )
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]), short_interval_count=0
        )
