"""Face endpoints (PRD 3.1)."""
from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success, paginate, sort_created
from serializers import (face_out, permit_out, work_order_out, flight_out)
from util import req_int, req_str, req_enum, req_bool, opt_int, opt_bool, \
    parse_date

bp = Blueprint("faces", __name__, url_prefix="/api")

DISPLAY_TYPES = ("STATIC", "DIGITAL")


def get_face_or_404(face_id):
    face = db.faces.get(face_id)
    if face is None:
        raise ApiError("ERR_FACE_NOT_FOUND", 404, "Face not found")
    return face


@bp.route("/faces", methods=["POST"])
def create_face():
    require_roles("InventoryManager")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    face_code = req_str(body, "face_code")
    structure_code = req_str(body, "structure_code")
    market_code = req_str(body, "market_code")
    display_type = req_enum(body, "display_type", DISPLAY_TYPES)
    illuminated = req_bool(body, "illuminated")
    daily_traffic_count = req_int(body, "daily_traffic_count", 0)
    width_inches = req_int(body, "width_inches", 1)
    height_inches = req_int(body, "height_inches", 1)
    loop_slots_total = opt_int(body, "loop_slots_total")
    if display_type == "DIGITAL":
        if loop_slots_total is None or not 1 <= loop_slots_total <= 16:
            raise ApiError("ERR_DIGITAL_SLOTS_REQUIRED", 400,
                           "DIGITAL faces require loop_slots_total in 1..16")
    else:
        if loop_slots_total is not None:
            raise ApiError("ERR_DIGITAL_SLOTS_REQUIRED", 400,
                           "STATIC faces must omit loop_slots_total")

    for other in db.faces.values():
        if other["face_code"] == face_code:
            raise err_invalid_request("face_code must be globally unique")

    face = db.new_resource()
    face.update({
        "face_code": face_code,
        "structure_code": structure_code,
        "market_code": market_code,
        "display_type": display_type,
        "illuminated": illuminated,
        "daily_traffic_count": daily_traffic_count,
        "width_inches": width_inches,
        "height_inches": height_inches,
        "loop_slots_total": loop_slots_total if display_type == "DIGITAL" else None,
        "status": "AVAILABLE",
        "booking_posture": "OPEN",
        "current_permit_id": None,
    })
    db.faces[face["id"]] = face
    return success(face_out(face), code=201)


@bp.route("/faces/<face_id>", methods=["GET"])
def get_face(face_id):
    require_roles("InventoryManager", "SalesPlanner", "OperationsAuditor",
                  "ComplianceOfficer")
    face = get_face_or_404(face_id)
    return success(face_out(face))


@bp.route("/faces/<face_id>", methods=["PUT"])
def update_face(face_id):
    require_roles("InventoryManager")
    face = get_face_or_404(face_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    # Family 4: shape
    new_traffic = opt_int(body, "daily_traffic_count", 0)
    new_illuminated = opt_bool(body, "illuminated")
    new_status = None
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("AVAILABLE", "UNDER_MAINTENANCE",
                                  "PERMIT_SUSPENDED", "DECOMMISSIONED"):
            raise err_invalid_request("Unknown face status")

    # Family 5: state legality
    if face["status"] == "DECOMMISSIONED":
        raise err_invalid_state("A DECOMMISSIONED face rejects all mutations")
    if "status" in body and body["status"] is not None:
        new_status = body["status"]
        if new_status == "PERMIT_SUSPENDED":
            raise err_invalid_state("PERMIT_SUSPENDED is system-set only")
        if new_status != face["status"]:
            allowed = {
                ("AVAILABLE", "UNDER_MAINTENANCE"),
                ("UNDER_MAINTENANCE", "AVAILABLE"),
                ("AVAILABLE", "DECOMMISSIONED"),
                ("UNDER_MAINTENANCE", "DECOMMISSIONED"),
            }
            if (face["status"], new_status) not in allowed:
                raise err_invalid_state(
                    "Face cannot transition %s -> %s"
                    % (face["status"], new_status))
        if new_status == "DECOMMISSIONED":
            blocking = [f for f in domain.face_flights(face["id"])
                        if f["status"] in domain.ACTIVE_FLIGHT_SET]
            if blocking:
                raise err_invalid_state(
                    "Face has flights in progress and cannot be decommissioned")

    traffic_changed = (new_traffic is not None
                       and new_traffic != face["daily_traffic_count"])
    illum_changed = (new_illuminated is not None
                     and new_illuminated != face["illuminated"])

    if new_traffic is not None:
        face["daily_traffic_count"] = new_traffic
    if new_illuminated is not None:
        face["illuminated"] = new_illuminated

    if new_status is not None and new_status != face["status"]:
        if new_status == "DECOMMISSIONED" \
                and face["status"] == "UNDER_MAINTENANCE":
            for w in domain.face_work_orders(face["id"]):
                if w["status"] in ("OPEN", "SCHEDULED"):
                    w["status"] = "CANCELLED"
                    db.touch(w)
        face["status"] = new_status
        face["booking_posture"] = domain.face_posture(new_status)

    db.touch(face)

    if traffic_changed or illum_changed:
        for f in domain.face_flights(face["id"]):
            if f["status"] in ("HELD", "BOOKED", "ART_CLEARED"):
                f["estimated_impressions"] = calc.estimated_impressions(
                    face, f["weeks"], f["loop_slots"])
                calc.replay_delivered(f)
                db.touch(f)

    return success(face_out(face))


@bp.route("/faces/<face_id>/permits", methods=["GET"])
def face_permits(face_id):
    require_roles("InventoryManager", "ComplianceOfficer")
    face = get_face_or_404(face_id)
    items = sort_created([p for p in db.permits.values()
                          if p["face_id"] == face["id"]])
    page, meta = paginate(items)
    return success([permit_out(p) for p in page], response_type="array",
                   page_meta=meta)


@bp.route("/faces/<face_id>/maintenance-work-orders", methods=["GET"])
def face_work_orders(face_id):
    require_roles("InventoryManager", "ComplianceOfficer")
    face = get_face_or_404(face_id)
    items = [w for w in db.work_orders.values() if w["face_id"] == face["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    page, meta = paginate(sort_created(items))
    return success([work_order_out(w) for w in page], response_type="array",
                   page_meta=meta)


@bp.route("/faces/<face_id>/flights", methods=["GET"])
def face_flights(face_id):
    require_roles("InventoryManager", "SalesPlanner", "OperationsAuditor")
    face = get_face_or_404(face_id)
    items = [f for f in db.flights.values() if f["face_id"] == face["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [f for f in items if f["status"] == status_filter]
    page, meta = paginate(sort_created(items))
    return success([flight_out(f) for f in page], response_type="array",
                   page_meta=meta)


@bp.route("/faces/<face_id>/availability", methods=["GET"])
def face_availability(face_id):
    require_roles("InventoryManager", "SalesPlanner")
    face = get_face_or_404(face_id)
    from_date = parse_date(request.args.get("from_date"), "from_date")
    to_date = parse_date(request.args.get("to_date"), "to_date")
    if to_date < from_date:
        raise err_invalid_request("to_date must not precede from_date")
    committed = domain.merged_calendar(face, False, from_date, to_date)
    forward = domain.merged_calendar(face, True, from_date, to_date)
    return success({"committed_calendar": committed,
                    "forward_calendar": forward})
