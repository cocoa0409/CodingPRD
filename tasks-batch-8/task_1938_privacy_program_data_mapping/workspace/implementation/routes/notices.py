"""Notices: draft/publish/retract with the supersede-and-retract protocol."""
from flask import Blueprint

import clock
import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_notice
from services.core import (base_entity, created_asc, maybe_resume_activity,
                           touch, windows_overlap)
from services.risk import NOTICE_SCOPES
from utils import parse_ts

bp = Blueprint("notices", __name__)


@bp.post("/privacy/notices")
def create_notice():
    require_roles("PrivacyAdmin")
    body = get_body()
    supersedes_notice_id = body.get("supersedes_notice_id")
    if (isinstance(supersedes_notice_id, str)
            and supersedes_notice_id not in db.notices):
        raise ApiError("ERR_NOT_FOUND", "supersedes_notice_id not found")
    scope = body.get("scope")
    title = body.get("title")
    text = body.get("body")
    if scope not in NOTICE_SCOPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid scope")
    if not isinstance(title, str) or not title:
        raise ApiError("ERR_INVALID_REQUEST", "title is required")
    if not isinstance(text, str):
        raise ApiError("ERR_INVALID_REQUEST", "body is required")
    try:
        effective_from = parse_ts(body.get("effective_from"))
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "effective_from must be an ISO 8601 timestamp")
    effective_to = None
    if body.get("effective_to") is not None:
        try:
            effective_to = parse_ts(body.get("effective_to"))
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "effective_to must be an ISO 8601 timestamp")
    if supersedes_notice_id is not None and not isinstance(supersedes_notice_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "supersedes_notice_id must be a string")
    notice = base_entity()
    notice.update({
        "scope": scope,
        "title": title,
        "body": text,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_notice_id": supersedes_notice_id,
        "status": "DRAFT",
        "published_at": None,
        "superseded_by_notice_id": None,
    })
    db.notices[notice["id"]] = notice
    return success(ser_notice(notice), 201)


@bp.get("/privacy/notices")
def list_notices():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.notices.values()))
    scope = _arg("scope")
    status = _arg("status")
    superseded_by = _arg("superseded_by_notice_id")
    supersedes = _arg("supersedes_notice_id")
    if scope is not None:
        items = [n for n in items if n["scope"] == scope]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    if superseded_by is not None:
        items = [n for n in items if n["superseded_by_notice_id"] == superseded_by]
    if supersedes is not None:
        items = [n for n in items if n["supersedes_notice_id"] == supersedes]
    return list_response(items, ser_notice)


def _arg(name):
    from flask import request
    return request.args.get(name)


@bp.get("/privacy/notices/<notice_id>")
def get_notice(notice_id):
    require_roles(*STAFF_ROLES)
    notice = db.notices.get(notice_id)
    if notice is None:
        raise ApiError("ERR_NOT_FOUND", "notice not found")
    return success(ser_notice(notice), 200)


@bp.post("/privacy/notices/<notice_id>/publish")
def publish_notice(notice_id):
    require_roles("PrivacyAdmin")
    notice = db.notices.get(notice_id)
    if notice is None:
        raise ApiError("ERR_NOT_FOUND", "notice not found")
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a DRAFT notice can be published")
    if (notice["effective_to"] is not None
            and notice["effective_to"] <= notice["effective_from"]):
        raise ApiError("ERR_INVALID_WINDOW",
                       "effective_to must be strictly after effective_from")
    target = None
    if notice["supersedes_notice_id"] is not None:
        target = db.notices.get(notice["supersedes_notice_id"])
        if (target is None or target["status"] != "PUBLISHED"
                or target["scope"] != notice["scope"]
                or not windows_overlap(notice["effective_from"], notice["effective_to"],
                                       target["effective_from"], target["effective_to"])):
            raise ApiError(
                "ERR_NOTICE_WINDOW_OVERLAP",
                "supersede target must be PUBLISHED, same scope, and window-overlapping")
    for other in db.notices.values():
        if other["id"] == notice["id"]:
            continue
        if target is not None and other["id"] == target["id"]:
            continue
        if (other["status"] == "PUBLISHED" and other["scope"] == notice["scope"]
                and windows_overlap(notice["effective_from"], notice["effective_to"],
                                    other["effective_from"], other["effective_to"])):
            raise ApiError(
                "ERR_NOTICE_WINDOW_OVERLAP",
                "window overlaps a PUBLISHED notice in the same scope")
    notice["status"] = "PUBLISHED"
    notice["published_at"] = clock.now()
    touch(notice)
    if target is not None:
        target["status"] = "SUPERSEDED"
        target["superseded_by_notice_id"] = notice["id"]
        touch(target)
        stale = [p for p in db.purposes.values()
                 if p["pinned_notice_id"] == target["id"] and p["status"] == "DOCUMENTED"]
        affected_activity_ids = []
        for purpose in created_asc(stale):
            purpose["status"] = "CONSENT_STALE"
            touch(purpose)
            if purpose["activity_id"] not in affected_activity_ids:
                affected_activity_ids.append(purpose["activity_id"])
        held_activity_ids = []
        affected = [db.activities[aid] for aid in affected_activity_ids
                    if aid in db.activities]
        for activity in created_asc(affected):
            if activity["status"] == "ACTIVE":
                activity["status"] = "COMPLIANCE_HOLD"
                touch(activity)
                held_activity_ids.append(activity["id"])
        transfers = [t for t in db.transfers.values()
                     if t["activity_id"] in held_activity_ids
                     and t["status"] == "APPROVED"]
        for transfer in created_asc(transfers):
            transfer["status"] = "SUSPENDED"
            transfer["suspension_reason"] = "ACTIVITY_HOLD"
            touch(transfer)
    return success(ser_notice(notice), 200)


@bp.post("/privacy/notices/<notice_id>/retract")
def retract_notice(notice_id):
    require_roles("PrivacyAdmin")
    notice = db.notices.get(notice_id)
    if notice is None:
        raise ApiError("ERR_NOT_FOUND", "notice not found")
    if notice["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PUBLISHED notice can be retracted")
    notice["status"] = "RETRACTED"
    touch(notice)
    restored = None
    for candidate in db.notices.values():
        if candidate.get("superseded_by_notice_id") == notice["id"]:
            restored = candidate
            break
    if restored is not None and restored["status"] == "SUPERSEDED":
        restored["status"] = "PUBLISHED"
        touch(restored)
        stale = [p for p in db.purposes.values()
                 if p["status"] == "CONSENT_STALE"
                 and p["pinned_notice_id"] == restored["id"]]
        for purpose in created_asc(stale):
            purpose["status"] = "DOCUMENTED"
            touch(purpose)
    held = [a for a in db.activities.values() if a["status"] == "COMPLIANCE_HOLD"]
    for activity in created_asc(held):
        maybe_resume_activity(activity)
    return success(ser_notice(notice), 200)
