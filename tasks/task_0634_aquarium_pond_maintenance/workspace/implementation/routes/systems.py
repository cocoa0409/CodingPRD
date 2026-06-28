"""SystemProfile, Livestock, Equipment endpoints (PRD §3.1, §3.2)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import (system_view, livestock_view, equipment_view,
                         install_view, emergency_view, quarantine_view,
                         feeding_plan_view)
import common as C

bp = Blueprint("systems", __name__)

READ_ROLES = {"AccountManager", "Dispatcher", "FieldTech", "CustomerOwner"}


# ===========================================================================
# SystemProfile
# ===========================================================================
@bp.post("/aquatics/systems")
def create_system():
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    contract_id = C.req_str(data, "contract_id")
    label = C.req_str(data, "label")
    system_kind = C.req_enum(data, "system_kind", {"REEF", "FRESHWATER", "POND", "PALUDARIUM"})
    nominal_volume_l = C.req_number(data, "nominal_volume_l", exclusive_min=0)
    substrate = C.req_number(data, "substrate_displacement_pct", allow_missing=True,
                             default=0.0, minimum=0, exclusive_max=1)

    # existence of contract (priority 4)
    if contract_id not in store.contracts:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")

    rec = C.make_record({
        "contract_id": contract_id,
        "label": label,
        "system_kind": system_kind,
        "nominal_volume_l": nominal_volume_l,
        "substrate_displacement_pct": substrate,
        "status": "PROVISIONING",
        "bioload_index": 0.0,
        "stocking_posture": "NORMAL",
    })
    store.systems[rec["id"]] = rec
    return object_response(system_view(rec), 201)


@bp.get("/aquatics/systems/<sid>")
def get_system(sid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = store.systems.get(sid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    return object_response(system_view(rec))


@bp.post("/aquatics/systems/<sid>/commission")
def commission_system(sid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.systems.get(sid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    if rec["status"] != "PROVISIONING":
        raise ApiError("ERR_INVALID_STATE", "Only a PROVISIONING system may be commissioned.")
    contract = store.contracts.get(rec["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Owning contract must be ACTIVE.")
    # blocked by open install
    for inst in store.installs.values():
        if inst["system_id"] == sid and inst["status"] in ("QUOTED", "APPROVED", "IN_BUILD"):
            raise ApiError("ERR_OPEN_INSTALL_BLOCKS_COMMISSION",
                           "Commission blocked by an open install project.")
    rec["status"] = "ACTIVE"
    C.touch(rec)
    return object_response(system_view(rec))


@bp.post("/aquatics/systems/<sid>/decommission")
def decommission_system(sid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.systems.get(sid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "System cannot be decommissioned from its current state.")
    # blocked by in-flight visit
    for v in store.visits.values():
        if v["system_id"] == sid and v["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_VISIT_IN_FLIGHT", "Decommission blocked by an in-flight visit.")
    rec["status"] = "DECOMMISSIONED"
    C.touch(rec)
    # cascade ALIVE livestock -> DECEASED
    for l in store.livestock.values():
        if l["system_id"] == sid and l["status"] == "ALIVE":
            l["status"] = "DECEASED"
            C.touch(l)
    C.recompute_system_bioload(rec)
    contract = store.contracts.get(rec["contract_id"])
    if contract is not None:
        C.recompute_alive_livestock_count(contract)
    return object_response(system_view(rec))


# ===========================================================================
# Livestock
# ===========================================================================
@bp.post("/aquatics/livestock")
def create_livestock():
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    system_id = C.req_str(data, "system_id")
    common_name = C.req_str(data, "common_name")
    species_class = C.req_enum(data, "species_class",
                               {"COMMUNITY", "CICHLID", "GOLDFISH", "PREDATOR", "INVERT"})
    adult_length_cm = C.req_number(data, "adult_length_cm", exclusive_min=0)

    system = store.systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")

    # overstock gate: projected bioload with the new ALIVE animal (priority 8)
    eff = float(C.effective_volume(system))
    from decimal import Decimal, ROUND_HALF_UP
    raw = Decimal("0")
    for l in store.livestock.values():
        if l["system_id"] == system_id and l["status"] == "ALIVE":
            raw += Decimal(str(l["adult_length_cm"])) * C.WASTE_FACTOR[l["species_class"]]
    raw += Decimal(str(adult_length_cm)) * C.WASTE_FACTOR[species_class]
    if eff == 0:
        projected = 0.0
    else:
        projected = float((raw / Decimal(str(eff)) * Decimal("100"))
                          .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if projected > 100.0:
        raise ApiError("ERR_OVERSTOCKED", "Adding this livestock would overstock the system.")

    rec = C.make_record({
        "system_id": system_id,
        "common_name": common_name,
        "species_class": species_class,
        "adult_length_cm": adult_length_cm,
        "status": "ALIVE",
    })
    store.livestock[rec["id"]] = rec
    C.recompute_system_bioload(system)
    contract = store.contracts.get(system["contract_id"])
    if contract is not None:
        C.recompute_alive_livestock_count(contract)
    return object_response(livestock_view(rec), 201)


@bp.get("/aquatics/systems/<sid>/livestock")
def list_system_livestock(sid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [l for l in store.livestock.values() if l["system_id"] == sid]
    if status is not None:
        recs = [l for l in recs if l["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([livestock_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/livestock/<lid>")
def get_livestock(lid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = store.livestock.get(lid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Livestock not found.")
    return object_response(livestock_view(rec))


# ===========================================================================
# Equipment
# ===========================================================================
@bp.post("/aquatics/equipment")
def create_equipment():
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    system_id = C.req_str(data, "system_id")
    device_kind = C.req_enum(data, "device_kind",
                             {"FILTER", "PUMP", "HEATER", "UV_STERILIZER", "SKIMMER"})
    media_interval_days = C.req_int(data, "media_interval_days", minimum=1)

    system = store.systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")

    rec = C.make_record({
        "system_id": system_id,
        "device_kind": device_kind,
        "media_interval_days": media_interval_days,
        "last_serviced_on": None,
        "media_due_on": None,
        "status": "OPERATIONAL",
    })
    rec["media_due_on"] = C.compute_media_due_on(rec, system)
    store.equipment[rec["id"]] = rec
    return object_response(equipment_view(rec), 201)


@bp.get("/aquatics/systems/<sid>/equipment")
def list_system_equipment(sid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    device_kind = request.args.get("device_kind")
    recs = [e for e in store.equipment.values() if e["system_id"] == sid]
    if device_kind is not None:
        recs = [e for e in recs if e["device_kind"] == device_kind]
    page, total = C.paginate(recs, limit, offset)
    return array_response([equipment_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/equipment/<eid>")
def get_equipment(eid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = store.equipment.get(eid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Equipment not found.")
    return object_response(equipment_view(rec))


# ===========================================================================
# Nested lists rooted at a system (installs/emergencies/quarantines/feeding)
# ===========================================================================
@bp.get("/aquatics/systems/<sid>/installs")
def list_system_installs(sid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "FieldTech", "CustomerOwner"})
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [i for i in store.installs.values() if i["system_id"] == sid]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([install_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/systems/<sid>/emergencies")
def list_system_emergencies(sid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher", "AccountManager", "FieldTech"})
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [e for e in store.emergencies.values() if e["system_id"] == sid]
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([emergency_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/systems/<sid>/quarantines")
def list_system_quarantines(sid):
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager", "Dispatcher"})
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [q for q in store.quarantines.values() if q["quarantine_tank_id"] == sid]
    if status is not None:
        recs = [q for q in recs if q["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([quarantine_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/systems/<sid>/feeding-plans")
def list_system_feeding_plans(sid):
    _, role = get_auth()
    require_roles(role, {"CustomerOwner", "AccountManager", "Dispatcher"})
    if sid not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [p for p in store.feeding_plans.values() if p["system_id"] == sid]
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([feeding_plan_view(r) for r in page], limit, offset, total)
