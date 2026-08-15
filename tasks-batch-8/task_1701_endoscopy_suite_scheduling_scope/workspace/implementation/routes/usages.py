"""ScopeUsage endpoints: traceability reads and the void compensation (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SCOPE_USAGE_NOT_FOUND,
    ERR_SCOPE_USAGE_NOT_VOIDABLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import public, touch
from validate import get_body, req_str, require_path_resource

bp = Blueprint("scope_usages", __name__)


def _bool_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise_error(ERR_INVALID_REQUEST, f"{name} must be true or false")


@bp.get("/endoscopy/scope-usages")
def list_scope_usages():
    return list_response("scope_usages", {
        "booking_id": request.args.get("booking_id"),
        "scope_id": request.args.get("scope_id"),
        "patient_id": request.args.get("patient_id"),
        "status": request.args.get("status"),
        "exposure_flagged": _bool_param("exposure_flagged"),
    })


@bp.get("/endoscopy/scope-usages/<rid>")
def get_scope_usage(rid):
    return get_one("scope_usages", rid, ERR_SCOPE_USAGE_NOT_FOUND)


@bp.post("/endoscopy/scope-usages/<rid>/void")
def void_scope_usage(rid):
    authorized(["Endoscopist"])
    usage = require_path_resource("scope_usages", rid, ERR_SCOPE_USAGE_NOT_FOUND)
    body = get_body()
    reason = req_str(body, "reason")
    # Rung 7 (state): the usage must be ACTIVE and its booking still IN_PROGRESS.
    booking = db["bookings"].get(usage["booking_id"])
    if usage["status"] != "ACTIVE" or booking is None or booking["status"] != "IN_PROGRESS":
        raise_error(ERR_SCOPE_USAGE_NOT_VOIDABLE,
                    "usage must be ACTIVE and its booking IN_PROGRESS to void")
    usage["status"] = "VOID"
    usage["void_reason"] = reason
    touch(usage)
    # Compensation: the IN_USE scope returns to AVAILABLE (use_count is a live
    # ledger over non-VOID usages, so the count self-corrects).
    scope = db["scopes"].get(usage["scope_id"])
    if scope is not None and scope["status"] == "IN_USE":
        scope["status"] = "AVAILABLE"
        touch(scope)
    return success_object(public(usage))
