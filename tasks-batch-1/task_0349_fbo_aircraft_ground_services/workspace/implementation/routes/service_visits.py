"""ServiceVisit endpoints + stay lifecycle (PRD §3.3, §3.7)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, parse_datetime,
                     parse_optional_datetime, pagination_params, paginate)
from services.derived import (compute_nights, compute_invoice_total,
                              recompute_open_invoice_balance)
from response import now_iso

bp = Blueprint("service_visits", __name__)


def visit_view(v):
    return {
        "id": v["id"],
        "operator_id": v["operator_id"],
        "aircraft_id": v["aircraft_id"],
        "arrival_utc": v["arrival_utc"],
        "departure_utc": v["departure_utc"],
        "nights": v["nights"],
        "status": v["status"],
        "services_outstanding": v["services_outstanding"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _load_visit(id, user_id, role):
    v = db.service_visits.get(id)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Service visit not found.")
    if role == "Operator" and user_id != v["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may act only on its own visits.")
    return v


@bp.route("/service-visits", methods=["POST"])
def create_visit():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    body = get_json()
    operator_id = require_string(body, "operator_id")
    aircraft_id = require_string(body, "aircraft_id")
    arrival = parse_datetime(body, "arrival_utc")
    departure = parse_datetime(body, "departure_utc")

    if role == "Operator" and user_id != operator_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may schedule only its own visits.")
    # Existence resolved left to right.
    operator = db.operators.get(operator_id)
    if operator is None:
        raise err(errors.ERR_NOT_FOUND, "Operator not found.")
    aircraft = db.aircraft.get(aircraft_id)
    if aircraft is None:
        raise err(errors.ERR_NOT_FOUND, "Aircraft not found.")
    # Interval validity.
    if not (departure > arrival):
        raise err(errors.ERR_INVALID_INTERVAL, "departure_utc must be strictly after arrival_utc.")

    v = db.common_create()
    v.update({
        "operator_id": operator_id,
        "aircraft_id": aircraft_id,
        "arrival_utc": body["arrival_utc"],
        "departure_utc": body["departure_utc"],
        "nights": compute_nights(arrival, departure),
        "status": "SCHEDULED",
        "services_outstanding": 0,
    })
    db.service_visits[v["id"]] = v
    return success(visit_view(v), 201)


@bp.route("/service-visits/<id>", methods=["GET"])
def get_visit(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    v = _load_visit(id, user_id, role)
    return success(visit_view(v), 200)


@bp.route("/service-visits", methods=["GET"])
def list_visits():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.service_visits.values())
    if role == "Operator":
        records = [r for r in records if r["operator_id"] == user_id]
    op_f = request.args.get("operator_id")
    ac_f = request.args.get("aircraft_id")
    st_f = request.args.get("status")
    if op_f is not None:
        records = [r for r in records if r["operator_id"] == op_f]
    if ac_f is not None:
        records = [r for r in records if r["aircraft_id"] == ac_f]
    if st_f is not None:
        records = [r for r in records if r["status"] == st_f]
    window, total = paginate(records, limit, offset)
    return list_response([visit_view(r) for r in window], limit, offset, total)


@bp.route("/service-visits/<id>/arrive", methods=["POST"])
def arrive(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    v = _load_visit(id, user_id, role)
    if v["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "arrive requires SCHEDULED status.")
    operator = db.operators.get(v["operator_id"])
    if operator["account_status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Operator account is not ACTIVE.")
    body = get_json()
    provided = parse_optional_datetime(body, "arrival_utc")
    if "arrival_utc" in body and body.get("arrival_utc") is not None:
        v["arrival_utc"] = body["arrival_utc"]
    else:
        v["arrival_utc"] = now_iso()
    v["status"] = "ON_GROUND"
    db.touch(v)
    return success(visit_view(v), 200)


@bp.route("/service-visits/<id>/start-servicing", methods=["POST"])
def start_servicing(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    v = _load_visit(id, user_id, role)
    if v["status"] != "ON_GROUND":
        raise err(errors.ERR_INVALID_STATE, "start-servicing requires ON_GROUND status.")
    has_occupied = any(
        pa["service_visit_id"] == v["id"] and pa["status"] == "OCCUPIED"
        for pa in db.parking_assignments.values()
    )
    if not has_occupied:
        raise err(errors.ERR_VISIT_NOT_SERVICEABLE,
                  "At least one parking assignment must be OCCUPIED before servicing.")
    v["status"] = "SERVICING"
    db.touch(v)
    return success(visit_view(v), 200)


@bp.route("/service-visits/<id>/mark-ready", methods=["POST"])
def mark_ready(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    v = _load_visit(id, user_id, role)
    if v["status"] != "SERVICING":
        raise err(errors.ERR_INVALID_STATE, "mark-ready requires SERVICING status.")
    # PRD §3.3: mark-ready is one of the visit's own "step requests"; an unsettled
    # visit is not in the required starting state for SERVICING → READY_FOR_DEPARTURE,
    # so settlement failures surface as ERR_INVALID_STATE (not ERR_VISIT_NOT_SERVICEABLE,
    # which is reserved for a downstream child operation needing a serviceable parent).
    if v["services_outstanding"] != 0:
        raise err(errors.ERR_INVALID_STATE,
                  "All ramp services must be COMPLETED or CANCELLED.")
    for fo in db.fuel_orders.values():
        if (fo["service_visit_id"] == v["id"]
                and fo["logistics_status"] in ("REQUESTED", "DISPATCHED")):
            raise err(errors.ERR_INVALID_STATE,
                      "No fuel order may still be REQUESTED or DISPATCHED.")
    v["status"] = "READY_FOR_DEPARTURE"
    db.touch(v)
    return success(visit_view(v), 200)


@bp.route("/service-visits/<id>/depart", methods=["POST"])
def depart(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    v = _load_visit(id, user_id, role)
    if v["status"] != "READY_FOR_DEPARTURE":
        raise err(errors.ERR_INVALID_STATE, "depart requires READY_FOR_DEPARTURE status.")
    # No RampSlot APPROVED with window_end in the future.
    from helpers import _parse_iso
    now = now_iso()
    now_dt = _parse_iso(now)
    for slot in db.ramp_slots.values():
        if slot["service_visit_id"] == v["id"] and slot["status"] == "APPROVED":
            end_dt = _parse_iso(slot["window_end_utc"])
            if end_dt is not None and end_dt > now_dt:
                raise err(errors.ERR_INVALID_STATE,
                          "An APPROVED slot with a future window must be used or revoked first.")

    # JOIN: transition visit, then any APPROVED slot whose window has passed -> USED.
    v["status"] = "DEPARTED"
    db.touch(v)
    for slot in db.ramp_slots.values():
        if slot["service_visit_id"] == v["id"] and slot["status"] == "APPROVED":
            end_dt = _parse_iso(slot["window_end_utc"])
            if end_dt is not None and end_dt <= now_dt:
                slot["status"] = "USED"
                db.touch(slot)

    # Create exactly one Invoice (ISSUED), compute total, recompute balance.
    inv = db.common_create()
    inv.update({
        "operator_id": v["operator_id"],
        "service_visit_id": v["id"],
        "total_cents": compute_invoice_total(v["id"]),
        "paid_cents": 0,
        "status": "ISSUED",
    })
    db.invoices[inv["id"]] = inv
    operator = db.operators.get(v["operator_id"])
    recompute_open_invoice_balance(operator)
    return success(visit_view(v), 200)


@bp.route("/service-visits/<id>/cancel", methods=["POST"])
def cancel(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    v = _load_visit(id, user_id, role)
    status = v["status"]
    if status not in ("SCHEDULED", "ON_GROUND"):
        raise err(errors.ERR_INVALID_STATE, "cancel requires SCHEDULED or ON_GROUND status.")

    if status == "ON_GROUND":
        # Precondition: no fuel order FUELED.
        for fo in db.fuel_orders.values():
            if fo["service_visit_id"] == v["id"] and fo["logistics_status"] == "FUELED":
                raise err(errors.ERR_INVALID_STATE,
                          "Cannot cancel: a fuel order has reached FUELED.")

    v["status"] = "CANCELLED"
    db.touch(v)

    # CASCADE — both branches release HELD/OCCUPIED parking and revoke
    # REQUESTED/APPROVED slots. The ON_GROUND branch additionally cancels
    # non-terminal ramp services.
    for pa in db.parking_assignments.values():
        if pa["service_visit_id"] == v["id"] and pa["status"] in ("HELD", "OCCUPIED"):
            pa["status"] = "RELEASED"
            db.touch(pa)
    for slot in db.ramp_slots.values():
        if slot["service_visit_id"] == v["id"] and slot["status"] in ("REQUESTED", "APPROVED"):
            slot["status"] = "REVOKED"
            db.touch(slot)
    if status == "ON_GROUND":
        for rs in db.ramp_services.values():
            if (rs["service_visit_id"] == v["id"]
                    and rs["status"] not in ("COMPLETED", "CANCELLED")):
                rs["status"] = "CANCELLED"
                db.touch(rs)
                v["services_outstanding"] -= 1
        db.touch(v)
    return success(visit_view(v), 200)
