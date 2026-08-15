"""PyrometryRecord endpoints (append-only evidence)."""
from flask import Blueprint

import validation as v
from db import store, new_id, new_evidence
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import Paginator, created, ok
from services import domain

bp = Blueprint("pyrometry", __name__)


@bp.post("/pyrometry-records")
def create_pyrometry_record():
    get_context()
    require_roles(["CalibrationTech"])
    body = v.get_body()
    # tier 4: body FK existence
    furnace = None
    if v.present(body, "furnace_id"):
        furnace = v.resolve_fk(store.furnaces, body.get("furnace_id"), "ERR_FURNACE_NOT_FOUND")
    # tier 9: required fields / enum validity
    if furnace is None:
        v.req_string(body, "furnace_id")  # raises ERR_INVALID_REQUEST
    record_type = v.req_enum(body, "record_type", domain.RECORD_TYPES)
    performed_at = v.req_datetime(body, "performed_at")
    result = v.req_enum(body, "result", domain.RESULTS)
    instrument_id = v.opt_string(body, "instrument_id", default=None)
    if record_type == "INSTRUMENT_CALIBRATION" and not instrument_id:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "instrument_id is required for INSTRUMENT_CALIBRATION records")
    record = {
        "id": new_id(),
        "furnace_id": furnace["id"],
        "record_type": record_type,
        "performed_at": performed_at,
        "result": result,
        "instrument_id": instrument_id,
        "next_due_at": domain.pyrometry_next_due(record_type, furnace["furnace_class"], performed_at),
    }
    new_evidence(record)
    store.pyrometry_records[record["id"]] = record
    # Recording pyrometry recomputes the furnace posture; leaving/returning QUALIFIED
    # cascades BUILDING <-> HOLD on this furnace's loads.
    domain.recompute_posture(furnace)
    return created(record)


@bp.get("/pyrometry-records")
def list_pyrometry_records():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.pyrometry_records.values())
    rows = pg.filter(rows, "furnace_id")
    rows = pg.filter(rows, "record_type")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/pyrometry-records/<record_id>")
def get_pyrometry_record(record_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.pyrometry_records, record_id, "ERR_PYROMETRY_RECORD_NOT_FOUND"))
