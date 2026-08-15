"""Clock + Facilities + Units."""
from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_NHSN_ORG_ID,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, recompute_summary, touch
from services.serializers import facility_view, unit_view
from util import fmt_dt, parse_dt, clock
from validate import (
    ERR_INVALID_REQUEST_PAIR,
    body,
    opt_number,
    opt_int,
    opt_string,
    pagination_args,
    req_enum,
    req_number,
    req_string,
)

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    b = body()
    v = b.get("to_iso8601")
    if v is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    try:
        dt = parse_dt(v, "to_iso8601")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO-8601 timestamp")
    clock.set(dt)
    return success_object({"current_utc": fmt_dt(clock.get())}, 200)


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
@bp.post("/api/facilities")
def create_facility():
    require_roles(["PlatformAdmin"])
    b = body()
    for f in ("name", "nhsn_org_id", "clabsi_baseline_per_1000", "cauti_baseline_per_1000", "ssi_baseline_per_procedure"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    name = req_string(b, "name")
    nhsn_org_id = req_string(b, "nhsn_org_id")
    clabsi = req_number(b, "clabsi_baseline_per_1000")
    cauti = req_number(b, "cauti_baseline_per_1000")
    ssi = req_number(b, "ssi_baseline_per_procedure")
    threshold = opt_number(b, "sir_high_threshold")
    if threshold is None:
        threshold = 1.25
    hh_min = opt_int(b, "hh_min_opportunities", min_v=0)
    if hh_min is None:
        hh_min = 30

    for f in db.facilities.values():
        if f["nhsn_org_id"] == nhsn_org_id:
            raise_err(ERR_DUPLICATE_NHSN_ORG_ID, "another facility already uses this nhsn_org_id")

    fac = new_entity({
        "name": name,
        "nhsn_org_id": nhsn_org_id,
        "clabsi_baseline_per_1000": clabsi,
        "cauti_baseline_per_1000": cauti,
        "ssi_baseline_per_procedure": ssi,
        "sir_high_threshold": threshold,
        "hh_min_opportunities": hh_min,
    })
    db.facilities[fac["id"]] = fac
    return success_object(facility_view(fac), 201)


@bp.get("/api/facilities/<fid>")
def get_facility(fid):
    require_roles(ALL_ROLES)
    fac = db.facilities.get(fid)
    if fac is None:
        raise_err(ERR_FACILITY_NOT_FOUND, "facility id does not exist")
    return success_object(facility_view(fac))


@bp.put("/api/facilities/<fid>")
def update_facility(fid):
    require_roles(["PlatformAdmin"])
    fac = db.facilities.get(fid)
    if fac is None:
        raise_err(ERR_FACILITY_NOT_FOUND, "facility id does not exist")
    b = body()
    if "expected_facility_version" not in b or b["expected_facility_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_facility_version")
    ev = b["expected_facility_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise_err(ERR_INVALID_REQUEST, "expected_facility_version must be an integer")

    name = opt_string(b, "name", min_len=1) if "name" in b else None
    clabsi = opt_number(b, "clabsi_baseline_per_1000")
    cauti = opt_number(b, "cauti_baseline_per_1000")
    ssi = opt_number(b, "ssi_baseline_per_procedure")
    threshold = opt_number(b, "sir_high_threshold")
    hh_min = opt_int(b, "hh_min_opportunities", min_v=0)

    # OCC check
    if ev != fac["version"]:
        raise_err(ERR_STALE_VERSION, "expected_facility_version does not match current version")

    if "name" in b and name is not None:
        fac["name"] = name
    if clabsi is not None:
        fac["clabsi_baseline_per_1000"] = clabsi
    if cauti is not None:
        fac["cauti_baseline_per_1000"] = cauti
    if ssi is not None:
        fac["ssi_baseline_per_procedure"] = ssi
    if threshold is not None:
        fac["sir_high_threshold"] = threshold
    if hh_min is not None:
        fac["hh_min_opportunities"] = hh_min
    touch(fac)

    # Recompute every mutable MonthlySummary across this facility's units.
    from services.core import MUTABLE_SUMMARY_STATUSES
    unit_ids = {u["id"] for u in db.units.values() if u["facility_id"] == fid}
    for s in db.monthly_summaries.values():
        if s["unit_id"] in unit_ids and s["status"] in MUTABLE_SUMMARY_STATUSES:
            recompute_summary(s)

    return success_object(facility_view(fac))


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
UNIT_TYPES = {"ICU", "WARD", "STEP_DOWN", "OR"}


@bp.post("/api/units")
def create_unit():
    require_roles(["PlatformAdmin"])
    b = body()
    for f in ("facility_id", "name", "unit_type", "nhsn_location_code"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    facility_id = b.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id:
        raise_err(ERR_INVALID_REQUEST, "facility_id must be a string")
    name = req_string(b, "name")
    unit_type = req_enum(b, "unit_type", UNIT_TYPES)
    nhsn_location_code = req_string(b, "nhsn_location_code")

    fac = db.facilities.get(facility_id)
    if fac is None:
        raise_err(ERR_FACILITY_NOT_FOUND, "facility id does not exist")

    unit = new_entity({
        "facility_id": facility_id,
        "name": name,
        "unit_type": unit_type,
        "nhsn_location_code": nhsn_location_code,
        "surveillance_posture": "NORMAL",
    })
    db.units[unit["id"]] = unit
    return success_object(unit_view(unit), 201)


@bp.get("/api/units")
def list_units():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    facility_id = request.args.get("facility_id")
    items = [u for u in db.units.values() if facility_id is None or u["facility_id"] == facility_id]
    items.sort(key=lambda u: u["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([unit_view(u) for u in page], total, limit, offset)


@bp.get("/api/units/<uid>")
def get_unit(uid):
    require_roles(ALL_ROLES)
    unit = db.units.get(uid)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")
    return success_object(unit_view(unit))
