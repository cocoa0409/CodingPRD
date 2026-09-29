"""Prescription endpoints."""
from flask import Blueprint, request

import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint

bp = Blueprint("prescriptions", __name__)


@bp.post("/vm/prescriptions")
@endpoint(["UtilityForester"])
def create_prescription():
    data = V.body()
    voltage_class = V.as_enum(data, "voltage_class", C.VOLTAGE_CLASSES)
    growth_zone = V.as_enum(data, "growth_zone", C.GROWTH_ZONES)
    base_cycle_years = V.as_number(data, "base_cycle_years", minimum=0, maximum=10,
                                  exclusive_min=True)
    clearance = V.as_number(data, "clearance_radius_ft", minimum=1, maximum=40)
    effective_from = V.as_date(data, "effective_from")
    ground_to_sky = V.as_boolean(data, "ground_to_sky", default=False)
    herbicide_allowed = V.as_boolean(data, "herbicide_allowed", default=True)

    rec = store.new_record()
    rec.update({
        "voltage_class": voltage_class,
        "growth_zone": growth_zone,
        "base_cycle_years": base_cycle_years,
        "clearance_radius_ft": clearance,
        "ground_to_sky": ground_to_sky,
        "herbicide_allowed": herbicide_allowed,
        "effective_from": effective_from,
        "status": "DRAFT",
    })
    store.prescriptions[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/prescriptions/<pid>/activate")
@endpoint(["UtilityForester"])
def activate_prescription(pid):
    rec = V.find(store.prescriptions, pid, "ERR_PRESCRIPTION_NOT_FOUND")
    services.require_state(rec, "prescription", ["DRAFT"])
    for peer in store.ordered(list(store.prescriptions.values())):
        if peer["id"] == rec["id"]:
            continue
        if (peer.get("status") == "ACTIVE"
                and peer.get("voltage_class") == rec.get("voltage_class")
                and peer.get("growth_zone") == rec.get("growth_zone")):
            peer["status"] = "SUPERSEDED"
            store.touch(peer)
    rec["status"] = "ACTIVE"
    store.touch(rec)
    return envelope.ok(store.public(rec))


@bp.get("/vm/prescriptions/<pid>")
@endpoint(ALL_ROLES)
def get_prescription(pid):
    rec = V.find(store.prescriptions, pid, "ERR_PRESCRIPTION_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/prescriptions")
@endpoint(ALL_ROLES)
def list_prescriptions():
    return envelope.list_response(list(store.prescriptions.values()), {
        "voltage_class": request.args.get("voltage_class"),
        "growth_zone": request.args.get("growth_zone"),
        "status": request.args.get("status"),
    })
