"""Assistive-technology benches and assessment runs (PRD 3.3, 3.4)."""
from datetime import timedelta

from flask import Blueprint

from db import db, new_row, now_iso, sort_key, stamp, touch
from derive import (
    flip_assessments_citing_run,
    flip_attested_assessments,
    recompute_product,
    refresh_component_evidence,
)
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import environment_out, run_out
from validate import (
    AT_PROFILES,
    DISABILITY_CATEGORIES,
    METHODS,
    OS_PLATFORMS,
    RUN_STATUSES,
    body,
    fk_component,
    fk_environment,
    pagination,
    paginate,
    path_environment,
    path_run,
    q_enum,
    q_str,
    v_datetime,
    v_enum,
    v_enum_array,
    v_int,
    v_str,
)

bp = Blueprint("runs", __name__)


# ------------------------------------------------------------- benches ------
@bp.post("/test-environments")
@endpoint(["AccessibilityLead"])
def create_environment():
    data = body()
    name = v_str(data, "name", required=True, min_len=1, max_len=120)
    at_profile = v_enum(data, "at_profile", AT_PROFILES, required=True)
    at_product_name = v_str(data, "at_product_name", required=True,
                            min_len=1, max_len=120)
    os_platform = v_enum(data, "os_platform", OS_PLATFORMS, required=True)
    buffer_minutes = v_int(data, "reconfiguration_buffer_minutes",
                           min_value=0, max_value=240, default=30)

    for existing in db.environments.values():
        if existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_ENVIRONMENT_NAME",
                           "Test environment name %s is already registered" % name)

    row = new_row({
        "name": name,
        "at_profile": at_profile,
        "at_product_name": at_product_name,
        "os_platform": os_platform,
        "reconfiguration_buffer_minutes": buffer_minutes,
    })
    db.environments[row["id"]] = row
    return obj_response(environment_out(row), 201)


@bp.get("/test-environments/<environment_id>")
@endpoint(ALL_ROLES)
def get_environment(environment_id):
    return obj_response(environment_out(path_environment(environment_id)))


# ---------------------------------------------------------------- runs ------
@bp.post("/assessment-runs")
@endpoint(["AccessibilityTester"])
def create_run():
    data = body()
    component = fk_component(data.get("component_id"))        # step 5
    environment = fk_environment(data.get("environment_id"))  # step 5

    v_str(data, "component_id", required=True, min_len=1)
    v_str(data, "environment_id", required=True, min_len=1)
    method = v_enum(data, "method", METHODS, required=True)
    at_profile = v_enum(data, "at_profile", AT_PROFILES, required=True)
    start_raw, start = v_datetime(data, "scheduled_start", required=True)
    end_raw, end = v_datetime(data, "scheduled_end", required=True)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Request body is invalid: 'scheduled_end' must be strictly "
                       "after 'scheduled_start'")
    exercised = v_int(data, "criteria_exercised", required=True,
                      min_value=1, max_value=500)
    categories = v_enum_array(data, "disability_categories_validated",
                              DISABILITY_CATEGORIES, required=True)

    # step 22: exercised criteria within the component's declared scope
    if exercised > component["applicable_criteria_count"]:
        raise ApiError("ERR_EXERCISED_EXCEEDS_SCOPE",
                       "criteria_exercised %d exceeds the component's applicable "
                       "criteria count %d" % (exercised,
                                              component["applicable_criteria_count"]))

    # step 24: bench occupation
    buffer_delta = timedelta(minutes=environment["reconfiguration_buffer_minutes"])
    for existing in db.runs.values():
        if existing["environment_id"] != environment["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if start < existing["_end_dt"] + buffer_delta and existing["_start_dt"] < end:
            raise ApiError("ERR_ENVIRONMENT_WINDOW_CONFLICT",
                           "Test environment %s is occupied during the requested "
                           "window" % environment["id"])

    # step 33: cross-aggregate consistency
    if at_profile != environment["at_profile"]:
        raise ApiError("ERR_ENVIRONMENT_PROFILE_MISMATCH",
                       "Bench %s provides %s, not %s"
                       % (environment["id"], environment["at_profile"], at_profile))

    row = new_row({
        "component_id": component["id"],
        "environment_id": environment["id"],
        "method": method,
        "at_profile": at_profile,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "criteria_exercised": exercised,
        "disability_categories_validated": categories,
        "status": "SCHEDULED",
        "defects_found": None,
        "void_reason": None,
        "completed_at": None,
    })
    row["_start_dt"] = start
    row["_end_dt"] = end
    db.runs[row["id"]] = row

    # PRD 3.3: the first booking starts the testing dimension
    if (component["assessment_state"] == "PLANNED"
            and component["assessment_scope"] != "EXCLUDED"):
        component["assessment_state"] = "IN_TESTING"
        stamp(component)
    return obj_response(run_out(row), 201)


@bp.get("/assessment-runs/<run_id>")
@endpoint(ALL_ROLES)
def get_run(run_id):
    return obj_response(run_out(path_run(run_id)))


@bp.get("/assessment-runs")
@endpoint(ALL_ROLES)
def list_runs():
    component_id = q_str("component_id")
    environment_id = q_str("environment_id")
    status = q_enum("status", RUN_STATUSES)
    method = q_enum("method", METHODS)
    limit, offset = pagination()
    rows = list(db.runs.values())
    if component_id is not None:
        rows = [r for r in rows if r["component_id"] == component_id]
    if environment_id is not None:
        rows = [r for r in rows if r["environment_id"] == environment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([run_out(r) for r in page], limit, offset, total)


@bp.post("/assessment-runs/<run_id>/complete")
@endpoint(["AccessibilityTester"])
def complete_run(run_id):
    run = path_run(run_id)
    data = body()
    defects = v_int(data, "defects_found", min_value=0, max_value=500)

    # step 8: actionability
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_NOT_ACTIONABLE",
                       "Assessment run %s is %s" % (run["id"], run["status"]))

    run["status"] = "COMPLETED"
    run["completed_at"] = now_iso()
    if defects is not None:
        run["defects_found"] = defects
    touch(run)

    component = db.components[run["component_id"]]
    refresh_component_evidence(component)
    touch(component)

    product = db.products[component["product_id"]]
    recompute_product(product)
    touch(product)
    return obj_response(run_out(run))


@bp.post("/assessment-runs/<run_id>/void")
@endpoint(["AccessibilityTester"])
def void_run(run_id):
    run = path_run(run_id)
    data = body()
    reason = v_str(data, "void_reason", required=True, min_len=1, max_len=2000)

    # step 8: actionability
    if run["status"] == "VOID":
        raise ApiError("ERR_RUN_NOT_ACTIONABLE",
                       "Assessment run %s is already VOID" % run["id"])
    if run["status"] == "COMPLETED":
        for issue in db.issues.values():
            if issue.get("resolution_run_id") == run["id"]:
                raise ApiError("ERR_RUN_NOT_ACTIONABLE",
                               "Assessment run %s is cited as resolution evidence"
                               % run["id"])

    run["status"] = "VOID"
    run["void_reason"] = reason
    touch(run)

    component = db.components[run["component_id"]]
    reverted = refresh_component_evidence(component)
    if reverted:
        flip_attested_assessments(component["id"])
    flip_assessments_citing_run(run["id"])
    touch(component)

    product = db.products[component["product_id"]]
    recompute_product(product)
    touch(product)
    return obj_response(run_out(run))
