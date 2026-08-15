"""Facility endpoints, including refresh-health, recompute, facility-scoped
reverse lookups, and refresh-cycle creation."""

from flask import Blueprint, request

import db
from clock import logical_clock
from errors import (
    ERR_DUPLICATE,
    ERR_REFERENCE_NOT_FOUND,
    raise_error,
)
from middleware import auth
from response import ok_object
from services.core import (
    get_or_404,
    list_response,
    new_record,
    pub,
    recompute_facility,
    refresh_health,
)
from util import body, v_int, v_str

bp = Blueprint("facilities", __name__)


@bp.post("/fca/facilities")
def create_facility():
    auth("Consultant")
    data = body()
    # Priority 4: body foreign keys must exist
    client_id = data.get("client_id")
    if client_id is not None and client_id not in db.clients:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"client_id does not reference an existing client: {client_id}",
        )
    # Priority 10: field shape
    name = v_str(data, "name")
    address = v_str(data, "address")
    gross_square_feet = v_int(data, "gross_square_feet", minimum=1)
    client_id = v_str(data, "client_id")
    rec = new_record()
    rec.update(
        {
            "client_id": client_id,
            "name": name,
            "address": address,
            "gross_square_feet": gross_square_feet,
            "current_replacement_value_cents": 0,
            "backlog_cost_cents": 0,
            "facility_condition_index": 0.0,
            "assessment_epoch": 0,
        }
    )
    db.facilities[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/fca/facilities")
def list_facilities():
    auth()
    records = list(db.facilities.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        records = [r for r in records if r["client_id"] == client_id]
    return list_response(records)


@bp.get("/fca/facilities/<facility_id>")
def get_facility(facility_id):
    auth()
    return ok_object(pub(get_or_404(db.facilities, facility_id, "Facility")))


@bp.get("/fca/facilities/<facility_id>/refresh-health")
def get_refresh_health(facility_id):
    auth()
    fac = get_or_404(db.facilities, facility_id, "Facility")
    return ok_object(refresh_health(fac))


@bp.post("/fca/facilities/<facility_id>/recompute")
def recompute(facility_id):
    auth("Consultant")
    fac = get_or_404(db.facilities, facility_id, "Facility")
    recompute_facility(fac)
    return ok_object(pub(fac))


@bp.get("/fca/facilities/<facility_id>/asset-systems")
def list_facility_asset_systems(facility_id):
    auth()
    get_or_404(db.facilities, facility_id, "Facility")
    records = [
        s for s in db.asset_systems.values() if s["facility_id"] == facility_id
    ]
    return list_response(records)


@bp.get("/fca/facilities/<facility_id>/capital-plans")
def list_facility_capital_plans(facility_id):
    auth()
    get_or_404(db.facilities, facility_id, "Facility")
    records = [
        p for p in db.capital_plans.values() if p["facility_id"] == facility_id
    ]
    return list_response(records)


@bp.get("/fca/facilities/<facility_id>/refresh-cycles")
def list_facility_refresh_cycles(facility_id):
    auth()
    get_or_404(db.facilities, facility_id, "Facility")
    records = [
        c for c in db.refresh_cycles.values() if c["facility_id"] == facility_id
    ]
    return list_response(records)


@bp.post("/fca/facilities/<facility_id>/refresh-cycles")
def create_refresh_cycle(facility_id):
    auth("Consultant")
    get_or_404(db.facilities, facility_id, "Facility")
    # Priority 11: at most one OPEN RefreshCycle per facility
    for cycle in db.refresh_cycles.values():
        if cycle["facility_id"] == facility_id and cycle["status"] == "OPEN":
            raise_error(
                ERR_DUPLICATE,
                "An OPEN refresh cycle already exists for this facility",
            )
    prior_epochs = [
        c["epoch"]
        for c in db.refresh_cycles.values()
        if c["facility_id"] == facility_id
    ]
    epoch = max(prior_epochs) + 1 if prior_epochs else 1
    rec = new_record()
    rec.update(
        {
            "facility_id": facility_id,
            "epoch": epoch,
            "status": "OPEN",
            "opened_at": logical_clock.now_iso(),
        }
    )
    db.refresh_cycles[rec["id"]] = rec
    return ok_object(pub(rec), 201)
