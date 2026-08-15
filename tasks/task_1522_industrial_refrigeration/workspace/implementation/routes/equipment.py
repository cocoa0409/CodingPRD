"""Equipment registry (PRD 3.3)."""
from flask import Blueprint

import calc
import envelope
from guards import (
    ALL_ROLES,
    apply_filters,
    bad_request,
    body_row,
    endpoint,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_int,
    req_string,
)
from serialize import equipment_out
from store import db, sorted_rows

bp = Blueprint("equipment", __name__)

CREATE_SCHEMA = (
    frozenset(
        ["system_id", "tag_number", "equipment_type", "inspection_interval_days", "inspection_method"]
    ),
    frozenset(
        ["system_id", "tag_number", "equipment_type", "inspection_interval_days", "inspection_method"]
    ),
)

INTEGRITY_VALUES = ("CURRENT", "DUE_SOON", "OVERDUE", "FAILED")


@bp.post("/psm/equipment")
@endpoint(["MaintenanceLead"], schema=CREATE_SCHEMA)
def create_equipment(ctx):
    # step 0 -- payload values (interval must be a strictly positive int)
    tag = req_string(ctx.body, "tag_number")
    eq_type = req_enum(ctx.body, "equipment_type")
    interval = req_int(ctx.body, "inspection_interval_days", minimum=1)
    method = req_enum(ctx.body, "inspection_method")
    # step 3 -- existence
    system = body_row(ctx.body, "systems", "system_id")
    # tag_number is unique per system (entities.Equipment.tag_number)
    for other in db.equipment.values():
        if other["system_id"] == system["id"] and other["tag_number"] == tag:
            bad_request("tag_number must be unique within the system.")
    row = db.create(
        "equipment",
        {
            "system_id": system["id"],
            "tag_number": tag,
            "equipment_type": eq_type,
            "inspection_interval_days": interval,
            "inspection_method": method,
            "last_completed_at": None,
            "last_result": None,
            "next_due_at": None,
        },
    )
    return envelope.created(equipment_out(row))


@bp.get("/psm/equipment/<equipment_id>")
@endpoint(ALL_ROLES)
def get_equipment(ctx, equipment_id):
    return envelope.ok(equipment_out(path_row("equipment", equipment_id)))


@bp.get("/psm/equipment")
@endpoint(ALL_ROLES)
def list_equipment(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.equipment.values())
    rows = apply_filters(rows, ctx, [("system_id", "system_id", None)])
    raw_status = ctx.args.get("integrity_status")
    if raw_status:
        if raw_status not in INTEGRITY_VALUES:
            bad_request("Query parameter 'integrity_status' carries an unknown value.")
        rows = [r for r in rows if calc.integrity_status(r) == raw_status]
    total = len(rows)
    return envelope.listing(
        [equipment_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )
