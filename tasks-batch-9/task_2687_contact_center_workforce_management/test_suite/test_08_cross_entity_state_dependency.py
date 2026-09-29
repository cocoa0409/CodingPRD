"""Outcomes that hinge on the state of a neighbouring entity, not on the request."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_hours,
    assert_cents,
    assert_cycle_ledgers,
    assert_instant_equals,
    assert_ratio,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ACTION_STATUS_ACCEPTED,
    ACTION_STATUS_OFFERED,
    POSTURE_OPEN,
    POSTURE_REQUIREMENTS_LOCKED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    RESPONSE_ACCEPT,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    build_canonical_week,
    generate_grid,
    lock_requirements,
    make_agent,
    make_forecast_group,
    make_labor_agreement,
    make_ot_offer,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    publish_shift,
    read_action,
    read_agent,
    read_cycle,
    read_shift,
    respond_to_action,
    set_clock,
)
from test_helpers.test_users import SCHEDULER_HEADERS, make_agent_headers


def _publish(api, schedule_shift_id):
    """Raw publication attempt so a refusal can be inspected."""
    return api.set_shift_publication(
        schedule_shift_id,
        f.publication_payload(PUBLICATION_PUBLISHED),
        SCHEDULER_HEADERS,
    )


def _accept(api, action_id, agent_id):
    """Raw acceptance so a refusal can be inspected."""
    return api.respond_to_intraday_action(
        action_id,
        f.action_response_payload(RESPONSE_ACCEPT),
        make_agent_headers(agent_id),
    )


class TestShiftPublicationRequiresCycleRequirementsLocked:
    """The same publication request is illegal or legal purely by the cycle's posture."""

    def test_a_fresh_cycle_starts_open_so_the_gate_is_shut(self, api):
        """The cycle the shift belongs to is created at OPEN.

        "A freshly created cycle is initialised with `posture` at `OPEN`,
        `version` at 1, `reforecast_generation` at 0, and every derived aggregate
        at its zero value: `short_interval_count`, `total_scheduled_hours`,
        `ot_spend_committed_cents`, `ot_hours_committed`, `headcount_active` and
        `pipeline_fte` all read zero, while `requirements_locked_at` and
        `published_at` are null."

        Design: Difficulty/cross_entity_state_dependency/shift_publication_requires_cycle_requirements_locked
        """
        world = build_canonical_week(api, cycle_overrides={"name": "W37-GATE"})

        assert_cycle_ledgers(
            world["cycle"],
            posture=POSTURE_OPEN,
            total_scheduled_hours=0.00,
            headcount_active=0,
        )
        assert world["cycle"]["requirements_locked_at"] is None

    def test_publishing_while_the_cycle_is_open_is_refused(self, api):
        """The publication is refused for the neighbouring cycle's posture, not for the shift.

        "The cycle's `posture` must be `REQUIREMENTS_LOCKED`,
        `SCHEDULE_PUBLISHED` or `INTRADAY_ALERT`, otherwise
        `ERR_CYCLE_NOT_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/shift_publication_requires_cycle_requirements_locked
        """
        world = build_canonical_week(api, cycle_overrides={"name": "W37-GATE"})

        response = _publish(api, world["shift"]["id"])

        validate_error(response, ApiErrorId.CYCLE_NOT_LOCKED.value)

    def test_the_refused_publication_leaves_the_shift_and_the_ledgers_alone(self, api):
        """The shift stays draft and nothing downstream of a publication moves.

        "The agent's `scheduled_hours_committed` — the sum of `paid_hours` over
        that agent's shifts whose `publication_status` is `PUBLISHED`, at two
        decimal places — and the cycle's `total_scheduled_hours` are both
        recomputed."

        Design: Difficulty/cross_entity_state_dependency/shift_publication_requires_cycle_requirements_locked
        """
        world = build_canonical_week(api, cycle_overrides={"name": "W37-GATE"})

        _publish(api, world["shift"]["id"])

        assert_shift_axes(
            read_shift(api, world["shift"]["id"]),
            publication_status=PUBLICATION_DRAFT,
        )
        assert_agent_hours(read_agent(api, world["agent"]["id"]), 0.00)
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]), total_scheduled_hours=0.00
        )

    def test_the_identical_request_succeeds_once_requirements_are_locked(self, api):
        """Locking the cycle is what makes the unchanged publication legal.

        "Locking requirements moves `OPEN → REQUIREMENTS_LOCKED` and is the act
        that makes schedule publication legal; it is refused unless at least one
        forecast group of the cycle has an `interval_count` of 1 or more, meaning
        some demand grid actually exists to lock."

        Design: Difficulty/cross_entity_state_dependency/shift_publication_requires_cycle_requirements_locked
        """
        world = build_canonical_week(api, cycle_overrides={"name": "W37-GATE"})
        _publish(api, world["shift"]["id"])

        locked = lock_requirements(api, world["cycle"]["id"])
        published = validate_success(_publish(api, world["shift"]["id"]), 200)

        assert_cycle_ledgers(locked, posture=POSTURE_REQUIREMENTS_LOCKED)
        assert locked["requirements_locked_at"] is not None
        assert_shift_axes(published, publication_status=PUBLICATION_PUBLISHED)

    def test_only_the_successful_publication_moves_the_workforce_aggregates(self, api):
        """The second attempt is what carries 7.50 hours and one active head into the cycle.

        "And the cycle's `headcount_active` is recomputed, because a draft or
        published shift is one of the two ways an agent enters the cycle's
        headcount."

        Design: Difficulty/cross_entity_state_dependency/shift_publication_requires_cycle_requirements_locked
        """
        world = build_canonical_week(api, cycle_overrides={"name": "W37-GATE"})
        _publish(api, world["shift"]["id"])
        lock_requirements(api, world["cycle"]["id"])

        validate_success(_publish(api, world["shift"]["id"]), 200)

        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            posture=POSTURE_REQUIREMENTS_LOCKED,
            total_scheduled_hours=7.50,
            headcount_active=1,
        )
        assert_agent_hours(read_agent(api, world["agent"]["id"]), 7.50)


