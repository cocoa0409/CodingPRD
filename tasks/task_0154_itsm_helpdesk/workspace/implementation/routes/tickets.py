"""Ticket routes: open/deflect, triage, work, SLA pause/resume, resolve/reopen/
close/cancel (PRD §3.2-§3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth, get_identity
from response import success_object, success_array
from services import serialize
from services.common import (
    stamp_create,
    touch,
    paginate,
    require_fields,
    require_string,
    sorted_by_created,
    recompute_queue_depth,
    recompute_linked_ticket_count,
    recompute_open_incident_count,
)
from services.sla import (
    compute_due_dates_provisional,
    recompute_due_dates_final,
    policy_for_ticket,
    whole_minutes_between,
    REOPEN_WINDOW_MINUTES,
    RESOLVE_REOPEN_PENALTY_MINUTES,
)

bp = Blueprint("tickets", __name__)

VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}
ALL_ROLES = ["PlatformAdmin", "Agent", "ChangeManager", "CabMember", "Requester"]


def _body():
    return request.get_json(silent=True) or {}


def _get_ticket_or_404(tid):
    rec = store.tickets.get(tid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Ticket not found.")
    return rec


# ---------------- Open / deflect (PRD §3.2) ----------------

@bp.route("/tickets", methods=["POST"])
def open_ticket():
    # POST /tickets tolerates an anonymous caller (PRD §2.1). If headers present,
    # role must be Requester or Agent.
    user_id, user_role = get_identity()
    if user_id and user_role:
        if user_role not in ("Requester", "Agent"):
            raise err("ERR_FORBIDDEN", "Role {} may not open a ticket.".format(user_role))

    body = _body()
    require_fields(body, ["short_description", "category_id"])
    short_description = require_string(body, "short_description")
    category_id = body["category_id"]

    # FK existence for category_id (PRD §2.5)
    category = store.categories.get(category_id)
    if category is None:
        raise err("ERR_FK_NOT_FOUND", "category_id does not resolve.")

    # priority: supplied or category default; validate enum
    priority = body.get("priority")
    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise err("ERR_INVALID_FIELD_VALUE", "priority must be one of P1..P4.")
    else:
        priority = category["default_priority"]

    asset_id = body.get("asset_id")
    if asset_id is not None and asset_id not in store.assets:
        raise err("ERR_FK_NOT_FOUND", "asset_id does not resolve.")

    kb_article_id = body.get("kb_article_id")
    accept_deflection = body.get("accept_deflection", False)
    if kb_article_id is not None and kb_article_id not in store.kb_articles:
        raise err("ERR_FK_NOT_FOUND", "kb_article_id does not resolve.")

    now = store.now()
    rec = {
        "short_description": short_description,
        "requester_id": user_id,
        "category_id": category_id,
        "priority": priority,
        "assignment_group_id": category["default_assignment_group_id"],
        "assignee_user_id": None,
        "lifecycle_state": "NEW",
        "sla_state": "RUNNING",
        "problem_id": None,
        "deflected": False,
        "reopen_count": 0,
        "opened_at": now,
        "response_due_at": None,
        "resolve_due_at": None,
        "paused_total_minutes": 0,
        "change_request_id": None,
        "asset_id": asset_id,
        "resolved_at": None,
        "pause_started_at": None,
    }
    stamp_create(rec)

    # Provisional SLA due dates (PRD §3.2)
    policy = store.sla_policies.get(category["sla_policy_id"])
    if policy is not None:
        compute_due_dates_provisional(rec, policy)

    store.tickets[rec["id"]] = rec

    # queue_depth recomputed upward (recompute reads live set)
    recompute_queue_depth(rec["assignment_group_id"])
    if asset_id is not None:
        recompute_open_incident_count(asset_id)

    # Deflection short-circuit (PRD §3.2)
    if accept_deflection is True and kb_article_id is not None:
        rec["lifecycle_state"] = "CANCELLED"
        rec["deflected"] = True
        touch(rec)
        art = store.kb_articles[kb_article_id]
        art["deflection_count"] = art.get("deflection_count", 0) + 1
        art["view_count"] = art.get("view_count", 0) + 1
        touch(art)
        # queue_depth no longer counts a CANCELLED ticket
        recompute_queue_depth(rec["assignment_group_id"])

    return success_object(serialize.ticket(rec), 201)


@bp.route("/tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    rec = _get_ticket_or_404(tid)
    return success_object(serialize.ticket(rec), 200)


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    items = list(store.tickets.values())
    for key in ("category_id", "assignment_group_id", "problem_id", "asset_id",
                "change_request_id", "requester_id", "lifecycle_state"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.ticket(t) for t in window], limit, offset, total)


# ---------------- Routing (OCC-guarded) (PRD §3.3, §2.7) ----------------

@bp.route("/tickets/<tid>/route", methods=["POST"])
def route_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    body = _body()
    require_fields(body, ["assignment_group_id", "expected_ticket_version"])
    target_group_id = body["assignment_group_id"]
    # FK existence
    target = store.assignment_groups.get(target_group_id)
    if target is None:
        raise err("ERR_FK_NOT_FOUND", "assignment_group_id does not resolve.")
    # State: PRD §3.3 frames routing as an early action moving a NEW ticket
    # between queues; "a routing ... attempted against a ticket not in the
    # required state is rejected with ERR_INVALID_STATE." Routing does NOT
    # transition lifecycle_state (only Assigning advances NEW -> ASSIGNED).
    if rec["lifecycle_state"] != "NEW":
        raise err("ERR_INVALID_STATE", "Ticket must be NEW to route.")
    # OCC check (priority after state per §3.10)
    expected = body["expected_ticket_version"]
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_ticket_version does not match current version.")

    source_group_id = rec.get("assignment_group_id")
    rec["assignment_group_id"] = target_group_id

    # OLA leg on fulfilment group
    if target.get("is_fulfilment_group"):
        policy = policy_for_ticket(rec)
        if policy is not None:
            rec["ola_due_at"] = store.now() + timedelta(minutes=policy["ola_target_minutes"])

    touch(rec)
    if source_group_id is not None:
        recompute_queue_depth(source_group_id)
    recompute_queue_depth(target_group_id)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Assign (PRD §3.3) ----------------

@bp.route("/tickets/<tid>/assign", methods=["POST"])
def assign_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    body = _body()
    require_fields(body, ["assignee_user_id"])
    assignee = require_string(body, "assignee_user_id")
    if rec["lifecycle_state"] != "NEW":
        raise err("ERR_INVALID_STATE", "Ticket must be NEW to assign.")
    rec["assignee_user_id"] = assignee
    rec["lifecycle_state"] = "ASSIGNED"
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Start work / first response (PRD §3.4) ----------------

@bp.route("/tickets/<tid>/start", methods=["POST"])
def start_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Ticket must be ASSIGNED to start.")
    if rec.get("assignee_user_id") is None:
        raise err("ERR_INVALID_STATE", "Ticket has no assignee.")

    now = store.now()
    response_due = rec.get("response_due_at")
    # Evaluate response leg BEFORE clearing response_due_at (PRD §3.4).
    if response_due is not None and now > response_due:
        rec["sla_state"] = "RESPONSE_BREACHED"
    # Record first response: clear response_due_at to null.
    rec["response_due_at"] = None
    rec["lifecycle_state"] = "IN_PROGRESS"
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Reprioritize (PRD §3.3) ----------------

@bp.route("/tickets/<tid>/reprioritize", methods=["POST"])
def reprioritize_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    body = _body()
    require_fields(body, ["priority"])
    priority = body["priority"]
    if priority not in VALID_PRIORITIES:
        raise err("ERR_INVALID_FIELD_VALUE", "priority must be one of P1..P4.")
    rec["priority"] = priority
    policy = policy_for_ticket(rec)
    if policy is not None:
        recompute_due_dates_final(rec, policy)
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Hold / Resume (PRD §3.4) ----------------

@bp.route("/tickets/<tid>/hold", methods=["POST"])
def hold_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Ticket must be IN_PROGRESS to hold.")
    rec["lifecycle_state"] = "ON_HOLD"
    rec["sla_state"] = "PAUSED"
    rec["pause_started_at"] = store.now()
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


def _resume_sla(rec):
    """Close the open paused interval, credit it back (calc sla_resume)."""
    pause_started_at = rec.get("pause_started_at")
    if pause_started_at is not None:
        delta = whole_minutes_between(store.now(), pause_started_at)
        if delta < 0:
            delta = 0
        rec["paused_total_minutes"] = rec.get("paused_total_minutes", 0) + delta
        if rec.get("resolve_due_at") is not None:
            rec["resolve_due_at"] = rec["resolve_due_at"] + timedelta(minutes=delta)
        rec["pause_started_at"] = None
    rec["sla_state"] = "RUNNING"


@bp.route("/tickets/<tid>/resume", methods=["POST"])
def resume_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "ON_HOLD":
        raise err("ERR_INVALID_STATE", "Ticket must be ON_HOLD to resume.")
    rec["lifecycle_state"] = "IN_PROGRESS"
    _resume_sla(rec)
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Attach change (PRD §3.5) ----------------

@bp.route("/tickets/<tid>/attach-change", methods=["POST"])
def attach_change(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    body = _body()
    require_fields(body, ["change_request_id"])
    change_request_id = body["change_request_id"]
    cr = store.change_requests.get(change_request_id)
    if cr is None:
        raise err("ERR_FK_NOT_FOUND", "change_request_id does not resolve.")
    if rec["lifecycle_state"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Ticket must be IN_PROGRESS to attach a change.")
    # change belongs to this ticket and is in DRAFT or PENDING_CAB
    if cr["ticket_id"] != tid or cr["state"] not in ("DRAFT", "PENDING_CAB"):
        raise err("ERR_INVALID_STATE", "Change is not attachable to this ticket.")
    rec["change_request_id"] = change_request_id
    rec["lifecycle_state"] = "PENDING_CHANGE"
    rec["sla_state"] = "PAUSED"
    rec["pause_started_at"] = store.now()
    touch(rec)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Link problem (PRD §3.8) ----------------

@bp.route("/tickets/<tid>/link-problem", methods=["POST"])
def link_problem(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    body = _body()
    require_fields(body, ["problem_id"])
    problem_id = body["problem_id"]
    if problem_id not in store.problems:
        raise err("ERR_FK_NOT_FOUND", "problem_id does not resolve.")
    rec["problem_id"] = problem_id
    touch(rec)
    recompute_linked_ticket_count(problem_id)
    return success_object(serialize.ticket(rec), 200)


# ---------------- Resolve (PRD §3.6) ----------------

@bp.route("/tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Ticket must be IN_PROGRESS to resolve.")
    # change-gated resolution (priority 9, after state per §3.10)
    if rec.get("change_request_id") is not None:
        raise err("ERR_CHANGE_GATING_RESOLUTION", "A non-terminal change gates resolution.")

    now = store.now()
    rec["lifecycle_state"] = "RESOLVED"
    rec["resolved_at"] = now
    resolve_due = rec.get("resolve_due_at")
    if resolve_due is not None and now > resolve_due:
        rec["sla_state"] = "RESOLVE_BREACHED"
    else:
        rec["sla_state"] = "MET"
    touch(rec)

    if rec.get("assignment_group_id"):
        recompute_queue_depth(rec["assignment_group_id"])
    if rec.get("problem_id"):
        recompute_linked_ticket_count(rec["problem_id"])
    return success_object(serialize.ticket(rec), 200)


# ---------------- Reopen (PRD §3.6) ----------------

@bp.route("/tickets/<tid>/reopen", methods=["POST"])
def reopen_ticket(tid):
    user_id, _ = require_auth(["Requester"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Ticket must be RESOLVED to reopen.")
    # temporal window (priority 12) — after state per §3.10
    now = store.now()
    resolved_at = rec.get("resolved_at")
    if resolved_at is None or whole_minutes_between(now, resolved_at) > REOPEN_WINDOW_MINUTES:
        raise err("ERR_REOPEN_WINDOW_CLOSED", "Reopen window has closed.")
    # ownership
    if user_id != rec.get("requester_id"):
        raise err("ERR_FORBIDDEN", "Only the ticket's requester may reopen it.")

    rec["lifecycle_state"] = "IN_PROGRESS"
    rec["reopen_count"] = rec.get("reopen_count", 0) + 1
    rec["sla_state"] = "RUNNING"
    # reopen penalty: push resolve_due_at out by 60 minutes for this event.
    if rec.get("resolve_due_at") is not None:
        rec["resolve_due_at"] = rec["resolve_due_at"] + timedelta(minutes=RESOLVE_REOPEN_PENALTY_MINUTES)
    rec["resolved_at"] = None
    touch(rec)
    if rec.get("assignment_group_id"):
        recompute_queue_depth(rec["assignment_group_id"])
    return success_object(serialize.ticket(rec), 200)


# ---------------- Close (PRD §3.6) ----------------

@bp.route("/tickets/<tid>/close", methods=["POST"])
def close_ticket(tid):
    require_auth(["Agent"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Ticket must be RESOLVED to close.")
    now = store.now()
    resolved_at = rec.get("resolved_at")
    window_elapsed = resolved_at is not None and whole_minutes_between(now, resolved_at) > REOPEN_WINDOW_MINUTES
    has_survey = any(s["ticket_id"] == tid for s in store.csat_surveys.values())
    if not (window_elapsed or has_survey):
        raise err("ERR_INVALID_STATE", "Cannot close before reopen window elapses without a survey.")
    rec["lifecycle_state"] = "CLOSED"
    touch(rec)
    if rec.get("asset_id"):
        recompute_open_incident_count(rec["asset_id"])
    return success_object(serialize.ticket(rec), 200)


# ---------------- Cancel (PRD §3.6) ----------------

@bp.route("/tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    user_id, _ = require_auth(["Requester"])
    rec = _get_ticket_or_404(tid)
    if rec["lifecycle_state"] != "NEW":
        raise err("ERR_INVALID_STATE", "Ticket must be NEW to cancel.")
    if user_id != rec.get("requester_id"):
        raise err("ERR_FORBIDDEN", "Only the ticket's requester may cancel it.")
    rec["lifecycle_state"] = "CANCELLED"
    touch(rec)
    if rec.get("assignment_group_id"):
        recompute_queue_depth(rec["assignment_group_id"])
    return success_object(serialize.ticket(rec), 200)
