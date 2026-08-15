from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_CROSS_NURSE_REFERENCE,
    ERR_DISCIPLINE_EFFECTIVE_FUTURE,
    ERR_INVALID_DISCIPLINE_STATE,
    ERR_INVALID_NURSE_STATE,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_RESOLUTION_PREMATURE,
    ERR_SEGREGATION_OF_DUTIES,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import (
    MIN_ACTIVE_DAYS,
    derive_privilege,
    invalidate_items_for,
    recompute_posture,
)
from util import parse_date_loose

bp = Blueprint("disciplines", __name__)

CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "license_id": ("string", False, None),
    "scope": ("string", True, ["LICENSE", "PRIVILEGE"]),
    "action_type": ("string", True, ["REPRIMAND", "PROBATION", "SUSPENSION", "REVOCATION"]),
    "effective_on": ("date", True, None),
}

ADJUDICATE_SCHEMA = {
    "outcome": ("string", True, ["SUSTAINED", "DISMISSED"]),
}

RESOLVE_SCHEMA = {
    "resolution_note": ("string", True, None),
}


def _action_or_404(action_id):
    return get_or_404("disciplines", action_id, ERR_NOT_FOUND, "Disciplinary action not found")


@bp.route("/credentialing/disciplinary-actions", methods=["POST"])
def create_discipline():
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    scope = body["scope"]
    license_id = body.get("license_id")
    lic = None
    if scope == "LICENSE":
        if license_id is None:
            raise ApiError(ERR_INVALID_REQUEST, "license_id is required when scope is LICENSE", 400)
        lic = get_or_404("licenses", license_id, ERR_LICENSE_NOT_FOUND, "license_id does not reference an existing license")
        if lic["nurse_id"] != nurse["id"]:
            raise ApiError(ERR_CROSS_NURSE_REFERENCE, "license_id belongs to a different nurse", 422)
    else:  # PRIVILEGE
        if license_id is not None:
            raise ApiError(ERR_INVALID_REQUEST, "license_id must be absent when scope is PRIVILEGE", 400)
    if nurse["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_NURSE_STATE, "Disciplinary actions require an ACTIVE nurse", 409)
    if body["effective_on"] > db.current_date():
        raise ApiError(ERR_DISCIPLINE_EFFECTIVE_FUTURE, "effective_on must not lie in the future", 422)
    action = create_entity("disciplines", {
        "nurse_id": nurse["id"],
        "license_id": license_id,
        "scope": scope,
        "action_type": body["action_type"],
        "effective_on": body["effective_on"].isoformat(),
        "status": "REPORTED",
        "reported_by_user_id": user_id,
        "acknowledged_by_user_id": None,
        "adjudicated_by_user_id": None,
        "resolution_note": None,
    })
    return success_object(serialize("disciplines", action), 201)


@bp.route("/credentialing/disciplinary-actions", methods=["GET"])
def list_disciplines():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("disciplines")
    for param in ("nurse_id", "license_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [d for d in rows if d[param] == value]
    total = len(rows)
    return success_list([serialize("disciplines", d) for d in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/disciplinary-actions/<actionId>", methods=["GET"])
def get_discipline(actionId):
    auth_context()
    action = _action_or_404(actionId)
    return success_object(serialize("disciplines", action))


@bp.route("/credentialing/disciplinary-actions/<actionId>/acknowledge", methods=["POST"])
def acknowledge_discipline(actionId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    action = _action_or_404(actionId)
    if action["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_DISCIPLINE_STATE, "Only a REPORTED action can be acknowledged", 409)
    action["status"] = "UNDER_REVIEW"
    action["acknowledged_by_user_id"] = user_id
    touch(action)
    return success_object(serialize("disciplines", action))


@bp.route("/credentialing/disciplinary-actions/<actionId>/adjudicate", methods=["POST"])
def adjudicate_discipline(actionId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    action = _action_or_404(actionId)
    body = validate_body(get_body(allow_empty=False), ADJUDICATE_SCHEMA)
    if action["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_DISCIPLINE_STATE, "Only an UNDER_REVIEW action can be adjudicated", 409)
    if user_id == action["acknowledged_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Adjudicator must differ from the acknowledger", 403)
    action["adjudicated_by_user_id"] = user_id
    outcome = body["outcome"]
    if outcome == "DISMISSED":
        action["status"] = "DISMISSED"
        touch(action)
        return success_object(serialize("disciplines", action))
    # SUSTAINED: encumbrance cascade.
    action["status"] = "ADJUDICATED"
    touch(action)
    nurse = db.STORES["nurses"].get(action["nurse_id"])
    if nurse is None:
        return success_object(serialize("disciplines", action))
    nurse["open_encumbrance_count"] += 1
    if action["scope"] == "LICENSE" and action["action_type"] in ("SUSPENSION", "REVOCATION"):
        lic = db.STORES["licenses"].get(action["license_id"])
        if lic is not None and lic["status"] == "ACTIVE":
            lic["status"] = "ENCUMBERED"
            touch(lic)
            invalidate_items_for(lic["id"])
    # Privilege re-derivation (downgrade on PRIVILEGE scope; LICENSE encumbrance also
    # removes the license from the ACTIVE set used by the derivation). A sustained
    # REPRIMAND is record-only: it changes no license, privilege, or posture (§3.8),
    # so the derivation is skipped for it.
    if action["action_type"] != "REPRIMAND":
        derive_privilege(nurse, reason="DISCIPLINE_CHANGE")
    # Posture recompute — PROBATION/SUSPENSION/REVOCATION land PRACTICE_RESTRICTED.
    recompute_posture(nurse)
    touch(nurse)  # persist open_encumbrance_count mutation
    return success_object(serialize("disciplines", action))


@bp.route("/credentialing/disciplinary-actions/<actionId>/resolve", methods=["POST"])
def resolve_discipline(actionId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    action = _action_or_404(actionId)
    body = validate_body(get_body(allow_empty=False), RESOLVE_SCHEMA)
    if action["status"] != "ADJUDICATED":
        raise ApiError(ERR_INVALID_DISCIPLINE_STATE, "Only an ADJUDICATED action can be resolved", 409)
    today = db.current_date()
    earliest = parse_date_loose(action["effective_on"]) + timedelta(days=MIN_ACTIVE_DAYS[action["action_type"]])
    if today < earliest:
        raise ApiError(ERR_RESOLUTION_PREMATURE, "Minimum active period has not elapsed", 422)
    action["status"] = "RESOLVED"
    action["resolution_note"] = body["resolution_note"]
    touch(action)
    nurse = db.STORES["nurses"].get(action["nurse_id"])
    if nurse is None:
        return success_object(serialize("disciplines", action))
    nurse["open_encumbrance_count"] -= 1
    if action["scope"] == "LICENSE" and action["action_type"] in ("SUSPENSION", "REVOCATION"):
        lic = db.STORES["licenses"].get(action["license_id"])
        if lic is not None and lic["status"] == "ENCUMBERED":
            lic["status"] = "ACTIVE" if parse_date_loose(lic["expires_on"]) >= today else "EXPIRED"
            touch(lic)
    derive_privilege(nurse, reason="DISCIPLINE_CHANGE")
    recompute_posture(nurse)
    touch(nurse)  # persist open_encumbrance_count mutation
    return success_object(serialize("disciplines", action))
