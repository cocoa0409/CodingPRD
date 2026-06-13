"""Crew endpoints (PRD §3.1, §3.3) plus crew scheduled-slot reads."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require
from response import ok_array, ok_object
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_enum,
    require_int,
    require_str,
    touch,
)
from services.lookups import get_crew

bp = Blueprint("crews", __name__)

SERVICE_TYPES = {"STEAM", "DRY"}


@bp.post("/crews")
def create_crew():
    require(["Dispatcher"])
    body = get_json_body()
    crew_name = require_str(body, "crew_name")
    supported = require_enum(body, "supported_service_type", SERVICE_TYPES)
    # turnaround_buffer_minutes >= 0 (PRD §3.1)
    buffer_minutes = require_int(body, "turnaround_buffer_minutes", minimum=0)

    record = init_common({
        "crew_name": crew_name,
        "supported_service_type": supported,
        "turnaround_buffer_minutes": buffer_minutes,
        "status": "AVAILABLE",
    })
    # version already initialized to 1 by init_common; PRD §3.1: new crew version 1.
    db.crews[record["id"]] = record
    return ok_object(public(record), 201)


@bp.get("/crews/<cid>")
def get_crew_ep(cid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    c = get_crew(cid)
    return ok_object(public(c), 200)


@bp.post("/crews/<cid>/out-of-service")
def out_of_service(cid):
    require(["Dispatcher"])
    c = get_crew(cid)
    c["status"] = "OUT_OF_SERVICE"
    touch(c)  # advances crew.version (PRD §3.1)
    return ok_object(public(c), 200)


@bp.get("/crews/<cid>/scheduled-slots")
def list_crew_slots(cid):
    require(["Dispatcher", "ServiceManager"])
    get_crew(cid)
    limit, offset = parse_pagination()
    rows = [s for s in db.scheduled_slots.values() if s["crew_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)
