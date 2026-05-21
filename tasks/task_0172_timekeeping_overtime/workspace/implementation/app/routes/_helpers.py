"""Shared route helpers — JSON parsing, ownership checks, OCC."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import request

from ..errors import (
    err_forbidden,
    err_invalid_input,
    err_version_conflict,
)


def parse_json_body() -> Dict[str, Any]:
    """Parse the request body as JSON; default to {} for empty bodies."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_input("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_input("Request body must be a JSON object.")
    return data


def enforce_employee_self_access(role: str, user_id: str, target_employee_id: str) -> None:
    """If role is Employee, X-User-ID must equal the target employee id."""
    if role == "Employee" and user_id != target_employee_id:
        raise err_forbidden(
            "Employee role may only access resources belonging to themselves."
        )


def check_occ_version(payload: Dict[str, Any], current: Dict[str, Any]) -> None:
    """If `version` is present in the payload, it must match current['version']."""
    if "version" in payload and payload["version"] is not None:
        v = payload["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err_invalid_input("version must be an integer.")
        if int(v) != int(current.get("version", 0)):
            raise err_version_conflict(
                f"Supplied version {v} does not match current {current.get('version')}."
            )
