"""Measure catalog endpoints."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import base_fields, store
from errors import ApiError
from lookups import get_measure, get_program_year
from respond import respond_list, success
from serialize import measure_out
from validate import get_body, opt_bool, req_int, req_str

bp = Blueprint("measures", __name__)


@bp.post("/measures")
@require_roles("ProgramAdministrator")
def create_measure():
    body = get_body()
    program_year_id = req_str(body, "program_year_id")
    measure_code = req_str(body, "measure_code")
    measure_name = req_str(body, "measure_name")
    base_rate_cents = req_int(body, "base_rate_cents", minimum=0)
    deemed_kwh_per_unit = req_int(body, "deemed_kwh_per_unit", minimum=0)
    requires_post_inspection = opt_bool(body, "requires_post_inspection", False)
    is_active = opt_bool(body, "is_active", True)
    # Body FK resolution.
    get_program_year(program_year_id)
    for existing in store.measures.values():
        if (
            existing["program_year_id"] == program_year_id
            and existing["measure_code"] == measure_code
        ):
            raise ApiError(
                "ERR_DUPLICATE_UNIQUE_FIELD",
                409,
                "measure_code '%s' already exists in program year %s"
                % (measure_code, program_year_id),
            )
    rec = base_fields()
    rec.update(
        {
            "program_year_id": program_year_id,
            "measure_code": measure_code,
            "measure_name": measure_name,
            "base_rate_cents": base_rate_cents,
            "deemed_kwh_per_unit": deemed_kwh_per_unit,
            "requires_post_inspection": requires_post_inspection,
            "is_active": is_active,
        }
    )
    store.measures[rec["id"]] = rec
    return success(measure_out(rec), "object", 201)


@bp.get("/measures")
@require_roles(*ALL_ROLES)
def list_measures():
    program_year_id = request.args.get("program_year_id")
    is_active_raw = request.args.get("is_active")
    rows = list(store.measures.values())
    if program_year_id is not None:
        rows = [r for r in rows if r["program_year_id"] == program_year_id]
    if is_active_raw is not None:
        lowered = is_active_raw.lower()
        if lowered not in ("true", "false"):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "is_active must be 'true' or 'false'"
            )
        wanted = lowered == "true"
        rows = [r for r in rows if r["is_active"] == wanted]
    return respond_list(rows, measure_out)


@bp.get("/measures/<rid>")
@require_roles(*ALL_ROLES)
def get_measure_route(rid):
    return success(measure_out(get_measure(rid)), "object", 200)
