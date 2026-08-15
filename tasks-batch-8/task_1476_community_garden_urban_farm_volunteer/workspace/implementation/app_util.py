"""Shared helpers for route modules (kept out of app.py to avoid circular imports)."""
from flask import request

from errors import err_invalid_request


def body() -> dict:
    """Parse the request JSON body; missing/malformed body is a shape error."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("request body must be a JSON object")
    return data
