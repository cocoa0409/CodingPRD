"""Complaints: file (resident ownership), list, get, drive lifecycle with SLA."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, optional_string,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("complaints", __name__)

CATEGORIES = {"HABITABILITY", "RENT", "UTILITY", "HARASSMENT", "OTHER"}
COMPLAINT_TARGETS = {"ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "ESCALATED_TO_AGENCY", "CLOSED"}


def _view(c):
    return {
        "id": c["id"],
        "tenancy_id": c["tenancy_id"],
        "category": c["category"],
        "description": c["description"],
        "status": c["status"],
        "filed_at": c["filed_at"],
        "acknowledged_at": c["acknowledged_at"],
        "sla_breached": c["sla_breached"],
        "resolution_note": c["resolution_note"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _site_of_tenancy(tenancy):
    unit = db.units.get(tenancy["unit_id"]) if tenancy else None
    if unit is None:
        return None
    return db.sites.get(unit["site_id"])


@bp.route("/complaints", methods=["POST"])
def create_complaint():
    user_id, role = require_roles("Resident", "IntakeCoordinator")
    body = get_body()
    tenancy_id = require_string(body, "tenancy_id")
    category = require_enum(body, "category", CATEGORIES)
    description = require_string(body, "description")

    t = db.tenancies.get(tenancy_id)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")
    # Resident ownership.
    if role == "Resident" and t["household_id"] != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS")
    # Tenancy must be ACTIVE or NOTICE (priority 7.5).
    if t["status"] not in ("ACTIVE", "NOTICE"):
        raise err("ERR_INVALID_STATE", "Complaints require tenancy in ACTIVE or NOTICE")

    now = db.now_ts()
    c = {
        "id": db.new_id(),
        "tenancy_id": tenancy_id,
        "category": category,
        "description": description,
        "status": "FILED",
        "filed_at": clock.current_iso(),
        "acknowledged_at": None,
        "sla_breached": False,
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.complaints[c["id"]] = c
    return success_object(_view(c), status=201)


@bp.route("/complaints", methods=["GET"])
def list_complaints():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.complaints.values())
    tenancy_f = get_filter("tenancy_id")
    status_f = get_filter("status")
    if tenancy_f is not None:
        items = [c for c in items if c["tenancy_id"] == tenancy_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(c) for c in page], total, limit, offset)


@bp.route("/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    get_auth()
    c = db.complaints.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(c))


@bp.route("/complaints/<cid>", methods=["PUT"])
def drive_complaint(cid):
    require_roles("SiteManager")
    body = get_body()
    target = require_enum(body, "status", COMPLAINT_TARGETS)
    c = db.complaints.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND")
    current = c["status"]
    now = db.now_ts()

    allowed = {
        "FILED": {"ACKNOWLEDGED"},
        "ACKNOWLEDGED": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED", "ESCALATED_TO_AGENCY"},
        "ESCALATED_TO_AGENCY": {"INVESTIGATING"},
        "RESOLVED": {"CLOSED"},
        "CLOSED": set(),
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move complaint from {current} to {target}")

    if target == "ACKNOWLEDGED":
        c["acknowledged_at"] = clock.current_iso()
        filed = clock._parse_iso(c["filed_at"])
        ack = clock.current_dt()
        deadline = filed + timedelta(hours=core.SLA_HOURS)
        c["sla_breached"] = ack > deadline

    if target == "RESOLVED":
        note = body.get("resolution_note")
        if note is None or not isinstance(note, str) or not note:
            raise err("ERR_INVALID_REQUEST", "resolution_note is required on RESOLVED")
        # Linked work orders must be terminal.
        for w in db.work_orders.values():
            if w.get("complaint_id") == cid and w["status"] not in ("VERIFIED", "CLOSED", "CANCELLED"):
                raise err("ERR_LINKED_WORK_ORDERS_OPEN")
        c["resolution_note"] = note

    c["status"] = target
    c["updated_at"] = now

    if target in ("ACKNOWLEDGED", "RESOLVED", "CLOSED"):
        t = db.tenancies.get(c["tenancy_id"])
        site = _site_of_tenancy(t)
        if site is not None:
            core.recompute_site_posture(site["id"])

    return success_object(_view(c))