def _paired_agreement_week(api):
    """One locked cycle, two published 7.50-hour shifts, two agreements, two 1.0-hour offers."""
    set_clock(api, CANONICAL_CLOCK)
    tight = make_labor_agreement(api, code="LA-TIGHT", max_weekly_hours=8.0)
    core = make_labor_agreement(api, code="LA-CORE", max_weekly_hours=45.0)
    cycle = make_planning_cycle(api, name="W37-CAP")
    group = make_forecast_group(api, cycle["id"])
    generate_grid(api, group["id"], HORIZON_START)
    tight_agent = make_agent(
        api,
        tight["id"],
        employee_code="E-TIGHT",
        full_name="Tight Agent",
        seniority_rank=1,
        weekly_contracted_hours=8.0,
        hourly_rate_cents=2400,
    )
    core_agent = make_agent(
        api,
        core["id"],
        employee_code="E-CORE",
        full_name="Core Agent",
        seniority_rank=2,
        weekly_contracted_hours=37.5,
        hourly_rate_cents=2400,
    )
    template = make_shift_template(api, cycle["id"], code="T-MON-AM", slots_total=2)
    shifts = {}
    for label, agent in (("tight", tight_agent), ("core", core_agent)):
        shifts[label] = make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], HORIZON_START
        )
    lock_requirements(api, cycle["id"])
    actions = {}
    for label, agent in (("tight", tight_agent), ("core", core_agent)):
        shifts[label] = publish_shift(api, shifts[label]["id"])
        actions[label] = make_ot_offer(
            api,
            cycle["id"],
            agent["id"],
            shifts[label]["id"],
            group["id"],
            hours=1.0,
            expires_at="2026-09-30T00:00:00Z",
        )
    return {
        "cycle": cycle,
        "group": group,
        "tight_agreement": tight,
        "core_agreement": core,
        "tight_agent": tight_agent,
        "core_agent": core_agent,
        "shifts": shifts,
        "actions": actions,
    }


