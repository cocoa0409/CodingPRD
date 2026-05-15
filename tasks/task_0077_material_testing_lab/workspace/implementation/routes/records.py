"""TestRecord routes: submit, list, modify (with DataModification log)."""

import json
import copy

from flask import Blueprint, g

from db import DB, new_id, LOCK
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_RETEST_LIMIT_EXCEEDED, ERR_DATA_MODIFICATION_REASON_REQUIRED,
    raise_error,
)
from middleware import auth_required
from response import success_response, list_response
from services.common import (
    get_json_body, require_fields, check_version, bump_version,
    parse_pagination, paginate,
)
from services.serializers import serialize_record, serialize_modification
from services.time_util import now_iso
from services.calculations import compute_test_result
from services.state import touch
from services.audit import emit_audit

bp = Blueprint("records", __name__)


@bp.post("/tasks/<tid>/records")
@auth_required(["Tester"])
def submit_record(tid):
    body = get_json_body()
    task = DB["tasks"].get(tid)
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if task.get("assigned_tester_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Only the assigned tester may submit records")
    # State preconditions:
    # - For initial submission: task must be IN_PROGRESS
    # - For retest submission (supersedes_record_id present): task must be
    #   AWAITING_RETEST, retest_count must be < 1
    require_fields(body, ["raw_data"])
    raw_data = body["raw_data"]
    if not isinstance(raw_data, dict):
        raise_error(ERR_VALIDATION, "raw_data must be an object")
    supersedes_id = body.get("supersedes_record_id")
    is_retest = supersedes_id is not None
    if is_retest:
        prev = DB["records"].get(supersedes_id)
        if prev is None:
            raise_error(ERR_NOT_FOUND, "supersedes_record_id not found")
        if prev.get("task_id") != tid:
            raise_error(ERR_NOT_FOUND, "supersedes_record_id does not belong to this task")
        if task.get("retest_count", 0) >= 1:
            raise_error(ERR_RETEST_LIMIT_EXCEEDED, "Task has already been retested")
        if task.get("status") != "AWAITING_RETEST":
            raise_error(ERR_INVALID_STATE, "Task must be AWAITING_RETEST to submit a retest")
    else:
        if task.get("status") != "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE, "Task must be IN_PROGRESS to submit a record")
    sample = DB["samples"].get(task["sample_id"])
    if sample is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    # Compute result
    try:
        result, abnormal = compute_test_result(task["test_method"], raw_data, sample["specification"])
    except (ValueError, Exception) as e:
        raise_error(ERR_VALIDATION, f"Cannot compute test result: {e}")

    with LOCK:
        now = now_iso()
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "task_id": tid,
            "tester_id": g.user_id,
            "raw_data": raw_data,
            "calculated_result": result,
            "abnormal_flag": abnormal,
            "status": "SUBMITTED",  # DRAFT auto-advances to SUBMITTED
            "supersedes_record_id": supersedes_id,
        }
        DB["records"][row["id"]] = row

        if is_retest:
            # Mark the previous record SUPERSEDED
            prev = DB["records"].get(supersedes_id)
            if prev is not None:
                prev["status"] = "SUPERSEDED"
                touch(prev)
            # Task: AWAITING_RETEST -> IN_PROGRESS, retest_count += 1
            task["retest_count"] = task.get("retest_count", 0) + 1
            task["status"] = "IN_PROGRESS"
            touch(task)
        else:
            # Initial submission: if abnormal and retest_count == 0, retest workflow
            if abnormal and task.get("retest_count", 0) == 0:
                task["status"] = "AWAITING_RETEST"
                touch(task)
                if sample.get("status") == "IN_TESTING":
                    sample["status"] = "RETESTING"
                    touch(sample)
            # else: task stays IN_PROGRESS

    return success_response(serialize_record(row), 201)


@bp.get("/tasks/<tid>/records")
@auth_required(["LabManager", "LabClerk", "Tester", "Reviewer", "Signatory"])
def list_task_records(tid):
    task = DB["tasks"].get(tid)
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    limit, offset = parse_pagination()
    rows = [r for r in DB["records"].values() if r.get("task_id") == tid]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_record(r) for r in page], total, limit, offset)


