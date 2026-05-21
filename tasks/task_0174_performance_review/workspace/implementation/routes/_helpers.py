"""Shared helpers for route modules."""

from typing import Any, Dict, Optional, Tuple

from flask import g, request

import config
from clock import clock
from db import _format_iso, new_id, parse_iso, store, utcnow_iso
from errors import raise_err


# -----------------------------------------------------------------------------
# JSON body helpers
# -----------------------------------------------------------------------------

def get_body() -> Dict[str, Any]:
    """Parse JSON body. Empty body returns {}. Malformed JSON -> ERR_VALIDATION."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err("ERR_VALIDATION", "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def get_query_int(name: str, default: int, minimum: Optional[int] = None,
                  maximum: Optional[int] = None) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", f"Query parameter '{name}' must be an integer.")
    if minimum is not None and v < minimum:
        raise_err("ERR_VALIDATION", f"Query parameter '{name}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise_err("ERR_VALIDATION", f"Query parameter '{name}' must be <= {maximum}.")
    return v


def pagination_params() -> Tuple[int, int]:
    limit = get_query_int(
        "limit", config.DEFAULT_LIMIT, minimum=config.MIN_LIMIT,
        maximum=config.MAX_LIMIT,
    )
    offset = get_query_int("offset", config.DEFAULT_OFFSET, minimum=0)
    return limit, offset


# -----------------------------------------------------------------------------
# Common-fields mutation helpers
# -----------------------------------------------------------------------------

def new_entity(extra: Dict[str, Any], with_version: bool = True) -> Dict[str, Any]:
    """Initialise a new entity dict with id, created_at, updated_at, version=0."""
    now = utcnow_iso()
    base = {"id": new_id(), "created_at": now, "updated_at": now}
    if with_version:
        base["version"] = 0
    base.update(extra)
    return base


def bump(entity: Dict[str, Any]) -> None:
    """Refresh updated_at and increment version by one."""
    entity["updated_at"] = utcnow_iso()
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1


def check_version(entity: Dict[str, Any], supplied: Any) -> None:
    """OCC equality check (priority 120). Omitted version => skip."""
    if supplied is None:
        return
    try:
        v = int(supplied)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", "Field 'version' must be an integer.")
    if v != int(entity.get("version", 0)):
        raise_err(
            "ERR_VERSION_CONFLICT",
            "Provided version does not match current entity version.",
        )


# -----------------------------------------------------------------------------
# Lookup helpers
# -----------------------------------------------------------------------------

def get_employee_or_404(employee_id: str, err: str = "ERR_NOT_FOUND") -> Dict[str, Any]:
    emp = store.employees.get(employee_id)
    if not emp:
        raise_err(err, f"Employee '{employee_id}' not found.")
    return emp


def get_cycle_or_404(cycle_id: str) -> Dict[str, Any]:
    c = store.cycles.get(cycle_id)
    if not c:
        raise_err("ERR_CYCLE_NOT_FOUND", f"Cycle '{cycle_id}' not found.")
    return c


def get_review_case_or_404(cycle_id: str, review_case_id: str) -> Dict[str, Any]:
    rc = store.review_cases.get(review_case_id)
    if not rc or rc["cycle_id"] != cycle_id:
        raise_err(
            "ERR_REVIEW_CASE_NOT_FOUND",
            f"ReviewCase '{review_case_id}' not found under cycle '{cycle_id}'.",
        )
    return rc


def get_calibration_session_or_404(cycle_id: str, session_id: str) -> Dict[str, Any]:
    cs = store.calibration_sessions.get(session_id)
    if not cs or cs["cycle_id"] != cycle_id:
        raise_err(
            "ERR_CALIBRATION_SESSION_NOT_FOUND",
            f"CalibrationSession '{session_id}' not found under cycle '{cycle_id}'.",
        )
    return cs


def get_goal_or_404(review_case_id: str, goal_id: str) -> Dict[str, Any]:
    g_ = store.goals.get(goal_id)
    if not g_ or g_["review_case_id"] != review_case_id:
        raise_err("ERR_NOT_FOUND", f"Goal '{goal_id}' not found.")
    return g_


def get_feedback_or_404(review_case_id: str, feedback_id: str) -> Dict[str, Any]:
    fr = store.feedback_requests.get(feedback_id)
    if not fr or fr["review_case_id"] != review_case_id:
        raise_err("ERR_NOT_FOUND", f"FeedbackRequest '{feedback_id}' not found.")
    return fr


def get_pip_or_404(cycle_id: str, pip_id: str) -> Dict[str, Any]:
    p = store.pip_cases.get(pip_id)
    if not p or p["cycle_id"] != cycle_id:
        raise_err("ERR_NOT_FOUND", f"PIPCase '{pip_id}' not found.")
    return p


def get_comp_plan_or_404(cycle_id: str, plan_id: str) -> Dict[str, Any]:
    cp = store.comp_plans.get(plan_id)
    if not cp or cp["cycle_id"] != cycle_id:
        raise_err("ERR_NOT_FOUND", f"CompPlan '{plan_id}' not found.")
    return cp


# -----------------------------------------------------------------------------
# Validation primitives
# -----------------------------------------------------------------------------

def require_field(body: Dict[str, Any], name: str) -> Any:
    if name not in body or body[name] is None:
        raise_err("ERR_VALIDATION", f"Required field '{name}' is missing.")
    return body[name]


def require_str(value: Any, name: str, min_len: int = 1, max_len: int = 10**9) -> str:
    if not isinstance(value, str):
        raise_err("ERR_VALIDATION", f"Field '{name}' must be a string.")
    if len(value) < min_len or len(value) > max_len:
        raise_err(
            "ERR_VALIDATION",
            f"Field '{name}' length must be in [{min_len}, {max_len}].",
        )
    return value


def require_int(value: Any, name: str, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err("ERR_VALIDATION", f"Field '{name}' must be an integer.")
    if minimum is not None and value < minimum:
        raise_err("ERR_VALIDATION", f"Field '{name}' must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise_err("ERR_VALIDATION", f"Field '{name}' must be <= {maximum}.")
    return value


def require_enum(value: Any, name: str, allowed: set) -> str:
    if value not in allowed:
        raise_err(
            "ERR_VALIDATION",
            f"Field '{name}' must be one of {sorted(allowed)}.",
        )
    return value


def require_iso(value: Any, name: str) -> str:
    try:
        parse_iso(value)
    except Exception:
        raise_err("ERR_VALIDATION", f"Field '{name}' must be ISO 8601 UTC.")
    return value


# -----------------------------------------------------------------------------
# Bell-curve target shape validation
# -----------------------------------------------------------------------------

def validate_bell_curve_target(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        raise_err(
            "ERR_BELL_CURVE_TARGET_INVALID",
            "bell_curve_target must be an object.",
        )
    expected = set(config.RATING_BUCKETS)
    if set(value.keys()) != expected:
        raise_err(
            "ERR_BELL_CURVE_TARGET_INVALID",
            "bell_curve_target keys must equal the five rating buckets.",
        )
    total = 0
    out = {}
    for k in config.RATING_BUCKETS:
        v = value[k]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_err(
                "ERR_BELL_CURVE_TARGET_INVALID",
                f"bell_curve_target.{k} must be an integer.",
            )
        if v < 0 or v > 100:
            raise_err(
                "ERR_BELL_CURVE_TARGET_INVALID",
                f"bell_curve_target.{k} must be in [0,100].",
            )
        out[k] = v
        total += v
    if total != 100:
        raise_err(
            "ERR_BELL_CURVE_TARGET_INVALID",
            "bell_curve_target values must sum to 100.",
        )
    return out


# -----------------------------------------------------------------------------
# Cycle state gate
# -----------------------------------------------------------------------------

def require_cycle_open(cycle: Dict[str, Any]) -> None:
    if cycle["status"] != "OPEN":
        raise_err(
            "ERR_CYCLE_NOT_OPEN",
            f"Cycle is in status {cycle['status']}, not OPEN.",
        )
