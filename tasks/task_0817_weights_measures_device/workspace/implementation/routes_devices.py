from core import (store, authorize, get_body, require_string, require_enum,
                  respond_object, respond_list, base_common, touch, serialize,
                  serialize_many, sort_by_created, paginate, ApiError)
from flask import request
from lookups import get_establishment, get_device
from services import (create_registration_invoice, apply_est_side_effect,
                      void_active_seals)

DEVICE_TYPES = {"SCALE", "FUEL_PUMP", "SCANNER"}
DEVICE_CLASSES = {"CLASS_III", "CLASS_IIIL"}
DEVICE_STATUSES = {"REGISTERED", "SEALED", "CONDEMNED", "OUT_OF_SERVICE", "RETIRED"}


def register(app):

    @app.route("/devices", methods=["POST"])
    def create_device():
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        establishment_id = require_string(body, "establishment_id")
        device_type = require_enum(body, "device_type", DEVICE_TYPES)
        serial_number = require_string(body, "serial_number")
        device_class = body.get("device_class")
        if device_class is None or device_class == "":
            device_class = "CLASS_III"
        elif device_class not in DEVICE_CLASSES:
            raise ApiError("ERR_VALIDATION", "invalid device_class")
        est = get_establishment(establishment_id)

        dev = base_common("Device")
        dev.update({
            "establishment_id": establishment_id,
            "device_type": device_type,
            "device_class": device_class,
            "serial_number": serial_number,
            "status": "REGISTERED",
        })
        store.devices[dev["id"]] = dev

        create_registration_invoice(dev)
        apply_est_side_effect(est)
        return respond_object(serialize(dev), 201)

    @app.route("/devices/<did>", methods=["GET"])
    def get_device_route(did):
        authorize(["ProgramAdmin", "Establishment", "Inspector"])
        dev = get_device(did)
        return respond_object(serialize(dev), 200)

    @app.route("/devices", methods=["GET"])
    def list_devices():
        authorize(["ProgramAdmin", "Establishment", "Inspector"])
        est_id = request.args.get("establishment_id")
        status = request.args.get("status")
        items = list(store.devices.values())
        if est_id is not None:
            items = [d for d in items if d["establishment_id"] == est_id]
        if status is not None:
            items = [d for d in items if d["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/devices/<did>/retire", methods=["POST"])
    def retire_device(did):
        authorize(["ProgramAdmin"])
        get_body(optional=True)  # reason? ignored
        dev = get_device(did)
        if dev["status"] == "RETIRED":
            raise ApiError("ERR_DEVICE_RETIRED", "Device is already retired")
        has_active = any(
            i["device_id"] == did and i["status"] == "IN_PROGRESS"
            for i in store.inspections.values()
        )
        if has_active:
            raise ApiError("ERR_DEVICE_HAS_ACTIVE_INSPECTION",
                           "Device has an inspection in progress")
        was_sealed = (dev["status"] == "SEALED")
        if was_sealed:
            void_active_seals(dev["id"])
        dev["status"] = "RETIRED"
        touch(dev)
        if was_sealed:
            est = store.establishments.get(dev["establishment_id"])
            if est is not None:
                apply_est_side_effect(est)
        return respond_object(serialize(dev), 200)
