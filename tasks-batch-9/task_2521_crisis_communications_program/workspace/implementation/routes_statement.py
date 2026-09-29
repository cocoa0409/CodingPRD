"""Message development, quorum routing, revision loop, publication (PRD 3.5-3.6).

Endpoints in this module (10):
  POST   /crisis/statements
  GET    /crisis/statements/{statement_id}
  GET    /crisis/statements
  POST   /crisis/statements/{statement_id}/submit-review
  POST   /crisis/statements/{statement_id}/revise
  POST   /crisis/statements/{statement_id}/publish
  POST   /crisis/statements/{statement_id}/withdraw
  GET    /crisis/approval-tasks/{task_id}
  GET    /crisis/approval-tasks
  POST   /crisis/approval-tasks/{task_id}/decide
"""

from datetime import timedelta

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    Field,
    authenticate,
    enum_filter,
    fail,
    floor_minutes,
    int_filter,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    str_filter,
    touch,
    validate_body,
)

bp = Blueprint("statement", __name__)

STATEMENT_STATES = (
    "DRAFT",
    "IN_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "PUBLISHED",
    "SUPERSEDED",
    "WITHDRAWN",
)
TASK_STATES = ("PENDING", "APPROVED", "REJECTED", "VOIDED", "EXPIRED")


