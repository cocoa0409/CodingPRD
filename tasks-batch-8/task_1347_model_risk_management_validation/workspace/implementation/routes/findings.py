"""Finding endpoints: raise, list, close (retest-gated), reopen."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import finding_json
from services import risk, workflow
from validate import get_body, pagination_params, v_enum

bp = Blueprint("findings", __name__)


def get_finding_or_404(model_id, finding_id):
    f = store.findings.get(finding_id)
    if f is None or f["model_id"] != model_id:
        raise ApiError(
            "ERR_NOT_FOUND", 404, "Finding '%s' does not exist" % finding_id
        )
    return f


@bp.post("/mrm/models/<model_id>/findings")
def create_finding(model_id):
    body = get_body()
    severity = v_enum(body, "severity", ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
    title = body.get("title")
    if not isinstance(title, str):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field 'title' is required and must be a string"
        )
    require_roles("ModelValidator", "ModelRiskOfficer")
    with store.lock:
        model = get_model_or_404(model_id)
        if model["status"] == "RETIRED":
            raise ApiError("ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED")
        finding = workflow.create_finding(model, severity, title, "VALIDATION", g.user_id)
        return success(finding_json(finding), 201)


@bp.get("/mrm/models/<model_id>/findings")
def list_findings(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    f_severity = request.args.get("severity")
    with store.lock:
        get_model_or_404(model_id)
        items = [f for f in store.findings.values() if f["model_id"] == model_id]
        items.sort(key=lambda f: (f["created_at"], f["_seq"]))
        if f_status is not None:
            items = [f for f in items if f["status"] == f_status]
        if f_severity is not None:
            items = [f for f in items if f["severity"] == f_severity]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([finding_json(f) for f in page], limit, offset, total)


@bp.post("/mrm/models/<model_id>/findings/<finding_id>/close")
def close_finding(model_id, finding_id):
    require_roles("ModelRiskOfficer")
    with store.lock:
        get_model_or_404(model_id)
        finding = get_finding_or_404(model_id, finding_id)
        if finding["status"] not in risk.OPEN_FINDING_STATES:
            raise ApiError(
                "ERR_FINDING_NOT_CLOSABLE",
                409,
                "Finding is already CLOSED",
            )
        # Retest evidence gate for HIGH/CRITICAL findings.
        if finding["severity"] in ("HIGH", "CRITICAL"):
            retested = any(
                e["model_id"] == model_id
                and e["status"] == "COMPLETED"
                and e["completed_at"] is not None
                and e["completed_at"] > finding["created_at"]
                for e in store.engagements.values()
            )
            if not retested:
                raise ApiError(
                    "ERR_RETEST_REQUIRED",
                    409,
                    "Closing a HIGH/CRITICAL finding requires a COMPLETED validation "
                    "engagement with completed_at after the finding's created_at",
                )
        finding["status"] = "CLOSED"
        finding["closed_at"] = store.now()
        workflow.mutate(finding)
        model = store.models[model_id]
        risk.recompute_risk(model)
        workflow.auto_resume_check(model)
        workflow.mutate(model)
        return success(finding_json(finding))


@bp.post("/mrm/models/<model_id>/findings/<finding_id>/reopen")
def reopen_finding(model_id, finding_id):
    require_roles("ModelRiskOfficer")
    with store.lock:
        get_model_or_404(model_id)
        finding = get_finding_or_404(model_id, finding_id)
        if finding["status"] != "CLOSED":
            raise ApiError(
                "ERR_FINDING_NOT_OPEN",
                409,
                "Finding is not in CLOSED status",
            )
        finding["status"] = "OPEN"
        finding["closed_at"] = None
        # remediation_due_at is preserved, not extended.
        workflow.mutate(finding)
        model = store.models[model_id]
        risk.recompute_risk(model)
        workflow.mutate(model)
        return success(finding_json(finding))