class TestOvertimeAcceptanceBoundedByAgreementWeeklyCeiling:
    """The ceiling lives on a third entity, so identical offers diverge by agreement."""

    def test_the_tight_agreement_refuses_the_extra_hour(self, api):
        """A 7.50-hour commitment plus one overtime hour breaks an 8.0-hour ceiling.

        "For an overtime offer it additionally requires that the cycle's overtime
        budget holds and that extending the shift keeps the agent's rest gap at or
        above the agreement's `min_rest_hours` and the agent's weekly committed
        total at or below the agreement's `max_weekly_hours` — the same three
        labour rules as publication apply here in the same relative order, so a
        rest breach surfaces as `ERR_MIN_REST_VIOLATION`, an overlap created by the
        extension surfaces as `ERR_SHIFT_OVERLAP`, and an hours breach surfaces as
        `ERR_MAX_WEEKLY_HOURS_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/ot_accept_bounded_by_labor_agreement_max_weekly
        """
        world = _paired_agreement_week(api)

        response = _accept(
            api, world["actions"]["tight"]["id"], world["tight_agent"]["id"]
        )

        validate_error(response, ApiErrorId.MAX_WEEKLY_HOURS_EXCEEDED.value)

    def test_the_refused_acceptance_prices_nothing_and_extends_nothing(self, api):
        """The offer stays open, unpriced, and the shift keeps its 16:00 finish.

        "The **weekly-hours rule** requires that the agent's
        `scheduled_hours_committed` plus this shift's `paid_hours` does not exceed
        the agreement's `max_weekly_hours`; a breach is refused with
        `ERR_MAX_WEEKLY_HOURS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/ot_accept_bounded_by_labor_agreement_max_weekly
        """
        world = _paired_agreement_week(api)

        _accept(api, world["actions"]["tight"]["id"], world["tight_agent"]["id"])

        stored = read_action(api, world["actions"]["tight"]["id"])
        assert stored["status"] == ACTION_STATUS_OFFERED
        assert_cents(stored["cost_cents"], 0, "cost_cents")
        shift = read_shift(api, world["shifts"]["tight"]["id"])
        assert_instant_equals(shift["end_at"], "2026-09-07T16:00:00Z", "end_at")
        assert_shift_hours(shift, ot_hours=0.00)
        assert_agent_hours(read_agent(api, world["tight_agent"]["id"]), 7.50)

    def test_the_roomier_agreement_accepts_the_same_hour_at_the_first_tier(self, api):
        """Under a 45.0-hour ceiling the identical acceptance books 3600 cents at 1.50.

        "The action's `ot_multiplier_applied` is stored as that tier multiplier
        multiplied by the agreement's `ot_premium_multiplier`, and `cost_cents` is
        the offer's `hours` multiplied by the agent's `hourly_rate_cents`,
        multiplied by the tier multiplier, multiplied by the agreement's
        `ot_premium_multiplier`, rounded half up to a whole cent."

        Design: Difficulty/cross_entity_state_dependency/ot_accept_bounded_by_labor_agreement_max_weekly
        """
        world = _paired_agreement_week(api)

        accepted = respond_to_action(
            api, world["actions"]["core"]["id"], world["core_agent"]["id"]
        )

        assert accepted["status"] == ACTION_STATUS_ACCEPTED
        assert_ratio(
            accepted["ot_multiplier_applied"], 1.50, "ot_multiplier_applied"
        )
        assert_cents(accepted["cost_cents"], 3600, "cost_cents")

    def test_only_the_permitted_acceptance_books_hours_and_spend(self, api):
        """The accepted hour lands on the agent and on both cycle overtime ledgers.

        "An accepted overtime offer then extends the shift's `end_at` by `hours`
        and recomputes the shift's `scheduled_seconds`, `ot_hours` and `paid_hours`,
        the agent's `scheduled_hours_committed`, the cycle's `ot_hours_committed`
        (the two-decimal sum of `hours` over the cycle's accepted overtime actions),
        the cycle's `ot_spend_committed_cents` (the integer sum of `cost_cents` over
        the same set) and the cycle's `total_scheduled_hours`."

        Design: Difficulty/cross_entity_state_dependency/ot_accept_bounded_by_labor_agreement_max_weekly
        """
        world = _paired_agreement_week(api)
        _accept(api, world["actions"]["tight"]["id"], world["tight_agent"]["id"])

        respond_to_action(
            api, world["actions"]["core"]["id"], world["core_agent"]["id"]
        )

        assert_agent_hours(read_agent(api, world["core_agent"]["id"]), 8.50)
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            ot_spend_committed_cents=3600,
            ot_hours_committed=1.00,
        )
