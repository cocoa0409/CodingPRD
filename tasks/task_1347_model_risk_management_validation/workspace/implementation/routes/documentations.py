"""Model documentation endpoints: submit, list, decide (SoD-guarded)."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import documentation_json
from services import workflow
from utils import new_id
from validate import get_body, pagination_params, v_bool, v_enum, v_str

bp = Blueprint("documentations", __name__)


@bp.post("/mrm/models/<model_id>/documentations")
def create_documentation(model_id):
    body = get_body()
    version_label = v_str(body, "version_label")
    has_dev = v_bool(body, "has_development_evidence")
    has_test = v_bool(body, "has_testing_evidence")
    has_lineage = v_bool(body, "has_data_lineage")
    require_roles("ModelOwner")
    with store.lock:
        model = get_model_or_404(model_id)
        if g.user_id != model["owner_user_id"]:
            raise ApiError(
                "ERR_NOT_MODEL_OWNER", 403, "Only the model owner may submit documentation"
            )
        if model["status"] == "RETIRED":
            raise ApiError(
                "ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED"
            )
        if not (has_dev and has_test and has_lineage):
            raise ApiError(
                "ERR_DOCUMENTATION_INCOMPLETE",
                409,
                "Documentation package must carry all three evidence flags",
            )
        now = store.now()
        doc = {
            "id": new_id(),
            "model_id": model_id,
            "version_label": version_label,
            "has_development_evidence": has_dev,
            "has_testing_evidence": has_test,
            "has_data_lineage": has_lineage,
            "submitted_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.documentations[doc["id"]] = doc
        return success(documentation_json(doc), 201)


@bp.get("/mrm/models/<model_id>/documentations")
def list_documentations(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_model_or_404(model_id)
        items = [
            d
            for d in store.documentations.values()
            if d["model_id"] == model_id
        ]
        items.sort(key=lambda d: (d["created_at"], d["_seq"]))
        if f_status is not None:
            items = [d for d in items if d["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([documentation_json(d) for d in page], limit, offset, total)


@bp.post("/mrm/models/<model_id>/documentations/<doc_id>/decide")
def decide_documentation(model_id, doc_id):
    body = get_body()
    decision = v_enum(body, "decision", ("APPROVE", "REJECT"))
    require_roles("ModelRiskOfficer")
    with store.lock:
        get_model_or_404(model_id)
        doc = store.documentations.get(doc_id)
        if doc is None or doc["model_id"] != model_id:
            raise ApiError(
                "ERR_NOT_FOUND", 404, "Documentation '%s' does not exist" % doc_id
            )
        # State gate
        if doc["status"] != "SUBMITTED":
            raise ApiError(
                "ERR_DOCUMENTATION_NOT_SUBMITTED",
                409,
                "Documentation package is not in SUBMITTED status",
            )
        # Segregation of duties: decider must differ from submitter.
        if g.user_id == doc["submitted_by_user_id"]:
            raise ApiError(
                "ERR_SOD_DOCUMENTATION_APPROVAL",
                403,
                "Documentation decider must differ from the submitter",
            )
        if decision == "APPROVE":
            doc["status"] = "APPROVED"
            # Approve supersedes every OTHER APPROVED package of the same model.
            for other in store.documentations.values():
                if (
                    other["id"] != doc["id"]
                    and other["model_id"] == model_id
                    and other["status"] == "APPROVED"
                ):
                    other["status"] = "SUPERSEDED"
                    workflow.mutate(other)
        else:
            doc["status"] = "REJECTED"
        doc["decided_by_user_id"] = g.user_id
        workflow.mutate(doc)
        return success(documentation_json(doc))
