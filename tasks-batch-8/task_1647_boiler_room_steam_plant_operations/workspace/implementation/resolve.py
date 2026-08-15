"""Path-template resolution, left to right, scope-checked (PRD 2.9, stage 3).

A nested identifier that does not resolve within its parent's scope fails with
ERR_NOT_FOUND at the first unresolved identifier.
"""
import store
from errors import raise_err, ERR_NOT_FOUND


def plant(pid):
    rec = store.plants.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Plant not found: %s" % pid)
    return rec


def boiler(plant_rec, bid):
    rec = store.boilers.get(bid)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "Boiler not found: %s" % bid)
    return rec


def operator(plant_rec, oid):
    rec = store.operators.get(oid)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "Operator not found: %s" % oid)
    return rec


def log_entry(boiler_rec, eid):
    rec = store.log_entries.get(eid)
    if rec is None or rec["boiler_id"] != boiler_rec["id"]:
        raise_err(ERR_NOT_FOUND, "BoilerLogEntry not found: %s" % eid)
    return rec


def chemistry_log(boiler_rec, lid):
    rec = store.chemistry_logs.get(lid)
    if rec is None or rec["boiler_id"] != boiler_rec["id"]:
        raise_err(ERR_NOT_FOUND, "ChemistryLog not found: %s" % lid)
    return rec


def inspection(boiler_rec, iid):
    rec = store.inspections.get(iid)
    if rec is None or rec["boiler_id"] != boiler_rec["id"]:
        raise_err(ERR_NOT_FOUND, "Inspection not found: %s" % iid)
    return rec


def steam_trap(plant_rec, tid):
    rec = store.steam_traps.get(tid)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "SteamTrap not found: %s" % tid)
    return rec


def dispatch(plant_rec, did):
    rec = store.dispatches.get(did)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "LoadDispatch not found: %s" % did)
    return rec


def incident(plant_rec, iid):
    rec = store.incidents.get(iid)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "Incident not found: %s" % iid)
    return rec


def delivery(plant_rec, fid):
    rec = store.fuel_deliveries.get(fid)
    if rec is None or rec["plant_id"] != plant_rec["id"]:
        raise_err(ERR_NOT_FOUND, "FuelDelivery not found: %s" % fid)
    return rec


# ---- flat-alias lookups (no parent scope; PRD 2.9) ----
def boiler_flat(bid):
    rec = store.boilers.get(bid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Boiler not found: %s" % bid)
    return rec


def operator_flat(oid):
    rec = store.operators.get(oid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Operator not found: %s" % oid)
    return rec


def log_entry_flat(eid):
    rec = store.log_entries.get(eid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "BoilerLogEntry not found: %s" % eid)
    return rec


def chemistry_log_flat(lid):
    rec = store.chemistry_logs.get(lid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "ChemistryLog not found: %s" % lid)
    return rec


def inspection_flat(iid):
    rec = store.inspections.get(iid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Inspection not found: %s" % iid)
    return rec


def steam_trap_flat(tid):
    rec = store.steam_traps.get(tid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "SteamTrap not found: %s" % tid)
    return rec


def dispatch_flat(did):
    rec = store.dispatches.get(did)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "LoadDispatch not found: %s" % did)
    return rec


def incident_flat(iid):
    rec = store.incidents.get(iid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Incident not found: %s" % iid)
    return rec


def delivery_flat(fid):
    rec = store.fuel_deliveries.get(fid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FuelDelivery not found: %s" % fid)
    return rec
