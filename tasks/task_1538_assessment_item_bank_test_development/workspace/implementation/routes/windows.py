"""FieldTestWindow and ItemResponse endpoints; window close drives the stats pipeline (PRD §3.4)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_WINDOW_NOT_SCHEDULED,
    ERR_WINDOW_NOT_OPEN,
    ERR_WINDOW_TIME_INVALID,
    ERR_WINDOW_STILL_RUNNING,
    ERR_ITEM_NOT_FIELD_TESTABLE,
    ERR_BIAS_GATE_NOT_PASSED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one, bool_param
from services.common import touch
from services.stats import (
    compute_item_stats, provisional_scope, final_scope, pass_flag_for, to_float,
)
from util import new_id, now_ts, parse_dt, program_clock_iso
from validate import (
    get_body, req_str, req_int, req_datetime, require_path_resource,
)

bp = Blueprint("windows", __name__)

WINDOW_ROLES = ["ProgramDirector", "Psychometrician", "TestAssembler"]
RESPONSE_READ_ROLES = ["ProgramDirector", "Psychometrician"]


@bp.post("/api/field-test-windows")
def create_window():
    caller = authorized(["ProgramDirector"])
    body = get_body()
    program_id = req_str(body, "program_id")
    window_label = req_str(body, "window_label")
    start_utc = req_datetime(body, "start_utc")
    end_utc = req_datetime(body, "end_utc")
    # Note: entity table nominally bounds target_sample_size to 50..10000, but the
    # pinned difficulty-design pipeline instances create windows with
    # target_sample_size=2; only the integer type is enforced.
    target_sample_size = req_int(body, "target_sample_size", minimum=1)

    program = db["assessment_programs"].get(program_id)
    if program is None:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, f"program_id does not resolve: {program_id}")

    start_dt, end_dt = parse_dt(start_utc), parse_dt(end_utc)
    if not start_dt < end_dt:
        raise_error(ERR_WINDOW_TIME_INVALID, "start_utc must be strictly before end_utc")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "window_label": window_label,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "target_sample_size": target_sample_size,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_seq": next_seq(),
    }
    db["field_test_windows"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/field-test-windows")
def list_windows():
    authorized(WINDOW_ROLES)
    filters = {"program_id": request.args.get("program_id")}
    return list_response("field_test_windows", filters)


@bp.get("/api/field-test-windows/<wid>")
def get_window(wid):
    authorized(WINDOW_ROLES)
    rec = require_path_resource("field_test_windows", wid)
    return get_one(rec)


@bp.post("/api/field-test-windows/<wid>/open")
def open_window(wid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("field_test_windows", wid)
    get_body()
    if rec["status"] != "SCHEDULED":
        raise_error(ERR_WINDOW_NOT_SCHEDULED, "window must be SCHEDULED to open")
    program = db["assessment_programs"].get(rec["program_id"])
    now_dt = program["_clock_dt"]
    if not (rec["_start_dt"] <= now_dt <= rec["_end_dt"]):
        raise_error(ERR_WINDOW_TIME_INVALID, "program clock is outside the window bounds")
    rec["status"] = "OPEN"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/field-test-windows/<wid>/close")
def close_window(wid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("field_test_windows", wid)
    get_body()
    if rec["status"] != "OPEN":
        raise_error(ERR_WINDOW_NOT_OPEN, "window must be OPEN to close")
    program = db["assessment_programs"].get(rec["program_id"])
    if program["_clock_dt"] < rec["_end_dt"]:
        raise_error(ERR_WINDOW_STILL_RUNNING, "program clock has not reached end_utc")

    rec["status"] = "CLOSED"
    touch(rec)

    # Statistics pipeline: every (item, window) pair with at least one response.
    item_ids_in_window = {
        r["item_id"] for r in db["item_responses"].values() if r["window_id"] == wid
    }
    prov_scope = provisional_scope(wid)
    fin_scope = final_scope(rec, wid)
    clock_iso = program_clock_iso(program)

    for item_id in sorted(item_ids_in_window):
        item = db["items"].get(item_id)
        if item is None:
            continue
        changed = False
        prov_responses = [r for r in prov_scope if r["item_id"] == item_id]
        if prov_responses:
            p_prov, pb_prov, n_prov = compute_item_stats(item, rec, prov_scope)
            _write_stat(item, rec, n_prov, p_prov, pb_prov, "PROVISIONAL", None, None)
            item["p_value_provisional"] = to_float(p_prov)
            item["point_biserial_provisional"] = to_float(pb_prov)
            changed = True
            if n_prov >= rec["target_sample_size"]:
                fin_responses = [r for r in fin_scope if r["item_id"] == item_id]
                if fin_responses:
                    p_fin, pb_fin, n_fin = compute_item_stats(item, rec, fin_scope)
                else:
                    from decimal import Decimal
                    p_fin, pb_fin, n_fin = Decimal("0.0000"), Decimal("0.0000"), 0
                flag = pass_flag_for(p_fin, pb_fin)
                _write_stat(item, rec, n_fin, p_fin, pb_fin, "FINAL", clock_iso, flag)
                item["p_value_final"] = to_float(p_fin)
                item["point_biserial_final"] = to_float(pb_fin)
        if item["status"] == "FIELD_TESTING":
            item["status"] = "STATS_REVIEW"
            changed = True
        if changed:
            touch(item)
    return success_object(public(rec))


def _write_stat(item, window, n_responses, p_value, point_biserial, stats_kind, finalized_at, pass_flag):
    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "item_id": item["id"],
        "window_id": window["id"],
        "n_responses": n_responses,
        "p_value": to_float(p_value),
        "point_biserial": to_float(point_biserial),
        "stats_kind": stats_kind,
        "finalized_at": finalized_at,
        "pass_flag": pass_flag,
        "_seq": next_seq(),
    }
    db["item_statistics"][rec["id"]] = rec
    return rec


@bp.post("/api/field-test-windows/<wid>/responses")
def ingest_response(wid):
    caller = authorized(["Psychometrician"])
    window = require_path_resource("field_test_windows", wid)
    body = get_body()
    item_id = req_str(body, "item_id")
    student_anon_id = req_str(body, "student_anon_id")
    response_timestamp = req_datetime(body, "response_timestamp")
    attempt_duration_seconds = req_int(body, "attempt_duration_seconds", minimum=0)
    raw_score = req_int(body, "raw_score", minimum=0)

    item = db["items"].get(item_id)
    if item is None:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, f"item_id does not resolve: {item_id}")
    if raw_score > item["max_score_points"]:
        raise_error(ERR_INVALID_REQUEST, "raw_score exceeds the item's max_score_points")

    if window["status"] != "OPEN":
        raise_error(ERR_WINDOW_NOT_OPEN, "responses may only be ingested into an OPEN window")

    # Bias gate (priority 7): an item still in BIAS_REVIEW cannot be field tested.
    if item["status"] == "BIAS_REVIEW":
        raise_error(ERR_BIAS_GATE_NOT_PASSED, "item has not passed bias/sensitivity review")

    # Referential gate (priority 11): status + no FINAL stat in a different window.
    if item["status"] not in ("FIELD_TEST_ELIGIBLE", "FIELD_TESTING"):
        raise_error(ERR_ITEM_NOT_FIELD_TESTABLE, "item is not FIELD_TEST_ELIGIBLE/FIELD_TESTING")
    for stat in db["item_statistics"].values():
        if (
            stat["item_id"] == item_id
            and stat["stats_kind"] == "FINAL"
            and stat["window_id"] != wid
        ):
            raise_error(ERR_ITEM_NOT_FIELD_TESTABLE, "item already has FINAL statistics in a different window")

    first_in_window = not any(
        r["item_id"] == item_id and r["window_id"] == wid
        for r in db["item_responses"].values()
    )

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "window_id": wid,
        "item_id": item_id,
        "student_anon_id": student_anon_id,
        "response_timestamp": response_timestamp,
        "attempt_duration_seconds": attempt_duration_seconds,
        "raw_score": raw_score,
        "excluded": False,
        "_seq": next_seq(),
    }
    db["item_responses"][rec["id"]] = rec

    if first_in_window:
        if item["status"] == "FIELD_TEST_ELIGIBLE":
            item["status"] = "FIELD_TESTING"
        item["field_test_attempt_count"] += 1
        touch(item)

    return success_object(public(rec), status=201)


@bp.get("/api/item-responses")
def list_responses():
    authorized(RESPONSE_READ_ROLES)
    filters = {
        "window_id": request.args.get("window_id"),
        "item_id": request.args.get("item_id"),
        "excluded": bool_param("excluded"),
    }
    return list_response("item_responses", filters)


@bp.get("/api/item-responses/<rid>")
def get_response(rid):
    authorized(RESPONSE_READ_ROLES)
    rec = require_path_resource("item_responses", rid)
    return get_one(rec)


@bp.post("/api/item-responses/<rid>/exclude")
def exclude_response(rid):
    caller = authorized(["Psychometrician"])
    rec = require_path_resource("item_responses", rid)
    get_body()
    rec["excluded"] = True
    # ItemResponse carries no updated_at / version (PRD §2.4 exception).
    return success_object(public(rec))
