from flask import request

from core import (store, authorize, get_body, respond_object, respond_list,
                  touch, serialize, serialize_many, sort_by_created, paginate,
                  ApiError)
from lookups import get_penalty
from services import apply_est_side_effect


def register(app):

    @app.route("/penalties/<pid>", methods=["GET"])
    def get_penalty_route(pid):
        authorize(["ProgramAdmin", "Establishment"])
        pen = get_penalty(pid)
        return respond_object(serialize(pen), 200)

    @app.route("/penalties", methods=["GET"])
    def list_penalties():
        authorize(["ProgramAdmin", "Establishment"])
        establishment_id = request.args.get("establishment_id")
        device_id = request.args.get("device_id")
        status = request.args.get("status")
        items = list(store.penalties.values())
        if establishment_id is not None:
            items = [p for p in items if p["establishment_id"] == establishment_id]
        if device_id is not None:
            items = [p for p in items if p["device_id"] == device_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/penalties/<pid>/pay", methods=["POST"])
    def pay_penalty(pid):
        role, uid = authorize(["Establishment", "ProgramAdmin"])
        get_body(optional=True)
        pen = get_penalty(pid)
        if role == "Establishment" and uid != pen["establishment_id"]:
            raise ApiError("ERR_OWNERSHIP_VIOLATION",
                           "Establishment may only pay its own penalties")
        if pen["status"] != "ASSESSED":
            raise ApiError("ERR_PENALTY_NOT_PAYABLE", "Penalty is not payable")
        pen["status"] = "PAID"
        touch(pen)
        est = store.establishments.get(pen["establishment_id"])
        if est is not None:
            apply_est_side_effect(est)
        return respond_object(serialize(pen), 200)

    @app.route("/penalties/<pid>/waive", methods=["POST"])
    def waive_penalty(pid):
        authorize(["ProgramAdmin"])
        get_body(optional=True)  # reason? ignored
        pen = get_penalty(pid)
        if pen["status"] != "ASSESSED":
            raise ApiError("ERR_PENALTY_NOT_PAYABLE", "Penalty is not in ASSESSED state")
        pen["status"] = "WAIVED"
        touch(pen)
        est = store.establishments.get(pen["establishment_id"])
        if est is not None:
            apply_est_side_effect(est)
        return respond_object(serialize(pen), 200)
