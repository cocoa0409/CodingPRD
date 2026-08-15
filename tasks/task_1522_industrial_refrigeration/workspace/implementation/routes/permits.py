"""Hot work permits: strict issuer/performer segregation, the five issue
gates, window-conflict geometry, and validity-window starts (PRD 3.7)."""
from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    paginate,
    pagination,
    path_row,
    req_instant,
    req_string,
)
from serialize import permit_out
from store import db, sorted_rows, touch

bp = Blueprint("permits", __name__)

CREATE_SCHEMA = (
    frozenset(
        ["facility_id", "system_id", "contractor_id", "work_description", "valid_from", "valid_until"]
    ),
    frozenset(
        ["facility_id", "system_id", "contractor_id", "work_description", "valid_from", "valid_until"]
    ),
)
EMPTY_SCHEMA = (frozenset(), frozenset())

STATUS_VALUES = (
    "REQUESTED",
    "ISSUED",
    "IN_PROGRESS",
    "SUSPENDED",
    "CLOSED",
    "VOIDED",
    "EXPIRED",
)


@bp.post("/psm/hot-work-permits")
@endpoint(["ContractorRep"], schema=CREATE_SCHEMA)
def request_permit(ctx):
    # step 0 -- payload values
    work_description = req_string(ctx.body, "work_description")
    valid_from = req_instant(ctx.body, "valid_from")
    valid_until = req_instant(ctx.body, "valid_until")
    # step 2 -- the performer pin: contractor_id must be the requester's own
    if ctx.body.get("contractor_id") != ctx.user_id:
        raise ApiError(
            "ERR_FORBIDDEN",
            "A ContractorRep may only request permits for its own contractor_id.",
        )
    # step 3 -- existence
    facility = body_row(ctx.body, "facilities", "facility_id")
    system = body_row(ctx.body, "systems", "system_id")
    contractor = body_row(ctx.body, "contractors", "contractor_id")
    # step 7 -- window sanity: half-open [valid_from, valid_until)
    if valid_from >= valid_until:
        raise ApiError("ERR_INVALID_WINDOW")
    # step 8 -- window conflict against the live permit book (same system)
    if calc.permit_window_conflicts(system["id"], valid_from, valid_until):
        raise ApiError("ERR_PERMIT_WINDOW_CONFLICT")
    # step 9 -- the system must belong to the named facility
    if system["facility_id"] != facility["id"]:
        raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    row = db.create(
        "hot_work_permits",
        {
            "facility_id": facility["id"],
            "system_id": system["id"],
            "contractor_id": contractor["id"],
            "work_description": work_description,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "REQUESTED",
        },
    )
    return envelope.created(permit_out(row))


@bp.get("/psm/hot-work-permits/<permit_id>")
@endpoint(ALL_ROLES)
def get_permit(ctx, permit_id):
    return envelope.ok(permit_out(path_row("hot_work_permits", permit_id)))


@bp.get("/psm/hot-work-permits")
@endpoint(ALL_ROLES)
def list_permits(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.hot_work_permits.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("system_id", "system_id", None),
            ("contractor_id", "contractor_id", None),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [permit_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/hot-work-permits/<permit_id>/issue")
@endpoint(["MaintenanceLead"], schema=EMPTY_SCHEMA)
def issue_permit(ctx, permit_id):
    permit = path_row("hot_work_permits", permit_id)
    # step 5 -- REQUESTED only
    if permit["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    # step 6 -- the five safety gates, in declared order
    contractor = db.contractors.get(permit["contractor_id"])
    if contractor is None or contractor["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_QUALIFIED")
    system = db.systems.get(permit["system_id"])
    if system is None or system["status"] != "IN_SERVICE":
        raise ApiError("ERR_SYSTEM_OUT_OF_SERVICE")
    if calc.system_has_failed_equipment(permit["system_id"]):
        raise ApiError("ERR_EQUIPMENT_INTEGRITY_FAILED")
    _, _, _, _, band = calc.posture(permit["facility_id"])
    if band == "NONCOMPLIANT":
        raise ApiError("ERR_FACILITY_NONCOMPLIANT")
    # step 8 -- the window conflict re-evaluated against the live permit book
    if calc.permit_window_conflicts(
        permit["system_id"], permit["valid_from"], permit["valid_until"], exclude_id=permit["id"]
    ):
        raise ApiError("ERR_PERMIT_WINDOW_CONFLICT")
    permit["status"] = "ISSUED"
    touch(permit)
    return envelope.ok(permit_out(permit))


@bp.post("/psm/hot-work-permits/<permit_id>/start")
@endpoint(["ContractorRep"], schema=EMPTY_SCHEMA)
def start_permit(ctx, permit_id):
    permit = path_row("hot_work_permits", permit_id)
    # step 2 -- the performer pin
    if ctx.user_id != permit["contractor_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the permit's own ContractorRep may start work.")
    # step 5 -- ISSUED or SUSPENDED (resume) only
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    # step 6 -- contractor still QUALIFIED, no FAILED equipment on the system
    contractor = db.contractors.get(permit["contractor_id"])
    if contractor is None or contractor["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_QUALIFIED")
    if calc.system_has_failed_equipment(permit["system_id"]):
        raise ApiError("ERR_EQUIPMENT_INTEGRITY_FAILED")
    # step 7 -- the clock must sit inside [valid_from, valid_until)
    now = db.now()
    if not (permit["valid_from"] <= now < permit["valid_until"]):
        raise ApiError("ERR_PERMIT_OUTSIDE_WINDOW")
    permit["status"] = "IN_PROGRESS"
    touch(permit)
    return envelope.ok(permit_out(permit))


@bp.post("/psm/hot-work-permits/<permit_id>/close")
@endpoint(["ContractorRep"], schema=EMPTY_SCHEMA)
def close_permit(ctx, permit_id):
    permit = path_row("hot_work_permits", permit_id)
    if ctx.user_id != permit["contractor_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the permit's own ContractorRep may close work.")
    if permit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    permit["status"] = "CLOSED"
    touch(permit)
    return envelope.ok(permit_out(permit))


@bp.post("/psm/hot-work-permits/<permit_id>/void")
@endpoint(["MaintenanceLead"], schema=EMPTY_SCHEMA)
def void_permit(ctx, permit_id):
    permit = path_row("hot_work_permits", permit_id)
    if permit["status"] not in ("REQUESTED", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE")
    permit["status"] = "VOIDED"
    touch(permit)
    return envelope.ok(permit_out(permit))