def statement_incident(statement):
    incident = store.incidents.get(statement["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The statement's incident no longer resolves.")
    return incident


# ---------------------------------------------------------------------------
# Statement
# ---------------------------------------------------------------------------
@bp.post("/crisis/statements")
def create_statement():
    caller = authenticate(("CommsLead",))
    body = validate_body(
        [
            Field("incident_id", "id", required=True),
            Field("statement_type", "enum", required=True, values=L.STATEMENT_TYPES),
            Field("body", "string", required=True, max_len=4000),
            Field("expected_incident_version", "int", required=True),
            Field("privilege_marked", "bool", default=False),
            Field("supersedes_statement_id", "id", default=None, nullable=True),
        ]
    )
    # 6. foreign keys.
    incident = L.get_incident(body["incident_id"])
    predecessor = None
    if body["supersedes_statement_id"] is not None:
        predecessor = L.get_statement(body["supersedes_statement_id"])
    # 8. optimistic concurrency on the shared parent (PRD 2.8).
    if body["expected_incident_version"] != incident["version"]:
        fail(
            "ERR_STALE_INCIDENT_VERSION",
            "expected_incident_version %s does not match the incident version %s."
            % (body["expected_incident_version"], incident["version"]),
        )
    # 11. and 12.
    L.require_activated(incident)
    L.require_not_frozen(incident)
    statement = new_record(
        {
            "incident_id": incident["id"],
            "drafted_by_member_id": caller.user_id,
            "supersedes_statement_id": predecessor["id"] if predecessor else None,
            "statement_type": body["statement_type"],
            "body": body["body"],
            "privilege_marked": body["privilege_marked"],
            "state": "DRAFT",
            "revision_round": 0,
            "revision_locked": False,
            "quorum_required": 0,
            "approvals_recorded": 0,
            "submitted_at": None,
            "review_deadline_at": None,
            "approved_at": None,
            "published_at": None,
            "approval_latency_minutes": None,
            "withdraw_reason": None,
        }
    )
    store.statements[statement["id"]] = statement
    L.refresh(incident)
    touch(incident)
    return ok(statement, 201)


@bp.get("/crisis/statements/<statement_id>")
def read_statement(statement_id):
    authenticate(ALL_ROLES)
    return ok(L.get_statement(statement_id))


@bp.get("/crisis/statements")
def list_statements():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    author = str_filter("drafted_by_member_id")
    supersedes = str_filter("supersedes_statement_id")
    stype = enum_filter("statement_type", L.STATEMENT_TYPES)
    state = enum_filter("state", STATEMENT_STATES)
    rows = list(store.statements.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if author is not None:
        rows = [r for r in rows if r["drafted_by_member_id"] == author]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_statement_id"] == supersedes]
    if stype is not None:
        rows = [r for r in rows if r["statement_type"] == stype]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/statements/<statement_id>/submit-review")
def submit_review(statement_id):
    authenticate(("CommsLead",))
    validate_body([])
    statement = L.get_statement(statement_id)
    # 10. from-state.
    if statement["state"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail(
            "ERR_STATEMENT_STATE_INVALID",
            "Submission is only accepted from DRAFT or REVISION_REQUESTED.",
        )
    incident = statement_incident(statement)
    # 11. and 12.
    L.require_activated(incident)
    L.require_not_frozen(incident)
    # 18. every required seat needs a non-empty eligible pool (atomic).
    roles = L.required_approver_roles(incident, statement)
    routed = []
    for team_role in roles:
        seat = L.route_approver(incident, statement, team_role)
        if seat is None:
            fail(
                "ERR_APPROVER_UNAVAILABLE",
                "No eligible ACKNOWLEDGED %s seat is available." % team_role,
            )
        routed.append((team_role, seat))
    # 25. revision budget.
    if statement["revision_locked"]:
        fail("ERR_REVISION_LIMIT_REACHED", "The statement's revision budget is exhausted.")
    now = store.now()
    statement["state"] = "IN_REVIEW"
    statement["quorum_required"] = len(roles)
    statement["approvals_recorded"] = 0
    statement["submitted_at"] = now
    statement["review_deadline_at"] = now + timedelta(
        minutes=L.REVIEW_SLA_MINUTES[incident["severity_tier"]]
    )
    statement["approved_at"] = None
    statement["approval_latency_minutes"] = None
    touch(statement)
    for team_role, seat in routed:
        task = new_record(
            {
                "statement_id": statement["id"],
                "assignee_member_id": seat["member_id"],
                "required_team_role": team_role,
                "is_veto_seat": team_role == "LEGAL_COUNSEL",
                "revision_round": statement["revision_round"],
                "state": "PENDING",
                "decision_comment": None,
                "decided_at": None,
            }
        )
        store.tasks[task["id"]] = task
    L.refresh(incident)
    touch(incident)
    return ok(statement)


@bp.post("/crisis/statements/<statement_id>/revise")
def revise_statement(statement_id):
    authenticate(("CommsLead",))
    body = validate_body([Field("body", "string", required=True, max_len=4000)])
    statement = L.get_statement(statement_id)
    if statement["state"] != "REVISION_REQUESTED":
        fail("ERR_STATEMENT_STATE_INVALID", "Revision is only permitted from REVISION_REQUESTED.")
    incident = statement_incident(statement)
    L.require_not_frozen(incident)
    if statement["revision_locked"] or statement["revision_round"] >= L.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_REACHED", "The statement's revision budget is exhausted.")
    statement["body"] = body["body"]
    statement["revision_round"] = statement["revision_round"] + 1
    if statement["revision_round"] >= L.MAX_REVISION_ROUNDS:
        statement["revision_locked"] = True
    statement["state"] = "DRAFT"
    statement["quorum_required"] = 0
    L.recompute_approvals_recorded(statement)
    touch(statement)
    L.refresh(incident)
    return ok(statement)


@bp.post("/crisis/statements/<statement_id>/publish")
def publish_statement(statement_id):
    caller = authenticate(("CommsLead",))
    validate_body([])
    statement = L.get_statement(statement_id)
    if statement["state"] != "APPROVED":
        fail("ERR_STATEMENT_STATE_INVALID", "Only an APPROVED statement may be published.")
    incident = statement_incident(statement)
    L.require_activated(incident)
    L.require_not_frozen(incident)
    if statement["privilege_marked"]:
        L.require_privilege(caller)
    now = store.now()
    statement["state"] = "PUBLISHED"
    statement["published_at"] = now
    touch(statement)
    if statement["statement_type"] == "HOLDING" and incident["holding_statement_published_at"] is None:
        incident["holding_statement_published_at"] = now
        incident["sla_breached"] = False
    if statement["supersedes_statement_id"]:
        predecessor = store.statements.get(statement["supersedes_statement_id"])
        if predecessor is not None and predecessor["state"] == "PUBLISHED":
            predecessor["state"] = "SUPERSEDED"
            touch(predecessor)
    L.refresh(incident)
    touch(incident)
    return ok(statement)


@bp.post("/crisis/statements/<statement_id>/withdraw")
def withdraw_statement(statement_id):
    authenticate(("CommsLead", "LegalCounsel"))
    body = validate_body([Field("withdraw_reason", "string", required=True)])
    statement = L.get_statement(statement_id)
    if statement["state"] not in (
        "DRAFT",
        "IN_REVIEW",
        "REVISION_REQUESTED",
        "APPROVED",
        "PUBLISHED",
    ):
        fail(
            "ERR_STATEMENT_STATE_INVALID",
            "A SUPERSEDED or already WITHDRAWN statement cannot be withdrawn.",
        )
    incident = statement_incident(statement)
    L.require_not_frozen(incident)
    from_state = statement["state"]
    statement["state"] = "WITHDRAWN"
    statement["withdraw_reason"] = body["withdraw_reason"]
    touch(statement)
    if from_state == "IN_REVIEW":
        # Compensation: void the round and restore the conserved ledger.
        L.void_pending_round_tasks(statement)
        L.recompute_approvals_recorded(statement)
    if from_state == "PUBLISHED":
        for notice in sorted(store.notices.values(), key=lambda n: n["_seq"]):
            if notice["statement_id"] != statement["id"]:
                continue
            if notice["state"] not in ("QUEUED", "BLOCKED"):
                continue
            notice["state"] = "CANCELLED"
            notice["cancel_reason"] = "AUTO_STATEMENT_WITHDRAWN"
            touch(notice)
        if (
            statement["statement_type"] == "HOLDING"
            and incident["holding_statement_published_at"] is not None
            and incident["holding_statement_published_at"] == statement["published_at"]
        ):
            incident["holding_statement_published_at"] = None
            L.evaluate_sla_breach(incident)
    L.refresh(incident)
    touch(incident)
    return ok(statement)


# ---------------------------------------------------------------------------
# ApprovalTask
# ---------------------------------------------------------------------------
@bp.get("/crisis/approval-tasks/<task_id>")
def read_task(task_id):
    authenticate(ALL_ROLES)
    return ok(L.get_task(task_id))


@bp.get("/crisis/approval-tasks")
def list_tasks():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    statement_id = str_filter("statement_id")
    assignee = str_filter("assignee_member_id")
    revision_round = int_filter("revision_round")
    state = enum_filter("state", TASK_STATES)
    rows = list(store.tasks.values())
    if statement_id is not None:
        rows = [r for r in rows if r["statement_id"] == statement_id]
    if assignee is not None:
        rows = [r for r in rows if r["assignee_member_id"] == assignee]
    if revision_round is not None:
        rows = [r for r in rows if r["revision_round"] == revision_round]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    # Pinned creation order is exactly the default created_at/_seq ordering.
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/approval-tasks/<task_id>/decide")
def decide_task(task_id):
    caller = authenticate(("IncidentLead", "LegalCounsel", "CommsLead", "ExecSponsor"))
    body = validate_body(
        [
            Field("decision", "enum", required=True, values=("APPROVE", "REJECT")),
            Field("decision_comment", "string", default=None, nullable=True),
        ]
    )
    task = L.get_task(task_id)
    # 7. ownership binding.
    if caller.user_id != task["assignee_member_id"]:
        fail("ERR_ROLE_NOT_PERMITTED", "Only the routed assignee may decide this task.")
    # 10. from-states.
    if task["state"] != "PENDING":
        fail("ERR_APPROVAL_TASK_NOT_PENDING", "The approval task is no longer PENDING.")
    statement = store.statements.get(task["statement_id"])
    if statement is None:
        fail("ERR_STATEMENT_NOT_FOUND", "The task's statement no longer resolves.")
    if statement["state"] != "IN_REVIEW":
        fail("ERR_STATEMENT_NOT_IN_REVIEW", "The statement is not IN_REVIEW.")
    incident = statement_incident(statement)
    # 13. privilege circle.
    if statement["privilege_marked"]:
        L.require_privilege(caller)
    # 14. segregation of duties.
    if caller.user_id == statement["drafted_by_member_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The drafter may not decide their own statement.")
    # 20. review deadline: a decision exactly at the deadline still counts.
    if statement["review_deadline_at"] is not None and store.now() > statement["review_deadline_at"]:
        fail("ERR_REVIEW_DEADLINE_PASSED", "The review deadline has passed.")

    now = store.now()
    task["decision_comment"] = body["decision_comment"]
    task["decided_at"] = now
    if body["decision"] == "APPROVE":
        task["state"] = "APPROVED"
        touch(task)
        L.recompute_approvals_recorded(statement)
        pending = [t for t in L.round_tasks(statement) if t["state"] == "PENDING"]
        if not pending and statement["approvals_recorded"] == statement["quorum_required"]:
            statement["state"] = "APPROVED"
            statement["approved_at"] = now
            statement["approval_latency_minutes"] = floor_minutes(statement["submitted_at"], now)
            L.unblock_notices(statement)
        touch(statement)
        L.refresh(incident)
    else:
        task["state"] = "REJECTED"
        touch(task)
        L.recompute_approvals_recorded(statement)
        L.push_revision_requested(statement, incident, exclude_task_id=task["id"])
        L.refresh(incident)
        touch(incident)
    return ok(task)
