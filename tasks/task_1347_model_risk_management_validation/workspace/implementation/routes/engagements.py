"""Validation engagement endpoints: open, list, complete, reopen (retest loop)."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import engagement_json
from services import risk, workflow
from utils import add_months, new_id
from validate import get_body, pagination_params, v_bool, v_dt, v_enum

bp = Blueprint("engagements", __name__)


@bp.post("/mrm/models/<model_id>/validation-engagements")
def create_engagement(model_id):
    body = get_body()
    scope_cs = v_bool(body, "scope_conceptual_soundness")
    scope_oa = v_bool(body, "scope_outcomes_analysis")
    period_start = v_dt(body, "period_start")
    period_end = v_dt(body, "period_end")
    # Request-shape rules: at least one scope flag; end strictly after start.
    if not (scope_cs or scope_oa):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "At least one validation scope flag must be selected",
        )
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "period_end must be strictly after period_start",
        )
    require_roles("ModelValidator")
    with store.lock:
        model = get_model_or_404(model_id)
        # State gate
        if model["status"] == "RETIRED":
            raise ApiError("ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED")
        # Safety gate: validator independence (segregation of duties).
        if g.user_id == model["owner_user_id"]:
            raise ApiError(
                "ERR_SOD_VALIDATION_INDEPENDENCE",
                403,
                "Validation must be independent of the model owner",
            )
        # Referential gate: at least one APPROVED documentation package.
        if not any(
            d["model_id"] == model_id and d["status"] == "APPROVED"
            for d in store.documentations.values()
        ):
            raise ApiError(
                "ERR_NO_APPROVED_DOCUMENTATION",
                409,
                "Model has no APPROVED documentation package",
            )
        # Constraint gate: half-open [start, end) window overlap; adjacency allowed.
        for e in store.engagements.values():
            if e["model_id"] != model_id:
                continue
            if period_start < e["period_end"] and e["period_start"] < period_end:
                raise ApiError(
                    "ERR_VALIDATION_WINDOW_OVERLAP",
                    409,
                    "Review window overlaps an existing engagement of this model",
                )
        now = store.now()
        eng = {
            "id": new_id(),
            "model_id": model_id,
            "validator_user_id": g.user_id,
            "scope_conceptual_soundness": scope_cs,
            "scope_outcomes_analysis": scope_oa,
            "period_start": period_start,
            "period_end": period_end,
            "status": "TESTING",
            "outcome": None,
            "assessed_complexity": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.engagements[eng["id"]] = eng
        return success(engagement_json(eng), 201)


@bp.get("/mrm/models/<model_id>/validation-engagements")
def list_engagements(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_model_or_404(model_id)
        items = [e for e in store.engagements.values() if e["model_id"] == model_id]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        if f_status is not None:
            items = [e for e in items if e["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([engagement_json(e) for e in page], limit, offset, total)


@bp.post("/mrm/validation-engagements/<engagement_id>/complete")
def complete_engagement(engagement_id):
    body = get_body()
    outcome = v_enum(
        body, "outcome", ("EFFECTIVE", "EFFECTIVE_WITH_FINDINGS", "INEFFECTIVE")
    )
    assessed_complexity = v_enum(body, "assessed_complexity", ("LOW", "MEDIUM", "HIGH"))
    require_roles("ModelValidator")
    with store.lock:
        eng = store.engagements.get(engagement_id)
        if eng is None:
            raise ApiError(
                "ERR_NOT_FOUND",
                404,
                "Validation engagement '%s' does not exist" % engagement_id,
            )
        if eng["status"] != "TESTING":
            raise ApiError(
                "ERR_ENGAGEMENT_NOT_IN_TESTING",
                409,
                "Engagement is not in TESTING status",
            )
        now = store.now()
        eng["status"] = "COMPLETED"
        eng["outcome"] = outcome
        eng["assessed_complexity"] = assessed_complexity
        eng["completed_at"] = now
        workflow.mutate(eng)
        # Completion ripples into the model: VALIDATOR_ASSESSED variant from now on.
        model = store.models[eng["model_id"]]
        model["assessed_complexity"] = assessed_complexity
        model["last_validated_at"] = now
        model["risk_score"] = risk.compute_score(model)
        model["risk_tier"] = risk.tier_of(model["risk_score"])
        model["validation_due_at"] = add_months(
            now, risk.REVALIDATION_MONTHS[model["risk_tier"]]
        )
        workflow.mutate(model)
        return success(engagement_json(eng))


@bp.post("/mrm/validation-engagements/<engagement_id>/reopen")
def reopen_engagement(engagement_id):
    require_roles("ModelValidator")
    with store.lock:
        eng = store.engagements.get(engagement_id)
        if eng is None:
            raise ApiError(
                "ERR_NOT_FOUND",
                404,
                "Validation engagement '%s' does not exist" % engagement_id,
            )
        if eng["status"] != "COMPLETED":
            raise ApiError(
                "ERR_ENGAGEMENT_NOT_COMPLETED",
                409,
                "Engagement is not in COMPLETED status",
            )
        # Retest loop: back to TESTING; model fields are NOT reverted.
        eng["status"] = "TESTING"
        eng["completed_at"] = None
        eng["outcome"] = None
        workflow.mutate(eng)
        return success(engagement_json(eng))
