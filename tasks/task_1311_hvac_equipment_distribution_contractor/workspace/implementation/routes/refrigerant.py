"""Refrigerant cylinders, the heel-compliance regime, and the event ledger."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_DUPLICATE, ERR_COMPLIANCE_HOLD, \
    ERR_INVALID_CYLINDER_WEIGHT, invalid_state
from middleware import authenticate, authorize
from response import success
from serializers import refrigerant_cylinder as ser_cyl, \
    refrigerant_event as ser_event
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_enum, \
    get_decimal, touch, quant2
from routes.common import body, get_path, get_ref, new_common, list_response
from utils import next_seq, new_id

bp = Blueprint("refrigerant", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "ComplianceOfficer"}
GAS_TYPES = {"R410A", "R454B", "R32"}


def _append_event(cylinder, event_type, delta, note=None):
    e = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": next_seq(),
        "cylinder_id": cylinder["id"],
        "event_type": event_type,
        "weight_delta_lbs": quant2(delta),
        "recorded_at": clock.now(),
        "note": note,
    }
    db.refrigerant_events[e["id"]] = e
    return e


@bp.post("/refrigerant-cylinders")
def create_cylinder():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"cylinder_tag", "refrigerant_type",
                                "tare_weight_lbs", "full_weight_lbs"}, struct)
    tag = get_str(data, "cylinder_tag", struct)
    gas = get_enum(data, "refrigerant_type", struct, GAS_TYPES)
    tare = get_decimal(data, "tare_weight_lbs", struct)
    full = get_decimal(data, "full_weight_lbs", struct)

    if isinstance(tag, str):
        for c in db.refrigerant_cylinders.values():
            if c["cylinder_tag"] == tag:
                raise ApiError(ERR_DUPLICATE, 409, "cylinder_tag already exists")
    struct.raise_if_bad()

    c = new_common()
    c.update({
        "cylinder_tag": tag,
        "refrigerant_type": gas,
        "tare_weight_lbs": quant2(tare),
        "full_weight_lbs": quant2(full),
        "current_weight_lbs": quant2(full),
        "holder_contractor_id": None,
        "issued_at": None,
        "status": "IN_STOCK",
    })
    db.refrigerant_cylinders[c["id"]] = c
    return success(ser_cyl(c), 201)


@bp.get("/refrigerant-cylinders/<cid>")
def get_cylinder(cid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    c = get_path(db.refrigerant_cylinders, cid)
    return success(ser_cyl(c))


@bp.get("/refrigerant-cylinders")
def list_cylinders():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"holder_contractor_id": request.args.get("holder_contractor_id"),
               "status": request.args.get("status")}
    return list_response(db.refrigerant_cylinders.values(), ser_cyl, filters)


@bp.post("/refrigerant-cylinders/<cid>/issue")
def issue_cylinder(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    c = get_path(db.refrigerant_cylinders, cid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"contractor_id"}, struct)
    contractor_id = data.get("contractor_id")
    contractor = None
    if isinstance(contractor_id, str):
        contractor = get_ref(db.contractors, contractor_id, "contractor_id")
    elif contractor_id is None:
        struct.add("Missing required field: contractor_id")
    else:
        struct.add("Field contractor_id must be a string")

    # From-state (priority 5) before the compliance gate (priority 7).
    if c["status"] != "IN_STOCK":
        raise invalid_state("Only an IN_STOCK cylinder may be issued")
    if contractor is not None and contractor["status"] != "ACTIVE":
        raise invalid_state("Target contractor is not ACTIVE")
    if contractor is not None and contractor["compliance_standing"] == "HOLD":
        raise ApiError(ERR_COMPLIANCE_HOLD, 422,
                       "Contractor compliance standing is HOLD")
    struct.raise_if_bad()

    _append_event(c, "ISSUE", Decimal("0"))
    c["holder_contractor_id"] = contractor_id
    c["issued_at"] = clock.now()
    c["status"] = "ISSUED"
    touch(c)
    return success(ser_cyl(c))


@bp.post("/refrigerant-cylinders/<cid>/return")
def return_cylinder(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    c = get_path(db.refrigerant_cylinders, cid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"returned_weight_lbs"}, struct)
    returned = get_decimal(data, "returned_weight_lbs", struct)

    # From-state (priority 5) before weight sanity (priority 8). The lazy
    # sweep has already flipped overdue ISSUED cylinders to RETURN_PENDING.
    if c["status"] not in ("ISSUED", "RETURN_PENDING"):
        raise invalid_state("Only an ISSUED or RETURN_PENDING cylinder may "
                            "be returned")
    if returned is not None:
        returned = quant2(returned)
        if returned < c["tare_weight_lbs"] or returned > c["full_weight_lbs"]:
            raise ApiError(ERR_INVALID_CYLINDER_WEIGHT, 422,
                           "returned_weight_lbs must be between tare and "
                           "full weight")
    struct.raise_if_bad()

    holder_id = c.get("holder_contractor_id")
    was_overdue = c["status"] == "RETURN_PENDING" or (
        c.get("issued_at") is not None
        and clock.now() > c["issued_at"] + timedelta(days=core.OVERDUE_DAYS))

    _append_event(c, "RETURN", returned - c["current_weight_lbs"])
    c["current_weight_lbs"] = returned

    # Heel check: shortfall beyond 10% of the charge appends an ADJUSTMENT
    # marker event and records a violation against the holder.
    if returned < c["full_weight_lbs"] * core.HEEL_MIN_FRACTION:
        _append_event(c, "ADJUSTMENT", Decimal("0"), note="HEEL_SHORTFALL")
        if holder_id:
            db.heel_violations.append({
                "contractor_id": holder_id,
                "recorded_at": clock.now(),
            })

    c["holder_contractor_id"] = None
    c["issued_at"] = None
    c["status"] = "RETURNED"
    touch(c)

    if holder_id:
        holder = db.contractors.get(holder_id)
        if holder is not None:
            core.recompute_compliance_standing(
                holder, overdue_return_just_cleared=was_overdue)
    return success(ser_cyl(c))


@bp.post("/refrigerant-cylinders/<cid>/reclaim")
def reclaim_cylinder(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    c = get_path(db.refrigerant_cylinders, cid)
    if c["status"] != "RETURNED":
        raise invalid_state("Only a RETURNED cylinder may be reclaimed")
    _append_event(c, "RECLAIM", c["tare_weight_lbs"] - c["current_weight_lbs"])
    c["current_weight_lbs"] = c["tare_weight_lbs"]
    c["status"] = "RECLAIMED"
    touch(c)
    return success(ser_cyl(c))


@bp.post("/refrigerant-cylinders/<cid>/refill")
def refill_cylinder(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    c = get_path(db.refrigerant_cylinders, cid)
    if c["status"] != "RETURNED":
        raise invalid_state("Only a RETURNED cylinder may be refilled")
    _append_event(c, "ADJUSTMENT", c["full_weight_lbs"] - c["current_weight_lbs"])
    c["current_weight_lbs"] = c["full_weight_lbs"]
    c["status"] = "IN_STOCK"
    touch(c)
    return success(ser_cyl(c))


@bp.get("/refrigerant-cylinders/<cid>/events")
def list_events(cid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    c = get_path(db.refrigerant_cylinders, cid)
    events = [e for e in db.refrigerant_events.values()
              if e["cylinder_id"] == c["id"]]
    # recorded_at ASC, created_at tie-break (insertion order is deterministic).
    return list_response(events, ser_event)
