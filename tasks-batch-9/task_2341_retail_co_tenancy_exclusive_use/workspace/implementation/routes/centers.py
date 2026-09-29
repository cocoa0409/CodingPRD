"""Centers, the logical clock and the compliance sweep."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import LIST_READ_ROLES, SINGLE_READ_ROLES, authorize, authorize_clock
from response import created, listing, ok
from util import D, fmt_dt, parse_dt

bp = Blueprint("centers", __name__)

POSTURES = ("COMPLIANT", "WATCH", "BREACH", "FROZEN")


def get_center(center_id):
    return resolve(store.centers, center_id, "ERR_CENTER_NOT_FOUND")


@bp.post("/centers")
def create_center():
    authorize(["AssetManager"])
    body = v.body()
    name = v.req_str(body, "name")
    total_gla = v.req_int(body, "total_gla_sqft", exclusive_min=0)
    grace = v.opt_int(body, "occupancy_grace_days", default=90, minimum=0)

    center = base(engine.stamp())
    center.update({
        "name": name,
        "total_gla_sqft": total_gla,
        "occupancy_grace_days": grace,
        "occupied_gla_sqft": 0,
        "open_occupancy_pct": D("0.00"),
        "operating_store_count": 0,
        "open_anchor_count": 0,
        "protected_exclusive_count": 0,
        "aggregate_effective_rent_cents": 0,
        "open_violation_count": 0,
        "compliance_posture": "COMPLIANT",
        "redevelopment_status": "NONE",
        "last_sweep_at": None,
    })
    store.centers[center["id"]] = center
    return created(strip(center))


@bp.get("/centers/<center_id>")
def read_center(center_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_center(center_id)))


@bp.get("/centers")
def list_centers():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.centers.values()))
    records = apply_filters(records, [
        ("compliance_posture", v.filter_value("compliance_posture")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/centers/<center_id>/compliance-sweep")
def compliance_sweep(center_id):
    authorize(["ComplianceOfficer"])
    v.body()
    center = get_center(center_id)
    return ok(engine.compliance_sweep(center))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize_clock(["LeaseAdministrator", "ComplianceOfficer", "AssetManager"])
    body = v.body()
    raw = v.req_str(body, "to_iso8601")
    instant = parse_dt(raw)
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'to_iso8601' must be an ISO-8601 UTC instant")
    engine.reposition_clock(instant)
    return ok({"current_utc": fmt_dt(instant)})
