"""Composite setup helpers.

Most interesting claims require the system to be walked into a specific state
through several PRD-declared endpoints. These helpers encapsulate those
multi-step preambles. They use get_success_data() internally so a setup failure
surfaces a clear "Setup step failed" message rather than a confusing assertion.

The test harness restarts the server (empty DB, clock reset) before every test,
so every helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as F
from . import test_users as U
from .constants import CLOCK_ANCHOR


# --------------------------------------------------------------------------- #
# Clock helpers (PRD §2.8, §3.9)
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str = CLOCK_ANCHOR):
    """Set the server clock to an absolute instant. Returns the reported `now`."""
    return get_success_data(
        api_client.clock_set({"to_iso8601": to_iso8601}, U.platform_admin())
    )


def advance_clock(minutes: int):
    """Advance the server clock by N minutes; fires breach transitions."""
    return get_success_data(
        api_client.clock_advance({"minutes": minutes}, U.platform_admin())
    )


# --------------------------------------------------------------------------- #
# Tier 1 — Catalog / configuration backbone (PRD §3.1)
# --------------------------------------------------------------------------- #
def setup_catalog(default_priority="P3", policy_overrides=None, group_overrides=None,
                  category_overrides=None):
    """Create SlaPolicy + AssignmentGroup + Category wired together.

    Returns (policy, group, category) as full resource dicts.
    """
    policy = get_success_data(
        api_client.create_sla_policy(
            F.create_sla_policy_payload(**(policy_overrides or {})),
            U.platform_admin(),
        )
    )
    group = get_success_data(
        api_client.create_assignment_group(
            F.create_assignment_group_payload(**(group_overrides or {})),
            U.platform_admin(),
        )
    )
    cat_extra = dict(category_overrides or {})
    category = get_success_data(
        api_client.create_category(
            F.create_category_payload(
                policy["id"], group["id"],
                default_priority=default_priority,
                **cat_extra,
            ),
            U.platform_admin(),
        )
    )
    return policy, group, category


def create_group(**overrides):
    """A bare assignment group."""
    return get_success_data(
        api_client.create_assignment_group(
            F.create_assignment_group_payload(**overrides), U.platform_admin()
        )
    )


def create_asset(**overrides):
    """A bare OPERATIONAL asset."""
    return get_success_data(
        api_client.create_asset(F.create_asset_payload(**overrides), U.platform_admin())
    )


# --------------------------------------------------------------------------- #
# Tier 1/2 — Ticket state progression
# --------------------------------------------------------------------------- #
def open_ticket(category_id, requester_id="req-1", ticket_overrides=None):
    """Open a NEW ticket under a category. Returns the ticket dict."""
    return get_success_data(
        api_client.create_ticket(
            F.create_ticket_payload(category_id, **(ticket_overrides or {})),
            U.requester(requester_id),
        )
    )


def setup_open_ticket(default_priority="P3", requester_id="req-1",
                      ticket_overrides=None, **catalog_kwargs):
    """Catalog + a single NEW ticket. Returns (policy, group, category, ticket)."""
    policy, group, category = setup_catalog(default_priority=default_priority, **catalog_kwargs)
    ticket = open_ticket(category["id"], requester_id=requester_id,
                         ticket_overrides=ticket_overrides)
    return policy, group, category, ticket


def assign_and_start(ticket_id, agent_id="agent-1"):
    """Walk a NEW ticket -> ASSIGNED -> IN_PROGRESS. Returns the IN_PROGRESS ticket."""
    get_success_data(
        api_client.assign_ticket(ticket_id, {"assignee_user_id": agent_id}, U.agent(agent_id))
    )
    return get_success_data(api_client.start_ticket(ticket_id, U.agent(agent_id)))


def setup_in_progress_ticket(default_priority="P3", requester_id="req-1",
                             agent_id="agent-1", **catalog_kwargs):
    """Catalog + ticket walked to IN_PROGRESS. Returns (policy, group, category, ticket).

    `ticket` is the IN_PROGRESS snapshot.
    """
    policy, group, category, ticket = setup_open_ticket(
        default_priority=default_priority, requester_id=requester_id, **catalog_kwargs
    )
    ticket = assign_and_start(ticket["id"], agent_id=agent_id)
    return policy, group, category, ticket


def setup_resolved_ticket(default_priority="P3", requester_id="req-1",
                          agent_id="agent-1", **catalog_kwargs):
    """Catalog + ticket walked to RESOLVED. Returns (policy, group, category, ticket).

    `ticket` is the RESOLVED snapshot.
    """
    policy, group, category, ticket = setup_in_progress_ticket(
        default_priority=default_priority, requester_id=requester_id,
        agent_id=agent_id, **catalog_kwargs
    )
    ticket = get_success_data(api_client.resolve_ticket(ticket["id"], U.agent(agent_id)))
    return policy, group, category, ticket


# --------------------------------------------------------------------------- #
# Tier 3 — Change-request lifecycle
# --------------------------------------------------------------------------- #
def create_and_submit_change(ticket_id, risk="MEDIUM", manager_id="cm-1"):
    """Raise a change on a ticket and submit it to CAB (DRAFT -> PENDING_CAB).

    Returns the submitted change dict (carries the current `version`,
    `required_approvals`).
    """
    change = get_success_data(
        api_client.create_change_request(
            F.create_change_request_payload(ticket_id, risk=risk),
            U.change_manager(manager_id),
        )
    )
    return get_success_data(
        api_client.submit_change(change["id"], U.change_manager(manager_id))
    )


def setup_submitted_change(risk="MEDIUM", default_priority="P2", manager_id="cm-1",
                           requester_id="req-1", **catalog_kwargs):
    """Catalog + ticket + change raised & submitted (PENDING_CAB).

    Returns (policy, group, category, ticket, change) where `change` is the
    PENDING_CAB snapshot.
    """
    policy, group, category, ticket = setup_open_ticket(
        default_priority=default_priority, requester_id=requester_id, **catalog_kwargs
    )
    change = create_and_submit_change(ticket["id"], risk=risk, manager_id=manager_id)
    return policy, group, category, ticket, change


def setup_ticket_pending_change(risk="LOW", default_priority="P2", manager_id="cm-1",
                                agent_id="agent-1", requester_id="req-1",
                                **catalog_kwargs):
    """Catalog + IN_PROGRESS ticket with a submitted change attached (PENDING_CHANGE).

    Returns (policy, group, category, ticket, change) where `ticket` is the
    PENDING_CHANGE snapshot and `change` the PENDING_CAB snapshot.
    """
    policy, group, category, ticket = setup_in_progress_ticket(
        default_priority=default_priority, requester_id=requester_id,
        agent_id=agent_id, **catalog_kwargs
    )
    change = create_and_submit_change(ticket["id"], risk=risk, manager_id=manager_id)
    ticket = get_success_data(
        api_client.attach_change(ticket["id"], {"change_request_id": change["id"]},
                                 U.agent(agent_id))
    )
    return policy, group, category, ticket, change


# --------------------------------------------------------------------------- #
# Tier 3 — Problem / known-error lifecycle
# --------------------------------------------------------------------------- #
def create_problem(owner_id="agent-p", **overrides):
    return get_success_data(
        api_client.create_problem(
            F.create_problem_payload(owner_user_id=owner_id, **overrides), U.agent()
        )
    )


def setup_known_error_problem(owner_id="agent-p"):
    """Problem walked OPEN -> ROOT_CAUSE_IDENTIFIED -> KNOWN_ERROR (no linked tickets).

    Returns (problem, known_error) where `problem` is the KNOWN_ERROR snapshot.
    """
    problem = create_problem(owner_id=owner_id)
    get_success_data(
        api_client.identify_root_cause(problem["id"], {}, U.agent(owner_id))
    )
    known_error = get_success_data(
        api_client.create_known_error(
            problem["id"], F.create_known_error_payload(), U.agent(owner_id)
        )
    )
    problem = get_success_data(api_client.get_problem(problem["id"], U.agent(owner_id)))
    return problem, known_error


def setup_known_error_with_linked_ticket(owner_id="agent-p", requester_id="req-1"):
    """A KNOWN_ERROR problem with one non-terminal linked ticket (linked_ticket_count=1).

    Returns (policy, group, category, ticket, problem). `ticket` is IN_PROGRESS,
    `problem` is the KNOWN_ERROR snapshot.
    """
    policy, group, category, ticket = setup_in_progress_ticket(
        default_priority="P3", requester_id=requester_id, agent_id=owner_id
    )
    problem = create_problem(owner_id=owner_id)
    get_success_data(
        api_client.link_problem(ticket["id"], {"problem_id": problem["id"]}, U.agent(owner_id))
    )
    get_success_data(
        api_client.identify_root_cause(problem["id"], {}, U.agent(owner_id))
    )
    get_success_data(
        api_client.create_known_error(
            problem["id"], F.create_known_error_payload(), U.agent(owner_id)
        )
    )
    problem = get_success_data(api_client.get_problem(problem["id"], U.agent(owner_id)))
    return policy, group, category, ticket, problem
