"""Change-control endpoints: submit (OCC-guarded), list, decide."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import change_request_json
from services import risk, workflow
from utils import add_months, new_id
from validate import get_body, pagination_params, v_enum, v_int, v_str

bp = Blueprint("change_requests", __name__)


@bp.post("/mrm/models/<model_id>/change-requests")
def create_change_request(model_id):
    body = get_body()
    change_type = v_enum(body, "change_type", ("MINOR", "MAJOR"))
    description = v_str(body, "description")
    expected_version = v_int(body, "expected_model_version")
    require_roles("ModelOwner")
    with store.lock:
        model = get_model_or_404(model_id)
        # Version guard: after existence, before ownership and state rules.
        if expected_version != model["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_model_version does not equal the model's current version",
            )
        if g.user_id != model["owner_user_id"]:
            raise ApiError(
                "ERR_NOT_MODEL_OWNER",
                403,
                "Only the model owner may submit change requests",
            )
        if model["status"] == "RETIRED":
            raise ApiError("ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED")
        now = store.now()
        cr = {
            "id": new_id(),
            "model_id": model_id,
            "change_type": change_type,
            "description": description,
            "submitted_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.change_requests[cr["id"]] = cr
        # Each successfully created change request advances the model's version.
        workflow.mutate(model)
        return success(change_request_json(cr), 201)


@bp.get("/mrm/models/<model_id>/change-requests")
def list_change_requests(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_model_or_404(model_id)
        items = [c for c in store.change_requests.values() if c["model_id"] == model_id]
        items.sort(key=lambda c: (c["created_at"], c["_seq"]))
        if f_status is not None:
            items = [c for c in items if c["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([change_request_json(c) for c in page], limit, offset, total)


@bp.post("/mrm/models/<model_id>/change-requests/<cr_id>/decide")
def decide_change_request(model_id, cr_id):
    body = get_body()
    decision = v_enum(body, "decision", ("APPROVE", "REJECT"))
    require_roles("ModelRiskOfficer")
    with store.lock:
        get_model_or_404(model_id)
        cr = store.change_requests.get(cr_id)
        if cr is None or cr["model_id"] != model_id:
            raise ApiError(
                "ERR_NOT_FOUND", 404, "Change request '%s' does not exist" % cr_id
            )
        if cr["status"] != "SUBMITTED":
            raise ApiError(
                "ERR_CHANGE_REQUEST_ALREADY_DECIDED",
                409,
                "Change request has already been decided",
            )
        model = store.models[model_id]
        if decision == "APPROVE":
            cr["status"] = "APPROVED"
            if cr["change_type"] == "MAJOR":
                # Compress revalidation: earlier of current value and now + 3 months.
                compressed = add_months(
                    store.now(), risk.MAJOR_CHANGE_REVALIDATION_MONTHS
                )
                if compressed < model["validation_due_at"]:
                    model["validation_due_at"] = compressed
        else:
            cr["status"] = "REJECTED"
        cr["decided_by_user_id"] = g.user_id
        workflow.mutate(cr)
        # The decision itself also advances the model's version.
        workflow.mutate(model)
        return success(change_request_json(cr))
