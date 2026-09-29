"""Composite scenario builders and pytest fixtures.

Two layers live here.

The lower layer is plain helper functions — ``make_planning_cycle``,
``publish_shift``, ``commit_allocation`` and friends.  Each performs one API
call with the correct acting role, validates leniently with
``get_success_data`` so a broken setup step fails loudly, accepts
``**overrides`` so a caller can bend one field, and returns the resource dict.

The upper layer is pytest fixtures that chain those helpers into the scenarios
the suite reuses: the canonical planning week, the partner-outsourcing week, the
small four-interval coverage week, the overtime chain, the voluntary-time-off
chain, the bidding chain, the adherence chain and the hiring pipeline.

Every fixture is function-scoped: the harness restarts the service before each
test, so each test begins against an empty database and builds its own world.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import api_client
from .constants import (
    ACTION_KIND_OT_OFFER,
    ADHERENCE_OUT_OF_ADHERENCE,
    BID_STATUS_SUBMITTED,
    CLASS_STATUS_CHARTERED,
    CLASS_STATUS_IN_TRAINING,
    DECISION_APPROVE,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_REQUIREMENTS_LOCKED,
    POSTURE_SCHEDULE_PUBLISHED,
    PUBLICATION_CANCELLED,
    PUBLICATION_PUBLISHED,
    RESPONSE_ACCEPT,
    ROUND_STATUS_OPEN,
    ROUND_STATUS_SCORING,
)
from .test_users import (
    ANALYST_HEADERS,
    COACH_HEADERS,
    INTRADAY_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_ALT_USER_ID,
    SOURCING_HEADERS,
    make_agent_headers,
    make_sourcing_headers,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"
HORIZON_START = "2026-09-07"
HORIZON_END = "2026-09-13"


# ─── Tier 0: read-back helpers ────────────────────────

def read_cycle(api, planning_cycle_id, headers=PLANNER_HEADERS):
    """Read one planning cycle with every derived aggregate."""
    return validate_success(api.get_planning_cycle(planning_cycle_id, headers))


def read_agreement(api, labor_agreement_id, headers=PLANNER_HEADERS):
    """Read one labour agreement."""
    return validate_success(api.get_labor_agreement(labor_agreement_id, headers))


def read_group(api, forecast_group_id, headers=ANALYST_HEADERS):
    """Read one forecast group."""
    return validate_success(api.get_forecast_group(forecast_group_id, headers))


def read_interval(api, interval_plan_id, headers=ANALYST_HEADERS):
    """Read one interval plan."""
    return validate_success(api.get_interval_plan(interval_plan_id, headers))


def read_agent(api, agent_id, headers=SCHEDULER_HEADERS):
    """Read one agent including the adherence and coaching rollups."""
    return validate_success(api.get_agent(agent_id, headers))


def read_template(api, shift_template_id, headers=SCHEDULER_HEADERS):
    """Read one shift template."""
    return validate_success(api.get_shift_template(shift_template_id, headers))


def read_round(api, bid_round_id, headers=SCHEDULER_HEADERS):
    """Read one bid round."""
    return validate_success(api.get_bid_round(bid_round_id, headers))


def read_bid(api, shift_bid_id, headers=SCHEDULER_HEADERS):
    """Read one bid."""
    return validate_success(api.get_shift_bid(shift_bid_id, headers))


def read_shift(api, schedule_shift_id, headers=SCHEDULER_HEADERS):
    """Read one shift with both state axes."""
    return validate_success(api.get_schedule_shift(schedule_shift_id, headers))


def read_exception(api, adherence_exception_id, headers=COACH_HEADERS):
    """Read one adherence exception request."""
    return validate_success(
        api.get_adherence_exception(adherence_exception_id, headers)
    )


def read_action(api, intraday_action_id, headers=INTRADAY_HEADERS):
    """Read one intraday action including its frozen cost."""
    return validate_success(api.get_intraday_action(intraday_action_id, headers))


def read_partner(api, outsource_partner_id, headers=SOURCING_HEADERS):
    """Read one outsourced partner including its ledgers."""
    return validate_success(
        api.get_outsource_partner(outsource_partner_id, headers)
    )


def read_allocation(api, partner_allocation_id, headers=SOURCING_HEADERS):
    """Read one partner allocation including both settlement variants."""
    return validate_success(
        api.get_partner_allocation(partner_allocation_id, headers)
    )


def read_hiring_class(api, hiring_class_id, headers=PLANNER_HEADERS):
    """Read one hiring class including its ramp."""
    return validate_success(api.get_hiring_class(hiring_class_id, headers))


def read_coverage_summary(api, planning_cycle_id, headers=PLANNER_HEADERS, params=None):
    """Read the cycle-wide coverage and outsourcing rollup."""
    return validate_success(
        api.get_coverage_summary(planning_cycle_id, headers, params)
    )


# ─── Tier 1: single-entity builders ───────────────────

def set_clock(api, to_iso8601, headers=PLANNER_HEADERS):
    """Move the logical clock and return the clock response."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), headers))


