from flask import Blueprint, g, request

import errors
from auth import require
from common import get_body, lookup, paginate, parse_pagination, require_enum, require_string
from envelope import array_response, object_response
from services import logic
from services.logic import serialize_citation
from store import db, touch

bp = Blueprint("citations", __name__)


@bp.route("/citations", methods=["POST"])
@require("Registrar", "SafetyAdministrator")
def create_citation():
    body = get_body()
    deficiency_id = require_string(body, "deficiency_id")
    deficiency = lookup(db.deficiencies, deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    if deficiency["status"] != "OPEN":
        raise errors.ApiError("ERR_DEFICIENCY_NOT_OPEN", 409,
                              "Deficiency is not OPEN.")
    device = db.devices[deficiency["device_id"]]
    citation = logic.issue_citation(deficiency, device)
    return object_response(serialize_citation(citation), 201)


@bp.route("/citations/<citation_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_citation(citation_id):
    c = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    return object_response(serialize_citation(c), 200)


@bp.route("/citations", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "BuildingOwner")
def list_citations():
    limit, offset = parse_pagination()
    deficiency_id = request.args.get("deficiency_id")
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    items = list(db.citations.values())
    if deficiency_id is not None:
        items = [c for c in items if c["deficiency_id"] == deficiency_id]
    if device_id is not None:
        items = [c for c in items if c["device_id"] == device_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_citation(c) for c in page], limit, offset, total)


@bp.route("/citations/<citation_id>/pay", methods=["POST"])
@require("BuildingOwner")
def pay_citation(citation_id):
    c = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    device = db.devices[c["device_id"]]
    if device["owner_id"] != g.user_id:
        raise errors.not_resource_owner()
    if c["status"] != "ISSUED":
        raise errors.ApiError("ERR_CITATION_NOT_PAYABLE", 409,
                              "Citation is not payable.")
    c["status"] = "PAID"
    touch(c)
    return object_response(serialize_citation(c), 200)


@bp.route("/citations/<citation_id>/contest", methods=["POST"])
@require("BuildingOwner")
def contest_citation(citation_id):
    c = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    device = db.devices[c["device_id"]]
    if device["owner_id"] != g.user_id:
        raise errors.not_resource_owner()
    if c["status"] != "ISSUED":
        raise errors.ApiError("ERR_CITATION_NOT_CONTESTABLE", 409,
                              "Citation is not contestable.")
    c["status"] = "CONTESTED"
    c["contest_count"] += 1
    touch(c)
    return object_response(serialize_citation(c), 200)


@bp.route("/citations/<citation_id>/resolve-contest", methods=["POST"])
@require("SafetyAdministrator")
def resolve_contest(citation_id):
    c = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    body = get_body()
    outcome = require_enum(body, "outcome", {"UPHELD", "DISMISSED"})
    if c["status"] != "CONTESTED":
        raise errors.ApiError("ERR_CITATION_NOT_CONTESTED", 409,
                              "Citation is not contested.")
    if outcome == "UPHELD":
        c["status"] = "ISSUED"
        touch(c)
    else:  # DISMISSED
        c["status"] = "DISMISSED"
        touch(c)
        deficiency = db.deficiencies.get(c["deficiency_id"])
        if deficiency is not None and deficiency["status"] == "CITED":
            deficiency["status"] = "WAIVED"
            touch(deficiency)
    return object_response(serialize_citation(c), 200)
