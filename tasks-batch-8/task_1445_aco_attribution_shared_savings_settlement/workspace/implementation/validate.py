"""Request body schema validation (validation priority 3 -> ERR_INVALID_REQUEST).

Checks: required fields present, types valid, enum members valid,
unknown fields rejected.
"""
import re
from datetime import datetime

from flask import request

from errors import bad_request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_json_body():
    """Return the request JSON object; {} when no body was sent."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise bad_request("Request body must be a valid JSON object")
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def validate_body(body, spec):
    """spec: {field: {"type": ..., "required": bool, "enum": [...],
                      "min": int, "max": int}}

    Types: "string", "int" (bool rejected), "bool", "date" (YYYY-MM-DD),
    "enum". Explicit JSON null is treated as absent.
    """
    for key in body:
        if key not in spec:
            raise bad_request(f"Unknown field in request body: {key}")
    for name, rule in spec.items():
        if name not in body or body[name] is None:
            if rule.get("required"):
                raise bad_request(f"Missing required field: {name}")
            continue
        val = body[name]
        kind = rule["type"]
        if kind == "string":
            if not isinstance(val, str):
                raise bad_request(f"Field {name} must be a string")
        elif kind == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise bad_request(f"Field {name} must be an integer")
            if "min" in rule and val < rule["min"]:
                raise bad_request(f"Field {name} must be >= {rule['min']}")
            if "max" in rule and val > rule["max"]:
                raise bad_request(f"Field {name} must be <= {rule['max']}")
        elif kind == "bool":
            if not isinstance(val, bool):
                raise bad_request(f"Field {name} must be a boolean")
        elif kind == "date":
            if not isinstance(val, str) or not _DATE_RE.match(val):
                raise bad_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                raise bad_request(f"Field {name} is not a valid calendar date")
        elif kind == "enum":
            if not isinstance(val, str) or val not in rule["enum"]:
                raise bad_request(
                    f"Field {name} must be one of {sorted(rule['enum'])}")
        else:  # pragma: no cover
            raise AssertionError(f"unknown spec type {kind}")
    return body