def make_labor_agreement(api, headers=PLANNER_HEADERS, **overrides):
    """Register a labour agreement carrying every safety ceiling."""
    return get_success_data(
        api.create_labor_agreement(f.labor_agreement_payload(**overrides), headers)
    )


def make_planning_cycle(api, headers=PLANNER_HEADERS, **overrides):
    """Open a planning cycle over one Monday-to-Sunday horizon."""
    return get_success_data(
        api.create_planning_cycle(f.planning_cycle_payload(**overrides), headers)
    )


def make_forecast_group(api, planning_cycle_id, headers=ANALYST_HEADERS, **overrides):
    """Create the canonical VOICE / VOICE_EN demand group."""
    return get_success_data(
        api.create_forecast_group(
            f.forecast_group_payload(planning_cycle_id, **overrides), headers
        )
    )


def make_partner_forecast_group(
    api, planning_cycle_id, headers=ANALYST_HEADERS, **overrides
):
    """Create the CHAT / CHAT_EN group whose intervals need outsourcing."""
    return get_success_data(
        api.create_forecast_group(
            f.partner_forecast_group_payload(planning_cycle_id, **overrides), headers
        )
    )


def make_coverage_forecast_group(
    api, planning_cycle_id, headers=ANALYST_HEADERS, **overrides
):
    """Create the small CHAT / CHAT_EN group of four one-agent intervals."""
    return get_success_data(
        api.create_forecast_group(
            f.coverage_forecast_group_payload(planning_cycle_id, **overrides), headers
        )
    )


def generate_grid(
    api, forecast_group_id, service_date=HORIZON_START, headers=ANALYST_HEADERS, **overrides
):
    """Generate one service date's interval grid and return the rows."""
    return get_success_data(
        api.generate_interval_plans(
            forecast_group_id, f.interval_grid_payload(service_date, **overrides), headers
        )
    )


def make_agent(api, labor_agreement_id, headers=SCHEDULER_HEADERS, **overrides):
    """Register one agent under a labour agreement."""
    return get_success_data(
        api.create_agent(f.agent_payload(labor_agreement_id, **overrides), headers)
    )


def make_shift_template(api, planning_cycle_id, headers=SCHEDULER_HEADERS, **overrides):
    """Define one biddable shift pattern inside a cycle."""
    return get_success_data(
        api.create_shift_template(
            f.shift_template_payload(planning_cycle_id, **overrides), headers
        )
    )


def make_schedule_shift(
    api,
    planning_cycle_id,
    agent_id,
    shift_template_id,
    service_date=HORIZON_START,
    headers=SCHEDULER_HEADERS,
    **overrides,
):
    """Create one draft shift directly."""
    return get_success_data(
        api.create_schedule_shift(
            f.schedule_shift_payload(
                planning_cycle_id, agent_id, shift_template_id, service_date, **overrides
            ),
            headers,
        )
    )


