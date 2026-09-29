"""Diversion and extension requests (PRD 3.4)."""
from flask import Blueprint

from db import db, new_record, touch
from errors import ApiError
from middleware import require
from response import ok
from services import calc, domain
import validate as v

bp = Blueprint("amendments", __name__)

AMENDMENT_TYPES = ("DIVERSION", "EXTENSION")
JUSTIFICATIONS = ("CONSIGNEE_CHANGE", "CARRIER_EQUIPMENT_FAILURE",
                  "PORT_CONGESTION", "WEATHER_DELAY")
IN_BOND_TYPES = ("IT", "TE", "IE")
AMENDABLE = ("FILED", "IN_TRANSIT", "OVERDUE")
DECISIONS = ("APPROVE", "DENY")


def _route_ok(in_bond_type, origin_port_id, destination_port_id):
    if in_bond_type == "IE":
        return origin_port_id == destination_port_id
    return origin_port_id != destination_port_id


@bp.route("/in-bond/amendment-requests", methods=["POST"])
def submit_amendment():
    user_id, _role = require("BondedCarrier")

    peeked = v.peek_body().get("movement_id")
    if isinstance(peeked, str):
        target = db.movements.get(peeked)
        if target is not None and target["carrier_id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    movement_id = v.req_str(body, "movement_id")
    amendment_type = v.req_enum(body, "amendment_type", AMENDMENT_TYPES)
    justification_code = v.req_enum(body, "justification_code", JUSTIFICATIONS)
    expected_version = v.req_int(body, "expected_movement_version", minimum=0)
    if amendment_type == "DIVERSION":
        port_code = v.req_str(body, "requested_destination_port_code")
        if len(port_code) != 4 or not port_code.isdigit():
            raise ApiError("ERR_INVALID_REQUEST")
        requested_type = v.opt_enum(body, "requested_in_bond_type", IN_BOND_TYPES)
        v.must_be_absent(body, "requested_days")
        requested_days = None
    else:
        port_code = None
        requested_type = None
        v.must_be_absent(body, "requested_destination_port_code")
        v.must_be_absent(body, "requested_in_bond_type")
        requested_days = v.req_int(body, "requested_days", minimum=1)

    movement = db.movements.get(movement_id)
    if movement is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    requested_port = None
    if port_code is not None:
        requested_port = domain.port_by_code(port_code)
        if requested_port is None:
            raise ApiError("ERR_PORT_NOT_FOUND")
    if movement["carrier_id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    # Band 8 - optimistic concurrency.
    if expected_version != movement["version"]:
        raise ApiError("ERR_STALE_MOVEMENT_VERSION")

    # Band 9 / 10 / 11.
    if movement["transit_status"] not in AMENDABLE:
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if movement["custody_status"] == "GENERAL_ORDER":
        raise ApiError("ERR_MOVEMENT_IN_GENERAL_ORDER")
    if movement["transit_status"] != "FILED" and not movement["seal_intact"]:
        raise ApiError("ERR_SEAL_INTEGRITY_UNRESOLVED")

    # Band 12 - the extension grace window.
    if amendment_type == "EXTENSION":
        cutoff = movement["transit_deadline_utc"] + calc.days(calc.LATE_EXTENSION_GRACE_DAYS)
        if db.now > cutoff:
            raise ApiError("ERR_TRANSIT_DEADLINE_PASSED")

    # Band 13.
    if amendment_type == "DIVERSION":
        effective_type = requested_type or movement["in_bond_type"]
        if not _route_ok(effective_type, movement["origin_port_id"], requested_port["id"]):
            raise ApiError("ERR_ROUTE_TYPE_MISMATCH")
    else:
        if movement["extension_days_granted"] + requested_days > calc.EXTENSION_DAYS_MAX:
            raise ApiError("ERR_EXTENSION_LIMIT_EXCEEDED")

    rec = new_record()
    rec.update({
        "movement_id": movement["id"],
        "amendment_type": amendment_type,
        "requested_destination_port_code": port_code,
        "requested_in_bond_type": requested_type,
        "requested_days": requested_days,
        "justification_code": justification_code,
        "status": "SUBMITTED",
        "granted_days": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "decision_reason_code": None,
        "resulting_deadline_utc": None,
    })
    db.amendments[rec["id"]] = rec

    for other in domain.amendments_of(movement["id"]):
        if other["id"] == rec["id"] or other["status"] != "SUBMITTED":
            continue
        other["status"] = "SUPERSEDED"
        other["decision_reason_code"] = "SUPERSEDED_BY_NEWER_REQUEST"
        touch(other)

    touch(movement)
    return ok(domain.amendment_json(rec), 201)


@bp.route("/in-bond/amendment-requests/<amendment_id>/decision", methods=["POST"])
def decide_amendment(amendment_id):
    user_id, _role = require("CBPOfficer")
    body = v.get_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    decision_reason_code = v.req_str(body, "decision_reason_code")
    granted_days = v.opt_int(body, "granted_days", minimum=0)

    rec = db.amendments.get(amendment_id)
    if rec is None:
        raise ApiError("ERR_AMENDMENT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE")

    movement = db.movements.get(rec["movement_id"])
    if movement is None or movement["transit_status"] not in AMENDABLE:
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    if decision == "APPROVE":
        if rec["amendment_type"] == "DIVERSION":
            port = domain.port_by_code(rec["requested_destination_port_code"])
            if port is None:
                raise ApiError("ERR_PORT_NOT_FOUND")
            effective_type = rec["requested_in_bond_type"] or movement["in_bond_type"]
            if not _route_ok(effective_type, movement["origin_port_id"], port["id"]):
                raise ApiError("ERR_ROUTE_TYPE_MISMATCH")
        else:
            if granted_days is None or granted_days < 1 or granted_days > rec["requested_days"]:
                raise ApiError("ERR_GRANTED_DAYS_INVALID")
            if movement["extension_days_granted"] + granted_days > calc.EXTENSION_DAYS_MAX:
                raise ApiError("ERR_EXTENSION_LIMIT_EXCEEDED")

    decided_at = db.now
    rec["decided_by_user_id"] = user_id
    rec["decided_at"] = decided_at
    rec["decision_reason_code"] = decision_reason_code

    if decision == "DENY":
        rec["status"] = "DENIED"
        touch(rec)
        return ok(domain.amendment_json(rec))

    rec["status"] = "APPROVED"
    if rec["amendment_type"] == "DIVERSION":
        port = domain.port_by_code(rec["requested_destination_port_code"])
        movement["destination_port_id"] = port["id"]
        if rec["requested_in_bond_type"] is not None:
            movement["in_bond_type"] = rec["requested_in_bond_type"]
        deadline = domain.recompute_transit_window(movement, anchor=decided_at)
    else:
        movement["extension_days_granted"] += granted_days
        rec["granted_days"] = granted_days
        deadline = domain.recompute_transit_window(movement)

    rec["resulting_deadline_utc"] = deadline
    touch(rec)

    if (movement["transit_status"] == "OVERDUE" and movement["overdue_days"] <= 2
            and deadline > db.now):
        movement["transit_status"] = "IN_TRANSIT"
        movement["overdue_days"] = 0
    touch(movement)
    return ok(domain.amendment_json(rec))
