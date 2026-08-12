"""Technicians: registration, certification updates, suspend/reinstate."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, invalid_request, logical_now, ok,
    ok_list, opt_datetime, opt_int, paginate, pagination, query_str,
    req_datetime, req_int, req_present, req_string,
)

bp = Blueprint("technicians", __name__)


def _validate_certified_methods(value):
    if not isinstance(value, list) or len(value) == 0:
        raise invalid_request(
            "Field 'certified_methods' must be a non-empty list.")
    methods = []
    for item in value:
        if not isinstance(item, str):
            raise invalid_request("certified_methods entries must be strings.")
        if item not in domain.STERILIZER_METHODS:
            raise ApiError("ERR_INVALID_ENUM_VALUE", 400,
                           "certified_methods entries must be one of %s."
                           % list(domain.STERILIZER_METHODS))
        methods.append(item)
    return methods


@bp.post("/spd/technicians")
def create_technician():
    auth(("FacilityAdmin",))
    body = get_body()
    name = req_string(body, "name")
    certification_level = req_int(body, "certification_level",
                                  minimum=1, maximum=3)
    certified_methods = _validate_certified_methods(
        req_present(body, "certified_methods"))
    certification_expires_at = req_datetime(body, "certification_expires_at")

    record = store.new_record()
    record.update({
        "name": name,
        "certification_level": certification_level,
        "certified_methods": certified_methods,
        "certification_expires_at": certification_expires_at,
        "status": "ACTIVE",
    })
    store.TECHNICIANS[record["id"]] = record
    return created(views.technician_view(record))


@bp.get("/spd/technicians")
def list_technicians():
    auth(ANY)
    limit, offset = pagination()
    status = query_str("status")
    domain.sweep_all_technicians()
    rows = [r for r in store.TECHNICIANS.values()
            if status is None or r["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.technician_view(r) for r in page], limit, offset, total)


@bp.get("/spd/technicians/<technician_id>")
def get_technician(technician_id):
    auth(ANY)
    record = store.fetch(store.TECHNICIANS, technician_id)
    domain.sweep_technician(record)
    return ok(views.technician_view(record))


@bp.put("/spd/technicians/<technician_id>")
def update_technician(technician_id):
    auth(("FacilityAdmin",))
    record = store.fetch(store.TECHNICIANS, technician_id)
    domain.sweep_technician(record)
    body = get_body()

    certification_level = opt_int(body, "certification_level",
                                  minimum=1, maximum=3)
    certified_methods = None
    if "certified_methods" in body and body["certified_methods"] is not None:
        certified_methods = _validate_certified_methods(body["certified_methods"])
    certification_expires_at = opt_datetime(body, "certification_expires_at")

    if certification_level is not None:
        record["certification_level"] = certification_level
    if certified_methods is not None:
        record["certified_methods"] = certified_methods
    if certification_expires_at is not None:
        record["certification_expires_at"] = certification_expires_at

    # renewal past the current logical time reactivates CERTIFICATION_EXPIRED
    if (record["status"] == "CERTIFICATION_EXPIRED"
            and record["certification_expires_at"] > logical_now()):
        record["status"] = "ACTIVE"

    store.touch(record)
    return ok(views.technician_view(record))


@bp.post("/spd/technicians/<technician_id>/suspend")
def suspend_technician(technician_id):
    auth(("SpdSupervisor",))
    record = store.fetch(store.TECHNICIANS, technician_id)
    domain.sweep_technician(record)
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_NOT_ACTIVE", 409,
                       "suspend requires technician ACTIVE.")
    record["status"] = "SUSPENDED"
    store.touch(record)
    return ok(views.technician_view(record))


@bp.post("/spd/technicians/<technician_id>/reinstate")
def reinstate_technician(technician_id):
    auth(("SpdSupervisor",))
    record = store.fetch(store.TECHNICIANS, technician_id)
    domain.sweep_technician(record)
    if record["status"] != "SUSPENDED":
        raise ApiError("ERR_TECHNICIAN_NOT_SUSPENDED", 409,
                       "reinstate requires technician SUSPENDED.")
    record["status"] = "ACTIVE"
    store.touch(record)
    return ok(views.technician_view(record))