def make_outsource_partner(api, headers=SOURCING_HEADERS, **overrides):
    """Register one outsourced partner."""
    return get_success_data(
        api.create_outsource_partner(f.outsource_partner_payload(**overrides), headers)
    )


def make_hiring_class(
    api, planning_cycle_id, labor_agreement_id, headers=PLANNER_HEADERS, **overrides
):
    """Plan one hiring class with its training and nesting ramp."""
    return get_success_data(
        api.create_hiring_class(
            f.hiring_class_payload(planning_cycle_id, labor_agreement_id, **overrides),
            headers,
        )
    )


def make_bid_round(api, planning_cycle_id, headers=SCHEDULER_HEADERS, **overrides):
    """Open one bidding round against a cycle."""
    return get_success_data(
        api.create_bid_round(f.bid_round_payload(planning_cycle_id, **overrides), headers)
    )


def make_marketing_event(
    api, planning_cycle_id, forecast_group_id=None, headers=ANALYST_HEADERS, **overrides
):
    """Register one marketing driver against a cycle."""
    return get_success_data(
        api.create_marketing_event(
            f.marketing_event_payload(planning_cycle_id, forecast_group_id, **overrides),
            headers,
        )
    )


# ─── Tier 2: transition helpers ───────────────────────

def set_posture(api, planning_cycle_id, target_posture, headers=PLANNER_HEADERS):
    """Drive the cycle posture state machine."""
    return get_success_data(
        api.set_cycle_posture(
            planning_cycle_id, f.posture_payload(target_posture), headers
        )
    )


def lock_requirements(api, planning_cycle_id, headers=PLANNER_HEADERS):
    """Move the cycle from open to requirements-locked."""
    return set_posture(api, planning_cycle_id, POSTURE_REQUIREMENTS_LOCKED, headers)


def revert_to_open(api, planning_cycle_id, headers=PLANNER_HEADERS):
    """Reopen forecasting after a requirements review."""
    return set_posture(api, planning_cycle_id, POSTURE_OPEN, headers)


def declare_schedule_published(api, planning_cycle_id, headers=SCHEDULER_HEADERS):
    """Declare the schedule live."""
    return set_posture(api, planning_cycle_id, POSTURE_SCHEDULE_PUBLISHED, headers)


def freeze_cycle(api, planning_cycle_id, headers=PLANNER_HEADERS):
    """Freeze the cycle irreversibly."""
    return set_posture(api, planning_cycle_id, POSTURE_FROZEN, headers)


def publish_shift(api, schedule_shift_id, headers=SCHEDULER_HEADERS):
    """Move one shift from draft to published."""
    return get_success_data(
        api.set_shift_publication(
            schedule_shift_id, f.publication_payload(PUBLICATION_PUBLISHED), headers
        )
    )


def cancel_shift(api, schedule_shift_id, headers=SCHEDULER_HEADERS):
    """Move one shift to the terminal cancelled publication state."""
    return get_success_data(
        api.set_shift_publication(
            schedule_shift_id, f.publication_payload(PUBLICATION_CANCELLED), headers
        )
    )


def post_actuals(
    api, interval_plan_id, actual_volume, actual_aht_seconds, headers=INTRADAY_HEADERS
):
    """Post observed volume and handle time against one interval."""
    return get_success_data(
        api.post_actuals(
            interval_plan_id,
            f.actuals_payload(actual_volume, actual_aht_seconds),
            headers,
        )
    )


def run_reforecast(
    api,
    planning_cycle_id,
    expected_cycle_version,
    effective_from_interval_start,
    headers=ANALYST_HEADERS,
    **overrides,
):
    """Replay posted actuals and re-forecast the forward window."""
    return get_success_data(
        api.reforecast(
            planning_cycle_id,
            f.reforecast_payload(
                expected_cycle_version, effective_from_interval_start, **overrides
            ),
            headers,
        )
    )


