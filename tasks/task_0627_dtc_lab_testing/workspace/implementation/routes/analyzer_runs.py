"""Analyzer runs with buffer-extended overlap (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str,
    require_int, paginate,
)

bp = Blueprint("analyzer_runs", __name__)


@bp.route("/catalog/analyzer-runs", methods=["POST"])
def create_run():
    require_role(["LabTech"])
    body = get_json()
    analyzer_code = require_str(body, "analyzer_code")
    run_start = require_str(body, "run_start")
    run_end = require_str(body, "run_end")
    buffer_minutes = require_int(body, "buffer_minutes", required=False, non_negative=True)
    if buffer_minutes is None:
        buffer_minutes = 30

    try:
        start_dt = clock.parse_iso(run_start)
        end_dt = clock.parse_iso(run_end)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "run_start/run_end must be ISO 8601")

    # run_end strictly after run_start.
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_REQUEST", "run_end must be after run_start")

    # Buffer-extended overlap vs RESERVED runs on the same analyzer_code.
    for ar in db.all_rows("analyzer_runs"):
        if ar["analyzer_code"] != analyzer_code or ar["status"] != "RESERVED":
            continue
        p_start = clock.parse_iso(ar["run_start"])
        p_end = clock.parse_iso(ar["run_end"])
        p_buf = ar.get("buffer_minutes", 30)
        # Non-overlap holds only when:
        #   new.run_start >= prior.run_end + prior.buffer  OR
        #   prior.run_start >= new.run_end + new.buffer
        no_overlap = (
            start_dt >= p_end + timedelta(minutes=p_buf)
            or p_start >= end_dt + timedelta(minutes=buffer_minutes)
        )
        if not no_overlap:
            raise err("ERR_ANALYZER_RUN_OVERLAP", "Analyzer run overlaps a reserved run")

    rec = db.new_record({
        "analyzer_code": analyzer_code,
        "run_start": run_start,
        "run_end": run_end,
        "buffer_minutes": buffer_minutes,
        "status": "RESERVED",
    })
    db.insert("analyzer_runs", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/analyzer-runs", methods=["GET"])
def list_runs():
    require_role(["LabTech", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("analyzer_runs"))
    analyzer_code = request.args.get("analyzer_code")
    if analyzer_code:
        rows = [r for r in rows if r["analyzer_code"] == analyzer_code]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/analyzer-runs/<rid>/release", methods=["POST"])
def release_run(rid):
    require_role(["LabTech"])
    rec = require_found("analyzer_runs", rid)
    if rec["status"] != "RESERVED":
        raise err("ERR_ANALYZER_RUN_NOT_RELEASABLE", "Analyzer run not RESERVED")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return success(serialize(rec))
