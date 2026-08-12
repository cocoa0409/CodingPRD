"""Tray templates and the availability projection."""
from flask import Blueprint, request

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, invalid_request, ok, ok_list,
    opt_enum, opt_int, opt_string, paginate, pagination, parse_dt, query_str,
    req_enum, req_int, req_present, req_string,
)

bp = Blueprint("templates", __name__)

PACKAGING_TYPES = ("WRAPPED", "RIGID_CONTAINER")


def _validate_requirements(value):
    """instrument_requirements: non-empty list of {instrument_type, quantity>=1}."""
    if not isinstance(value, list) or len(value) == 0:
        raise invalid_request(
            "Field 'instrument_requirements' must be a non-empty list.")
    lines = []
    for line in value:
        if not isinstance(line, dict):
            raise invalid_request(
                "instrument_requirements lines must be objects.")
        itype = line.get("instrument_type")
        if not isinstance(itype, str) or not itype:
            raise invalid_request(
                "instrument_requirements lines need an instrument_type string.")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise invalid_request(
                "instrument_requirements quantity must be an integer >= 1.")
        lines.append({"instrument_type": itype, "quantity": qty})
    return lines


@bp.post("/spd/tray-templates")
def create_tray_template():
    auth(("FacilityAdmin",))
    body = get_body()
    code = req_string(body, "code")
    name = req_string(body, "name")
    specialty = req_string(body, "specialty")
    packaging_type = req_enum(body, "packaging_type", PACKAGING_TYPES)
    requirements = _validate_requirements(req_present(body, "instrument_requirements"))
    assembly_minutes = req_int(body, "assembly_minutes")

    # p9 constraint gate: uniqueness
    for existing in store.TRAY_TEMPLATES.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_TEMPLATE_CODE", 409,
                           "TrayTemplate code already registered.")

    record = store.new_record()
    record.update({
        "code": code,
        "name": name,
        "specialty": specialty,
        "packaging_type": packaging_type,
        "instrument_requirements": requirements,
        "assembly_minutes": assembly_minutes,
    })
    store.TRAY_TEMPLATES[record["id"]] = record
    return created(views.tray_template_view(record))


@bp.get("/spd/tray-templates")
def list_tray_templates():
    auth(ANY)
    limit, offset = pagination()
    specialty = query_str("specialty")
    rows = [r for r in store.TRAY_TEMPLATES.values()
            if specialty is None or r["specialty"] == specialty]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.tray_template_view(r) for r in page], limit, offset, total)


@bp.get("/spd/tray-templates/<template_id>")
def get_tray_template(template_id):
    auth(ANY)
    record = store.fetch(store.TRAY_TEMPLATES, template_id)
    return ok(views.tray_template_view(record))


@bp.put("/spd/tray-templates/<template_id>")
def update_tray_template(template_id):
    auth(("FacilityAdmin",))
    record = store.fetch(store.TRAY_TEMPLATES, template_id)
    body = get_body()

    # p4 request shape: optional fields validated when present
    name = opt_string(body, "name")
    specialty = opt_string(body, "specialty")
    packaging_type = opt_enum(body, "packaging_type", PACKAGING_TYPES)
    requirements = None
    if "instrument_requirements" in body and body["instrument_requirements"] is not None:
        requirements = _validate_requirements(body["instrument_requirements"])
    assembly_minutes = opt_int(body, "assembly_minutes")
    # OCC field is a non-optional input (PRD section 2.7)
    expected = req_int(body, "expected_template_version")

    # p5 optimistic concurrency — before any business rule
    if expected != record["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_template_version does not equal the current version.")

    if name is not None:
        record["name"] = name
    if specialty is not None:
        record["specialty"] = specialty
    if packaging_type is not None:
        record["packaging_type"] = packaging_type
    if requirements is not None:
        record["instrument_requirements"] = requirements
    if assembly_minutes is not None:
        record["assembly_minutes"] = assembly_minutes
    store.touch(record)
    return ok(views.tray_template_view(record))


@bp.get("/spd/tray-templates/<template_id>/availability")
def tray_template_availability(template_id):
    auth(ANY)
    template = store.fetch(store.TRAY_TEMPLATES, template_id)
    raw = request.args.get("window_start_at")
    if raw is None or raw == "":
        raise invalid_request("Query parameter 'window_start_at' is required.")
    window_start = parse_dt(raw, "window_start_at")

    confirmed = 0
    pipeline_extra = 0
    for tray in store.TRAYS.values():
        if tray["template_id"] != template["id"]:
            continue
        if (tray["status"] == "STERILE"
                and tray["sterility_expires_at"] is not None
                and tray["sterility_expires_at"] > window_start):
            confirmed += 1
        elif tray["status"] == "IN_LOAD":
            load = store.STERILIZATION_LOADS.get(tray["current_load_id"])
            if load is None or load["status"] not in ("LOADING", "RUNNING", "COMPLETED"):
                continue
            sterilizer = store.STERILIZERS.get(load["sterilizer_id"])
            if sterilizer is None:
                continue
            projected = domain.projected_release_at(load, sterilizer)
            # inclusive boundary: projected_release_at <= W
            if projected is not None and projected <= window_start:
                pipeline_extra += 1

    return ok({
        "template_id": template["id"],
        "window_start_at": window_start,
        "confirmed_available_count": confirmed,
        "pipeline_available_count": confirmed + pipeline_extra,
    })
