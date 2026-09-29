"""Occupancy measurements: preparation, certification and supersession."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import LIST_READ_ROLES, SINGLE_READ_ROLES, authorize
from response import created, listing, ok
from util import as_date, fmt_dt

bp = Blueprint("measurements", __name__)

VARIANTS = ("SNAPSHOT_STRICT", "TRAILING_GRACE")


def get_measurement(measurement_id):
    return resolve(store.measurements, measurement_id, "ERR_MEASUREMENT_NOT_FOUND")


def _overlaps(a_from, a_through, b_from, b_through):
    """Half-open windows: touching endpoints do not overlap."""
    return a_from < b_through and b_from < a_through


@bp.post("/centers/<center_id>/occupancy-measurements")
def create_measurement(center_id):
    role, user_id = authorize(["ComplianceOfficer"])
    body = v.body()
    variant = v.req_enum(body, "variant", VARIANTS)
    from_date = v.req_date(body, "window_from_date")
    through_date = v.req_date(body, "window_through_date")
    expected_version = v.req_int(body, "expected_center_version", minimum=0)
    if as_date(through_date) <= as_date(from_date):
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_through_date must be strictly after window_from_date")

    center = resolve(store.centers, center_id, "ERR_CENTER_NOT_FOUND")
    if expected_version != center["version"]:
        raise ApiError("ERR_STALE_CENTER_VERSION")

    new_from, new_through = as_date(from_date), as_date(through_date)
    for other in engine.measurements_of_center(center["id"]):
        if other["status"] == "SUPERSEDED":
            continue
        if _overlaps(new_from, new_through,
                     as_date(other["window_from_date"]),
                     as_date(other["window_through_date"])):
            raise ApiError("ERR_MEASUREMENT_WINDOW_OVERLAP")

    measured_at = engine.now()
    figures = engine.snapshot(center, variant, measured_at)
    measurement = base(fmt_dt(measured_at))
    measurement.update({
        "center_id": center["id"],
        "variant": variant,
        "window_from_date": from_date,
        "window_through_date": through_date,
        "measured_at": fmt_dt(measured_at),
        "total_gla_sqft": figures["total_gla_sqft"],
        "occupied_gla_sqft": figures["counted_gla_sqft"],
        "gla_occupancy_pct": figures["gla_occupancy_pct"],
        "open_store_count": figures["open_store_count"],
        "open_anchor_count": figures["open_anchor_count"],
        "counted_lease_count": figures["counted_lease_count"],
        "excluded_lease_count": figures["excluded_lease_count"],
        "breached_condition_count": 0,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "certified_by_user_id": None,
        "certified_at": None,
    })
    store.measurements[measurement["id"]] = measurement

    # every other DRAFT row of the center is superseded on the spot
    for other in engine.measurements_of_center(center["id"]):
        if other["id"] != measurement["id"] and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            engine.touch(other)

    engine.bump_center(center)
    return created(strip(measurement))


@bp.get("/occupancy-measurements/<measurement_id>")
def read_measurement(measurement_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_measurement(measurement_id)))


def _filtered_measurements(center_id=None):
    records = engine._ordered(list(store.measurements.values()))
    if center_id is not None:
        records = [r for r in records if r["center_id"] == center_id]
    return apply_filters(records, [
        ("center_id", v.filter_value("center_id")),
        ("variant", v.filter_value("variant")),
        ("status", v.filter_value("status")),
    ])


@bp.get("/occupancy-measurements")
def list_measurements():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    page, total = paginate(_filtered_measurements(), limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.get("/centers/<center_id>/occupancy-measurements")
def list_center_measurements(center_id):
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    center = resolve(store.centers, center_id, "ERR_CENTER_NOT_FOUND")
    page, total = paginate(_filtered_measurements(center["id"]), limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/occupancy-measurements/<measurement_id>/certify")
def certify(measurement_id):
    role, user_id = authorize(["ComplianceOfficer"])
    v.body()
    measurement = get_measurement(measurement_id)
    if measurement["status"] != "DRAFT":
        raise ApiError("ERR_MEASUREMENT_STATE_INVALID")
    if user_id is not None and user_id == measurement["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    center = resolve(store.centers, measurement["center_id"], "ERR_CENTER_NOT_FOUND")
    own_from = as_date(measurement["window_from_date"])
    own_through = as_date(measurement["window_through_date"])
    for other in engine.measurements_of_center(center["id"]):
        if other["id"] == measurement["id"] or other["status"] != "CERTIFIED":
            continue
        if _overlaps(own_from, own_through,
                     as_date(other["window_from_date"]),
                     as_date(other["window_through_date"])):
            raise ApiError("ERR_MEASUREMENT_WINDOW_OVERLAP")

    measurement["status"] = "CERTIFIED"
    measurement["certified_by_user_id"] = user_id
    measurement["certified_at"] = engine.stamp()
    engine.touch(measurement)

    engine.evaluate_center_conditions(center, "CERTIFIED_MEASUREMENT", measurement)
    measurement["breached_condition_count"] = engine.breached_condition_count(
        center["id"])
    engine.bump_center(center)
    return ok(strip(measurement))


@bp.post("/occupancy-measurements/<measurement_id>/supersede")
def supersede(measurement_id):
    authorize(["ComplianceOfficer"])
    body = v.body()
    v.opt_str(body, "supersede_reason_code")
    measurement = get_measurement(measurement_id)
    if measurement["status"] != "CERTIFIED":
        raise ApiError("ERR_MEASUREMENT_STATE_INVALID")
    center = resolve(store.centers, measurement["center_id"], "ERR_CENTER_NOT_FOUND")

    measurement["status"] = "SUPERSEDED"
    engine.touch(measurement)

    for cond in engine.conditions_of_center(center["id"]):
        if cond.get("last_evaluated_measurement_id") == measurement["id"]:
            cond["last_evaluated_measurement_id"] = None
            engine.touch(cond)
            engine.evaluate_condition(cond, "LIVE_STRICT")
    engine.bump_center(center)
    return ok(strip(measurement))
