from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_MACHINE_LINE_NOT_FOUND, ERR_MOLD_NOT_FOUND, \
    ERR_BOTTLE_SPEC_NOT_FOUND, ERR_DUPLICATE_CODE
from calc import throughput_preview
from services import stamp_new, ser_machine_line, ser_mold, \
    ser_schedule_slot, sorted_rows
from util import new_id, num_out
from validate import get_body, check_fields, pagination_params, query_filter, \
    query_number

bp = Blueprint("machine_lines", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler", "LogisticsCoordinator"]
SLOT_READ_ROLES = ["PlantAdmin", "ProcessEngineer", "ProductionScheduler"]
SLOT_STATUSES = {"CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}


def get_line_or_404(line_id):
    line = store.machine_lines.get(line_id)
    if line is None:
        raise_err(ERR_MACHINE_LINE_NOT_FOUND, "MachineLine id does not resolve")
    return line


@bp.post("/machine-lines")
def create_line():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {
        "line_code": ("str", True),
        "has_inline_labeler": ("bool", True),
        "max_bottle_diameter_mm": ("number", True),
        "resident_volume_kg": ("number", True),
    })
    for l in store.machine_lines.values():
        if l["line_code"] == body["line_code"]:
            raise_err(ERR_DUPLICATE_CODE, "line_code must be unique")
    line = {
        "line_code": body["line_code"],
        "has_inline_labeler": body["has_inline_labeler"],
        "max_bottle_diameter_mm": body["max_bottle_diameter_mm"],
        "resident_volume_kg": body["resident_volume_kg"],
        "last_color_class": None,
        "status": "IDLE",
    }
    stamp_new(line, new_id())
    store.machine_lines[line["id"]] = line
    return success_object(ser_machine_line(line), 201)


@bp.get("/machine-lines/<lid>")
def get_line(lid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_machine_line(get_line_or_404(lid)))


@bp.get("/machine-lines/<lid>/molds")
def line_molds(lid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
                        "ProductionScheduler"])
    get_line_or_404(lid)
    limit, offset = pagination_params()
    rows = [m for m in store.molds.values()
            if m["installed_line_id"] == lid and m["status"] == "INSTALLED"]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_mold(m) for m in page], limit, offset, len(rows))


@bp.get("/machine-lines/<lid>/schedule-slots")
def line_slots(lid):
    _, role = authenticate()
    require_role(role, SLOT_READ_ROLES)
    get_line_or_404(lid)
    status = query_filter("status", SLOT_STATUSES)
    limit, offset = pagination_params()
    rows = [s for s in store.schedule_slots.values()
            if s["machine_line_id"] == lid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_schedule_slot(s) for s in page], limit, offset,
                        len(rows))


@bp.get("/machine-lines/<lid>/throughput-preview")
def throughput(lid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer", "ProductionScheduler"])
    line = get_line_or_404(lid)
    from flask import request
    mold_id = request.args.get("mold_id")
    bottle_spec_id = request.args.get("bottle_spec_id")
    if mold_id is None:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "missing required query parameter: mold_id")
    if bottle_spec_id is None:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST,
                  "missing required query parameter: bottle_spec_id")
    planned_weight_g = query_number("planned_weight_g", required=True)
    mold = store.molds.get(mold_id)
    if mold is None:
        raise_err(ERR_MOLD_NOT_FOUND, "Mold id does not resolve")
    spec = store.bottle_specs.get(bottle_spec_id)
    if spec is None:
        raise_err(ERR_BOTTLE_SPEC_NOT_FOUND, "BottleSpec id does not resolve")
    opens = sum(1 for b in store.cavity_blockouts.values()
                if b["mold_id"] == mold["id"] and b["status"] == "OPEN")
    result = throughput_preview(
        mold["base_cavities"], opens, mold["reference_weight_g"],
        spec["label_type"] != "NONE", line["has_inline_labeler"],
        planned_weight_g)
    return success_object({
        "effective_cavities": result["effective_cavities"],
        "cycle_time_s": num_out(result["cycle_time_s"]),
        "cycles_per_hour": num_out(result["cycles_per_hour"]),
        "hourly_output": result["hourly_output"],
    })
