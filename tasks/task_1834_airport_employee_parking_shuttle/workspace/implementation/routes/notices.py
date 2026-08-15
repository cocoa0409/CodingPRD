"""ServiceChangeNotice endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import fmt_dt, now, parse_dt, touch
from domain import get_or_404, serialize_notice
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("notices", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")

NOTICE_TYPES = {"LOT_CLOSURE", "LOT_REOPEN", "ROUTE_SUSPENSION", "HEADWAY_CHANGE", "GENERAL"}


@bp.route("/parking/notices", methods=["POST"])
def create_notice():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("notice_type", "headline", "effective_from"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    ntype = body["notice_type"]
    if ntype not in NOTICE_TYPES:
        raise_error("ERR_INVALID_REQUEST", "invalid notice_type")
    effective_from = parse_dt(body["effective_from"])
    if effective_from is None:
        raise_error("ERR_INVALID_REQUEST", "effective_from must be a valid ISO datetime")
    effective_to = None
    if body.get("effective_to") is not None:
        effective_to = parse_dt(body["effective_to"])
        if effective_to is None:
            raise_error("ERR_INVALID_REQUEST", "effective_to must be a valid ISO datetime")
        if effective_to <= effective_from:
            raise_error("ERR_INVALID_REQUEST", "effective_to must be later than effective_from")
    lot_id = body.get("lot_id")
    route_id = body.get("route_id")
    new_headway = body.get("new_headway_minutes")
    # Existence for supplied FK ids (priority 4)
    if lot_id is not None:
        get_or_404(db.lots, lot_id)
    if route_id is not None:
        get_or_404(db.routes, route_id)
    # Target coherence (priority 11)
    if ntype in ("LOT_CLOSURE", "LOT_REOPEN"):
        if lot_id is None or route_id is not None:
            raise_error("ERR_NOTICE_TARGET_MISMATCH",
                        "LOT_CLOSURE/LOT_REOPEN require lot_id and forbid route_id")
    elif ntype in ("ROUTE_SUSPENSION", "HEADWAY_CHANGE"):
        if route_id is None or lot_id is not None:
            raise_error("ERR_NOTICE_TARGET_MISMATCH",
                        "ROUTE_SUSPENSION/HEADWAY_CHANGE require route_id and forbid lot_id")
        if ntype == "HEADWAY_CHANGE":
            if new_headway is None:
                raise_error("ERR_NOTICE_TARGET_MISMATCH",
                            "HEADWAY_CHANGE requires new_headway_minutes")
    if new_headway is not None:
        if not isinstance(new_headway, int) or isinstance(new_headway, bool) or new_headway <= 0:
            raise_error("ERR_INVALID_REQUEST", "new_headway_minutes must be > 0 when present")
    rec = db.new_record({
        "lot_id": lot_id,
        "route_id": route_id,
        "notice_type": ntype,
        "headline": body["headline"],
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "new_headway_minutes": new_headway,
        "status": "DRAFT",
        "published_at": None,
    })
    db.notices[rec["id"]] = rec
    return success_object(serialize_notice(rec), 201)


@bp.route("/parking/notices/<nid>", methods=["GET"])
def get_notice(nid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.notices, nid)
    return success_object(serialize_notice(rec), 200)


@bp.route("/parking/notices", methods=["GET"])
def list_notices():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    lot_id = request.args.get("lot_id")
    route_id = request.args.get("route_id")
    notice_type = request.args.get("notice_type")
    status = request.args.get("status")
    items = sorted(db.notices.values(), key=lambda n: n["created_at"])
    out = []
    for n in items:
        if lot_id is not None and n.get("lot_id") != lot_id:
            continue
        if route_id is not None and n.get("route_id") != route_id:
            continue
        if notice_type is not None and n["notice_type"] != notice_type:
            continue
        if status is not None and n["status"] != status:
            continue
        out.append(serialize_notice(n))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/notices/<nid>/events", methods=["POST"])
def notice_event(nid):
    require_roles("ParkingAdmin")
    notice = get_or_404(db.notices, nid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("PUBLISH", "CANCEL"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    if event_type == "PUBLISH":
        if notice["status"] != "DRAFT":
            raise_error("ERR_INVALID_STATE", "PUBLISH requires the notice to be DRAFT")
        effective_from = parse_dt(notice["effective_from"])
        if effective_from < now() + timedelta(hours=72):
            raise_error("ERR_NOTICE_EFFECTIVE_TOO_SOON",
                        "effective_from must be at least 72 hours in the future")
        notice["status"] = "PUBLISHED"
        notice["published_at"] = fmt_dt(now())
        touch(notice)
    else:  # CANCEL
        if notice["status"] not in ("DRAFT", "PUBLISHED"):
            raise_error("ERR_INVALID_STATE", "CANCEL requires DRAFT or PUBLISHED")
        notice["status"] = "CANCELLED"
        touch(notice)
    return success_object(serialize_notice(notice), 200)
