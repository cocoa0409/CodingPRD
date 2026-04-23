from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.rider import Rider
from response import success_response
from errors import raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_VALIDATION, ERR_SUSPEND_CRITERIA_NOT_MET

bp = Blueprint("riders", __name__)


def get_rider_or_404(rider_id):
    r = db.riders.get(rider_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Rider not found.")
    return r


@bp.route("/api/riders", methods=["POST"])
@require_roles("PlatformAdmin")
def create_rider():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    phone = data.get("phone")

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "Name is required.")
    if not phone or not isinstance(phone, str) or len(phone.strip()) == 0:
        raise_error(ERR_VALIDATION, "Phone is required.")

    for r in db.riders.values():
        if r.phone == phone:
            raise_error(ERR_VALIDATION, "Phone must be unique across all riders.")

    rider = Rider(name, phone)
    db.riders[rider.id] = rider
    return success_response(rider.to_dict(), 201)


@bp.route("/api/riders/<rider_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def get_rider(rider_id):
    r = get_rider_or_404(rider_id)
    if request.user_role == "Rider" and request.user_id != r.id:
        raise_error(ERR_FORBIDDEN, "Cannot view another rider's profile.")
    return success_response(r.to_dict())


@bp.route("/api/riders/<rider_id>/go-online", methods=["POST"])
@require_roles("Rider")
def go_online(rider_id):
    r = get_rider_or_404(rider_id)
    if request.user_id != r.id:
        raise_error(ERR_FORBIDDEN, "Cannot change another rider's status.")
    if r.status != "OFFLINE":
        raise_error(ERR_INVALID_STATE, "Rider must be OFFLINE to go online.")
    r.status = "AVAILABLE"
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/riders/<rider_id>/go-offline", methods=["POST"])
@require_roles("Rider")
def go_offline(rider_id):
    r = get_rider_or_404(rider_id)
    if request.user_id != r.id:
        raise_error(ERR_FORBIDDEN, "Cannot change another rider's status.")
    if r.status != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE to go offline.")
    active = any(
        a for a in db.assignments.values()
        if a.rider_id == r.id and a.status in ("OFFERED", "ACCEPTED", "PICKED_UP")
    )
    if active:
        raise_error(ERR_INVALID_STATE, "Cannot go offline while active assignments exist.")
    r.status = "OFFLINE"
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/riders/<rider_id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_rider(rider_id):
    r = get_rider_or_404(rider_id)
    if r.status != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE to suspend.")
    if r.on_time_rate >= 0.70 and r.acceptance_rate >= 0.50:
        raise_error(ERR_SUSPEND_CRITERIA_NOT_MET, "Rider does not meet suspension criteria.")
    r.status = "SUSPENDED"
    r.touch()
    return success_response(r.to_dict())
