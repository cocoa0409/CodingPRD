"""Shared route helpers — body parsing, ownership checks."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import request

from ..errors import err_forbidden, err_validation


def parse_json_body() -> Dict[str, Any]:
    """Parse the request body as JSON; default to {} for empty bodies."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_validation("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object.")
    return data


def enforce_employee_ownership(role: str, user_id: str, employee_id: str) -> None:
    """If role is Employee, X-User-ID must equal the path employee_id."""
    if role == "Employee" and user_id != employee_id:
        raise err_forbidden("Employee role may only access their own resources.")
