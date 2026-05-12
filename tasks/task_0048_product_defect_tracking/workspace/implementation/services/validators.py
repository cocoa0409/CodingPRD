"""Reusable validation helpers."""

from __future__ import annotations

from flask import request

import db
from config import VALID_ROLES
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PROJECT_NOT_FOUND,
    ERR_MODULE_NOT_FOUND,
    ERR_TEAM_MEMBER_NOT_FOUND,
    ERR_DEFECT_NOT_FOUND,
    ERR_OVERRIDE_NOT_FOUND,
    ERR_REGRESSION_NOT_FOUND,
    ERR_FIX_RECORD_NOT_FOUND,
    ERR_PROJECT_ARCHIVED,
    ERR_STALE_DATA,
)


def get_json():
    """Return parsed JSON body, or raise ERR_INVALID_REQUEST."""
    if request.method == "GET":
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise AppError(ERR_INVALID_REQUEST, "Body is not valid JSON", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AppError(ERR_INVALID_REQUEST, "Body must be a JSON object", 400)
    return body


def require_fields(body: dict, required: list[str]):
    for field in required:
        if field not in body or body[field] is None:
            raise AppError(ERR_INVALID_REQUEST, f"Missing field: {field}", 400)


def require_str(body, name, *, non_empty=True):
    v = body.get(name)
    if v is None:
        raise AppError(ERR_INVALID_REQUEST, f"Missing field: {name}", 400)
    if not isinstance(v, str):
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be string", 400)
    if non_empty and v == "":
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be non-empty", 400)
    return v


def require_int(body, name, *, allow_zero=True):
    v = body.get(name)
    if v is None:
        raise AppError(ERR_INVALID_REQUEST, f"Missing field: {name}", 400)
    if isinstance(v, bool) or not isinstance(v, int):
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be integer", 400)
    if not allow_zero and v == 0:
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be non-zero", 400)
    return v


def require_number(body, name):
    v = body.get(name)
    if v is None:
        raise AppError(ERR_INVALID_REQUEST, f"Missing field: {name}", 400)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be number", 400)
    return v


def require_enum(body, name, valid_values: set):
    v = require_str(body, name)
    if v not in valid_values:
        raise AppError(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(valid_values)}", 400)
    return v


def find_project_or_404(project_id: str):
    p = db.find_by_id("projects", project_id)
    if not p:
        raise AppError(ERR_PROJECT_NOT_FOUND, f"Project {project_id} not found", 404)
    return p


def find_module_or_404(module_id: str):
    m = db.find_by_id("modules", module_id)
    if not m:
        raise AppError(ERR_MODULE_NOT_FOUND, f"Module {module_id} not found", 404)
    return m


def find_team_member_or_404(tm_id: str):
    tm = db.find_by_id("team_members", tm_id)
    if not tm:
        raise AppError(ERR_TEAM_MEMBER_NOT_FOUND, f"TeamMember {tm_id} not found", 404)
    return tm


def find_defect_or_404(defect_id: str):
    d = db.find_by_id("defects", defect_id)
    if not d:
        raise AppError(ERR_DEFECT_NOT_FOUND, f"Defect {defect_id} not found", 404)
    return d


def find_override_or_404(override_id: str):
    o = db.find_by_id("severity_overrides", override_id)
    if not o:
        raise AppError(ERR_OVERRIDE_NOT_FOUND, f"Override {override_id} not found", 404)
    return o


def find_regression_or_404(rr_id: str):
    r = db.find_by_id("regression_runs", rr_id)
    if not r:
        raise AppError(ERR_REGRESSION_NOT_FOUND, f"RegressionRun {rr_id} not found", 404)
    return r


def find_fix_record_or_404(fr_id: str):
    fr = db.find_by_id("fix_records", fr_id)
    if not fr:
        raise AppError(ERR_FIX_RECORD_NOT_FOUND, f"FixRecord {fr_id} not found", 404)
    return fr


def ensure_project_active(project):
    if project.get("status") == "ARCHIVED":
        raise AppError(ERR_PROJECT_ARCHIVED, f"Project {project['id']} is archived", 409)


def check_version(body: dict, row: dict):
    """Optimistic concurrency check (skipped when body omits version)."""
    if "version" not in body or body.get("version") is None:
        return
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise AppError(ERR_INVALID_REQUEST, "version must be integer", 400)
    if v != row.get("version"):
        raise AppError(ERR_STALE_DATA, "version mismatch", 409)
