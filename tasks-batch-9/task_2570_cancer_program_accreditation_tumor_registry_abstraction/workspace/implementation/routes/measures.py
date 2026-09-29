"""CoC quality measures, stratified performance and improvement projects."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import all_of, clock_date, mark
from errors import ApiError, invalid
from middleware import ANY_ROLE, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("measures", __name__)

EVALUABLE_STATES = ("DRAFT", "MEASURED", "PROJECT_CLOSED_ACHIEVED",
                    "PROJECT_CLOSED_MISSED")


@bp.post(PREFIX + "/quality-measures")
@endpoint(["RegistryManager", "AccreditationCoordinator"])
def create_measure():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    measure_code = validate.f_str(body, "measure_code")
    measurement_year = validate.f_int(body, "measurement_year")
    threshold_pct = validate.f_pct(body, "threshold_pct")

    need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    measure = db.new_entity("measure", {
        "program_id": program_id,
        "measure_code": measure_code,
        "measurement_year": measurement_year,
        "threshold_pct": threshold_pct,
        "strata": [],
        "included_strata_count": 0,
        "performance_rate_pct": None,
        "pooled_rate_pct": None,
        "performance_state": "NOT_EVALUATED",
        "measure_state": "DRAFT",
        "project_title": None,
        "target_rate_pct": None,
        "final_rate_pct": None,
    })
    return ok(measure, 201)


@bp.get(PREFIX + "/quality-measures")
@endpoint(ANY_ROLE)
def list_measures():
    program_id = validate.q_str("program_id")
    measure_code = validate.q_str("measure_code")
    measurement_year = validate.q_int("measurement_year")
    measure_state = validate.q_enum("measure_state", spec.MEASURE_STATES)
    performance_state = validate.q_enum("performance_state",
                                        spec.PERFORMANCE_STATES)
    items = all_of("measure")
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if measure_code is not None:
        items = [m for m in items if m["measure_code"] == measure_code]
    if measurement_year is not None:
        items = [m for m in items if m["measurement_year"] == measurement_year]
    if measure_state is not None:
        items = [m for m in items if m["measure_state"] == measure_state]
    if performance_state is not None:
        items = [m for m in items
                 if m["performance_state"] == performance_state]
    return page(items)


@bp.get(PREFIX + "/quality-measures/<measure_id>")
@endpoint(ANY_ROLE)
def read_measure(measure_id):
    measure = need("measure", measure_id, "ERR_MEASURE_NOT_FOUND")
    return ok(measure)


@bp.post(PREFIX + "/quality-measures/<measure_id>/evaluate")
@endpoint(["RegistryManager", "AccreditationCoordinator"])
def evaluate_measure(measure_id):
    body = validate.body()
    raw = body.get("strata")
    if raw is None:
        raise invalid("Field 'strata' is required.")
    if not isinstance(raw, list):
        raise invalid("Field 'strata' must be an array.")
    strata = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid("Each strata entry must be an object.")
        strata.append({
            "stage_group": validate.f_enum(entry, "stage_group",
                                           spec.STAGE_GROUPS),
            "eligible_case_count": validate.f_int(entry, "eligible_case_count",
                                                  minimum=0),
            "compliant_case_count": validate.f_int(entry,
                                                   "compliant_case_count",
                                                   minimum=0),
        })

    measure = need("measure", measure_id, "ERR_MEASURE_NOT_FOUND")
    if measure["measure_state"] not in EVALUABLE_STATES:
        raise ApiError("ERR_MEASURE_STATE_INVALID")

    _surviving, included, performance, pooled = calcs.measure_rates(strata)
    if included == 0:
        raise ApiError("ERR_MEASURE_STRATA_EMPTY")

    state = calcs.performance_state(performance, measure["threshold_pct"])

    mark(measure)
    measure["strata"] = strata
    measure["included_strata_count"] = included
    measure["performance_rate_pct"] = performance
    measure["pooled_rate_pct"] = pooled
    measure["performance_state"] = state
    measure["measure_state"] = ("PROJECT_REQUIRED"
                                if state == "UNDER_THRESHOLD" else "MEASURED")
    return ok(measure)


@bp.post(PREFIX + "/quality-measures/<measure_id>/improvement-project")
@endpoint(["AccreditationCoordinator"])
def improvement_project(measure_id):
    body = validate.body()
    action = validate.f_enum(body, "action", spec.PROJECT_ACTIONS)
    project_title = validate.f_str(body, "project_title",
                                   required=(action == "OPEN"))
    target_rate_pct = validate.f_pct(body, "target_rate_pct",
                                     required=(action == "OPEN"))
    final_rate_pct = validate.f_pct(body, "final_rate_pct",
                                    required=(action == "CLOSE"))

    measure = need("measure", measure_id, "ERR_MEASURE_NOT_FOUND")

    if action == "OPEN":
        if measure["measure_state"] != "PROJECT_REQUIRED":
            raise ApiError("ERR_PROJECT_NOT_REQUIRED")
        current = measure["performance_rate_pct"]
        if current is not None and target_rate_pct <= current:
            raise invalid("target_rate_pct must exceed the measure's current "
                          "performance_rate_pct.")
        mark(measure)
        measure["project_title"] = project_title
        measure["target_rate_pct"] = target_rate_pct
        measure["measure_state"] = "PROJECT_ACTIVE"
        return ok(measure)

    if measure["measure_state"] != "PROJECT_ACTIVE":
        raise ApiError("ERR_MEASURE_STATE_INVALID")

    mark(measure)
    measure["final_rate_pct"] = final_rate_pct
    measure["performance_state"] = calcs.performance_state(
        final_rate_pct, measure["threshold_pct"])

    if measure["performance_state"] == "UNDER_THRESHOLD":
        measure["measure_state"] = "PROJECT_CLOSED_MISSED"
        program = db.get("program", measure["program_id"])
        if program is not None:
            services.cite_deficiency(program, "STD 7.3", "MAJOR", clock_date(),
                                     source_measure_id=measure["id"])
            services.refresh_program_aggregates(program)
    else:
        measure["measure_state"] = "PROJECT_CLOSED_ACHIEVED"
    return ok(measure)
