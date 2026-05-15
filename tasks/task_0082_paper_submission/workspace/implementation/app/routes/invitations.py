"""Reviewer invitation endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from ..auth import require_auth
from ..calculations import (
    COI_REJECT_THRESHOLD,
    REVIEWER_MAX_CONCURRENT,
    coi_score_from_signals,
    coi_signals,
    match_score,
)
from ..clock import clock
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..store import fmt_ts, store
from ..utils import (
    get_json_body,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_str,
)


invitations_bp = Blueprint("invitations", __name__)


def _author_rows_for_manuscript(m: dict) -> list[dict]:
    ids = [m["corresponding_author_id"]] + list(m.get("co_author_ids") or [])
    rows = []
    for aid in ids:
        a = store.authors.get(aid)
        if a:
            rows.append(a)
    return rows


def _existing_invitation(manuscript_id: str, reviewer_id: str, revision_round: int) -> dict | None:
    for inv in store.reviewer_invitations.values():
        if (
            inv["manuscript_id"] == manuscript_id
            and inv["reviewer_id"] == reviewer_id
            and inv["revision_round"] == revision_round
        ):
            return inv
    return None


def _create_invitation_row(m: dict, reviewer_id: str) -> dict:
    """Internal helper used by both /manuscripts/{id}/invitations and
    /manuscripts/{id}/reinvite-reviewers. Caller must hold store.lock and have
    verified the reviewer exists.

    Raises ERR_REVIEWER_EXCLUDED_BY_AUTHOR, ERR_REVIEWER_CONFLICT, or
    ERR_INVITATION_ALREADY_EXISTS as appropriate.
    """
    rev = store.reviewers.get(reviewer_id)
    if not rev:
        raise api_error("ERR_NOT_FOUND", "reviewer_id does not exist")

    # uniqueness on (manuscript_id, reviewer_id, revision_round)
    if _existing_invitation(m["id"], reviewer_id, m["revision_round"]):
        raise api_error("ERR_INVITATION_ALREADY_EXISTS",
                        "Invitation already exists for this reviewer at this round")

    # COI scoring
    authors = _author_rows_for_manuscript(m)
    s_co, s_inst, s_exc = coi_signals(authors, rev, m.get("excluded_reviewer_ids") or [])
    coi = coi_score_from_signals(s_co, s_inst, s_exc)
    # Distinct error when ONLY signal is excluded-by-author
    if s_exc and not s_co and not s_inst:
        raise api_error(
            "ERR_REVIEWER_EXCLUDED_BY_AUTHOR",
            "Reviewer is in the author's excluded list",
        )
    if coi >= COI_REJECT_THRESHOLD:
        raise api_error("ERR_REVIEWER_CONFLICT", f"coi_score {coi} >= threshold")

    ms = match_score(m, rev)
    now = clock.now()
    deadline = now + timedelta(days=7)
    inv = {
        "manuscript_id": m["id"],
        "reviewer_id": reviewer_id,
        "revision_round": m["revision_round"],
        "response_deadline_at": fmt_ts(deadline),
        "status": "PENDING",
        "coi_score": coi,
        "match_score": ms,
    }
    store.stamp_create(inv)
    store.reviewer_invitations[inv["id"]] = inv
    store.append_audit(
        actor_role=g.user_role,
        actor_id=g.user_id,
        entity="ReviewerInvitation",
        entity_id=inv["id"],
        action="INVITATION_CREATED",
        from_state=None,
        to_state="PENDING",
        details={"reviewer_id": reviewer_id, "revision_round": inv["revision_round"]},
    )
    return inv


@invitations_bp.route("/manuscripts/<mid>/invitations", methods=["POST"])
@require_auth(["AssociateEditor"])
def create_invitation(mid: str):
    body = get_json_body()
    reviewer_id = require_str(body, "reviewer_id")
    with store.lock:
        m = store.manuscripts.get(mid)
        if not m:
            raise api_error("ERR_NOT_FOUND", "Manuscript not found")
        if g.user_id != m.get("associate_editor_id"):
            raise api_error("ERR_FORBIDDEN", "Caller is not the assigned associate editor")
        if m["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in UNDER_REVIEW state")
        inv = _create_invitation_row(m, reviewer_id)
        return success_envelope(inv, status=201, response_type="object")


@invitations_bp.route("/manuscripts/<mid>/invitations", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor"])
def list_invitations(mid: str):
    m = store.manuscripts.get(mid)
    if not m:
        raise api_error("ERR_NOT_FOUND", "Manuscript not found")
    limit, offset = parse_pagination()
    rd_filter = request.args.get("revision_round")
    status_filter = request.args.get("status")
    rows = [i for i in store.reviewer_invitations.values() if i["manuscript_id"] == mid]
    rows.sort(key=lambda r: r["created_at"])
    if rd_filter is not None:
        try:
            rd_val = int(rd_filter)
        except ValueError:
            raise api_error("ERR_VALIDATION", "revision_round must be an integer")
        rows = [r for r in rows if r["revision_round"] == rd_val]
    if status_filter:
        rows = [r for r in rows if r.get("status") == status_filter]
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)


def _resolve_invitation(mid: str, iid: str) -> tuple[dict, dict]:
    m = store.manuscripts.get(mid)
    if not m:
        raise api_error("ERR_NOT_FOUND", "Manuscript not found")
    inv = store.reviewer_invitations.get(iid)
    if not inv or inv["manuscript_id"] != mid:
        raise api_error("ERR_NOT_FOUND", "Invitation not found")
    return m, inv


@invitations_bp.route("/manuscripts/<mid>/invitations/<iid>/accept", methods=["POST"])
@require_auth(["Reviewer"])
def accept_invitation(mid: str, iid: str):
    with store.lock:
        m, inv = _resolve_invitation(mid, iid)
        if g.user_id != inv["reviewer_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the invited reviewer")
        if inv["status"] != "PENDING":
            raise api_error("ERR_INVALID_STATE", "Invitation not pending")
        if m["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in UNDER_REVIEW state")
        # Deadline check
        deadline_dt = parse_iso_datetime(inv["response_deadline_at"])
        if clock.now() > deadline_dt:
            raise api_error("ERR_INVITATION_DEADLINE_PASSED", "Response deadline has passed")
        rev = store.reviewers.get(inv["reviewer_id"])
        if not rev:
            raise api_error("ERR_NOT_FOUND", "Reviewer not found")
        # Capacity: active_assignments + 1 must not exceed REVIEWER_MAX_CONCURRENT
        if rev.get("active_assignments", 0) + 1 > REVIEWER_MAX_CONCURRENT:
            raise api_error("ERR_REVIEWER_OVERLOADED",
                            "Accepting would exceed reviewer max concurrent capacity")
        prev = inv["status"]
        inv["status"] = "ACCEPTED"
        store.stamp_update(inv)
        rev["active_assignments"] = rev.get("active_assignments", 0) + 1
        store.stamp_update(rev)
        # Create paired Review row in DRAFT
        now = clock.now()
        review = {
            "invitation_id": inv["id"],
            "manuscript_id": m["id"],
            "revision_round": inv["revision_round"],
            "rating": None,
            "recommendation": None,
            "comments_to_author": None,
            "comments_to_editor": None,
            "status": "DRAFT",
            "submitted_at": None,
            "review_deadline_at": fmt_ts(now + timedelta(days=21)),
        }
        store.stamp_create(review)
        store.reviews[review["id"]] = review
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="ReviewerInvitation", entity_id=inv["id"],
            action="INVITATION_ACCEPTED", from_state=prev, to_state="ACCEPTED",
            details={"review_id": review["id"]},
        )
        return success_envelope(inv, status=200, response_type="object")


@invitations_bp.route("/manuscripts/<mid>/invitations/<iid>/decline", methods=["POST"])
@require_auth(["Reviewer"])
def decline_invitation(mid: str, iid: str):
    with store.lock:
        m, inv = _resolve_invitation(mid, iid)
        if g.user_id != inv["reviewer_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the invited reviewer")
        if inv["status"] != "PENDING":
            raise api_error("ERR_INVALID_STATE", "Invitation not pending")
        prev = inv["status"]
        inv["status"] = "DECLINED"
        store.stamp_update(inv)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="ReviewerInvitation", entity_id=inv["id"],
            action="INVITATION_DECLINED", from_state=prev, to_state="DECLINED",
        )
        return success_envelope(inv, status=200, response_type="object")


@invitations_bp.route("/manuscripts/<mid>/invitations/<iid>/withdraw", methods=["POST"])
@require_auth(["AssociateEditor"])
def withdraw_invitation(mid: str, iid: str):
    with store.lock:
        m, inv = _resolve_invitation(mid, iid)
        if g.user_id != m.get("associate_editor_id"):
            raise api_error("ERR_FORBIDDEN", "Caller is not the assigned associate editor")
        if inv["status"] != "PENDING":
            raise api_error("ERR_INVALID_STATE", "Invitation not pending")
        prev = inv["status"]
        inv["status"] = "WITHDRAWN"
        store.stamp_update(inv)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="ReviewerInvitation", entity_id=inv["id"],
            action="INVITATION_WITHDRAWN", from_state=prev, to_state="WITHDRAWN",
        )
        return success_envelope(inv, status=200, response_type="object")
