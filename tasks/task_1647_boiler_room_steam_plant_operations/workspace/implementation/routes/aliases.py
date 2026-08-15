"""Flat alias read endpoints (PRD 2.9): reverse-FK reachability. Read-only;
all writes flow through the nested paths."""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from services import (
    boiler_json,
    chemistry_json,
    delivery_json,
    dispatch_json,
    incident_json,
    inspection_json,
    log_entry_json,
    operator_json,
    trap_json,
)
from util import list_response, success_object

bp = Blueprint("aliases", __name__)

ALL_READERS = ["PlantManager", "Operator", "Inspector"]
PM_OP = ["PlantManager", "Operator"]


def _filter(records, params, keys):
    out = records
    for k in keys:
        v = params.get(k)
        if v is not None:
            out = [r for r in out if r.get(k) == v]
    return out


# ---- boilers ----
@bp.get("/plants/boilers/<boilerId>")
def alias_get_boiler(boilerId):
    _, role = authenticate()
    authorize(role, ALL_READERS)
    return success_object(boiler_json(resolve.boiler_flat(boilerId)))


@bp.get("/plants/boilers")
def alias_list_boilers():
    _, role = authenticate()
    authorize(role, ALL_READERS)
    recs = _filter(list(store.boilers.values()), request.args, ["plant_id"])
    return list_response(recs, boiler_json)


# ---- operators ----
@bp.get("/plants/operators/<operatorId>")
def alias_get_operator(operatorId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(operator_json(resolve.operator_flat(operatorId)))


@bp.get("/plants/operators")
def alias_list_operators():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.operators.values()), request.args, ["plant_id"])
    return list_response(recs, operator_json)


# ---- boiler log entries ----
@bp.get("/plants/boiler-log-entries/<entryId>")
def alias_get_log_entry(entryId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(log_entry_json(resolve.log_entry_flat(entryId)))


@bp.get("/plants/boiler-log-entries")
def alias_list_log_entries():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.log_entries.values()), request.args,
                   ["boiler_id", "recorded_by_operator_id"])
    return list_response(recs, log_entry_json)


# ---- chemistry logs ----
@bp.get("/plants/chemistry-logs/<logId>")
def alias_get_chemistry_log(logId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(chemistry_json(resolve.chemistry_log_flat(logId)))


@bp.get("/plants/chemistry-logs")
def alias_list_chemistry_logs():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.chemistry_logs.values()), request.args,
                   ["boiler_id", "recorded_by_operator_id"])
    return list_response(recs, chemistry_json)


# ---- inspections ----
@bp.get("/plants/inspections/<inspectionId>")
def alias_get_inspection(inspectionId):
    _, role = authenticate()
    authorize(role, ALL_READERS)
    return success_object(inspection_json(resolve.inspection_flat(inspectionId)))


@bp.get("/plants/inspections")
def alias_list_inspections():
    _, role = authenticate()
    authorize(role, ALL_READERS)
    recs = _filter(list(store.inspections.values()), request.args, ["boiler_id"])
    return list_response(recs, inspection_json)


# ---- steam traps ----
@bp.get("/plants/steam-traps/<trapId>")
def alias_get_steam_trap(trapId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(trap_json(resolve.steam_trap_flat(trapId)))


@bp.get("/plants/steam-traps")
def alias_list_steam_traps():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.steam_traps.values()), request.args, ["plant_id"])
    return list_response(recs, trap_json)


# ---- load dispatches ----
@bp.get("/plants/load-dispatches/<dispatchId>")
def alias_get_dispatch(dispatchId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(dispatch_json(resolve.dispatch_flat(dispatchId)))


@bp.get("/plants/load-dispatches")
def alias_list_dispatches():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.dispatches.values()), request.args, ["plant_id"])
    return list_response(recs, dispatch_json)


# ---- incidents ----
@bp.get("/plants/incidents/<incidentId>")
def alias_get_incident(incidentId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(incident_json(resolve.incident_flat(incidentId)))


@bp.get("/plants/incidents")
def alias_list_incidents():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.incidents.values()), request.args,
                   ["plant_id", "raised_by_operator_id", "triggered_boiler_id"])
    return list_response(recs, incident_json)


# ---- fuel deliveries ----
@bp.get("/plants/fuel-deliveries/<deliveryId>")
def alias_get_delivery(deliveryId):
    _, role = authenticate()
    authorize(role, PM_OP)
    return success_object(delivery_json(resolve.delivery_flat(deliveryId)))


@bp.get("/plants/fuel-deliveries")
def alias_list_deliveries():
    _, role = authenticate()
    authorize(role, PM_OP)
    recs = _filter(list(store.fuel_deliveries.values()), request.args, ["plant_id"])
    return list_response(recs, delivery_json)
