"""Maintenance request endpoints (PRD §3.5)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_BOX_NOT_FOUND,
    ERR_BOX_NOT_PUBLIC,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MAINTENANCE_NOT_FOUND,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_SCHEDULE_DATE_PAST,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_maintenance
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    optional_string,
    paginate,
    parse_date_value,
    parse_pagination,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("maintenance", __name__)

CATEGORIES = {"WEATHER_DAMAGE", "VANDALISM", "WEAR", "INSTALLATION_DEFECT"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
RESOLVE_OUTCOMES = {"RESOLVED", "WONT_FIX"}


def _load_request(request_id: str) -> dict:
    req = db.maintenance_requests.get(request_id)
    if req is None:
        raise_err(ERR_MAINTENANCE_NOT_FOUND, "No maintenance request with the given id")
    return req


@bp.route("/library-network/maintenance-requests", methods=["POST"])
@require_roles("Anonymous", "Steward", "Moderator", "NetworkAdmin")
def create_request(_user_id, _role):
    body = get_json_body()
    box_id = body.get("box_id")

    # Body referential integrity (stage 4).
    box = None
    if isinstance(box_id, str):
        box = db.boxes.get(box_id)
        if box is None:
            raise_body_ref_err(ERR_BOX_NOT_FOUND, "No box with the given id")

    # Business constraint (stage 9): only public fixtures are reportable —
    # CHARTERED, ACTIVE, SUSPENDED (§3.5).
    if box is not None and box["charter_status"] not in ("CHARTERED", "ACTIVE", "SUSPENDED"):
        raise_err(ERR_BOX_NOT_PUBLIC, "Box is not a public fixture")

    # Schema (stage 11).
    box_id = require_string(body, "box_id")
    category = require_enum(body, "category", CATEGORIES)
    description = require_string(body, "description")
    box = db.boxes[box_id]

    now = db.clock()
    season = domain.season_for(now)
    req = {
        "box_id": box_id,
        "category": category,
        "description": description,
        "severity": None,
        "status": "REPORTED",
        "season_at_report": season,
        "season_multiplier": 2.0 if season == "WINTER" else 1.0,
        "sla_deadline_at": None,
        "triaged_at": None,
        "scheduled_date": None,
        "resolved_at": None,
        "resolution_count": 0,
        "reimbursement_cents": None,
        "sla_breached": False,
    }
    db.stamp_new(req)
    db.maintenance_requests[req["id"]] = req
    return success_object(serialize_maintenance(req), 201)


@bp.route("/library-network/maintenance-requests", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_requests(_user_id, _role):
    limit, offset = parse_pagination()
    items = [
        serialize_maintenance(m)
        for m in sort_by_created_at(list(db.maintenance_requests.values()))
    ]
    items = apply_filters(items, ["box_id", "status", "severity"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/maintenance-requests/<request_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_request(request_id: str, _user_id, _role):
    return success_object(serialize_maintenance(_load_request(request_id)))


@bp.route("/library-network/maintenance-requests/<request_id>/triage", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def triage_request(request_id: str, _user_id, _role):
    req = _load_request(request_id)
    body = get_json_body()

    # State precondition (stage 5).
    if req["status"] not in ("REPORTED", "REOPENED"):
        raise_err(ERR_INVALID_STATE, "Request is not in REPORTED or REOPENED status")

    # Temporal rule (stage 8): scheduled_date must not precede the logical date.
    raw_date = body.get("scheduled_date")
    if isinstance(raw_date, str) and len(raw_date) == 10:
        try:
            sched = parse_date_value(raw_date, "scheduled_date")
        except Exception:
            sched = None  # malformed date — deferred to the schema stage below
        if sched is not None and sched.date() < db.clock().date():
            raise_err(ERR_SCHEDULE_DATE_PAST, "scheduled_date is before the current logical date")

    # Schema (stage 11).
    severity = require_enum(body, "severity", SEVERITIES)
    sched_dt = parse_date_value(body.get("scheduled_date"), "scheduled_date")
    if sched_dt.date() < db.clock().date():
        raise_err(ERR_SCHEDULE_DATE_PAST, "scheduled_date is before the current logical date")

    triaged_at = db.clock()
    req["severity"] = severity
    req["triaged_at"] = db.format_iso(triaged_at)
    req["scheduled_date"] = body["scheduled_date"]
    req["sla_deadline_at"] = db.format_iso(
        domain.sla_deadline(triaged_at, severity, req["season_multiplier"])
    )
    req["status"] = "SCHEDULED"
    db.touch(req)

    box = db.boxes.get(req["box_id"])
    if box is not None:
        domain.recompute_posture(box)
    return success_object(serialize_maintenance(req))


@bp.route("/library-network/maintenance-requests/<request_id>/resolve", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def resolve_request(request_id: str, _user_id, _role):
    req = _load_request(request_id)
    body = get_json_body()
    outcome = body.get("outcome")

    # State preconditions (stage 5) per branch.
    if outcome == "RESOLVED":
        if req["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Request is not in SCHEDULED status")
    elif outcome == "WONT_FIX":
        if req["status"] not in ("REPORTED", "SCHEDULED"):
            raise_err(ERR_INVALID_STATE, "Request cannot be marked WONT_FIX from its current state")

    # Schema (stage 11).
    outcome = require_enum(body, "outcome", RESOLVE_OUTCOMES)
    parts = optional_field(body, "parts", [])
    if not isinstance(parts, list):
        raise_err(ERR_INVALID_REQUEST, "Field parts must be an array")
    for line in parts:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "Each parts line must be an object")
        qty = line.get("qty")
        cost = line.get("unit_cost_cents")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err(ERR_INVALID_REQUEST, "Each parts line requires qty >= 1")
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise_err(ERR_INVALID_REQUEST, "Each parts line requires unit_cost_cents >= 0")
    labor_hours = optional_field(body, "labor_hours", 0)
    if isinstance(labor_hours, bool) or not isinstance(labor_hours, (int, float)) or labor_hours < 0:
        raise_err(ERR_INVALID_REQUEST, "Field labor_hours must be a number >= 0")
    resolution_notes = optional_string(body, "resolution_notes")

    if outcome == "WONT_FIX":
        was_scheduled = req["status"] == "SCHEDULED"
        req["status"] = "WONT_FIX"
        if resolution_notes is not None:
            req["resolution_notes"] = resolution_notes
        db.touch(req)
        if was_scheduled:
            box = db.boxes.get(req["box_id"])
            if box is not None:
                domain.recompute_posture(box)
        return success_object(serialize_maintenance(req))

    # outcome == RESOLVED
    req["reimbursement_cents"] = domain.parts_reimbursement(parts, labor_hours)
    resolved_at = db.clock()
    req["resolved_at"] = db.format_iso(resolved_at)
    req["sla_breached"] = resolved_at > db.parse_iso(req["sla_deadline_at"])
    req["resolution_count"] = req.get("resolution_count", 0) + 1
    req["status"] = "RESOLVED"
    if resolution_notes is not None:
        req["resolution_notes"] = resolution_notes
    db.touch(req)

    box = db.boxes.get(req["box_id"])
    if box is not None:
        # Recognition: +40 MAINTENANCE_RESOLVED for the box's steward.
        domain.add_recognition_event(
            box["steward_id"], "MAINTENANCE_RESOLVED", 40, "MAINTENANCE_REQUEST", req["id"]
        )
        domain.refresh_box_activity(box)
    return success_object(serialize_maintenance(req))


@bp.route("/library-network/maintenance-requests/<request_id>/reopen", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def reopen_request(request_id: str, _user_id, _role):
    req = _load_request(request_id)

    # Ownership (stage 2): a steward may reopen only requests on their own box.
    box = db.boxes.get(req["box_id"])
    if _role == "Steward" and (box is None or box["steward_id"] != _user_id):
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only reopen requests on their own box")

    # State precondition (stage 5).
    if req["status"] != "RESOLVED":
        raise_err(ERR_INVALID_STATE, "Request is not in RESOLVED status")

    # Temporal rule (stage 8): strict 14-day window; exactly 14 days is expired.
    resolved_at = db.parse_iso(req["resolved_at"])
    if (db.clock() - resolved_at) >= timedelta(days=14):
        raise_err(ERR_REOPEN_WINDOW_EXPIRED, "The 14-day reopen window has expired")

    req["status"] = "REOPENED"
    req["reimbursement_cents"] = None
    db.touch(req)
    if box is not None:
        domain.recompute_posture(box)
    return success_object(serialize_maintenance(req))
