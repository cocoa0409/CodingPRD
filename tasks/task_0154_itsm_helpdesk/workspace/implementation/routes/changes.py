"""ChangeRequest / CabVote routes: raise, submit, vote (CAB tally, SoD, OCC),
implement, fail, and the bubble-up cascade to the gated ticket (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from response import success_object, success_array
from services import serialize
from services.common import (
    stamp_create,
    touch,
    paginate,
    require_fields,
    require_string,
    sorted_by_created,
    recompute_change_tally,
)
from services.sla import whole_minutes_between, REJECT_VETO_THRESHOLD

bp = Blueprint("changes", __name__)

VALID_RISK = {"LOW", "MEDIUM", "HIGH"}
VALID_DECISION = {"APPROVE", "REJECT"}
QUORUM_FOR_RISK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
ALL_ROLES = ["PlatformAdmin", "Agent", "ChangeManager", "CabMember", "Requester"]


def _body():
    return request.get_json(silent=True) or {}


def _get_change_or_404(cid):
    rec = store.change_requests.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Change request not found.")
    return rec


@bp.route("/change-requests", methods=["POST"])
def create_change():
    user_id, _ = require_auth(["ChangeManager"])
    body = _body()
    require_fields(body, ["title", "ticket_id", "risk"])
    title = require_string(body, "title")
    ticket_id = body["ticket_id"]
    risk = body["risk"]
    if ticket_id not in store.tickets:
        raise err("ERR_FK_NOT_FOUND", "ticket_id does not resolve.")
    if risk not in VALID_RISK:
        raise err("ERR_INVALID_FIELD_VALUE", "risk must be one of LOW/MEDIUM/HIGH.")
    rec = {
        "title": title,
        "ticket_id": ticket_id,
        "raised_by_user_id": user_id,
        "risk": risk,
        "state": "DRAFT",
        "required_approvals": None,
        "approve_count": 0,
        "reject_count": 0,
    }
    stamp_create(rec)
    store.change_requests[rec["id"]] = rec
    return success_object(serialize.change_request(rec), 201)


@bp.route("/change-requests/<cid>", methods=["GET"])
def get_change(cid):
    rec = _get_change_or_404(cid)
    return success_object(serialize.change_request(rec), 200)


@bp.route("/change-requests", methods=["GET"])
def list_changes():
    items = list(store.change_requests.values())
    ticket_id = request.args.get("ticket_id")
    state = request.args.get("state")
    if ticket_id is not None:
        items = [c for c in items if c["ticket_id"] == ticket_id]
    if state is not None:
        items = [c for c in items if c["state"] == state]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.change_request(c) for c in window], limit, offset, total)


@bp.route("/change-requests/<cid>/submit", methods=["POST"])
def submit_change(cid):
    user_id, _ = require_auth(["ChangeManager"])
    rec = _get_change_or_404(cid)
    if rec["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Change must be DRAFT to submit.")
    if user_id != rec["raised_by_user_id"]:
        raise err("ERR_FORBIDDEN", "Only the raising manager may submit this change.")
    rec["state"] = "PENDING_CAB"
    rec["required_approvals"] = QUORUM_FOR_RISK[rec["risk"]]
    rec["approve_count"] = 0
    rec["reject_count"] = 0
    touch(rec)
    return success_object(serialize.change_request(rec), 200)


def _resume_gated_ticket(ticket):
    """Bubble-up cascade: PENDING_CHANGE -> IN_PROGRESS, resume SLA (PRD §3.5)."""
    if ticket["lifecycle_state"] != "PENDING_CHANGE":
        return
    pause_started_at = ticket.get("pause_started_at")
    if pause_started_at is not None:
        delta = whole_minutes_between(store.now(), pause_started_at)
        if delta < 0:
            delta = 0
        ticket["paused_total_minutes"] = ticket.get("paused_total_minutes", 0) + delta
        if ticket.get("resolve_due_at") is not None:
            ticket["resolve_due_at"] = ticket["resolve_due_at"] + timedelta(minutes=delta)
        ticket["pause_started_at"] = None
    ticket["lifecycle_state"] = "IN_PROGRESS"
    ticket["sla_state"] = "RUNNING"
    ticket["change_request_id"] = None
    touch(ticket)


@bp.route("/change-requests/<cid>/votes", methods=["POST"])
def cast_vote(cid):
    user_id, _ = require_auth(["CabMember"])
    rec = _get_change_or_404(cid)
    body = _body()
    require_fields(body, ["decision", "expected_change_request_version"])
    decision = body["decision"]
    expected = body["expected_change_request_version"]

    # State: must be PENDING_CAB to accept votes (priority 5, before OCC).
    if rec["state"] != "PENDING_CAB":
        raise err("ERR_INVALID_STATE", "Change is not open for voting.")
    # OCC (priority 6)
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_change_request_version does not match current version.")
    # SoD (priority 7) before duplicate-vote (priority 8)
    if user_id == rec["raised_by_user_id"]:
        raise err("ERR_SOD_VIOLATION", "The change raiser may not vote on their own change.")
    for v in store.cab_votes.values():
        if v["change_request_id"] == cid and v["voter_user_id"] == user_id:
            raise err("ERR_DUPLICATE_VOTE", "This member already voted on this change.")
    # decision enum (priority 16)
    if decision not in VALID_DECISION:
        raise err("ERR_INVALID_FIELD_VALUE", "decision must be APPROVE or REJECT.")

    # Append immutable vote (CabVote: id + created_at only, no version/updated_at).
    vote = {
        "change_request_id": cid,
        "voter_user_id": user_id,
        "decision": decision,
    }
    stamp_create(vote, with_version=False)
    store.cab_votes[vote["id"]] = vote

    # Recompute tally from distinct voters (PRD §3.5)
    recompute_change_tally(rec)

    # Pinned evaluation order: on APPROVE evaluate quorum; on REJECT evaluate veto.
    transitioned = False
    if decision == "APPROVE":
        if rec["approve_count"] >= rec["required_approvals"]:
            rec["state"] = "APPROVED"
            transitioned = True
    elif decision == "REJECT":
        if rec["reject_count"] >= REJECT_VETO_THRESHOLD:
            rec["state"] = "REJECTED"
            transitioned = True

    # The vote increments the change's version (PRD §3.5).
    touch(rec)

    # Bubble-up cascade to gated ticket on APPROVED/REJECTED
    if transitioned:
        ticket = store.tickets.get(rec["ticket_id"])
        if ticket is not None:
            _resume_gated_ticket(ticket)

    return success_object(serialize.cab_vote(vote), 201)


@bp.route("/change-requests/<cid>/votes", methods=["GET"])
def list_votes(cid):
    _get_change_or_404(cid)
    items = [v for v in store.cab_votes.values() if v["change_request_id"] == cid]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.cab_vote(v) for v in window], limit, offset, total)


@bp.route("/change-requests/<cid>/implement", methods=["POST"])
def implement_change(cid):
    require_auth(["ChangeManager"])
    rec = _get_change_or_404(cid)
    if rec["state"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Change must be APPROVED to implement.")
    rec["state"] = "IMPLEMENTED"
    touch(rec)
    return success_object(serialize.change_request(rec), 200)


@bp.route("/change-requests/<cid>/fail", methods=["POST"])
def fail_change(cid):
    require_auth(["ChangeManager"])
    rec = _get_change_or_404(cid)
    if rec["state"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Change must be APPROVED to fail.")
    rec["state"] = "FAILED"
    touch(rec)
    return success_object(serialize.change_request(rec), 200)
