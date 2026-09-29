"""Machining of critical components and the process-capability gate."""

from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES
from errors import ApiError
from response import list_response, object_response
from store import db, set_fields

bp = Blueprint("machining", __name__)

COMPONENT_TYPES = ("CRANKSHAFT", "CYLINDER_BORE", "CAMSHAFT")
RUN_STATUSES = ("OPEN", "CLOSED", "CAPABILITY_HOLD")
CRITICALITY_BY_COMPONENT = {
    "CRANKSHAFT": "CRITICAL",
    "CYLINDER_BORE": "CRITICAL",
    "CAMSHAFT": "MAJOR",
}


@bp.route("/machining-runs", methods=["POST"])
@endpoint(["QualityEngineer"])
def open_run():
    payload = v.body()
    platform_id = v.id_field(payload, "engine_platform_id")
    casting_lot_id = v.id_field(payload, "casting_lot_id")
    component_type = v.enum_field(payload, "component_type", COMPONENT_TYPES)
    lsl_mm = v.number_field(payload, "lsl_mm")
    usl_mm = v.number_field(payload, "usl_mm")
    if usl_mm <= lsl_mm:
        v.bad("usl_mm must be strictly greater than lsl_mm.")

    platform = svc.get_platform(platform_id)
    lot = svc.get_lot(casting_lot_id)

    if lot["status"] not in ("ACCEPTED", "DEVIATION_ACCEPTED"):
        raise ApiError(
            "ERR_COMPONENT_LOT_NOT_RELEASABLE",
            "The feeding casting lot is not releasable to the floor.",
        )
    if lot["component_category"] != "CASTING":
        raise ApiError(
            "ERR_COMPONENT_CATEGORY_MISMATCH",
            "The casting slot must be fed by a CASTING lot.",
        )

    run = store.new_record(OrderedDict([
        ("engine_platform_id", platform["id"]),
        ("casting_lot_id", lot["id"]),
        ("component_type", component_type),
        ("criticality", CRITICALITY_BY_COMPONENT[component_type]),
        ("lsl_mm", lsl_mm),
        ("usl_mm", usl_mm),
        ("measurements", None),
        ("sample_count", 0),
        ("mean_mm", None),
        ("sigma_mm", None),
        ("cpk", None),
        ("status", "OPEN"),
        ("closed_at", None),
    ]))
    db.machining_runs[run["id"]] = run
    return object_response(store.public(run), 201)


@bp.route("/machining-runs/<run_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_run(run_id):
    run = svc.get_machining_run(run_id)
    return object_response(store.public(run), 200)


@bp.route("/machining-runs", methods=["GET"])
@endpoint(READ_ROLES)
def list_runs():
    limit, offset = v.pagination()
    platform_id = v.query_string("engine_platform_id")
    casting_lot_id = v.query_string("casting_lot_id")
    status = v.query_enum("status", RUN_STATUSES)
    rows = store.sort_created_asc(list(db.machining_runs.values()))
    if platform_id is not None:
        rows = [r for r in rows if r["engine_platform_id"] == platform_id]
    if casting_lot_id is not None:
        rows = [r for r in rows if r["casting_lot_id"] == casting_lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/machining-runs/<run_id>/close", methods=["POST"])
@endpoint(["QualityEngineer"])
def close_run(run_id):
    payload = v.body()
    raw = v.array_field(payload, "measurements")
    measurements = []
    for entry in raw:
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            v.bad("Each entry of 'measurements' must be a number.")
        try:
            value = Decimal(str(entry))
        except (InvalidOperation, ValueError):
            v.bad("Each entry of 'measurements' must be a number.")
            value = None
        if not value.is_finite():
            v.bad("Each entry of 'measurements' must be a finite number.")
        measurements.append(value)

    run = svc.get_machining_run(run_id)
    if run["status"] not in ("OPEN", "CAPABILITY_HOLD"):
        raise ApiError(
            "ERR_MACHINING_RUN_STATE_INVALID",
            "Only an OPEN or CAPABILITY_HOLD machining run may be closed.",
        )
    if len(measurements) < calc.MIN_CAPABILITY_SAMPLE:
        raise ApiError(
            "ERR_CAPABILITY_SAMPLE_INSUFFICIENT",
            "At least %d dimensional readings are required."
            % calc.MIN_CAPABILITY_SAMPLE,
        )

    n, mean, sigma, cpk, status = calc.capability(
        measurements, run["lsl_mm"], run["usl_mm"], run["criticality"]
    )
    set_fields(
        run,
        measurements=measurements,
        sample_count=n,
        mean_mm=mean,
        sigma_mm=sigma,
        cpk=cpk,
        status=status,
        closed_at=store.now_clock(),
    )
    return object_response(store.public(run), 200)
