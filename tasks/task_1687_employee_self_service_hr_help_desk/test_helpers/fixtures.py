"""Composite setup helpers.

Multi-step arrangements used by the test suite: rosters, queues, ticket
lifecycles, KB publishing flows, DCR/fraud pipelines, and staffing windows.
Every helper builds its preconditions from scratch through the public API and
uses the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors.

Identity threading: after creating an entity-backed identity (Employee or
Agent), every ownership-gated call in the same flow uses
make_employee_headers(employee["id"]) / make_*_agent_headers(agent["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_employee_payload,
    create_team_payload,
    create_agent_payload,
    create_category_payload,
    create_sla_policy_payload,
    create_kb_article_payload,
    create_ticket_payload,
    create_dcr_payload,
    create_staffing_window_payload,
    create_agent_shift_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_helpdesk_agent_headers,
    make_sensitive_case_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]
PLANNER = TEST_USERS["planner_headers"]
KM1 = TEST_USERS["km1_headers"]
KM2 = TEST_USERS["km2_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock_to(to_iso8601: str) -> dict:
    """Advance the logical clock; returns {"now_utc": ...}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Roster primitives
# ---------------------------------------------------------------------------

def make_team(name=None) -> dict:
    payload = create_team_payload()
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_team(payload, ADMIN))


def make_agent(team_id, tier="T1", clearance=None, capacity_max=None, active=None,
               display_name=None, email=None) -> dict:
    payload = create_agent_payload(team_id)
    payload["tier"] = tier
    if clearance is not None:
        payload["clearance"] = clearance
    if capacity_max is not None:
        payload["capacity_max"] = capacity_max
    if active is not None:
        payload["active"] = active
    if display_name is not None:
        payload["display_name"] = display_name
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_agent(payload, ADMIN))


def make_category(team_id, is_sensitive=None, active=None, code=None, name=None) -> dict:
    payload = create_category_payload(team_id)
    if is_sensitive is not None:
        payload["is_sensitive"] = is_sensitive
    if active is not None:
        payload["active"] = active
    if code is not None:
        payload["code"] = code
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_category(payload, ADMIN))


def make_sla_policy(category_id, priority="P3", first_response_minutes=480,
                    resolution_minutes=480, clock_mode=None) -> dict:
    payload = create_sla_policy_payload(
        category_id,
        priority=priority,
        first_response_minutes=first_response_minutes,
        resolution_minutes=resolution_minutes,
    )
    if clock_mode is not None:
        payload["clock_mode"] = clock_mode
    return get_success_data(api_client.create_sla_policy(payload, ADMIN))


def make_employee(manager_id=None, **overrides) -> dict:
    payload = create_employee_payload(**overrides)
    if manager_id is not None:
        payload["manager_id"] = manager_id
    return get_success_data(api_client.create_employee(payload, ADMIN))


