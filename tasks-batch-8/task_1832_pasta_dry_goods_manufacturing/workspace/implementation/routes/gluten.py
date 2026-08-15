"""GlutenTest endpoints: polymorphic record (LINE_SWAB | PRODUCT_TEST) and verify."""
from flask import Blueprint

import db
from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services.cascades import run_quality_reject_cascade
from validation import fk_exists, raw_body, require_path_entity, validate_schema

bp = Blueprint("gluten", __name__)

TEST_TYPES = ["LINE_SWAB", "PRODUCT_TEST"]
RESULTS = ["PASS", "FAIL"]


@bp.post("/gluten-tests")
def create_gluten_test():
    uid, role, _ = get_context()
    require_roles(["QATechnician"])
    body = raw_body()
    # Existence (priority 4) of present body FKs in declared input order.
    line = fk_exists(store.production_lines, body, "line_id", "ERR_LINE_NOT_FOUND")
    run = fk_exists(store.production_runs, body, "run_id", "ERR_RUN_NOT_FOUND")
    validate_schema(body, {
        "test_type": ("enum", True, TEST_TYPES),
        "line_id": ("string", False, None),
        "run_id": ("string", False, None),
        "result": ("enum", True, RESULTS),
    })
    # Polymorphic subject, exclusive per test_type (payload shape, priority 5).
    if body["test_type"] == "LINE_SWAB":
        if "line_id" not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "LINE_SWAB requires line_id")
        if "run_id" in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "LINE_SWAB forbids run_id")
    else:
        if "run_id" not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "PRODUCT_TEST requires run_id")
        if "line_id" in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "PRODUCT_TEST forbids line_id")
    test = {
        "id": new_id(),
        "test_type": body["test_type"],
        "line_id": body.get("line_id"),
        "run_id": body.get("run_id"),
        "result": body["result"],
        "recorded_by_user_id": uid,
        "status": "RECORDED",
        "verified_by_user_id": None,
    }
    new_common(test)
    store.gluten_tests[test["id"]] = test
    return created(test)


@bp.get("/gluten-tests")
def list_gluten_tests():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.gluten_tests.values())
    for field in ("line_id", "run_id", "test_type", "status"):
        rows = paginate.filter(rows, field)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/gluten-tests/<test_id>")
def get_gluten_test(test_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.gluten_tests, test_id, "ERR_GLUTEN_TEST_NOT_FOUND"))


@bp.post("/gluten-tests/<test_id>/verify")
def verify_gluten_test(test_id):
    uid, role, _ = get_context()
    require_roles(["QAManager"])
    test = require_path_entity(store.gluten_tests, test_id, "ERR_GLUTEN_TEST_NOT_FOUND")
    if uid == test["recorded_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Verifier must differ from the recording user")
    if test["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Gluten test is already VERIFIED")
    if test["test_type"] == "LINE_SWAB":
        line = store.production_lines[test["line_id"]]
        if (line["cleaning_completed_at"] is None
                or test["created_at"] < line["cleaning_completed_at"]
                or line["gluten_posture"] != "AWAITING_SWAB"):
            raise ApiError("ERR_STALE_SWAB", 409,
                           "Swab predates the last completed cleaning or line is not AWAITING_SWAB")
    test["status"] = "VERIFIED"
    test["verified_by_user_id"] = uid
    touch(test)
    if test["test_type"] == "LINE_SWAB":
        line = store.production_lines[test["line_id"]]
        if test["result"] == "PASS":
            line["gluten_posture"] = "GF_VALIDATED"
        else:
            line["gluten_posture"] = "CLEANING_IN_PROGRESS"  # fail loop
        touch(line)
    else:
        if test["result"] == "FAIL":
            run = store.production_runs[test["run_id"]]
            if run["quality_disposition"] in ("PENDING_QA", "HELD"):
                run["quality_disposition"] = "REJECTED"  # auto-reject
                touch(run)
                run_quality_reject_cascade(run)
    return ok(test)