def set_event_status(api, marketing_event_id, target_status, headers=ANALYST_HEADERS):
    """Drive the marketing-event lifecycle."""
    return get_success_data(
        api.set_marketing_event_status(
            marketing_event_id, f.marketing_event_status_payload(target_status), headers
        )
    )


def record_observation(
    api, schedule_shift_id, out_of_adherence_seconds, headers=INTRADAY_HEADERS
):
    """Record one adherence observation, replacing the stored seconds."""
    return get_success_data(
        api.record_adherence_observation(
            schedule_shift_id,
            f.adherence_observation_payload(out_of_adherence_seconds),
            headers,
        )
    )


def file_exception(api, schedule_shift_id, agent_id, duration_seconds, **overrides):
    """File the acting agent's own exception against their flagged shift."""
    return get_success_data(
        api.create_adherence_exception(
            f.adherence_exception_payload(
                schedule_shift_id, agent_id, duration_seconds, **overrides
            ),
            make_agent_headers(agent_id),
        )
    )


def decide_exception(
    api, adherence_exception_id, decision=DECISION_APPROVE, headers=COACH_HEADERS, **overrides
):
    """Record the coach's branching decision on one exception."""
    return get_success_data(
        api.decide_adherence_exception(
            adherence_exception_id,
            f.exception_decision_payload(decision, **overrides),
            headers,
        )
    )


def resubmit_exception(api, adherence_exception_id, agent_id, duration_seconds, **overrides):
    """Return an exception awaiting information to submitted status."""
    return get_success_data(
        api.resubmit_adherence_exception(
            adherence_exception_id,
            f.exception_resubmit_payload(duration_seconds, **overrides),
            make_agent_headers(agent_id),
        )
    )


def make_ot_offer(
    api,
    planning_cycle_id,
    agent_id,
    schedule_shift_id,
    target_forecast_group_id,
    hours=4.0,
    headers=INTRADAY_HEADERS,
    **overrides,
):
    """Create an overtime offer to one agent."""
    return get_success_data(
        api.create_intraday_action(
            f.ot_offer_payload(
                planning_cycle_id,
                agent_id,
                schedule_shift_id,
                target_forecast_group_id,
                hours=hours,
                **overrides,
            ),
            headers,
        )
    )


def make_vto_offer(
    api,
    planning_cycle_id,
    agent_id,
    schedule_shift_id,
    hours=1.0,
    headers=INTRADAY_HEADERS,
    **overrides,
):
    """Create a voluntary-time-off offer to one agent."""
    return get_success_data(
        api.create_intraday_action(
            f.vto_offer_payload(
                planning_cycle_id, agent_id, schedule_shift_id, hours=hours, **overrides
            ),
            headers,
        )
    )


def make_routing_adjustment(
    api,
    planning_cycle_id,
    source_forecast_group_id,
    target_forecast_group_id,
    interval_start,
    agents_shifted=1,
    headers=INTRADAY_HEADERS,
    **overrides,
):
    """Create a routing adjustment, which auto-accepts inside its own request."""
    return get_success_data(
        api.create_intraday_action(
            f.routing_adjustment_payload(
                planning_cycle_id,
                source_forecast_group_id,
                target_forecast_group_id,
                interval_start,
                agents_shifted=agents_shifted,
                **overrides,
            ),
            headers,
        )
    )


def respond_to_action(api, intraday_action_id, agent_id, response=RESPONSE_ACCEPT):
    """The offered agent accepts or declines their own offer."""
    return get_success_data(
        api.respond_to_intraday_action(
            intraday_action_id,
            f.action_response_payload(response),
            make_agent_headers(agent_id),
        )
    )


def revoke_action(api, intraday_action_id, headers=INTRADAY_HEADERS):
    """Revoke an offered or accepted intraday action."""
    return get_success_data(api.revoke_intraday_action(intraday_action_id, headers))