def _diff_dict(prev, new, prefix="raw_data"):
    """Yield (field_path, prev_value, new_value) for top-level keys that changed.
    Uses dot notation; for nested dicts, descends one level (and so on).
    """
    out = []
    keys = set(prev.keys()) | set(new.keys())
    for k in keys:
        pv = prev.get(k, None)
        nv = new.get(k, None)
        path = f"{prefix}.{k}"
        if isinstance(pv, dict) and isinstance(nv, dict):
            out.extend(_diff_dict(pv, nv, prefix=path))
        else:
            if pv != nv:
                out.append((path, pv, nv))
    return out


@bp.patch("/records/<rid>")
@auth_required(["Tester"])
def modify_record(rid):
    body = get_json_body()
    row = DB["records"].get(rid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Record not found")
    # Only the original tester (or per scaffold any Tester role, but PRD says the
    # tester who needs to revise their record). We require tester_id matches.
    if row.get("tester_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Only the authoring tester may modify a record")
    if row.get("status") != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only SUBMITTED records may be modified")
    # Reason precedes version per validation ordering? Per priority table:
    # ERR_DATA_MODIFICATION_REASON_REQUIRED is priority 20, ERR_VERSION_CONFLICT
    # is priority 21 — reason is checked first.
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise_error(ERR_DATA_MODIFICATION_REASON_REQUIRED, "reason required")
    check_version(body, row)
    with LOCK:
        row = DB["records"].get(rid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Record not found")
        check_version(body, row)
        if row.get("status") != "SUBMITTED":
            raise_error(ERR_INVALID_STATE, "Only SUBMITTED records may be modified")
        # Apply raw_data merge (shallow first-level merge — keys in patch
        # override; absent keys preserved).
        new_raw = copy.deepcopy(row["raw_data"])
        if "raw_data" in body:
            patch = body["raw_data"]
            if not isinstance(patch, dict):
                raise_error(ERR_VALIDATION, "raw_data must be an object")
            for k, v in patch.items():
                new_raw[k] = v
        # Compute new result + abnormal
        task = DB["tasks"].get(row["task_id"])
        if task is None:
            raise_error(ERR_NOT_FOUND, "Task not found")
        sample = DB["samples"].get(task["sample_id"])
        if sample is None:
            raise_error(ERR_NOT_FOUND, "Sample not found")
        try:
            new_result, new_abnormal = compute_test_result(
                task["test_method"], new_raw, sample["specification"]
            )
        except Exception as e:
            raise_error(ERR_VALIDATION, f"Cannot recompute test result: {e}")
        # Diff and append DataModification rows
        diffs = _diff_dict(row["raw_data"], new_raw, prefix="raw_data")
        if row.get("calculated_result") != new_result:
            diffs.append(("calculated_result", row.get("calculated_result"), new_result))
        if row.get("abnormal_flag") != new_abnormal:
            diffs.append(("abnormal_flag", row.get("abnormal_flag"), new_abnormal))
        for (path, pv, nv) in diffs:
            mod = {
                "id": new_id(),
                "created_at": now_iso(),
                "record_id": rid,
                "actor_role": g.user_role,
                "actor_id": g.user_id,
                "field_path": path,
                "previous_value": json.dumps(pv),
                "new_value": json.dumps(nv),
                "reason": reason,
            }
            DB["modifications"].append(mod)
        # Apply changes
        row["raw_data"] = new_raw
        row["calculated_result"] = new_result
        row["abnormal_flag"] = new_abnormal
        bump_version(row)
        # Audit event
        emit_audit("DATA_MODIFIED", "TestRecord", rid, g.user_role, g.user_id,
                   {"fields_changed": [p for (p, _, _) in diffs], "reason": reason})
    return success_response(serialize_record(row), 200)


@bp.get("/records/<rid>/modifications")
@auth_required(["LabManager", "Reviewer", "Signatory"])
def list_modifications(rid):
    if rid not in DB["records"]:
        raise_error(ERR_NOT_FOUND, "Record not found")
    limit, offset = parse_pagination()
    rows = [m for m in DB["modifications"] if m.get("record_id") == rid]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_modification(m) for m in page], total, limit, offset)
