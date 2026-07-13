from flask import request

from core import (store, authorize, get_body, require_string, require_enum,
                  respond_object, respond_list, base_common, touch, serialize,
                  serialize_many, sort_by_created, paginate, ApiError)
from lookups import get_device, get_complaint

DISPOSITIONS = {"UPHELD", "DISMISSED"}


def register(app):

    @app.route("/complaints", methods=["POST"])
    def create_complaint():
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        device_id = require_string(body, "device_id")
        complainant_name = require_string(body, "complainant_name")
        description = require_string(body, "description")
        get_device(device_id)
        comp = base_common("Complaint")
        comp.update({
            "device_id": device_id,
            "complainant_name": complainant_name,
            "description": description,
            "status": "FILED",
        })
        store.complaints[comp["id"]] = comp
        return respond_object(serialize(comp), 201)

    @app.route("/complaints/<cid>", methods=["GET"])
    def get_complaint_route(cid):
        authorize(["ProgramAdmin", "Inspector"])
        comp = get_complaint(cid)
        return respond_object(serialize(comp), 200)

    @app.route("/complaints", methods=["GET"])
    def list_complaints():
        authorize(["ProgramAdmin", "Inspector"])
        device_id = request.args.get("device_id")
        status = request.args.get("status")
        items = list(store.complaints.values())
        if device_id is not None:
            items = [c for c in items if c["device_id"] == device_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/complaints/<cid>/resolve", methods=["POST"])
    def resolve_complaint(cid):
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        disposition = require_enum(body, "disposition", DISPOSITIONS)
        comp = get_complaint(cid)
        if comp["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Complaint is not in a resolvable state")
        if disposition == "UPHELD":
            device = store.devices.get(comp["device_id"])
            if device is None or device["status"] != "CONDEMNED":
                raise ApiError("ERR_INVALID_STATE",
                               "A complaint can be upheld only when its device is CONDEMNED")
            comp["status"] = "UPHELD"
        else:
            comp["status"] = "DISMISSED"
        touch(comp)
        return respond_object(serialize(comp), 200)