def file_performance_report(
    api, outsource_partner_id, sl_attainment_pct, headers=SOURCING_HEADERS, **overrides
):
    """Append one service-level attainment report to a partner."""
    return get_success_data(
        api.create_performance_report(
            outsource_partner_id,
            f.performance_report_payload(sl_attainment_pct, **overrides),
            headers,
        )
    )


def propose_allocation(
    api,
    outsource_partner_id,
    interval_plan_id,
    allocated_volume,
    headers=SOURCING_HEADERS,
    **overrides,
):
    """Propose one allocation against one interval plan."""
    return get_success_data(
        api.create_partner_allocation(
            f.partner_allocation_payload(
                outsource_partner_id, interval_plan_id, allocated_volume, **overrides
            ),
            headers,
        )
    )


def generate_allocations(api, interval_plan_id, headers=SOURCING_HEADERS):
    """Run the cheapest-first allocation waterfall for one interval."""
    return get_success_data(
        api.generate_partner_allocations(
            f.generate_allocations_payload(interval_plan_id), headers
        )
    )


def commit_allocation(
    api,
    partner_allocation_id,
    expected_partner_version,
    headers=None,
):
    """Commit a proposed allocation as an operator other than the proposer."""
    actor = headers or make_sourcing_headers(SOURCING_ALT_USER_ID)
    return get_success_data(
        api.commit_partner_allocation(
            partner_allocation_id,
            f.commit_allocation_payload(expected_partner_version),
            actor,
        )
    )


def revoke_allocation(api, partner_allocation_id, headers=SOURCING_HEADERS):
    """Revoke a proposed or committed allocation."""
    return get_success_data(api.revoke_partner_allocation(partner_allocation_id, headers))


def settle_allocation(
    api, partner_allocation_id, delivered_volume, headers=SOURCING_HEADERS
):
    """Settle a committed allocation with the delivered volume."""
    return get_success_data(
        api.settle_partner_allocation(
            partner_allocation_id, f.settle_allocation_payload(delivered_volume), headers
        )
    )


def set_round_status(api, bid_round_id, target_status, headers=SCHEDULER_HEADERS):
    """Drive the bid-round lifecycle."""
    return get_success_data(
        api.set_bid_round_status(
            bid_round_id, f.bid_round_status_payload(target_status), headers
        )
    )


def open_round(api, bid_round_id, headers=SCHEDULER_HEADERS):
    """Move a round to open so bids may arrive."""
    return set_round_status(api, bid_round_id, ROUND_STATUS_OPEN, headers)


def score_round(api, bid_round_id, headers=SCHEDULER_HEADERS):
    """Close intake by moving a round to scoring."""
    return set_round_status(api, bid_round_id, ROUND_STATUS_SCORING, headers)


def award_round(api, bid_round_id, headers=SCHEDULER_HEADERS):
    """Run the seniority-ordered award allocator."""
    return get_success_data(api.award_bid_round(bid_round_id, headers))


def make_shift_bid(api, bid_round_id, agent_id, preference_template_ids):
    """Submit one agent's ranked preference list into an open round."""
    return get_success_data(
        api.create_shift_bid(
            f.shift_bid_payload(bid_round_id, agent_id, preference_template_ids),
            make_agent_headers(agent_id),
        )
    )


def withdraw_bid(api, shift_bid_id, agent_id):
    """Withdraw the acting agent's own bid while the round is open."""
    return get_success_data(
        api.withdraw_shift_bid(shift_bid_id, make_agent_headers(agent_id))
    )


def set_class_status(api, hiring_class_id, target_status, headers=PLANNER_HEADERS):
    """Drive the hiring-class lifecycle short of graduation."""
    return get_success_data(
        api.set_hiring_class_status(
            hiring_class_id, f.hiring_class_status_payload(target_status), headers
        )
    )


def charter_class(api, hiring_class_id, headers=PLANNER_HEADERS):
    """Put a planned cohort into the pipeline."""
    return set_class_status(api, hiring_class_id, CLASS_STATUS_CHARTERED, headers)


