"""Trucks with fixed compartments (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize, ALL_ROLES
from services import ser_truck
from validation import get_body, field, req_str, req_enum, req_num, bad, MISSING

bp = Blueprint("trucks", __name__)


def _get_truck(tid):
    t = STORE["trucks"].get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Truck {tid} not found")
    return t


def parse_compartments(data):
    comps = field(data, "compartments")
    if not isinstance(comps, list) or not (1 <= len(comps) <= 8):
        bad("compartments must be a list of 1 to 8 entries")
    seen = set()
    parsed = []
    for entry in comps:
        if not isinstance(entry, dict):
            bad("Each compartment must be an object")
        seq = entry.get("compartment_seq", MISSING)
        if seq is MISSING or isinstance(seq, bool) or not isinstance(seq, (int, str)):
            bad("Each compartment requires a compartment_seq")
        capacity = req_num(entry, "capacity_tons", gt=Decimal("0"))
        if seq in seen:
            bad("compartment_seq must be unique within a truck")
        seen.add(seq)
        parsed.append({"compartment_seq": seq, "capacity_tons": capacity})
    return parsed


@bp.post("/api/trucks")
def create_truck():
    uid, role = authenticate()
    data = get_body()
    plate_no = req_str(data, "plate_no")
    capability = req_enum(data, "cargo_class_capability",
                          ("STANDARD_ONLY", "MEDICATED_CAPABLE"))
    compartments = parse_compartments(data)
    authorize(role, uid, {"MillManager"})
    if any(t["plate_no"] == plate_no for t in STORE["trucks"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Plate {plate_no!r} already exists")
    rec = make_record()
    rec.update(plate_no=plate_no, cargo_class_capability=capability,
               compartments=compartments, status="AVAILABLE")
    STORE["trucks"][rec["id"]] = rec
    return success(ser_truck(rec), 201)


@bp.get("/api/trucks/<tid>")
def get_truck(tid):
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    return success(ser_truck(_get_truck(tid)), 200)


@bp.post("/api/trucks/<tid>/set-status")
def set_truck_status(tid):
    uid, role = authenticate()
    data = get_body()
    status = req_enum(data, "status", ("AVAILABLE", "RETIRED"))
    authorize(role, uid, {"MillManager"})
    t = _get_truck(tid)
    if status == "AVAILABLE" or t["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an AVAILABLE truck can transition, and only to RETIRED")
    if any(tr["truck_id"] == tid and tr["status"] in ("PLANNED", "LOADING", "IN_TRANSIT")
           for tr in STORE["trips"].values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Truck has non-terminal trips and cannot be retired")
    t["status"] = "RETIRED"
    bump(t)
    return success(ser_truck(t), 200)
