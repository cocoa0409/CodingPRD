"""Ticket assignment, optimistic concurrency, confidentiality masking, and
derived workload counters (PRD §2.7, §2.9, §3.1, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_employee_headers,
    make_helpdesk_agent_headers,
    make_sensitive_case_manager_headers,
    make_specialist_agent_headers,
    assert_open_ticket_conservation,
    assert_version_incremented,
    make_team,
    make_agent,
    make_category,
    make_sla_policy,
    make_employee,
    create_ticket_for,
    get_ticket,
    assign_ticket,
    resolve_ticket,
    MASKED_PLACEHOLDER,
)

ADMIN = TEST_USERS["admin_headers"]


def test_ticket_list_employee_scope(api):
    """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee`; ownership checks on any resource that references an employee —
    a ticket's `employee_id`, a survey's `employee_id`, a data change request's
    `employee_id`, an article view's `employee_id`, an audit entry's `employee_id` —
    compare that foreign key against `X-User-ID`, and list endpoints visible to this
    role are force-scoped to the caller's own records."
    PRD §3.5: "callers in the `Employee` role see only their own tickets."

    Design: Corner/endpoints/ticket_list_employee_scope
    """
    team = make_team("SC Team")
    category = make_category(team["id"], code="SCO", name="Scope")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    e1 = make_employee(employee_number="E402", full_name="One Uno", email="uno@x.com")
    e2 = make_employee(employee_number="E403", full_name="Two Dos", email="dos@x.com")
    create_ticket_for(e1["id"], category["id"], subject="t1")
    create_ticket_for(e2["id"], category["id"], subject="t2")

    data, meta = validate_paginated(api.list_tickets(make_employee_headers(e1["id"])))
    assert meta["total_count"] == 1, f"an employee must see only their own tickets, got {meta['total_count']}"
    assert data[0]["employee_id"] == e1["id"]


def test_sensitive_ticket_masked_read(api):
    """PRD §2.7: "Reads behave differently: rather than being rejected, they are
    masked. When the reader lacks `SENSITIVE` clearance and is not the owning
    employee, a sensitive ticket's `subject` and `description` are returned as the
    literal placeholder `[REDACTED]`, and the computed `masked` flag on the response
    is true; the owning employee and `SENSITIVE`-cleared staff see the full text with
    `masked` false."
    PRD §2.10: "5. **Record-level ownership.** For an `Employee` caller acting on a
    specific located resource, the resource's owning `employee_id` must equal the
    caller's `X-User-ID`. Failures: `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/endpoints/sensitive_ticket_masked_read
    """
    team = make_team("MSK Team")
    category = make_category(team["id"], code="MSK", name="Sensitive", is_sensitive=True)
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    owner = make_employee(employee_number="E404", full_name="Own Er", email="own@x.com")
    other = make_employee(employee_number="E405", full_name="Oth Er", email="oth@x.com")
    ticket = create_ticket_for(owner["id"], category["id"],
                               subject="private matter", description="details")
    assert ticket["sensitive"] is True
    std = make_agent(team["id"], tier="T1", clearance="STANDARD",
                     display_name="Std", email="std@x.com")
    sen = make_agent(team["id"], tier="T1", clearance="SENSITIVE",
                     display_name="Sen", email="sen@x.com")

    masked = validate_success(
        api.get_ticket(ticket["id"], make_helpdesk_agent_headers(std["id"]))
    )
    assert masked["masked"] is True
    assert masked["subject"] == MASKED_PLACEHOLDER
    assert masked["description"] == MASKED_PLACEHOLDER

    full = validate_success(
        api.get_ticket(ticket["id"], make_sensitive_case_manager_headers(sen["id"]))
    )
    assert full["masked"] is False
    assert full["subject"] == "private matter"

    owned = validate_success(api.get_ticket(ticket["id"], make_employee_headers(owner["id"])))
    assert owned["subject"] == "private matter", "the owning employee sees the full text"

    resp = api.get_ticket(ticket["id"], make_employee_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_occ_stale_ticket_assign_rejected(api):
    """PRD §2.9: "`POST /hr-helpdesk/tickets/{id}/assign` requires the non-optional
    request field `expected_ticket_version`, carrying the caller's last observed
    `version` of the target Ticket. If that value does not equal the ticket's current
    `version` — because another writer has advanced the ticket since the caller last
    read it — the assignment is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412)."
    PRD §2.9: "Reassignment is legitimate product behavior: a ticket may be re-homed
    from one agent to another, so staleness is detected purely through this version
    check, never through any state precondition."

    Design: Corner/cross_cutting_layers/occ_stale_ticket_assign_rejected
    """
    team = make_team("OCC Team")
    a1 = make_agent(team["id"], tier="T1", display_name="A1", email="o1@x.com")
    a2 = make_agent(team["id"], tier="T1", display_name="A2", email="o2@x.com")
    category = make_category(team["id"], code="OCC", name="OCC")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E601", full_name="Occ Curre", email="occ@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="s")
    observed_version = ticket["version"]

    assigned = validate_success(
        api.assign_ticket(
            ticket["id"],
            {"agent_id": a1["id"], "expected_ticket_version": observed_version},
            make_helpdesk_agent_headers(a1["id"]),
        )
    )
    assert_version_incremented(assigned["version"], observed_version)

    # Assignment is defined only from NEW/TRIAGED/ESCALATED/REOPENED (PRD §3.5),
    # so the ticket — now IN_PROGRESS — is cycled through RESOLVED back to
    # REOPENED (still assigned to a1) before the stale reassign attempt. This
    # keeps the version advanced past the caller's last observed value while
    # landing the ticket in a state where the OCC check (not the state check)
    # is the rejecting tier.
    resolve_ticket(ticket["id"], a1["id"], resolution_summary="fixed")
    validate_success(
        api.reopen_ticket(ticket["id"], {"reason": "still broken"},
                          make_employee_headers(employee["id"]))
    )

    resp = api.assign_ticket(
        ticket["id"],
        {"agent_id": a2["id"], "expected_ticket_version": observed_version},
        make_helpdesk_agent_headers(a2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TICKET_VERSION.value)

    data = get_ticket(ticket["id"])
    assert data["assigned_agent_id"] == a1["id"], "the stale assign must not re-home the ticket"


def _two_agent_queue(api):
    """Two SENSITIVE T1 agents and a sensitive-category ticket.

    The category is sensitive so intake performs the §3.4 sensitive
    auto-assignment: the ticket opens NEW with the earlier-created agent (a1)
    already assigned. NEW is an assignable from-state (§3.5) and NEW tickets
    count toward assigned_open_count (§3.1), so the reassignment tests can
    re-home the ticket a1 -> a2 directly from its intake state."""
    team = make_team("WL Team")
    a1 = make_agent(team["id"], tier="T1", clearance="SENSITIVE",
                    display_name="A1", email="a1@x.com", capacity_max=10)
    a2 = make_agent(team["id"], tier="T1", clearance="SENSITIVE",
                    display_name="A2", email="a2@x.com", capacity_max=10)
    category = make_category(team["id"], code="WLC", name="WL Cat", is_sensitive=True)
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E140", full_name="Will Load", email="will@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="wl")
    assert ticket["assigned_agent_id"] == a1["id"], (
        "sensitive intake must auto-assign the earliest SENSITIVE agent (a1)"
    )
    assert ticket["workflow_status"] == "NEW"
    return a1, a2, ticket


def test_reassign_moves_open_count_between_agents(api):
    """PRD §3.1: "Two computed fields describe the agent's live load and health:
    `assigned_open_count` counts tickets currently assigned to the agent in
    `TRIAGED`, `IN_PROGRESS`, `PENDING_EMPLOYEE`, or `ESCALATED`, plus tickets still
    in `NEW` — a combination that occurs only through the sensitive auto-assignment
    at intake described in §3.4; and `rolling_csat`, the recency-weighted
    satisfaction mean of §3.8, which stays null until the agent has at least one
    submitted survey inside the measurement window."
    PRD §3.5: "The effects are: `assigned_agent_id` is set, an `ASSIGNED` event is
    appended (an `UNASSIGNED` and `ASSIGNED` pair when a prior agent is being
    replaced), and the ticket's `version` increments."

    Design: Difficulty/compensating_invariant/agent_workload_conserved_across_assign_reassign
    """
    a1, a2, ticket = _two_agent_queue(api)
    # Intake auto-assigned the NEW ticket to a1 (a1's assigned_open_count is 1);
    # reassigning to a2 re-homes it NEW -> IN_PROGRESS.
    assign_ticket(ticket["id"], a2["id"])

    agent_a1 = validate_success(api.get_agent(a1["id"], ADMIN))
    agent_a2 = validate_success(api.get_agent(a2["id"], ADMIN))
    assert agent_a1["assigned_open_count"] == 0, "the reassign debits the previous agent"
    assert agent_a2["assigned_open_count"] == 1, "the reassign credits the new agent"
    assert_open_ticket_conservation(agent_a1, agent_a2, expected_total=1)


def test_reassign_updates_ticket_assignee_and_version(api):
    """PRD §2.9: "Reassignment is legitimate product behavior: a ticket may be
    re-homed from one agent to another, so staleness is detected purely through this
    version check, never through any state precondition."
    PRD §3.5: "The effects are: `assigned_agent_id` is set, an `ASSIGNED` event is
    appended (an `UNASSIGNED` and `ASSIGNED` pair when a prior agent is being
    replaced), and the ticket's `version` increments."
    PRD §3.5: "Assignment moves a ticket from any of `NEW`, `TRIAGED`, `ESCALATED`,
    or `REOPENED` to `IN_PROGRESS`."

    Design: Difficulty/compensating_invariant/agent_workload_conserved_across_assign_reassign
    """
    a1, a2, ticket = _two_agent_queue(api)
    # Intake auto-assigned the NEW ticket to a1; reassigning to a2 replaces the
    # prior agent and moves NEW -> IN_PROGRESS.
    second = assign_ticket(ticket["id"], a2["id"])

    assert second["assigned_agent_id"] == a2["id"]
    assert second["workflow_status"] == "IN_PROGRESS"
    assert_version_incremented(second["version"], ticket["version"])

    events = [e["event_type"] for e in
              validate_paginated(api.list_ticket_events(ticket["id"], ADMIN))[0]]
    assert "UNASSIGNED" in events and "ASSIGNED" in events, (
        "replacing a prior agent appends the UNASSIGNED/ASSIGNED pair"
    )


def test_capacity_boundary_at_capacity_rejected(api):
    """PRD §3.5: "Three fit checks follow: the assignee's `assigned_open_count` must
    be strictly below their `capacity_max` (otherwise `ERR_AGENT_AT_CAPACITY`, and
    recall that a `capacity_max` of 0 renders an agent unassignable); a sensitive
    ticket accepts only an assignee whose `clearance` is `SENSITIVE` (otherwise
    `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`); and the assignee's `tier` must equal
    the ticket's current `tier` (otherwise `ERR_AGENT_TIER_INSUFFICIENT`)."

    Design: Corner/validations/capacity_boundary_at_capacity_rejected
    """
    team = make_team("CAP Team")
    agent = make_agent(team["id"], tier="T1", email="cap@x.com", capacity_max=1)
    category = make_category(team["id"], code="CAP", name="Cap")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E315", full_name="Cap City", email="cap@x.com")
    t1 = create_ticket_for(employee["id"], category["id"], subject="t1")
    t2 = create_ticket_for(employee["id"], category["id"], subject="t2")
    assign_ticket(t1["id"], agent["id"])  # fills the single capacity slot

    resp = api.assign_ticket(
        t2["id"],
        {"agent_id": agent["id"], "expected_ticket_version": t2["version"]},
        make_helpdesk_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_AT_CAPACITY.value)

    data = get_ticket(t2["id"])
    assert data["workflow_status"] == "NEW"
    assert data["assigned_agent_id"] is None


def test_agent_tier_mismatch_assign_rejected(api):
    """PRD §3.5: "Three fit checks follow: the assignee's `assigned_open_count` must
    be strictly below their `capacity_max` (otherwise `ERR_AGENT_AT_CAPACITY`, and
    recall that a `capacity_max` of 0 renders an agent unassignable); a sensitive
    ticket accepts only an assignee whose `clearance` is `SENSITIVE` (otherwise
    `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`); and the assignee's `tier` must equal
    the ticket's current `tier` (otherwise `ERR_AGENT_TIER_INSUFFICIENT`)."

    Design: Corner/validations/agent_tier_mismatch_assign_rejected
    """
    team = make_team("TIER Team")
    sp = make_agent(team["id"], tier="T2", display_name="SP", email="tier@x.com")
    category = make_category(team["id"], code="TIR", name="Tier")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E314", full_name="Tia Tier", email="tia@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="s")
    assert ticket["tier"] == "T1"

    resp = api.assign_ticket(
        ticket["id"],
        {"agent_id": sp["id"], "expected_ticket_version": ticket["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_TIER_INSUFFICIENT.value)

    data = get_ticket(ticket["id"])
    assert data["workflow_status"] == "NEW"
    assert data["assigned_agent_id"] is None


def _sensitive_ticket_and_capped_standard_agent(api):
    team = make_team("Sec Team")
    category = make_category(team["id"], code="SEC", name="Sensitive", is_sensitive=True)
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E900", full_name="Sue Secret", email="sue@x.com")
    # No SENSITIVE-clearance agent exists, so intake leaves the ticket unassigned.
    ticket = create_ticket_for(employee["id"], category["id"], subject="confidential")
    assert ticket["assigned_agent_id"] is None and ticket["workflow_status"] == "NEW"
    agent_x = make_agent(team["id"], tier="T1", clearance="STANDARD", capacity_max=0,
                         display_name="Std Agent", email="std@x.com")
    return ticket, agent_x


def test_assign_sensitive_to_uncleared_agent_reports_clearance_error(api):
    """PRD §2.10: "When several checks could reject the same request, they are
    evaluated in the following fixed order, and the earliest failing tier determines
    the response:"
    PRD §2.10: "7. **Business safety.** Confidentiality clearance on writes to
    sensitive tickets (`ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`, 403); the fraud gate
    on approval (`ERR_FRAUD_VERIFICATION_REQUIRED`, 409); the employee-active gate on
    data change creation and approval (`ERR_EMPLOYEE_INACTIVE`, 422); and the
    segregation-of-duties rules (`ERR_AUTHOR_CANNOT_PUBLISH`,
    `ERR_SELF_APPROVAL_FORBIDDEN`, `ERR_VERIFIER_CANNOT_APPROVE`, all 403)."
    PRD §2.10: "8. **Business constraints.** Capacity (`ERR_AGENT_AT_CAPACITY`, 409),
    tier match (`ERR_AGENT_TIER_INSUFFICIENT`, 409), specialist pool emptiness
    (`ERR_NO_ELIGIBLE_SPECIALIST`, 422), interval overlaps (`ERR_SHIFT_OVERLAP`,
    `ERR_WINDOW_OVERLAP`, 409), uniqueness (`ERR_SLA_POLICY_DUPLICATE`,
    `ERR_DUPLICATE_DATA_CHANGE_PENDING`, `ERR_DUPLICATE_EMPLOYEE_NUMBER`,
    `ERR_DUPLICATE_CATEGORY_CODE`, 409), and the two optimistic-concurrency checks
    (`ERR_STALE_TICKET_VERSION`, `ERR_STALE_EMPLOYEE_VERSION`, 412)."

    Design: Difficulty/priority_pair_validation_conflict/assign_sensitive_uncleared_at_capacity_safety_beats_constraint
    """
    ticket, agent_x = _sensitive_ticket_and_capped_standard_agent(api)

    # The assignee violates both the confidentiality rule (sensitive ticket,
    # STANDARD clearance; tier 7) and the capacity rule (capacity_max 0; tier 8).
    resp = api.assign_ticket(
        ticket["id"],
        {"agent_id": agent_x["id"], "expected_ticket_version": ticket["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED.value)


def test_failed_confidentiality_assign_leaves_ticket_unassigned(api):
    """PRD §3.5: "Three fit checks follow: the assignee's `assigned_open_count` must
    be strictly below their `capacity_max` (otherwise `ERR_AGENT_AT_CAPACITY`, and
    recall that a `capacity_max` of 0 renders an agent unassignable); a sensitive
    ticket accepts only an assignee whose `clearance` is `SENSITIVE` (otherwise
    `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`); and the assignee's `tier` must equal
    the ticket's current `tier` (otherwise `ERR_AGENT_TIER_INSUFFICIENT`)."
    PRD §3.4: "An empty pool simply leaves the ticket unassigned in `NEW`, waiting
    for triage."

    Design: Difficulty/priority_pair_validation_conflict/assign_sensitive_uncleared_at_capacity_safety_beats_constraint
    """
    ticket, agent_x = _sensitive_ticket_and_capped_standard_agent(api)

    resp = api.assign_ticket(
        ticket["id"],
        {"agent_id": agent_x["id"], "expected_ticket_version": ticket["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED.value)

    data = get_ticket(ticket["id"])
    assert data["assigned_agent_id"] is None
    assert data["workflow_status"] == "NEW"


def test_specialist_cannot_assign_others(api):
    """PRD §3.5: "`SpecialistAgent` and `SensitiveCaseManager` callers may only
    self-assign — the supplied `agent_id` must equal the caller's `X-User-ID`, and
    attempts to assign someone else are rejected as scope violations with
    `ERR_FORBIDDEN_ROLE` — while `HelpDeskAgent` and `HRServicesAdmin` may assign any
    eligible agent."

    Design: Corner/rbac/specialist_cannot_assign_others
    """
    team = make_team("SA Team")
    sp = make_agent(team["id"], tier="T2", display_name="SP", email="sp2@x.com")
    a1 = make_agent(team["id"], tier="T1", display_name="A1", email="a1b@x.com")
    category = make_category(team["id"], code="SA", name="SA")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E504", full_name="Self Assign", email="sa@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="s")

    resp = api.assign_ticket(
        ticket["id"],
        {"agent_id": a1["id"], "expected_ticket_version": ticket["version"]},
        make_specialist_agent_headers(sp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    data = get_ticket(ticket["id"])
    assert data["workflow_status"] == "NEW"
    assert data["assigned_agent_id"] is None


def test_open_ticket_count_reconciliation(api):
    """PRD §3.1: "`has_pending_dcr`, initially false, is true exactly while any data
    change request of the employee sits in `PENDING_VERIFICATION` or
    `PENDING_APPROVAL`, and is maintained on request creation, approval, rejection,
    and cancellation — every flip bumps the employee's `version`;
    `open_ticket_count` is the computed count of the employee's tickets in `NEW`,
    `TRIAGED`, `IN_PROGRESS`, `PENDING_EMPLOYEE`, `ESCALATED`, or `REOPENED`."
    PRD §3.5: "Cancelling moves `NEW` or `TRIAGED` to `CANCELLED` at the owner's
    request, optionally with a `reason`, and clears `assigned_agent_id`."

    Design: Corner/cross_cutting_layers/open_ticket_count_reconciliation
    """
    team = make_team("REC Team")
    category = make_category(team["id"], code="REC", name="Rec")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E603", full_name="Rec Oncile", email="rec@x.com")
    t1 = create_ticket_for(employee["id"], category["id"], subject="t1")
    create_ticket_for(employee["id"], category["id"], subject="t2")

    after_create = validate_success(api.get_employee(employee["id"], ADMIN))
    assert after_create["open_ticket_count"] == 2

    validate_success(
        api.cancel_ticket(t1["id"], {"reason": "duplicate"},
                          make_employee_headers(employee["id"]))
    )
    after_cancel = validate_success(api.get_employee(employee["id"], ADMIN))
    assert after_cancel["open_ticket_count"] == 1, (
        "the CANCELLED ticket leaves the open set on the very next read"
    )
