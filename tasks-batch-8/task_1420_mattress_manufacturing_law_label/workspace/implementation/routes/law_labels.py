"""LawLabel endpoints (nested under models plus cross-model browse)."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_string, body, check_occ, require
from routes.models import get_model
from services import cascade

bp = Blueprint("law_labels", __name__)

PROP65_WARNING = "PROP 65 WARNING"


def law_label_view(l):
    return {
        "id": l["id"],
        "model_id": l["model_id"],
        "spec_id": l["spec_id"],
        "spec_version": l["spec_version"],
        "state_code": l["state_code"],
        "content_text": l["content_text"],
        "created_by_user_id": l["created_by_user_id"],
        "approved_by_user_id": l["approved_by_user_id"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def get_label(model, label_id):
    label = db.law_labels.get(label_id)
    if label is None or label["model_id"] != model["id"]:
        errors.raise_err(errors.ERR_LABEL_NOT_FOUND, "law label not found")
    return label


def render_content_text(spec, model):
    parts = list(spec["required_phrases"])
    # intersection of spec filling codes with the model BOM's filling codes,
    # in BOM line creation order (created_at ascending)
    spec_codes = set(spec["filling_content_codes"])
    lines = [l for l in db.bom_lines.values() if l["model_id"] == model["id"]]
    lines.sort(key=lambda l: l["_seq"])
    seen = set()
    for line in lines:
        code = line["filling_content_code"]
        if code is not None and code in spec_codes and code not in seen:
            seen.add(code)
            parts.append(code)
    if spec["prop65_warning_required"]:
        parts.append(PROP65_WARNING)
    return "\n".join(parts)


@bp.route("/models/<mid>/law-labels", methods=["POST"])
def generate_label(mid):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    data = body()
    state_code = as_string(require(data, "state_code"), "state_code")
    # tier 5: model must be CERTIFIED or ACTIVE
    if model["status"] not in ("CERTIFIED", "ACTIVE"):
        errors.raise_err(errors.ERR_MODEL_NOT_CERTIFIED, "model must be CERTIFIED or ACTIVE")
    # tier 6: a PUBLISHED spec must exist for the state
    spec = None
    for s in db.specs.values():
        if s["state_code"] == state_code and s["status"] == "PUBLISHED":
            if spec is None or (s["created_at"], s["id"]) > (spec["created_at"], spec["id"]):
                spec = s
    if spec is None:
        errors.raise_err(errors.ERR_SPEC_NOT_PUBLISHED, "no PUBLISHED spec for state")
    # tier 12: OCC on the model
    check_occ(require(data, "expected_model_version"), model["version"])
    label = {
        "id": db.new_id(),
        "model_id": model["id"],
        "spec_id": spec["id"],
        "spec_version": spec["version"],
        "state_code": state_code,
        "content_text": render_content_text(spec, model),
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "GENERATED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.law_labels, label)
    cascade.bump(model)
    return response.success_object(law_label_view(label), 201)


@bp.route("/models/<mid>/law-labels", methods=["GET"])
def list_model_labels(mid):
    middleware.require_roles(middleware.ALL_ROLES)
    model = get_model(mid)
    items = [l for l in db.law_labels.values() if l["model_id"] == model["id"]]
    q = request.args.get("state_code")
    if q is not None:
        items = [l for l in items if l["state_code"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [l for l in items if l["status"] == q]
    items.sort(key=lambda l: l["_seq"])
    return response.success_list([law_label_view(l) for l in items])


@bp.route("/law-labels", methods=["GET"])
def browse_labels():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.law_labels.values())
    q = request.args.get("model_id")
    if q is not None:
        items = [l for l in items if l["model_id"] == q]
    q = request.args.get("spec_id")
    if q is not None:
        items = [l for l in items if l["spec_id"] == q]
    q = request.args.get("state_code")
    if q is not None:
        items = [l for l in items if l["state_code"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [l for l in items if l["status"] == q]
    items.sort(key=lambda l: l["_seq"])
    return response.success_list([law_label_view(l) for l in items])


@bp.route("/law-labels/<labelId>", methods=["GET"])
def get_one_label(labelId):
    middleware.require_roles(middleware.ALL_ROLES)
    label = db.law_labels.get(labelId)
    if label is None:
        errors.raise_err(errors.ERR_LABEL_NOT_FOUND, "law label not found")
    return response.success_object(law_label_view(label))


@bp.route("/models/<mid>/law-labels/<labelId>/approve", methods=["POST"])
def approve_label(mid, labelId):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    label = get_label(model, labelId)
    if label["status"] != "GENERATED":
        errors.raise_err(errors.ERR_LABEL_NOT_GENERATED, "label must be GENERATED")
    if user_id == label["created_by_user_id"]:
        errors.raise_err(errors.ERR_SEGREGATION_OF_DUTIES, "approver must differ from creator")
    label["status"] = "APPROVED"
    label["approved_by_user_id"] = user_id
    cascade.bump(label)
    return response.success_object(law_label_view(label))


@bp.route("/models/<mid>/law-labels/<labelId>/reject", methods=["POST"])
def reject_label(mid, labelId):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    label = get_label(model, labelId)
    if label["status"] != "GENERATED":
        errors.raise_err(errors.ERR_LABEL_NOT_GENERATED, "label must be GENERATED")
    if user_id == label["created_by_user_id"]:
        errors.raise_err(errors.ERR_SEGREGATION_OF_DUTIES, "rejector must differ from creator")
    label["status"] = "REJECTED"
    cascade.bump(label)
    return response.success_object(law_label_view(label))


@bp.route("/models/<mid>/law-labels/<labelId>/activate", methods=["POST"])
def activate_label(mid, labelId):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    label = get_label(model, labelId)
    # tier 5
    if label["status"] != "APPROVED":
        errors.raise_err(errors.ERR_LABEL_NOT_APPROVED, "label must be APPROVED")
    # tier 6: pinned spec still PUBLISHED, then model CERTIFIED|ACTIVE
    spec = db.specs.get(label["spec_id"])
    if spec is None or spec["status"] != "PUBLISHED":
        errors.raise_err(errors.ERR_SPEC_SUPERSEDED, "pinned spec is no longer PUBLISHED")
    if model["status"] not in ("CERTIFIED", "ACTIVE"):
        errors.raise_err(errors.ERR_MODEL_NOT_CERTIFIED, "model must be CERTIFIED or ACTIVE")
    # supersede any other ACTIVE label for the same model + state (voluntary
    # replacement: no orders are held)
    for other in db.law_labels.values():
        if (
            other["id"] != label["id"]
            and other["model_id"] == model["id"]
            and other["state_code"] == label["state_code"]
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "SUPERSEDED"
            cascade.bump(other)
    label["status"] = "ACTIVE"
    cascade.bump(label)
    return response.success_object(law_label_view(label))
