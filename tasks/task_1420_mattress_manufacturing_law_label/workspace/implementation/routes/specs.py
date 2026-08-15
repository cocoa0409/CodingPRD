"""StateLawLabelSpec endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_bool, as_string, as_string_list, body, require
from services import cascade

bp = Blueprint("specs", __name__)


def spec_view(s):
    return {
        "id": s["id"],
        "state_code": s["state_code"],
        "filling_content_codes": s["filling_content_codes"],
        "required_phrases": s["required_phrases"],
        "prop65_warning_required": s["prop65_warning_required"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def get_spec(spec_id):
    s = db.specs.get(spec_id)
    if s is None:
        errors.raise_err(errors.ERR_SPEC_NOT_FOUND, "spec not found")
    return s


@bp.route("/law-label-specs", methods=["POST"])
def create_spec():
    middleware.require_roles(["ComplianceOfficer"])
    data = body()
    state_code = as_string(require(data, "state_code"), "state_code")
    filling = as_string_list(require(data, "filling_content_codes"), "filling_content_codes")
    phrases = as_string_list(require(data, "required_phrases"), "required_phrases")
    prop65 = as_bool(require(data, "prop65_warning_required"), "prop65_warning_required")
    spec = {
        "id": db.new_id(),
        "state_code": state_code,
        "filling_content_codes": list(filling),
        "required_phrases": list(phrases),
        "prop65_warning_required": prop65,
        "status": "DRAFT",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.specs, spec)
    return response.success_object(spec_view(spec), 201)


@bp.route("/law-label-specs", methods=["GET"])
def list_specs():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.specs.values())
    q = request.args.get("state_code")
    if q is not None:
        items = [s for s in items if s["state_code"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [s for s in items if s["status"] == q]
    items.sort(key=lambda s: s["_seq"])
    return response.success_list([spec_view(s) for s in items])


@bp.route("/law-label-specs/<specId>", methods=["GET"])
def get_one_spec(specId):
    middleware.require_roles(middleware.ALL_ROLES)
    s = get_spec(specId)
    return response.success_object(spec_view(s))


@bp.route("/law-label-specs/<sid>/law-labels", methods=["GET"])
def list_spec_labels(sid):
    middleware.require_roles(middleware.ALL_ROLES)
    spec = get_spec(sid)
    from routes.law_labels import law_label_view

    items = [l for l in db.law_labels.values() if l["spec_id"] == spec["id"]]
    items.sort(key=lambda l: l["_seq"])
    return response.success_list([law_label_view(l) for l in items])


@bp.route("/law-label-specs/<sid>/publish", methods=["POST"])
def publish_spec(sid):
    middleware.require_roles(["ComplianceOfficer"])
    spec = get_spec(sid)
    if spec["status"] != "DRAFT":
        errors.raise_err(errors.ERR_SPEC_NOT_DRAFT, "spec must be DRAFT")
    # supersede any other PUBLISHED spec for the same state
    for other in db.specs.values():
        if (
            other["id"] != spec["id"]
            and other["state_code"] == spec["state_code"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            cascade.bump(other)
    spec["status"] = "PUBLISHED"
    cascade.bump(spec)
    return response.success_object(spec_view(spec))
