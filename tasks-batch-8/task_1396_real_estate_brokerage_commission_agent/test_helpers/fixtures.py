"""Composite setup helpers built from PRD-declared endpoints only.

Every helper starts from an empty database (the runner restarts the server
before each test) and drives the public API to reach the state a test needs.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agent_payload,
    create_plan_p1_payload,
    create_plan_p2_payload,
    create_deal_payload,
    create_enrollment_payload,
    create_debit_adjustment_payload,
)
from .test_users import TEST_USERS, make_transaction_coordinator_headers, make_office_manager_headers


def _admin():
    return TEST_USERS["broker_admin_headers"]


def _tc():
    return TEST_USERS["transaction_coordinator_headers"]


def _om():
    return TEST_USERS["office_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity progression
# ---------------------------------------------------------------------------

def setup_active_agent(joined_at="2025-09-01", name="Agent A", **agent_overrides):
    """Create + activate an agent. Returns the activated agent dict."""
    payload = create_agent_payload(full_name=name, joined_at=joined_at, **agent_overrides)
    agent = get_success_data(api_client.create_agent(payload, _admin()))
    activated = get_success_data(api_client.activate_agent(agent["id"], _admin()))
    return activated


def setup_active_plan_p1(**overrides):
    """Create + activate plan P1. Returns the activated plan dict."""
    plan = get_success_data(api_client.create_plan(create_plan_p1_payload(**overrides), _admin()))
    return get_success_data(api_client.activate_plan(plan["id"], _admin()))


def setup_active_plan_p2(**overrides):
    """Create + activate plan P2. Returns the activated plan dict."""
    plan = get_success_data(api_client.create_plan(create_plan_p2_payload(**overrides), _admin()))
    return get_success_data(api_client.activate_plan(plan["id"], _admin()))


# ---------------------------------------------------------------------------
# Tier 2: agent + plan + enrollment hierarchy
# ---------------------------------------------------------------------------

def setup_agent_on_plan(joined_at="2025-09-01", effective_from=None, plan_overrides=None,
                        agent_overrides=None, agent_name="Agent A"):
    """Active agent enrolled in an ACTIVE P1 plan.

    Returns (agent, plan, enrollment). The enrollment is created with the
    agent's current version so OCC succeeds.
    """
    agent = setup_active_agent(joined_at=joined_at, name=agent_name, **(agent_overrides or {}))
    plan = setup_active_plan_p1(**(plan_overrides or {}))
    enrollment = get_success_data(api_client.create_enrollment(
        agent["id"],
        create_enrollment_payload(plan["id"], effective_from or joined_at, agent["version"]),
        _admin(),
    ))
    # Refresh agent — enrollment creation bumps Agent.version
    agent = get_success_data(api_client.get_agent(agent["id"], _admin()))
    return agent, plan, enrollment


def setup_agent_with_debit(debit_cents, joined_at="2025-09-01", effective_from=None,
                           plan_overrides=None, agent_name="Agent A"):
    """Active agent on P1 with a manual debit balance pre-loaded.

    Returns (agent, plan, enrollment).
    """
    agent, plan, enrollment = setup_agent_on_plan(
        joined_at=joined_at, effective_from=effective_from,
        plan_overrides=plan_overrides, agent_name=agent_name,
    )
    get_success_data(api_client.create_debit_adjustment(
        agent["id"], create_debit_adjustment_payload(debit_cents, "seed debit"), _admin()))
    agent = get_success_data(api_client.get_agent(agent["id"], _admin()))
    return agent, plan, enrollment


# ---------------------------------------------------------------------------
# Tier 3: deal lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_deal(agent_id, **deal_overrides):
    """Create a DRAFT deal. Returns the deal dict."""
    return get_success_data(api_client.create_deal(
        create_deal_payload(agent_id, **deal_overrides), _tc()))


def setup_pending_deal(agent_id, **deal_overrides):
    """Create + submit a deal. Returns the PENDING_CLOSING deal dict."""
    deal = create_draft_deal(agent_id, **deal_overrides)
    return get_success_data(api_client.submit_deal(deal["id"], _tc()))


def setup_closed_deal(agent_id, close_payload=None, **deal_overrides):
    """Create + submit + close a deal. Returns the CLOSED deal dict."""
    deal = setup_pending_deal(agent_id, **deal_overrides)
    return get_success_data(api_client.close_deal(deal["id"], close_payload or {}, _tc()))


def setup_settled_deal(agent_id, close_payload=None, poster_user_id="tc-1", **deal_overrides):
    """Create + submit + close + settle a deal.

    Returns (settlement, closed_deal). Settlement is posted by the given
    coordinator user id so downstream SoD tests can pick a different user.
    """
    deal = setup_closed_deal(agent_id, close_payload=close_payload, **deal_overrides)
    settlement = get_success_data(api_client.settle_deal(
        deal["id"], make_transaction_coordinator_headers(poster_user_id)))
    return settlement, deal


# ---------------------------------------------------------------------------
# Tier 3b: leg helpers
# ---------------------------------------------------------------------------

def get_settlement_legs(settlement_id, **filters):
    """List legs of a settlement; extra query filters pass through."""
    params = {"settlement_id": settlement_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_legs(_om(), params=params))


def get_leg_by_type(settlement_id, payee_type):
    legs = get_settlement_legs(settlement_id, payee_type=payee_type)
    assert legs, f"expected a {payee_type} leg on settlement {settlement_id}"
    return legs[0]


def authorize_leg(leg_id, user_id="om-1"):
    return get_success_data(api_client.authorize_leg(leg_id, make_office_manager_headers(user_id)))


def release_leg(leg_id, user_id="om-2"):
    return get_success_data(api_client.release_leg(leg_id, make_office_manager_headers(user_id)))


def authorize_and_release_leg(leg_id, authorizer="om-1", releaser="om-2"):
    authorize_leg(leg_id, user_id=authorizer)
    return release_leg(leg_id, user_id=releaser)


def setup_released_deal(agent_id, poster_user_id="tc-1", authorizer="om-1", releaser="om-2",
                        **deal_overrides):
    """Settle a deal and release every leg. Returns (settlement, deal, legs)."""
    settlement, deal = setup_settled_deal(agent_id, poster_user_id=poster_user_id, **deal_overrides)
    legs = get_settlement_legs(settlement["id"])
    for leg in legs:
        authorize_and_release_leg(leg["id"], authorizer=authorizer, releaser=releaser)
    legs = get_settlement_legs(settlement["id"])
    return settlement, deal, legs


# ---------------------------------------------------------------------------
# Tier 4: window observation
# ---------------------------------------------------------------------------

def get_window_for_agent(agent_id, index=0):
    """Return the agent's anniversary window at the given index."""
    windows = get_success_data(api_client.list_anniversary_periods(
        _admin(), params={"agent_id": agent_id, "limit": 100}))
    assert len(windows) > index, f"expected window[{index}] for agent {agent_id}"
    return windows[index]
