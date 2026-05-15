"""Tester routes: create, read (self-only for Tester role), patch, list."""

from flask import Blueprint, g, request

from db import DB, new_id, LOCK
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_FORBIDDEN, raise_error
from middleware import auth_required
from response import success_response, list_response
from services.common import get_json_body, require_fields, check_version, bump_version, parse_pagination, paginate
from services.serializers import serialize_tester
from services.time_util import now_iso, parse_iso
from services.calculations import compute_qualification_posture
from services.state import reconcile_tester_posture, tester_has_category_in_effect

bp = Blueprint("testers", __name__)


def _validate_qualifications(quals):
    if not isinstance(quals, list):
        raise_error(ERR_VALIDATION, "qualifications must be a list")
    valid_categories = {"CONCRETE", "STEEL_REBAR", "SOIL", "ASPHALT", "CEMENT"}
    for q in quals:
        if not isinstance(q, dict):
            raise_error(ERR_VALIDATION, "qualification entries must be objects")
        for k in ("material_category", "valid_from", "valid_to"):
            if k not in q or q[k] is None:
                raise_error(ERR_VALIDATION, f"qualification missing {k}")
        if q["material_category"] not in valid_categories:
            raise_error(ERR_VALIDATION, "qualification.material_category invalid")
        try:
            parse_iso(q["valid_from"])
        except Exception:
            # Allow plain date strings
            from datetime import date
            try:
                date.fromisoformat(q["valid_from"])
            except Exception:
                raise_error(ERR_VALIDATION, "qualification.valid_from invalid")
        try:
            parse_iso(q["valid_to"])
        except Exception:
            from datetime import date
            try:
                date.fromisoformat(q["valid_to"])
            except Exception:
                raise_error(ERR_VALIDATION, "qualification.valid_to invalid")


@bp.post("/testers")
@auth_required(["LabManager"])
def create_tester():
    body = get_json_body()
    require_fields(body, ["full_name", "qualifications"])
    name = body["full_name"]
    if not isinstance(name, str) or not name:
        raise_error(ERR_VALIDATION, "full_name required")
    _validate_qualifications(body["qualifications"])
    max_tasks = body.get("max_concurrent_tasks", 5)
    if not isinstance(max_tasks, int) or max_tasks < 0:
        raise_error(ERR_VALIDATION, "max_concurrent_tasks must be non-negative integer")
    now = now_iso()
    with LOCK:
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "full_name": name,
            "qualifications": body["qualifications"],
            "max_concurrent_tasks": max_tasks,
            "active_task_count": 0,
            "qualification_posture": compute_qualification_posture(body["qualifications"]),
        }
        DB["testers"][row["id"]] = row
    return success_response(serialize_tester(row), 201)


@bp.get("/testers/<tid>")
@auth_required(["LabManager", "LabClerk", "Tester"])
def read_tester(tid):
    row = DB["testers"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Tester not found")
    # Tester role: self-only
    if g.user_role == "Tester" and g.user_id != tid:
        raise_error(ERR_FORBIDDEN, "Tester may only read their own row")
    return success_response(serialize_tester(row), 200)


@bp.patch("/testers/<tid>")
@auth_required(["LabManager"])
def update_tester(tid):
    body = get_json_body()
    row = DB["testers"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Tester not found")
    check_version(body, row)
    with LOCK:
        row = DB["testers"].get(tid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Tester not found")
        check_version(body, row)
        changed = False
        if "qualifications" in body:
            _validate_qualifications(body["qualifications"])
            row["qualifications"] = body["qualifications"]
            changed = True
        if "max_concurrent_tasks" in body:
            mt = body["max_concurrent_tasks"]
            if not isinstance(mt, int) or mt < 0:
                raise_error(ERR_VALIDATION, "max_concurrent_tasks invalid")
            row["max_concurrent_tasks"] = mt
            changed = True
        if changed:
            bump_version(row)
            # Recompute posture on qualifications mutation; at_mutation variant
            # — no cascade.
            reconcile_tester_posture(row, with_cascade=False)
    return success_response(serialize_tester(row), 200)


@bp.get("/testers")
@auth_required(["LabManager"])
def list_testers():
    limit, offset = parse_pagination()
    posture_filter = request.args.get("posture")
    category_filter = request.args.get("material_category")
    rows = list(DB["testers"].values())
    if posture_filter:
        rows = [r for r in rows if r.get("qualification_posture") == posture_filter]
    if category_filter:
        rows = [r for r in rows if tester_has_category_in_effect(r, category_filter)]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_tester(r) for r in page], total, limit, offset)
