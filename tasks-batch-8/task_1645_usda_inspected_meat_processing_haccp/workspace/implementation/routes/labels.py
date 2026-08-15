"""Label approval endpoints."""

from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_string, req_array, req_int, req_enum
from errors import (raise_error, ERR_NOT_FOUND, ERR_LABEL_INVALID_STATE,
                    ERR_CLAIM_SUBSTANTIATION_MISSING, ERR_INVALID_REQUEST)
from serializers import label_out
from services import touch

bp = Blueprint("labels", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")
CLAIMS = {"ORGANIC", "GRASS_FED", "NO_ANTIBIOTICS_EVER", "NATURAL"}


def _get_label(label_id):
    la = store.label_approvals.get(label_id)
    if not la:
        raise_error(ERR_NOT_FOUND, "Label approval not found")
    return la


@bp.route("/plants/<pid>/label-approvals", methods=["POST"])
def create_label(pid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    product_name = req_string(body, "product_name")
    claims = req_array(body, "claims")
    for c in claims:
        if c not in CLAIMS:
            raise_error(ERR_INVALID_REQUEST, f"Unknown claim: {c}")
    substantiation_doc_refs = req_array(body, "substantiation_doc_refs")
    formulation_version = req_int(body, "formulation_version", ge=1)

    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")

    now = store.now_iso()
    la = {
        "id": new_id(),
        "plant_id": pid,
        "product_name": product_name,
        "claims": claims,
        "substantiation_doc_refs": substantiation_doc_refs,
        "formulation_version": formulation_version,
        "approved_formulation_version": None,
        "status": "DRAFT",
        "rejection_reason": None,
        "approved_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.label_approvals[la["id"]] = la
    return success_object(label_out(la), 201)


@bp.route("/label-approvals/<lid>", methods=["GET"])
def get_label(lid):
    require_roles(*READ_ROLES)
    return success_object(label_out(_get_label(lid)))


@bp.route("/label-approvals", methods=["GET"])
def list_labels():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    status = request.args.get("status")
    product_name = request.args.get("product_name")
    items = sorted(store.label_approvals.values(), key=lambda l: (l["created_at"], l["id"]))
    if plant_id is not None:
        items = [l for l in items if l["plant_id"] == plant_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if product_name is not None:
        items = [l for l in items if l["product_name"] == product_name]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([label_out(l) for l in page], limit, offset, total)


@bp.route("/label-approvals/<lid>/submit", methods=["POST"])
def submit_label(lid):
    user_id, _ = require_roles("QAManager")
    get_body()
    la = _get_label(lid)
    if la["status"] not in ("DRAFT", "REJECTED"):
        raise_error(ERR_LABEL_INVALID_STATE, "Label must be DRAFT or REJECTED to submit")
    if len(la["substantiation_doc_refs"]) < len(la["claims"]):
        raise_error(ERR_CLAIM_SUBSTANTIATION_MISSING,
                    "At least one substantiation doc ref per claim is required")
    if la["status"] == "REJECTED":
        la["rejection_reason"] = None
    la["status"] = "SUBMITTED"
    touch(la)
    return success_object(label_out(la))


@bp.route("/label-approvals/<lid>/approve", methods=["POST"])
def approve_label(lid):
    user_id, _ = require_roles("Inspector")
    get_body()
    la = _get_label(lid)
    if la["status"] != "SUBMITTED":
        raise_error(ERR_LABEL_INVALID_STATE, "Label must be SUBMITTED to approve")
    la["status"] = "APPROVED"
    la["approved_formulation_version"] = la["formulation_version"]
    la["approved_by"] = user_id
    touch(la)
    return success_object(label_out(la))


@bp.route("/label-approvals/<lid>/reject", methods=["POST"])
def reject_label(lid):
    user_id, _ = require_roles("Inspector")
    body = get_body()
    reason = req_string(body, "rejection_reason")
    la = _get_label(lid)
    if la["status"] != "SUBMITTED":
        raise_error(ERR_LABEL_INVALID_STATE, "Label must be SUBMITTED to reject")
    la["status"] = "REJECTED"
    la["rejection_reason"] = reason
    touch(la)
    return success_object(label_out(la))