def start_training(api, hiring_class_id, headers=PLANNER_HEADERS):
    """Move a chartered cohort into training."""
    return set_class_status(api, hiring_class_id, CLASS_STATUS_IN_TRAINING, headers)


def graduate_class(api, hiring_class_id, headers=PLANNER_HEADERS):
    """Graduate a class in training, minting its expected agents."""
    return get_success_data(api.graduate_hiring_class(hiring_class_id, headers))


# ─── Tier 3: composite scenario builders ──────────────

def build_canonical_week(
    api,
    clock=CANONICAL_CLOCK,
    agreement_overrides=None,
    cycle_overrides=None,
    group_overrides=None,
    agent_overrides=None,
    template_overrides=None,
    service_date=HORIZON_START,
):
    """The canonical planning week: agreement, cycle, demand grid, roster and one draft shift.

    Leaves the cycle in ``OPEN`` and the shift in ``DRAFT`` so a caller can
    exercise the posture gate and the publication guards itself.
    """
    set_clock(api, clock)
    agreement = make_labor_agreement(api, **(agreement_overrides or {}))
    cycle = make_planning_cycle(api, **(cycle_overrides or {}))
    group = make_forecast_group(api, cycle["id"], **(group_overrides or {}))
    intervals = generate_grid(api, group["id"], service_date)
    agent = make_agent(api, agreement["id"], **(agent_overrides or {}))
    template = make_shift_template(api, cycle["id"], **(template_overrides or {}))
    shift = make_schedule_shift(
        api, cycle["id"], agent["id"], template["id"], service_date
    )
    return {
        "agreement": agreement,
        "cycle": cycle,
        "group": group,
        "intervals": intervals,
        "agent": agent,
        "template": template,
        "shift": shift,
        "agent_headers": make_agent_headers(agent["id"]),
    }


def build_published_week(api, **kwargs):
    """The canonical week advanced to a locked cycle with the shift published."""
    world = build_canonical_week(api, **kwargs)
    lock_requirements(api, world["cycle"]["id"])
    world["shift"] = publish_shift(api, world["shift"]["id"])
    world["cycle"] = read_cycle(api, world["cycle"]["id"])
    return world


def build_partner_week(
    api,
    clock=CANONICAL_CLOCK,
    cycle_overrides=None,
    group_overrides=None,
    service_date=HORIZON_START,
):
    """A cycle whose CHAT_EN demand grid has two intervals of eighty-two allocatable contacts."""
    set_clock(api, clock)
    cycle = make_planning_cycle(api, **(cycle_overrides or {}))
    group = make_partner_forecast_group(api, cycle["id"], **(group_overrides or {}))
    intervals = generate_grid(api, group["id"], service_date)
    return {"cycle": cycle, "group": group, "intervals": intervals}


def build_coverage_week(
    api, clock=CANONICAL_CLOCK, cycle_overrides=None, service_date=HORIZON_START
):
    """A cycle whose CHAT_EN grid is four small intervals each needing one agent."""
    set_clock(api, clock)
    cycle = make_planning_cycle(api, **(cycle_overrides or {}))
    group = make_coverage_forecast_group(api, cycle["id"])
    intervals = generate_grid(api, group["id"], service_date)
    return {"cycle": cycle, "group": group, "intervals": intervals}


def build_ot_offer_week(api, hours=4.0, **kwargs):
    """A published week carrying one open overtime offer against the published shift."""
    world = build_published_week(api, **kwargs)
    world["action"] = make_ot_offer(
        api,
        world["cycle"]["id"],
        world["agent"]["id"],
        world["shift"]["id"],
        world["group"]["id"],
        hours=hours,
    )
    return world


def build_vto_offer_week(api, hours=1.0, **kwargs):
    """A published week carrying one open voluntary-time-off offer."""
    world = build_published_week(api, **kwargs)
    world["action"] = make_vto_offer(
        api, world["cycle"]["id"], world["agent"]["id"], world["shift"]["id"], hours=hours
    )
    return world


