"""Tow-assist routes (scaffold §1.5 — Tow Assist block; PRD §3.7).

The dispatch endpoint runs the strict two-step evaluation in
calculations.tow_assistance_dispatch and persists a (immutable) TowAssistEvent.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import tow_assistance_outcome
from services.validation import (
    lookup_or_404,
    require_fields,
    require_number,
)


bp = Blueprint("tow_assist", __name__)


@bp.post("/tow-assist-events")
def create_tow_assist_event():
    require_auth(["Tenant", "MarinaStaff", "HarborMaster"])()
    body = get_json_body()
    require_fields(body, ["tenant_id", "vessel_id", "marina_id", "incident_distance_nm"])
    tenant = lookup_or_404(db.tenants, body["tenant_id"], "Tenant")
    vessel = lookup_or_404(db.vessels, body["vessel_id"], "Vessel")
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")
    incident_distance_nm = require_number(
        body["incident_distance_nm"], "incident_distance_nm", min_value=0.0
    )

    with db.mutation_lock:
        today_utc = db.now_logical_date()
        outcome = tow_assistance_outcome(
            vessel, marina, incident_distance_nm, today_utc
        )
        event = {
            "tenant_id": tenant["id"],
            "vessel_id": vessel["id"],
            "marina_id": marina["id"],
            "incident_distance_nm": incident_distance_nm,
            "outcome": outcome,
            "dispatched_at": db.now_logical_iso(),
        }
        db.stamp_immutable(event)
        db.tow_assist_events[event["id"]] = event
        return ok_object(event, 201)


@bp.get("/tow-assist-events")
def list_tow_assist_events():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.tow_assist_events.values())
    for key in ("tenant_id", "vessel_id", "marina_id"):
        if key in request.args:
            val = request.args[key]
            items = [e for e in items if e.get(key) == val]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/tow-assist-events/<eid>")
def get_tow_assist_event(eid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    event = lookup_or_404(db.tow_assist_events, eid, "TowAssistEvent")
    return ok_object(event, 200)