def set_employee_status(employee_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_employee_status(employee_id, {"status": status}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Knowledge base flows (PRD §3.3)
# ---------------------------------------------------------------------------

def author_article(category_id, author_headers, title=None, body=None,
                   supersedes_article_id=None, keywords=None) -> dict:
    payload = create_kb_article_payload(category_id)
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if supersedes_article_id is not None:
        payload["supersedes_article_id"] = supersedes_article_id
    if keywords is not None:
        payload["keywords"] = keywords
    return get_success_data(api_client.create_kb_article(payload, author_headers))


def submit_review(article_id, headers) -> dict:
    return get_success_data(api_client.submit_article_review(article_id, headers))


def publish_article(article_id, publisher_headers) -> dict:
    return get_success_data(api_client.publish_kb_article(article_id, publisher_headers))


def make_published_article(category_id, title=None, body=None,
                           author_headers=KM1, publisher_headers=KM2,
                           supersedes_article_id=None, keywords=None) -> dict:
    """Author -> submit-review -> publish (publisher differs from author)."""
    article = author_article(
        category_id, author_headers, title=title, body=body,
        supersedes_article_id=supersedes_article_id, keywords=keywords,
    )
    submit_review(article["id"], author_headers)
    return publish_article(article["id"], publisher_headers)


def record_article_view(article_id, employee_id) -> dict:
    headers = make_employee_headers(employee_id)
    return get_success_data(
        api_client.create_article_view({"article_id": article_id}, headers)
    )


# ---------------------------------------------------------------------------
# Ticket intake and lifecycle (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------

def create_ticket_for(employee_id, category_id, subject=None, description=None,
                      priority=None) -> dict:
    payload = create_ticket_payload(employee_id, category_id)
    if subject is not None:
        payload["subject"] = subject
    if description is not None:
        payload["description"] = description
    if priority is not None:
        payload["priority"] = priority
    return get_success_data(
        api_client.create_ticket(payload, make_employee_headers(employee_id))
    )


def get_ticket(ticket_id) -> dict:
    return get_success_data(api_client.get_ticket(ticket_id, ADMIN))


def ticket_version(ticket_id) -> int:
    return get_ticket(ticket_id)["version"]


def triage_ticket(ticket_id, agent_id, priority=None) -> dict:
    payload = {}
    if priority is not None:
        payload["priority"] = priority
    return get_success_data(
        api_client.triage_ticket(ticket_id, payload, make_helpdesk_agent_headers(agent_id))
    )


def assign_ticket(ticket_id, agent_id, expected_version=None, assigner_headers=None) -> dict:
    """Assign with a fresh OCC version (read-then-assign is the caller's last
    observed version, PRD §2.9). Defaults the caller to the assignee acting as
    a HelpDeskAgent, which may assign any eligible agent (PRD §3.5)."""
    if expected_version is None:
        expected_version = ticket_version(ticket_id)
    if assigner_headers is None:
        assigner_headers = make_helpdesk_agent_headers(agent_id)
    return get_success_data(
        api_client.assign_ticket(
            ticket_id,
            {"agent_id": agent_id, "expected_ticket_version": expected_version},
            assigner_headers,
        )
    )


def respond_ticket(ticket_id, agent_id, body="working on it") -> dict:
    return get_success_data(
        api_client.respond_ticket(ticket_id, {"body": body},
                                  make_helpdesk_agent_headers(agent_id))
    )


def resolve_ticket(ticket_id, agent_id, resolution_summary="resolved",
                   resolution_article_id=None) -> dict:
    payload = {"resolution_summary": resolution_summary}
    if resolution_article_id is not None:
        payload["resolution_article_id"] = resolution_article_id
    return get_success_data(
        api_client.resolve_ticket(ticket_id, payload, make_helpdesk_agent_headers(agent_id))
    )


def surveys_for_ticket(ticket_id):
    """Returns (data_list, meta) of surveys filtered by ticket_id."""
    return validate_paginated(
        api_client.list_surveys(ADMIN, params={"ticket_id": ticket_id})
    )


def survey_for_ticket(ticket_id) -> dict:
    data, meta = surveys_for_ticket(ticket_id)
    assert meta["total_count"] >= 1, f"expected a survey for ticket {ticket_id}"
    return data[0]


def submit_survey_score(survey_id, employee_id, score, comment=None) -> dict:
    payload = {"score": score}
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(
        api_client.submit_survey(survey_id, payload, make_employee_headers(employee_id))
    )


def events_of(ticket_id):
    """Chronological event log of a ticket (PRD §3.5), as admin."""
    data, _meta = validate_paginated(api_client.list_ticket_events(ticket_id, ADMIN))
    return data


# ---------------------------------------------------------------------------
# Composite: a minimal working queue
# ---------------------------------------------------------------------------

def setup_queue(first_response_minutes=480, resolution_minutes=480,
                clock_mode=None, agent_tier="T1", agent_clearance=None,
                capacity_max=10, is_sensitive=None, priority="P3") -> dict:
    """Team + one agent + category routed to the team + one SLA policy row
    + one employee. Returns a dict with all of them."""
    team = make_team()
    agent = make_agent(
        team["id"], tier=agent_tier, clearance=agent_clearance, capacity_max=capacity_max
    )
    category = make_category(team["id"], is_sensitive=is_sensitive)
    policy = make_sla_policy(
        category["id"], priority=priority,
        first_response_minutes=first_response_minutes,
        resolution_minutes=resolution_minutes,
        clock_mode=clock_mode,
    )
    employee = make_employee()
    return {
        "team": team, "agent": agent, "category": category,
        "policy": policy, "employee": employee,
    }


def setup_ticket_assigned(**queue_kwargs) -> dict:
    """Queue + one ticket assigned (IN_PROGRESS) to the queue's agent."""
    ctx = setup_queue(**queue_kwargs)
    ticket = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"])
    ticket = assign_ticket(ticket["id"], ctx["agent"]["id"])
    ctx["ticket"] = ticket
    return ctx


def setup_ticket_resolved(**queue_kwargs) -> dict:
    """Queue + ticket assigned and resolved; returns ctx with ticket + survey."""
    ctx = setup_ticket_assigned(**queue_kwargs)
    ticket = resolve_ticket(ctx["ticket"]["id"], ctx["agent"]["id"])
    ctx["ticket"] = ticket
    ctx["survey"] = survey_for_ticket(ticket["id"])
    return ctx


def resolve_and_submit_survey(ctx, subject, score, clock_iso=None) -> dict:
    """At the (optionally re-set) logical clock: create a ticket in the ctx
    category for the ctx employee, assign to the ctx agent, resolve, then
    submit the issued survey with the given score. Returns the ticket."""
    if clock_iso is not None:
        set_clock_to(clock_iso)
    ticket = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"], subject=subject)
    ticket = assign_ticket(ticket["id"], ctx["agent"]["id"])
    ticket = resolve_ticket(ticket["id"], ctx["agent"]["id"])
    survey = survey_for_ticket(ticket["id"])
    submit_survey_score(survey["id"], ctx["employee"]["id"], score)
    return ticket


# ---------------------------------------------------------------------------
# Data change requests and fraud verification (PRD §3.7)
# ---------------------------------------------------------------------------

def employee_version(employee_id) -> int:
    return get_success_data(api_client.get_employee(employee_id, ADMIN))["version"]


def create_dcr(employee_id, change_type, new_values=None,
               expected_employee_version=None) -> dict:
    """Create a DCR as the owning employee with a fresh OCC employee version."""
    if expected_employee_version is None:
        expected_employee_version = employee_version(employee_id)
    payload = create_dcr_payload(
        employee_id, change_type, expected_employee_version
    )
    if new_values is not None:
        payload["new_values"] = new_values
    return get_success_data(
        api_client.create_data_change_request(payload, make_employee_headers(employee_id))
    )


def get_dcr(dcr_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_data_change_request(dcr_id, headers or STEWARD)
    )


def fraud_verification_of(dcr_id, employee_id) -> dict:
    """The DCR's single fraud verification record, read by the owner employee."""
    data, meta = validate_paginated(
        api_client.list_fraud_verifications(dcr_id, make_employee_headers(employee_id))
    )
    assert meta["total_count"] == 1, f"expected exactly one fraud verification for {dcr_id}"
    return data[0]


def challenge_code_of(dcr_id, employee_id) -> str:
    return fraud_verification_of(dcr_id, employee_id)["challenge_code"]


def verify_dcr(dcr_id, method, caller_employee_id, evidence_code=None):
    """Raw verify call (returns the Response; caller inspects success/error)."""
    payload = {"method": method}
    if evidence_code is not None:
        payload["evidence_code"] = evidence_code
    return api_client.verify_data_change_request(
        dcr_id, payload, make_employee_headers(caller_employee_id)
    )


def approve_dcr(dcr_id, steward_headers=None) -> dict:
    return get_success_data(
        api_client.approve_data_change_request(dcr_id, steward_headers or STEWARD)
    )


def audit_log_of_employee(employee_id, headers=None):
    """Newest-first audit trail of the employee (PRD §3.7)."""
    data, meta = validate_paginated(
        api_client.get_employee_audit_log(employee_id, headers or ADMIN)
    )
    return data, meta


# ---------------------------------------------------------------------------
# Seasonal staffing (PRD §3.9)
# ---------------------------------------------------------------------------

def make_window(team_id, window_start="2026-08-03T00:00:00Z",
                window_end="2026-08-08T00:00:00Z", required_t1_hours=10,
                required_t2_hours=0, sla_multiplier=None, name=None) -> dict:
    payload = create_staffing_window_payload(
        team_id,
        window_start=window_start,
        window_end=window_end,
        required_t1_hours=required_t1_hours,
        required_t2_hours=required_t2_hours,
    )
    if sla_multiplier is not None:
        payload["sla_multiplier"] = sla_multiplier
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_staffing_window(payload, PLANNER))


def make_shift(agent_id, window_id, shift_start="2026-08-03T09:00:00Z",
               shift_end="2026-08-03T17:00:00Z") -> dict:
    payload = create_agent_shift_payload(
        agent_id, window_id, shift_start=shift_start, shift_end=shift_end
    )
    return get_success_data(api_client.create_agent_shift(payload, PLANNER))


def get_window(window_id) -> dict:
    return get_success_data(api_client.get_staffing_window(window_id, PLANNER))
