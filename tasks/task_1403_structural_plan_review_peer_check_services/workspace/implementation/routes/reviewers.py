"""Reviewer endpoints."""

from datetime import date

from flask import Blueprint

import db
from errors import ApiError, ERR_REVIEWER_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_string, opt_int,
)
from response import success_object
from services.core import refresh_reviewer_count

bp = Blueprint("reviewers", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")
LICENSE_TYPES = ("PE", "SE")


def _valid_iso_date(s):
    if not isinstance(s, str):
        return False
    parts = s.split("-")
    if len(parts) != 3:
        return False
    try:
        date(int(parts[0]), int(parts[1]), int(parts[2]))
        return True
    except ValueError:
        return False


def _get_or_404(rid):
    r = db.reviewers.get(rid)
    if r is None:
        raise ApiError(ERR_REVIEWER_NOT_FOUND, 404, "No reviewer with the given id")
    return r


@bp.post("/plan-review/reviewers")
def create_reviewer():
    require_roles("PlatformAdmin")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"full_name", "licenses", "max_concurrent_assignments"})
    require_fields(body, ["full_name", "licenses"])
    full_name = require_string(body, "full_name")
    licenses = body["licenses"]
    if not isinstance(licenses, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "licenses must be an array")
    cleaned = []
    for lic in licenses:
        if not isinstance(lic, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "each license must be an object")
        for f in ("state_code", "license_type", "license_number", "expires_on"):
            if f not in lic or lic[f] is None:
                raise ApiError(ERR_INVALID_REQUEST, 400, f"license missing field: {f}")
        if lic["license_type"] not in LICENSE_TYPES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "license_type must be PE or SE")
        if not _valid_iso_date(lic["expires_on"]):
            raise ApiError(ERR_INVALID_REQUEST, 400, "expires_on must be YYYY-MM-DD")
        cleaned.append({
            "state_code": lic["state_code"],
            "license_type": lic["license_type"],
            "license_number": lic["license_number"],
            "expires_on": lic["expires_on"],
        })
    max_concurrent = opt_int(body, "max_concurrent_assignments", 3)

    entity = db.stamp_new({
        "full_name": full_name,
        "licenses": cleaned,
        "max_concurrent_assignments": max_concurrent,
        "active_assignment_count": 0,
    })
    db.reviewers[entity["id"]] = entity
    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/reviewers/<rid>")
def get_reviewer(rid):
    require_roles(*READ_ROLES)
    r = _get_or_404(rid)
    refresh_reviewer_count(r)
    return success_object(db.serialize(r))