def build_flagged_shift_week(api, out_of_adherence_seconds=5400, **kwargs):
    """A published week whose shift has been observed below the coaching threshold."""
    world = build_published_week(api, **kwargs)
    world["shift"] = record_observation(
        api, world["shift"]["id"], out_of_adherence_seconds
    )
    world["agent"] = read_agent(api, world["agent"]["id"])
    return world


def build_exception_case(
    api, out_of_adherence_seconds=5400, duration_seconds=2700, **kwargs
):
    """A flagged shift with the agent's own exception request already filed."""
    world = build_flagged_shift_week(
        api, out_of_adherence_seconds=out_of_adherence_seconds, **kwargs
    )
    world["exception"] = file_exception(
        api, world["shift"]["id"], world["agent"]["id"], duration_seconds
    )
    return world


def build_open_round_week(api, clock=CANONICAL_CLOCK, template_overrides=None):
    """A cycle with one template, one agent and a bidding round already open."""
    set_clock(api, clock)
    agreement = make_labor_agreement(api)
    cycle = make_planning_cycle(api)
    template = make_shift_template(api, cycle["id"], **(template_overrides or {}))
    agent = make_agent(api, agreement["id"])
    bid_round = make_bid_round(api, cycle["id"])
    bid_round = open_round(api, bid_round["id"])
    return {
        "agreement": agreement,
        "cycle": cycle,
        "template": template,
        "agent": agent,
        "round": bid_round,
        "agent_headers": make_agent_headers(agent["id"]),
    }


# ─── Tier 4: pytest fixtures ──────────────────────────

@pytest.fixture
def clock_at_canonical(api):
    """Move the logical clock to the canonical planning instant."""
    return set_clock(api, CANONICAL_CLOCK)


@pytest.fixture
def agreement(api, clock_at_canonical):
    """One permissive labour agreement."""
    return make_labor_agreement(api)


@pytest.fixture
def cycle(api, clock_at_canonical):
    """One open planning cycle over the standard horizon."""
    return make_planning_cycle(api)


@pytest.fixture
def voice_group(api, cycle):
    """The canonical VOICE / VOICE_EN demand group of the open cycle."""
    return make_forecast_group(api, cycle["id"])


@pytest.fixture
def voice_intervals(api, voice_group):
    """The four-row Monday interval grid of the canonical demand group."""
    return generate_grid(api, voice_group["id"])


@pytest.fixture
def roster_agent(api, agreement):
    """One VOICE_EN agent under the permissive agreement."""
    return make_agent(api, agreement["id"])


@pytest.fixture
def partner(api, clock_at_canonical):
    """One CHAT_EN outsourced partner priced at 12,500 millicents."""
    return make_outsource_partner(api)


@pytest.fixture
def canonical_week(api):
    """Agreement, open cycle, demand grid, roster and one draft shift."""
    return build_canonical_week(api)


@pytest.fixture
def published_week(api):
    """The canonical week with the cycle locked and the shift published."""
    return build_published_week(api)


@pytest.fixture
def partner_week(api):
    """A CHAT_EN cycle whose two intervals each need eighty-two outsourced contacts."""
    return build_partner_week(api)


@pytest.fixture
def coverage_week(api):
    """A CHAT_EN cycle of four small intervals each requiring one agent."""
    return build_coverage_week(api)


@pytest.fixture
def ot_offer_week(api):
    """A published week carrying one four-hour overtime offer."""
    return build_ot_offer_week(api)


@pytest.fixture
def flagged_shift_week(api):
    """A published week whose shift has been flagged out of adherence."""
    return build_flagged_shift_week(api)


@pytest.fixture
def exception_case(api):
    """A flagged shift with the agent's exception request already on file."""
    return build_exception_case(api)


@pytest.fixture
def open_round_week(api):
    """A cycle with one template, one agent and an open bidding round."""
    return build_open_round_week(api)
