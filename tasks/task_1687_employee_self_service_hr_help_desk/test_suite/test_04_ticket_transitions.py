"""Ticket workflow transitions (PRD §3.5, §3.6): invalid-transition lockdown,
escalation, the reopen cycle, auto-close, the event log, and SLA attainment."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    make_employee_headers,
    make_helpdesk_agent_headers,
    assert_ticket,
    assert_event_type_sequence,
    assert_instant_equals,
    make_team,
    make_agent,
    make_category,
    make_sla_policy,
    make_employee,
    author_article,
    create_ticket_for,
    get_ticket,
    triage_ticket,
    assign_ticket,
    respond_ticket,
    resolve_ticket,
    surveys_for_ticket,
    events_of,
    set_clock_to,
    setup_ticket_resolved,
    setup_queue,
)

ADMIN = TEST_USERS["admin_headers"]
KM1 = TEST_USERS["km1_headers"]


def test_resolve_from_new_rejected(api):
    """PRD §3.5: "Resolution moves `IN_PROGRESS` or `REOPENED` to `RESOLVED` under
    the same clearance rule, and the agent supplies a `resolution_summary` plus an
    optional `resolution_article_id` citing the knowledge article that solved the
    case — the cited article must be `PUBLISHED`, otherwise the resolve fails with
    `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`."
    PRD §3.5: "Ownership failures on any of these employee actions surface as
    `ERR_FORBIDDEN_ROLE`, and attempting any transition from a state that does not
    support it surfaces as `ERR_TICKET_INVALID_STATE`."

    Design: Corner/state_machines/resolve_from_new_rejected
    """
    ctx = setup_queue(first_response_minutes=60, resolution_minutes=240)
    ticket = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"], subject="q")
    assert ticket["workflow_status"] == "NEW"

    resp = api.resolve_ticket(
        ticket["id"], {"resolution_summary": "nope"},
        make_helpdesk_agent_headers(ctx["agent"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value)

    _data, meta = surveys_for_ticket(ticket["id"])
    assert meta["total_count"] == 0, "no survey may be issued for a rejected resolve"


def test_cancel_from_resolved_rejected(api):
    """PRD §3.5: "Cancelling moves `NEW` or `TRIAGED` to `CANCELLED` at the owner's
    request, optionally with a `reason`, and clears `assigned_agent_id`."
    PRD §3.5: "Ownership failures on any of these employee actions surface as
    `ERR_FORBIDDEN_ROLE`, and attempting any transition from a state that does not
    support it surfaces as `ERR_TICKET_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_resolved_rejected
    """
    ctx = setup_ticket_resolved(first_response_minutes=60, resolution_minutes=240)
    ticket = ctx["ticket"]
    assert ticket["workflow_status"] == "RESOLVED"

    resp = api.cancel_ticket(ticket["id"], {}, make_employee_headers(ctx["employee"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value)

    data = get_ticket(ticket["id"])
    assert data["workflow_status"] == "RESOLVED", "ticket must remain RESOLVED after a rejected cancel"


def test_escalate_assigns_t2_specialist_and_keeps_sla_clock(api):
    """PRD §3.5: "Escalation hands a ticket to the specialists. A `HelpDeskAgent`
    escalates from `TRIAGED` or `IN_PROGRESS`, optionally recording a `reason`; the
    ticket must still be tier `T1`, and escalating an already-`T2` ticket fails with
    `ERR_TICKET_INVALID_STATE`."
    PRD §3.5: "Otherwise the winner, ranked by `assigned_open_count` ascending with
    ties broken by earlier agent `created_at`, becomes the `assigned_agent_id`; the
    ticket's `tier` flips to `T2`, `escalation_count` increments, and the ticket
    lands in `ESCALATED`."
    PRD §3.5: "Crucially, escalation does not touch the SLA clocks:
    `first_response_due_at`, `resolution_due_at`, and `sla_status` carry over
    unchanged."

    Design: Corner/state_machines/escalate_assigns_t2_specialist_and_keeps_sla_clock
    """
    team = make_team("ESC Team")
    a1 = make_agent(team["id"], tier="T1", display_name="Tier1", email="t1@x.com")
    sp = make_agent(team["id"], tier="T2", display_name="Spec", email="sp@x.com")
    category = make_category(team["id"], code="ESC", name="Esc Cat")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E103", full_name="Eli Esc", email="eli@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="q")
    triage_ticket(ticket["id"], a1["id"])

    escalated = validate_success(
        api.escalate_ticket(ticket["id"], {"reason": "needs specialist"},
                            make_helpdesk_agent_headers(a1["id"]))
    )
    assert_ticket(escalated)
    assert escalated["workflow_status"] == "ESCALATED"
    assert escalated["tier"] == "T2"
    assert escalated["escalation_count"] == 1
    assert escalated["assigned_agent_id"] == sp["id"]
    assert_instant_equals(escalated["resolution_due_at"], "2026-08-01T08:00:00Z")
    assert_instant_equals(escalated["first_response_due_at"], "2026-08-01T08:00:00Z")

    resp = api.escalate_ticket(ticket["id"], {"reason": "again"},
                               make_helpdesk_agent_headers(a1["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value)

    events = events_of(ticket["id"])
    assert any(e["event_type"] == "ESCALATED" for e in events), "an ESCALATED event must be logged"


def test_escalate_no_eligible_specialist(api):
    """PRD §3.5: "The server then runs the specialist selector over agents whose
    `team_id` equals the category's `specialist_team_id`, who are tier `T2`, active,
    under capacity, and — when the ticket is sensitive — `SENSITIVE`-cleared."
    PRD §3.5: "An empty pool rejects the escalation with `ERR_NO_ELIGIBLE_SPECIALIST`
    and leaves the ticket exactly as it was."

    Design: Corner/state_machines/escalate_no_eligible_specialist
    """
    team = make_team("NoSpec Team")
    a1 = make_agent(team["id"], tier="T1", display_name="Only T1", email="o@x.com")
    category = make_category(team["id"], code="NOS", name="No Spec")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E104", full_name="Noel Spec", email="noel@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="q")
    triage_ticket(ticket["id"], a1["id"])

    resp = api.escalate_ticket(ticket["id"], {}, make_helpdesk_agent_headers(a1["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SPECIALIST.value)

    data = get_ticket(ticket["id"])
    assert data["workflow_status"] == "TRIAGED"
    assert data["tier"] == "T1"
    assert data["assigned_agent_id"] is None


def test_ticket_events_chronological(api):
    """PRD §3.5: "Every state-moving call appends to the ticket's event log. Each
    entry records the `ticket_id`, the `actor_user_id` (the literal string `system`
    for clock-driven events), the `event_type`, the `from_state` and `to_state` of
    the transition (null where an event has no workflow dimension), and a `note`
    carrying the reason or body supplied with the triggering call where one exists."
    PRD §3.5: "The owner and the agent roles read the log in chronological order,
    `created_at` ascending."

    Design: Corner/endpoints/ticket_events_chronological
    """
    ctx = setup_queue(first_response_minutes=480, resolution_minutes=480)
    ticket = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"], subject="s")
    triage_ticket(ticket["id"], ctx["agent"]["id"])
    assign_ticket(ticket["id"], ctx["agent"]["id"])
    resolve_ticket(ticket["id"], ctx["agent"]["id"], resolution_summary="done")

    events = events_of(ticket["id"])
    assert len(events) == 4, f"expected exactly 4 events, got {len(events)}"
    assert_event_type_sequence(events, ["CREATED", "TRIAGED", "ASSIGNED", "RESOLVED"])
    assigned = next(e for e in events if e["event_type"] == "ASSIGNED")
    assert assigned["from_state"] == "TRIAGED"
    assert assigned["to_state"] == "IN_PROGRESS"


def test_reopen_boundary_exactly_seventy_two_hours(api):
    """PRD §3.5: "Reopening takes `RESOLVED` back to `REOPENED`: it requires the
    owner, a `reason`, and timeliness — the reopen must arrive no later than
    seventy-two hours after `resolved_at`, with the boundary instant itself still
    allowed; a later attempt fails with `ERR_REOPEN_WINDOW_PASSED`."

    Design: Corner/state_machines/reopen_boundary_exactly_72h
    """
    team = make_team("RO Team")
    agent = make_agent(team["id"], tier="T1", email="ro@x.com")
    category = make_category(team["id"], code="RO", name="Reopen")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E109", full_name="Re Open", email="re@x.com")
    t1 = create_ticket_for(employee["id"], category["id"], subject="t1")
    t2 = create_ticket_for(employee["id"], category["id"], subject="t2")
    assign_ticket(t1["id"], agent["id"])
    assign_ticket(t2["id"], agent["id"])
    resolve_ticket(t1["id"], agent["id"], resolution_summary="r1")
    resolve_ticket(t2["id"], agent["id"], resolution_summary="r2")

    # Exactly resolved_at + 72h: the boundary instant is still allowed.
    set_clock_to("2026-08-04T00:00:00Z")
    reopened = validate_success(
        api.reopen_ticket(t1["id"], {"reason": "still broken"},
                          make_employee_headers(employee["id"]))
    )
    assert reopened["workflow_status"] == "REOPENED"

    # One minute past the boundary.
    set_clock_to("2026-08-04T00:01:00Z")
    resp = api.reopen_ticket(t2["id"], {"reason": "too late"},
                             make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_PASSED.value)


def test_ticket_auto_close_after_five_days(api):
    """PRD §3.5: "Closing moves `RESOLVED` to `CLOSED` — either manually by the
    owner, or by the system itself once the ticket has sat resolved for at least five
    days, evaluated when the clock advances; both paths stamp `closed_at` and append
    an event, `CLOSED` for the manual path and `AUTO_CLOSED` for the sweep."
    PRD §2.5: "Third, tickets that have sat in `RESOLVED` for at least five days are
    auto-closed."

    Design: Corner/state_machines/ticket_auto_close_after_five_days
    """
    team = make_team("AC Team")
    agent = make_agent(team["id"], tier="T1", email="ac@x.com")
    category = make_category(team["id"], code="ACL", name="Auto Close")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=4800)
    employee = make_employee(employee_number="E107", full_name="Auto Close", email="auto@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="q")
    assign_ticket(ticket["id"], agent["id"])
    resolve_ticket(ticket["id"], agent["id"], resolution_summary="done")

    # resolved_at 2026-08-01T00:00:00Z; exactly five days later is auto-close time.
    set_clock_to("2026-08-06T00:00:00Z")
    data = get_ticket(ticket["id"])
    assert data["workflow_status"] == "CLOSED", (
        f"resolved ticket must auto-close after five days, got {data['workflow_status']}"
    )
    events = events_of(ticket["id"])
    assert any(e["event_type"] == "AUTO_CLOSED" for e in events), "an AUTO_CLOSED event must be logged"


def _resolved_then_clock_to_10(api):
    """Ticket responded to and resolved at the startup instant; clock at 10:00.

    The agent responds before resolving so `first_responded_at` is set — a
    REOPENED ticket with no recorded response and a past `first_response_due_at`
    would be reported `BREACHED_RESPONSE` by the lazy SLA evaluation of PRD
    §3.6, which is not what these reopen-cycle tests exercise."""
    team = make_team("Cycle Team")
    agent = make_agent(team["id"], tier="T1", display_name="Agent C", email="c@x.com")
    category = make_category(team["id"], code="CYC", name="Cycle Cat")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E400", full_name="Rey Open", email="rey@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="cyc")
    assign_ticket(ticket["id"], agent["id"])
    respond_ticket(ticket["id"], agent["id"])
    resolve_ticket(ticket["id"], agent["id"], resolution_summary="first fix")
    set_clock_to("2026-08-01T10:00:00Z")
    return {"team": team, "agent": agent, "category": category,
            "employee": employee, "ticket": ticket}


def test_reopen_reanchors_resolution_due_from_reopen_instant(api):
    """PRD §3.5: "Reopening increments `reopen_count`, resets `sla_status` to
    `ON_TRACK`, and re-anchors `resolution_due_at` from the reopen instant as that
    instant plus the policy's resolution minutes scaled by the creation-time surge
    multiplier, rounded up to whole minutes; no new survey is created, because a
    ticket issues only one ever."

    Design: Difficulty/non_linear_state_machine/ticket_reopen_cycle_sla_reanchor
    """
    ctx = _resolved_then_clock_to_10(api)
    emp_headers = make_employee_headers(ctx["employee"]["id"])

    reopened = validate_success(
        api.reopen_ticket(ctx["ticket"]["id"], {"reason": "still broken"}, emp_headers)
    )
    assert reopened["workflow_status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["sla_status"] == "ON_TRACK"
    # Re-anchored: 10:00 + 480 minutes (multiplier 1.0 at creation) = 18:00.
    assert_instant_equals(reopened["resolution_due_at"], "2026-08-01T18:00:00Z")


def test_reopen_resolve_cycle_issues_no_second_survey(api):
    """PRD §3.5: "Resolution moves `IN_PROGRESS` or `REOPENED` to `RESOLVED` under
    the same clearance rule, and the agent supplies a `resolution_summary` plus an
    optional `resolution_article_id` citing the knowledge article that solved the
    case — the cited article must be `PUBLISHED`, otherwise the resolve fails with
    `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`."
    PRD §3.8: "A ticket's first resolution issues exactly one survey, and only the
    first resolution ever does — a later reopen-and-resolve cycle creates none."
    PRD §3.5: "The server stamps `resolved_at`, then sets `sla_status` to `MET` when
    the resolution instant is no later than `resolution_due_at`, and to
    `BREACHED_RESOLUTION` when it is strictly later — in both cases overwriting
    whatever of `ON_TRACK`, `AT_RISK`, or `BREACHED_RESPONSE` stood before."

    Design: Difficulty/non_linear_state_machine/ticket_reopen_cycle_sla_reanchor
    """
    ctx = _resolved_then_clock_to_10(api)
    emp_headers = make_employee_headers(ctx["employee"]["id"])
    ticket_id = ctx["ticket"]["id"]

    validate_success(api.reopen_ticket(ticket_id, {"reason": "still broken"}, emp_headers))
    resolved = resolve_ticket(ticket_id, ctx["agent"]["id"], resolution_summary="second fix")
    assert resolved["workflow_status"] == "RESOLVED"
    assert resolved["reopen_count"] == 1
    # Second resolution at 10:00 is no later than the re-anchored 18:00 due.
    assert resolved["sla_status"] == "MET"

    _data, meta = surveys_for_ticket(ticket_id)
    assert meta["total_count"] == 1, "the reopen-resolve cycle must not issue a second survey"


def _ticket_in_progress_with_draft_article(api):
    team = make_team("KB Team")
    agent = make_agent(team["id"], tier="T1", display_name="Agent KB", email="kb@x.com")
    category = make_category(team["id"], code="KBC", name="KB Cat")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E120", full_name="Ken Base", email="ken@x.com")
    article = author_article(category["id"], KM1, title="Reset SSO", body="steps")
    ticket = create_ticket_for(employee["id"], category["id"], subject="sso broken")
    assign_ticket(ticket["id"], agent["id"])
    return {"agent": agent, "article": article, "ticket": ticket, "employee": employee}


def test_resolve_with_draft_article_rejected(api):
    """PRD §3.5: "Resolution moves `IN_PROGRESS` or `REOPENED` to `RESOLVED` under
    the same clearance rule, and the agent supplies a `resolution_summary` plus an
    optional `resolution_article_id` citing the knowledge article that solved the
    case — the cited article must be `PUBLISHED`, otherwise the resolve fails with
    `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/ticket_resolution_requires_published_article
    """
    ctx = _ticket_in_progress_with_draft_article(api)
    assert ctx["article"]["status"] == "DRAFT"

    resp = api.resolve_ticket(
        ctx["ticket"]["id"],
        {"resolution_summary": "see article", "resolution_article_id": ctx["article"]["id"]},
        make_helpdesk_agent_headers(ctx["agent"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED.value)


def test_rejected_resolve_leaves_ticket_in_progress(api):
    """PRD §3.5: "Resolution moves `IN_PROGRESS` or `REOPENED` to `RESOLVED` under
    the same clearance rule, and the agent supplies a `resolution_summary` plus an
    optional `resolution_article_id` citing the knowledge article that solved the
    case — the cited article must be `PUBLISHED`, otherwise the resolve fails with
    `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`."
    PRD §3.5: "The server stamps `resolved_at`, then sets `sla_status` to `MET` when
    the resolution instant is no later than `resolution_due_at`, and to
    `BREACHED_RESOLUTION` when it is strictly later — in both cases overwriting
    whatever of `ON_TRACK`, `AT_RISK`, or `BREACHED_RESPONSE` stood before."

    Design: Difficulty/cross_entity_state_dependency/ticket_resolution_requires_published_article
    """
    ctx = _ticket_in_progress_with_draft_article(api)

    resp = api.resolve_ticket(
        ctx["ticket"]["id"],
        {"resolution_summary": "see article", "resolution_article_id": ctx["article"]["id"]},
        make_helpdesk_agent_headers(ctx["agent"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED.value)

    data = get_ticket(ctx["ticket"]["id"])
    assert data["workflow_status"] == "IN_PROGRESS"
    assert data["resolved_at"] is None, "a rejected resolve must not stamp resolved_at"


def test_sla_attainment_seventy_five_percent(api):
    """PRD §3.6: "The SLA attainment metric for a `category_id` pools the category's
    tickets that have reached resolution at least once — `resolved_at` set, with
    `workflow_status` currently `RESOLVED`, `REOPENED`, or `CLOSED`, so a reopened
    ticket counts once by its current `sla_status` — and reports `met_count` of
    tickets at `MET`, `breached_count` at `BREACHED_RESOLUTION`, and
    `attainment_pct`: one hundred times the met count divided by the sum of the two,
    rounded half-up to one decimal place, and exactly 0.0 when the pool is empty."

    Design: Corner/calculations/sla_attainment_75pct
    """
    team = make_team("ATT Team")
    agent = make_agent(team["id"], tier="T1", email="att@x.com")
    category = make_category(team["id"], code="ATT", name="Attain")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E201", full_name="Att Ain", email="att@x.com")

    resolved_ids = []
    for subject in ("t1", "t2", "t3"):
        ticket = create_ticket_for(employee["id"], category["id"], subject=subject)
        assign_ticket(ticket["id"], agent["id"])
        resolve_ticket(ticket["id"], agent["id"], resolution_summary=f"{subject} done")
        resolved_ids.append(ticket["id"])

    t4 = create_ticket_for(employee["id"], category["id"], subject="t4")
    # 09:00 is strictly past t4's 08:00 resolution deadline.
    set_clock_to("2026-08-01T09:00:00Z")
    assign_ticket(t4["id"], agent["id"])
    late = resolve_ticket(t4["id"], agent["id"], resolution_summary="r4 late")
    assert late["sla_status"] == "BREACHED_RESOLUTION"

    metrics = validate_success(
        api.get_sla_attainment(ADMIN, params={"category_id": category["id"]})
    )
    assert metrics["met_count"] == 3
    assert metrics["breached_count"] == 1
    assert metrics["attainment_pct"] == pytest.approx(75.0, abs=1e-6)
