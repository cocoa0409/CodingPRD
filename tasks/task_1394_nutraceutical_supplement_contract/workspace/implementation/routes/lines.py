"""Production lines, cleaning validation, and stability chambers (PRD 3.6-3.7)."""
from flask import Blueprint

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_CLEANING_STATE,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from util import (
    body,
    invalid,
    not_found,
    paginate,
    req_enum,
    req_int,
    req_str,
    sorted_by_created,
)

bp = Blueprint("lines", __name__)


# ---------------------------------------------------------------------------
# Production lines
# ---------------------------------------------------------------------------
@bp.post("/api/production-lines")
@require_roles("ProductionPlanner")
def create_production_line(user_id, role):
    data = body()
    name = req_str(data, "name")
    line = new_entity({
        "name": name,
        "cleaning_status": "CLEAN_VALIDATED",
        "current_allergen_class": "NONE",
    })
    store["production_lines"][line["id"]] = line
    return ok(line, 201)


@bp.get("/api/production-lines/<line_id>")
@require_roles(*ANY_ROLE)
def get_production_line(user_id, role, line_id):
    line = store["production_lines"].get(line_id)
    if line is None:
        not_found()
    return ok(line)


@bp.get("/api/production-lines/<line_id>/cleaning-validations")
@require_roles(*ANY_ROLE)
def list_cleaning_validations(user_id, role, line_id):
    line = store["production_lines"].get(line_id)
    if line is None:
        not_found()
    items = sorted_by_created(
        c for c in store["cleaning_validations"].values() if c["production_line_id"] == line_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


# ---------------------------------------------------------------------------
# Cleaning validation cycle (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/api/production-lines/<line_id>/cleaning-validations")
@require_roles("ProductionOperator")
def record_cleaning(user_id, role, line_id):
    line = store["production_lines"].get(line_id)
    if line is None:
        not_found()
    if line["cleaning_status"] != "DIRTY":
        raise_error(ERR_CLEANING_STATE, "Cleaning may only be recorded on a DIRTY line")
    data = body()
    notes = data.get("notes")
    if notes is not None and not isinstance(notes, str):
        invalid("'notes' must be a string when provided")
    validation = new_entity({
        "production_line_id": line_id,
        "notes": notes,
        "recorded_by_id": user_id,
        "swab_result": None,
        "swabbed_by_id": None,
        "approved_by_id": None,
        "status": "RECORDED",
    })
    store["cleaning_validations"][validation["id"]] = validation
    line["cleaning_status"] = "CLEAN_PENDING_VALIDATION"
    touch(line)
    return ok(validation, 201)


@bp.post("/api/cleaning-validations/<validation_id>/swab")
@require_roles("QAChemist")
def record_swab(user_id, role, validation_id):
    validation = store["cleaning_validations"].get(validation_id)
    if validation is None:
        not_found()
    if validation["status"] != "RECORDED":
        raise_error(ERR_CLEANING_STATE, "Swab requires a RECORDED cleaning validation")
    data = body()
    result = req_enum(data, "result", ("PASS", "FAIL"))
    validation["swab_result"] = result
    line = store["production_lines"].get(validation["production_line_id"])
    if result == "PASS":
        validation["status"] = "SWAB_PASSED"
        validation["swabbed_by_id"] = user_id
    else:
        validation["status"] = "FAILED"
        if line is not None:
            line["cleaning_status"] = "DIRTY"
            touch(line)
    touch(validation)
    return ok(validation)


@bp.post("/api/cleaning-validations/<validation_id>/approve")
@require_roles("QAManager")
def approve_cleaning(user_id, role, validation_id):
    validation = store["cleaning_validations"].get(validation_id)
    if validation is None:
        not_found()
    if validation["status"] != "SWAB_PASSED":
        raise_error(ERR_CLEANING_STATE, "Approval requires a SWAB_PASSED cleaning validation")
    if user_id == validation["recorded_by_id"]:
        raise_error(
            ERR_SOD_VIOLATION,
            "The approving manager must differ from the recording operator",
        )
    validation["status"] = "VALIDATED"
    validation["approved_by_id"] = user_id
    touch(validation)
    line = store["production_lines"].get(validation["production_line_id"])
    if line is not None:
        line["cleaning_status"] = "CLEAN_VALIDATED"
        line["current_allergen_class"] = "NONE"
        touch(line)
    return ok(validation)


# ---------------------------------------------------------------------------
# Stability chambers
# ---------------------------------------------------------------------------
@bp.post("/api/stability-chambers")
@require_roles("ProductionPlanner")
def create_chamber(user_id, role):
    data = body()
    name = req_str(data, "name")
    capacity_units = req_int(data, "capacity_units", min_val=1)
    chamber = new_entity({
        "name": name,
        "capacity_units": capacity_units,
        "occupied_units": 0,
    })
    store["stability_chambers"][chamber["id"]] = chamber
    return ok(chamber, 201)


@bp.get("/api/stability-chambers/<chamber_id>")
@require_roles(*ANY_ROLE)
def get_chamber(user_id, role, chamber_id):
    chamber = store["stability_chambers"].get(chamber_id)
    if chamber is None:
        not_found()
    return ok(chamber)


@bp.get("/api/stability-chambers/<chamber_id>/stability-studies")
@require_roles(*ANY_ROLE)
def list_chamber_studies(user_id, role, chamber_id):
    chamber = store["stability_chambers"].get(chamber_id)
    if chamber is None:
        not_found()
    items = sorted_by_created(
        s for s in store["stability_studies"].values() if s["chamber_id"] == chamber_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)
