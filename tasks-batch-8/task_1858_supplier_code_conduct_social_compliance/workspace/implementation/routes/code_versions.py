"""CodeVersion endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES
from response import success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CODE_VERSION_INVALID_STATE,
)
from services.utils import new_uuid, parse_iso

bp = Blueprint("code_versions", __name__)


def serialize(cv):
    return {
        "id": cv["id"],
        "version_label": cv["version_label"],
        "effective_from": cv["effective_from"],
        "zero_tolerance_categories": cv["zero_tolerance_categories"],
        "status": cv["status"],
        "created_at": cv["created_at"],
        "updated_at": cv["updated_at"],
        "version": cv["version"],
    }


@bp.route("/code-versions", methods=["POST"])
def create_code_version():
    require_roles("SourcingProgramAdmin")
    body = request.get_json(silent=True) or {}
    version_label = body.get("version_label")
    effective_from = body.get("effective_from")
    zt_cats = body.get("zero_tolerance_categories")
    if not isinstance(version_label, str) or not version_label:
        raise_err(ERR_INVALID_REQUEST, "version_label is required")
    if not isinstance(effective_from, str) or not effective_from:
        raise_err(ERR_INVALID_REQUEST, "effective_from is required")
    if not isinstance(zt_cats, list):
        raise_err(ERR_INVALID_REQUEST, "zero_tolerance_categories must be an array")
    cv = {
        "id": new_uuid(),
        "version_label": version_label,
        "effective_from": effective_from,
        "zero_tolerance_categories": list(zt_cats),
        "status": "DRAFT",
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.code_versions[cv["id"]] = cv
    return success_object(serialize(cv), 201)


@bp.route("/code-versions/<cv_id>", methods=["GET"])
def get_code_version(cv_id):
    require_roles(*ALL_BUSINESS_ROLES)
    cv = db.code_versions.get(cv_id)
    if not cv:
        raise_err(ERR_NOT_FOUND, "code version not found")
    return success_object(serialize(cv))


@bp.route("/code-versions/<cv_id>/transition", methods=["POST"])
def transition_code_version(cv_id):
    require_roles("SourcingProgramAdmin")
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if not isinstance(to_status, str) or not to_status:
        raise_err(ERR_INVALID_REQUEST, "to_status is required")
    cv = db.code_versions.get(cv_id)
    if not cv:
        raise_err(ERR_NOT_FOUND, "code version not found")
    if to_status == "PUBLISHED":
        if cv["status"] != "DRAFT":
            raise_err(ERR_CODE_VERSION_INVALID_STATE,
                      f"cannot publish from {cv['status']}")
        cv["status"] = "PUBLISHED"
    elif to_status == "RETIRED":
        if cv["status"] != "PUBLISHED":
            raise_err(ERR_CODE_VERSION_INVALID_STATE,
                      f"cannot retire from {cv['status']}")
        cv["status"] = "RETIRED"
    else:
        raise_err(ERR_INVALID_REQUEST, f"invalid to_status {to_status}")
    cv["updated_at"] = db.get_clock()
    cv["version"] += 1
    return success_object(serialize(cv))
