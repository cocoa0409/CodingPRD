"""EffluentLimit endpoints."""

import uuid
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_OUTFALL_NOT_FOUND,
    ERR_LIMIT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_OUTFALL_INACTIVE,
    ERR_LIMIT_RANGE_OVERLAP,
    ERR_LIMIT_SUPERSEDE_MISMATCH,
    ERR_LIMIT_NOT_ACTIVE,
    ERR_LIMIT_NOT_A_SUCCESSOR,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso, dec, check_enum
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_effluent_limit,
    paginate,
    PARAMETER_CODES,
    LIMIT_TYPES,
    UNITS,
    AVERAGE_METHODS,
    MONITORING_FREQUENCIES,
)

bp = Blueprint("effluent_limits", __name__)


def _ranges_intersect(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; None `to` = open-ended."""
    # a starts before b ends (or b open), and b starts before a ends (or a open)
    a_before_b_end = b_to is None or a_from < b_to
    b_before_a_end = a_to is None or b_from < a_to
    return a_before_b_end and b_before_a_end


@bp.route("/npdes/effluent-limits", methods=["POST"])
def create_limit():
    user_id, role = require_roles(["EnvironmentalManager"])
    body = get_body()
    require_fields(
        body,
        [
            "outfall_id",
            "parameter_code",
            "limit_type",
            "limit_value",
            "unit",
            "monitoring_frequency",
            "effective_from",
            "expected_outfall_version",
        ],
    )
    outfall = db.outfalls.get(body["outfall_id"])
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")

    check_enum(body["parameter_code"], PARAMETER_CODES, "parameter_code")
    check_enum(body["limit_type"], LIMIT_TYPES, "limit_type")
    check_enum(body["unit"], UNITS, "unit")
    check_enum(body["monitoring_frequency"], MONITORING_FREQUENCIES, "monitoring_frequency")
    average_method = body.get("average_method", "ARITHMETIC")
    check_enum(average_method, AVERAGE_METHODS, "average_method")

    limit_value = dec(body["limit_value"])
    if limit_value <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "limit_value must be strictly greater than zero")

    effective_from = parse_iso(body["effective_from"], "effective_from")
    effective_to = None
    if body.get("effective_to") is not None:
        effective_to = parse_iso(body["effective_to"], "effective_to")
        if effective_to <= effective_from:
            raise err(ERR_INVALID_REQUEST, 400, "effective_to must be strictly after effective_from")

    supersedes_limit_id = body.get("supersedes_limit_id")

    # OCC guard
    expected = body.get("expected_outfall_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_INVALID_REQUEST, 400, "expected_outfall_version must be an integer")
    if expected != outfall["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_outfall_version does not match Outfall.version")

    # Outfall must be ACTIVE
    if outfall["status"] != "ACTIVE":
        raise err(ERR_OUTFALL_INACTIVE, 409, "Outfall is not ACTIVE")

    # Range-overlap check (excluding the limit named by supersedes_limit_id)
    for other in db.effluent_limits.values():
        if other["outfall_id"] != outfall["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["parameter_code"] != body["parameter_code"]:
            continue
        if other["limit_type"] != body["limit_type"]:
            continue
        if supersedes_limit_id is not None and other["id"] == supersedes_limit_id:
            continue
        if _ranges_intersect(effective_from, effective_to, other["effective_from"], other["effective_to"]):
            raise err(
                ERR_LIMIT_RANGE_OVERLAP,
                409,
                "New limit's effective range overlaps an existing ACTIVE limit",
            )

    # Supersede consistency check
    predecessor = None
    if supersedes_limit_id is not None:
        predecessor = db.effluent_limits.get(supersedes_limit_id)
        if (
            predecessor is None
            or predecessor["status"] != "ACTIVE"
            or predecessor["outfall_id"] != outfall["id"]
            or predecessor["parameter_code"] != body["parameter_code"]
            or predecessor["limit_type"] != body["limit_type"]
        ):
            raise err(
                ERR_LIMIT_SUPERSEDE_MISMATCH,
                400,
                "supersedes_limit_id must reference an ACTIVE limit of the same outfall, parameter_code and limit_type",
            )

    limit = base_entity("EffluentLimit")
    limit["id"] = str(uuid.uuid4())
    limit.update(
        {
            "outfall_id": outfall["id"],
            "parameter_code": body["parameter_code"],
            "limit_type": body["limit_type"],
            "limit_value": limit_value,
            "unit": body["unit"],
            "average_method": average_method,
            "monitoring_frequency": body["monitoring_frequency"],
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
            "supersedes_limit_id": supersedes_limit_id,
        }
    )
    db.effluent_limits[limit["id"]] = limit

    # Atomic supersession of predecessor
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        touch(predecessor)
        append_audit("EffluentLimit", predecessor["id"], "LIMIT_SUPERSEDED", user_id, role)

    # Every successful creation bumps Outfall.version
    touch(outfall)
    append_audit("EffluentLimit", limit["id"], "LIMIT_CREATED", user_id, role)
    return success(serialize_effluent_limit(limit), 201)


@bp.route("/npdes/effluent-limits", methods=["GET"])
def list_limits():
    require_roles(["Any"])
    items = list(db.effluent_limits.values())
    outfall_id = request.args.get("outfall_id")
    if outfall_id:
        items = [l for l in items if l["outfall_id"] == outfall_id]
    supersedes = request.args.get("supersedes_limit_id")
    if supersedes:
        items = [l for l in items if l.get("supersedes_limit_id") == supersedes]
    status = request.args.get("status")
    if status:
        items = [l for l in items if l["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_effluent_limit(l) for l in page], total, limit, offset)


@bp.route("/npdes/effluent-limits/<lid>", methods=["GET"])
def get_limit(lid):
    require_roles(["Any"])
    limit = db.effluent_limits.get(lid)
    if limit is None:
        raise err(ERR_LIMIT_NOT_FOUND, 404, "EffluentLimit not found")
    return success(serialize_effluent_limit(limit), 200)


@bp.route("/npdes/effluent-limits/<lid>/rescind", methods=["POST"])
def rescind_limit(lid):
    user_id, role = require_roles(["EnvironmentalManager"])
    limit = db.effluent_limits.get(lid)
    if limit is None:
        raise err(ERR_LIMIT_NOT_FOUND, 404, "EffluentLimit not found")
    if limit["status"] != "ACTIVE":
        raise err(ERR_LIMIT_NOT_ACTIVE, 409, "Limit is not ACTIVE")
    if limit.get("supersedes_limit_id") is None:
        raise err(ERR_LIMIT_NOT_A_SUCCESSOR, 409, "Limit was not created as a successor")

    predecessor = db.effluent_limits.get(limit["supersedes_limit_id"])
    limit["status"] = "RESCINDED"
    touch(limit)
    append_audit("EffluentLimit", limit["id"], "LIMIT_RESCINDED", user_id, role)
    if predecessor is not None and predecessor["status"] == "SUPERSEDED":
        predecessor["status"] = "ACTIVE"
        touch(predecessor)
        append_audit("EffluentLimit", predecessor["id"], "LIMIT_RESTORED", user_id, role)

    outfall = db.outfalls.get(limit["outfall_id"])
    if outfall is not None:
        touch(outfall)
    return success(serialize_effluent_limit(limit), 200)
