"""Emergency service boundaries and their coverage cell claims."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, sorted_rows, touch

bp = Blueprint("boundaries", __name__)

SERVICE_TYPES = ["LAW", "FIRE", "EMS"]
BOUNDARY_STATUSES = ["DRAFT", "PROPOSED", "ACTIVE", "RETIRED"]
ASSIGNMENT_STATUSES = ["PENDING", "ACTIVE", "RETIRED"]


def _own_boundary(boundary, user_id):
    if boundary["agency_id"] != user_id:
        raise ApiError("ERR_AGENCY_IDENTITY_MISMATCH",
                       "This boundary belongs to another agency.")


def _window_invalid(why):
    raise ApiError("ERR_BOUNDARY_WINDOW_INVALID", why)


@bp.post("/emergency-service-boundaries")
def create_boundary():
    user_id, _role = v.auth(["AgencyLiaison"])
    data = v.body()
    named = data.get("agency_id") if isinstance(data, dict) else None
    if isinstance(named, str) and named != user_id:
        raise ApiError("ERR_AGENCY_IDENTITY_MISMATCH",
                       "A liaison may not create a boundary for another agency.")
    agency = v.maybe_find("agency", v.raw_ref(data, "agency_id"))
    v.req_id(data, "agency_id")
    effective_start = v.req_dt(data, "effective_start")
    effective_end = v.opt_dt(data, "effective_end")
    if effective_end is not None and effective_end <= effective_start:
        _window_invalid("effective_end must be strictly after effective_start.")

    row = base_record()
    row.update({
        "agency_id": agency["id"],
        "service_type": agency["agency_type"],
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "DRAFT",
        "retired_at": None,
        "retire_reason": None,
    })
    db.boundaries[row["id"]] = row
    return created(ser.boundary(row))


@bp.get("/emergency-service-boundaries/<identifier>")
def get_boundary(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("boundary", identifier)
    return ok(ser.boundary(row))


@bp.get("/emergency-service-boundaries")
def list_boundaries():
    v.auth(v.ALL_ROLES)
    agency_id = v.q_str("agency_id")
    if agency_id is not None:
        v.find("agency", agency_id)
    service_type = v.q_enum("service_type", SERVICE_TYPES)
    status = v.q_enum("status", BOUNDARY_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.boundaries.values()))
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if service_type is not None:
        rows = [r for r in rows if r["service_type"] == service_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.boundary(r) for r in page], limit, offset, total)


@bp.post("/emergency-service-boundaries/<identifier>/cell-assignments")
def create_cell_assignment(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    boundary = v.find("boundary", identifier)
    _own_boundary(boundary, user_id)
    data = v.body()
    cell = v.maybe_find("cell", v.raw_ref(data, "cell_id"))
    v.req_id(data, "cell_id")
    effective_start = v.req_dt(data, "effective_start")
    expected = v.req_int(data, "expected_boundary_version")
    effective_end = v.opt_dt(data, "effective_end")

    if boundary["status"] != "DRAFT":
        raise ApiError("ERR_BOUNDARY_INVALID_STATE",
                       "Cells may only be claimed while the boundary is DRAFT; this one is %s."
                       % boundary["status"])
    if expected != boundary["version"]:
        raise ApiError("ERR_STALE_BOUNDARY_VERSION",
                       "expected_boundary_version %d does not match the stored version %d."
                       % (expected, boundary["version"]))

    if effective_end is not None and effective_end <= effective_start:
        _window_invalid("effective_end must be strictly after effective_start.")
    if not calc.window_contained(effective_start, effective_end,
                                 boundary["effective_start"], boundary["effective_end"]):
        _window_invalid("The claim window must lie wholly inside the boundary's own window.")
    agency = db.agencies.get(boundary["agency_id"])
    if agency is None or cell["jurisdiction_id"] != agency["jurisdiction_id"]:
        _window_invalid("The claimed cell lies outside the boundary agency's jurisdiction.")

    row = base_record()
    row.update({
        "boundary_id": boundary["id"],
        "cell_id": cell["id"],
        "service_type": boundary["service_type"],
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "PENDING",
    })
    db.assignments[row["id"]] = row
    touch(boundary)
    cascade.pin_staleness_for_boundary(boundary)
    return created(ser.assignment(row))


@bp.get("/emergency-service-boundaries/<identifier>/cell-assignments")
def list_boundary_cell_assignments(identifier):
    v.auth(v.ALL_ROLES)
    boundary = v.find("boundary", identifier)
    status = v.q_enum("status", ASSIGNMENT_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows([r for r in db.assignments.values()
                        if r["boundary_id"] == boundary["id"]])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.assignment(r) for r in page], limit, offset, total)


@bp.post("/emergency-service-boundaries/<identifier>/propose")
def propose_boundary(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    boundary = v.find("boundary", identifier)
    _own_boundary(boundary, user_id)
    if boundary["status"] != "DRAFT":
        raise ApiError("ERR_BOUNDARY_INVALID_STATE",
                       "Only a DRAFT boundary may be proposed; this one is %s."
                       % boundary["status"])
    if calc.assigned_cell_count(boundary["id"]) < 1:
        raise ApiError("ERR_BOUNDARY_INVALID_STATE",
                       "A boundary must hold at least one cell claim before it is proposed.")
    boundary["status"] = "PROPOSED"
    touch(boundary)
    cascade.pin_staleness_for_boundary(boundary)
    return ok(ser.boundary(boundary))


@bp.post("/emergency-service-boundaries/<identifier>/activate")
def activate_boundary(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    boundary = v.find("boundary", identifier)
    _own_boundary(boundary, user_id)
    if boundary["status"] != "PROPOSED":
        raise ApiError("ERR_BOUNDARY_INVALID_STATE",
                       "Only a PROPOSED boundary may be activated; this one is %s."
                       % boundary["status"])
    agency = db.agencies.get(boundary["agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise ApiError("ERR_AGENCY_NOT_ACTIVE",
                       "A suspended agency may not activate emergency service boundaries.")

    own = sorted_rows([r for r in db.assignments.values()
                       if r["boundary_id"] == boundary["id"]])
    for claim in own:
        for other in calc.cell_assignments(claim["cell_id"], claim["service_type"], ("ACTIVE",)):
            if other["boundary_id"] == boundary["id"]:
                continue
            if calc.windows_intersect(claim["effective_start"], claim["effective_end"],
                                      other["effective_start"], other["effective_end"]):
                raise ApiError("ERR_COVERAGE_OVERLAP",
                               "Cell %s already has an ACTIVE %s assignment over an "
                               "intersecting window." % (claim["cell_id"], claim["service_type"]))

    for claim in own:
        if claim["status"] != "PENDING":
            continue
        claim["status"] = "ACTIVE"
        touch(claim)
    boundary["status"] = "ACTIVE"
    touch(boundary)
    cascade.pin_staleness_for_boundary(boundary)
    return ok(ser.boundary(boundary))


@bp.post("/emergency-service-boundaries/<identifier>/retire")
def retire_boundary(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    boundary = v.find("boundary", identifier)
    _own_boundary(boundary, user_id)
    data = v.body()
    reason = v.req_str(data, "retire_reason", 1)
    if boundary["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError("ERR_BOUNDARY_INVALID_STATE",
                       "A %s boundary cannot be retired." % boundary["status"])

    boundary["retired_at"] = db.now()
    boundary["retire_reason"] = reason
    boundary["status"] = "RETIRED"
    for claim in sorted_rows([r for r in db.assignments.values()
                              if r["boundary_id"] == boundary["id"]]):
        if claim["status"] not in ("PENDING", "ACTIVE"):
            continue
        claim["status"] = "RETIRED"
        touch(claim)
    touch(boundary)
    cascade.pin_staleness_for_boundary(boundary)
    return ok(ser.boundary(boundary))


@bp.get("/boundary-cell-assignments/<identifier>")
def get_cell_assignment(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("assignment", identifier)
    return ok(ser.assignment(row))


@bp.get("/boundary-cell-assignments")
def list_cell_assignments():
    v.auth(v.ALL_ROLES)
    boundary_id = v.q_str("boundary_id")
    if boundary_id is not None:
        v.find("boundary", boundary_id)
    cell_id = v.q_str("cell_id")
    if cell_id is not None:
        v.find("cell", cell_id)
    service_type = v.q_enum("service_type", SERVICE_TYPES)
    status = v.q_enum("status", ASSIGNMENT_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.assignments.values()))
    if boundary_id is not None:
        rows = [r for r in rows if r["boundary_id"] == boundary_id]
    if cell_id is not None:
        rows = [r for r in rows if r["cell_id"] == cell_id]
    if service_type is not None:
        rows = [r for r in rows if r["service_type"] == service_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.assignment(r) for r in page], limit, offset, total)
