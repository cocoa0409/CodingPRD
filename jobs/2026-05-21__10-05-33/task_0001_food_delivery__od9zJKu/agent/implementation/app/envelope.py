"""Response envelopes and unique IDs."""
from __future__ import annotations

import random
import string
import uuid

from flask import jsonify

from .clock import iso_now


def new_request_id() -> str:
    rnd = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{rnd}"


def new_uuid() -> str:
    return str(uuid.uuid4())


def _meta(pagination: dict | None = None) -> dict:
    base = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }
    if pagination:
        base.update(pagination)
    return base


def success(data, status: int = 200, response_type: str = "object", pagination: dict | None = None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


class APIError(Exception):
    def __init__(self, error_id: str, message: str, status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


# Convenience constructors per error catalogue
def err_auth_required(msg="Missing or invalid auth headers"): return APIError("ERR_AUTH_REQUIRED", msg, 401)
def err_forbidden(msg="Operation not permitted"): return APIError("ERR_FORBIDDEN", msg, 403)
def err_not_found(msg="Resource not found"): return APIError("ERR_NOT_FOUND", msg, 404)
def err_invalid_state(msg="Resource is not in a valid state for this operation"): return APIError("ERR_INVALID_STATE", msg, 409)
def err_version_conflict(msg="Stale version"): return APIError("ERR_VERSION_CONFLICT", msg, 409)
def err_order_already_assigned(msg="Order already assigned"): return APIError("ERR_ORDER_ALREADY_ASSIGNED", msg, 409)
def err_duplicate_return(msg="A return is already open on this order"): return APIError("ERR_DUPLICATE_RETURN", msg, 409)
def err_restaurant_unavailable(msg="Restaurant unavailable"): return APIError("ERR_RESTAURANT_UNAVAILABLE", msg, 422)
def err_suspend_criteria_not_met(msg="Suspension criteria not met"): return APIError("ERR_SUSPEND_CRITERIA_NOT_MET", msg, 422)
def err_return_window_expired(msg="Return window expired"): return APIError("ERR_RETURN_WINDOW_EXPIRED", msg, 422)
def err_refund_amount_invalid(msg="Refund amount invalid"): return APIError("ERR_REFUND_AMOUNT_INVALID", msg, 422)
def err_order_invalid(msg="Order is invalid"): return APIError("ERR_ORDER_INVALID", msg, 422)
def err_related_return_unresolved(msg="Linked return is not yet resolved"): return APIError("ERR_RELATED_RETURN_UNRESOLVED", msg, 422)
def err_validation(msg="Invalid input"): return APIError("ERR_VALIDATION", msg, 422)
