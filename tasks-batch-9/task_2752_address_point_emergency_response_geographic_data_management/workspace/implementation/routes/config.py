"""Jurisdictions, agencies, coverage cells and the logical clock."""

from flask import Blueprint

import calc
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, fmt_dt, sorted_rows, touch

bp = Blueprint("config", __name__)

JURISDICTION_TYPES = ["COUNTY", "MUNICIPAL", "UNINCORPORATED"]
AGENCY_TYPES = ["LAW", "FIRE", "EMS"]
AGENCY_STATUSES = ["ACTIVE", "SUSPENDED"]


# ---------------------------------------------------------------------------
# jurisdictions
# ---------------------------------------------------------------------------
@bp.post("/jurisdictions")
def create_jurisdiction():
    v.auth(["SystemAdmin"])
    data = v.body()
    name = v.req_str(data, "name", 1, 120)
    code = v.req_str(data, "code", 2, 8, r"^[A-Z0-9]{2,8}$")
    jurisdiction_type = v.req_enum(data, "jurisdiction_type", JURISDICTION_TYPES)
    postal_city = v.req_str(data, "postal_city", 1, 60)

    for row in db.jurisdictions.values():
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION_CODE",
                           "Jurisdiction code '%s' is already registered." % code)

    row = base_record()
    row.update({
        "name": name,
        "code": code,
        "jurisdiction_type": jurisdiction_type,
        "postal_city": postal_city.upper(),
    })
    db.jurisdictions[row["id"]] = row
    return created(ser.jurisdiction(row))


@bp.get("/jurisdictions/<identifier>")
def get_jurisdiction(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("jurisdiction", identifier)
    return ok(ser.jurisdiction(row))


@bp.get("/jurisdictions")
def list_jurisdictions():
    v.auth(v.ALL_ROLES)
    jurisdiction_type = v.q_enum("jurisdiction_type", JURISDICTION_TYPES)
    code = v.q_str("code")
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.jurisdictions.values()))
    if jurisdiction_type is not None:
        rows = [r for r in rows if r["jurisdiction_type"] == jurisdiction_type]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.jurisdiction(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# agencies
# ---------------------------------------------------------------------------
@bp.post("/agencies")
def create_agency():
    v.auth(["SystemAdmin"])
    data = v.body()
    jurisdiction = v.maybe_find("jurisdiction", v.raw_ref(data, "jurisdiction_id"))
    name = v.req_str(data, "name", 1, 120)
    agency_type = v.req_enum(data, "agency_type", AGENCY_TYPES)
    v.req_id(data, "jurisdiction_id")
    contact_phone = v.opt_str(data, "contact_phone", 0, 40)

    row = base_record()
    row.update({
        "name": name,
        "agency_type": agency_type,
        "jurisdiction_id": jurisdiction["id"],
        "contact_phone": contact_phone,
        "status": "ACTIVE",
        "suspended_reason": None,
    })
    db.agencies[row["id"]] = row
    return created(ser.agency(row))


@bp.get("/agencies/<identifier>")
def get_agency(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("agency", identifier)
    return ok(ser.agency(row))


@bp.get("/agencies")
def list_agencies():
    v.auth(v.ALL_ROLES)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    agency_type = v.q_enum("agency_type", AGENCY_TYPES)
    status = v.q_enum("status", AGENCY_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.agencies.values()))
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if agency_type is not None:
        rows = [r for r in rows if r["agency_type"] == agency_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.agency(r) for r in page], limit, offset, total)


@bp.post("/agencies/<identifier>/suspend")
def suspend_agency(identifier):
    v.auth(["SystemAdmin"])
    row = v.find("agency", identifier)
    data = v.body()
    reason = v.req_str(data, "suspended_reason", 1)
    row["status"] = "SUSPENDED"
    row["suspended_reason"] = reason
    touch(row)
    return ok(ser.agency(row))


# ---------------------------------------------------------------------------
# coverage cells
# ---------------------------------------------------------------------------
@bp.post("/coverage-cells")
def create_cell():
    v.auth(["SystemAdmin", "GisAnalyst"])
    data = v.body()
    jurisdiction = v.maybe_find("jurisdiction", v.raw_ref(data, "jurisdiction_id"))
    cell_code = v.req_str(data, "cell_code", 1, 12, r"^[A-Z0-9]{1,12}$")
    v.req_id(data, "jurisdiction_id")
    centroid_lat = v.opt_number(data, "centroid_lat", -90, 90)
    centroid_lon = v.opt_number(data, "centroid_lon", -180, 180)

    for row in db.cells.values():
        if row["jurisdiction_id"] == jurisdiction["id"] and row["cell_code"] == cell_code:
            raise ApiError("ERR_DUPLICATE_CELL_CODE",
                           "Cell code '%s' already exists in this jurisdiction." % cell_code)

    row = base_record()
    row.update({
        "cell_code": cell_code,
        "jurisdiction_id": jurisdiction["id"],
        "centroid_lat": centroid_lat,
        "centroid_lon": centroid_lon,
    })
    db.cells[row["id"]] = row
    return created(ser.cell(row))


@bp.get("/coverage-cells/<identifier>")
def get_cell(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("cell", identifier)
    return ok(ser.cell(row))


@bp.get("/coverage-cells")
def list_cells():
    v.auth(v.ALL_ROLES)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    cell_code = v.q_str("cell_code")
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.cells.values()))
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if cell_code is not None:
        rows = [r for r in rows if r["cell_code"] == cell_code]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.cell(r) for r in page], limit, offset, total)


@bp.get("/coverage-cells/<identifier>/coverage-status")
def cell_coverage_status(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("cell", identifier)
    now = db.now()
    return ok({
        "cell_id": row["id"],
        "evaluated_at": fmt_dt(now),
        "covered_service_types": calc.cell_covered_service_types(row["id"], now),
        "gap_service_types": calc.cell_gap_service_types(row["id"], now),
        "proposed_conflict_service_types": calc.cell_proposed_conflict_service_types(row["id"]),
        "responding_assignment_count": calc.cell_active_assignment_count(row["id"], now),
        "forward_gap_service_types": calc.cell_forward_gap_service_types(row["id"], now),
    })


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    v.auth(["SystemAdmin"])
    data = v.body()
    instant = v.req_dt(data, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_dt(db.clock)})
