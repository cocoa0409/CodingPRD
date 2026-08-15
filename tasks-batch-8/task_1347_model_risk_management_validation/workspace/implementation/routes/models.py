"""Model inventory endpoints: register, list, get, approve, retire."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from serializers import model_json
from services import risk, workflow
from utils import add_months, new_id
from validate import get_body, pagination_params, v_enum, v_int, v_opt_bool, v_str

bp = Blueprint("models", __name__)


def get_model_or_404(model_id):
    m = store.models.get(model_id)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Model '%s' does not exist" % model_id)
    return m


@bp.post("/mrm/models")
def create_model():
    body = get_body()
    name = v_str(body, "name")
    business_unit = v_str(body, "business_unit")
    declared_complexity = v_enum(body, "declared_complexity", ("LOW", "MEDIUM", "HIGH"))
    usage_scope = v_enum(body, "usage_scope", ("SINGLE_DESK", "MULTI_DESK", "ENTERPRISE"))
    exposure_amount = v_int(body, "exposure_amount", minimum=0)
    is_vendor_model = v_opt_bool(body, "is_vendor_model", False)
    require_roles("ModelOwner")
    with store.lock:
        now = store.now()
        model = {
            "id": new_id(),
            "name": name,
            "business_unit": business_unit,
            "owner_user_id": g.user_id,
            "is_vendor_model": is_vendor_model,
            "declared_complexity": declared_complexity,
            "assessed_complexity": None,
            "usage_scope": usage_scope,
            "exposure_amount": exposure_amount,
            "risk_score": 0,
            "risk_tier": None,
            "status": "REGISTERED",
            "last_validated_at": None,
            "validation_due_at": None,
            "replaced_by_model_id": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.models[model["id"]] = model
        # DEV_DECLARED variant at registration; findings penalty is zero.
        model["risk_score"] = risk.compute_score(model)
        model["risk_tier"] = risk.tier_of(model["risk_score"])
        model["validation_due_at"] = add_months(
            now, risk.REVALIDATION_MONTHS[model["risk_tier"]]
        )
        return success(model_json(model), 201)


@bp.get("/mrm/models")
def list_models():
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    f_tier = request.args.get("risk_tier")
    f_owner = request.args.get("owner_user_id")
    f_replaced_by = request.args.get("replaced_by_model_id")
    with store.lock:
        items = sorted(store.models.values(), key=lambda m: (m["created_at"], m["_seq"]))
        if f_status is not None:
            items = [m for m in items if m["status"] == f_status]
        if f_tier is not None:
            items = [m for m in items if m["risk_tier"] == f_tier]
        if f_owner is not None:
            items = [m for m in items if m["owner_user_id"] == f_owner]
        if f_replaced_by is not None:
            items = [m for m in items if m["replaced_by_model_id"] == f_replaced_by]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([model_json(m) for m in page], limit, offset, total)


@bp.get("/mrm/models/<model_id>")
def get_model(model_id):
    require_roles(*BUSINESS_ROLES)
    with store.lock:
        return success(model_json(get_model_or_404(model_id)))


@bp.post("/mrm/models/<model_id>/approve")
def approve_model(model_id):
    require_roles("ModelRiskOfficer")
    with store.lock:
        model = get_model_or_404(model_id)
        # State gate
        if model["status"] != "REGISTERED":
            raise ApiError(
                "ERR_MODEL_NOT_APPROVABLE",
                409,
                "Only a REGISTERED model can be approved for use",
            )
        # Safety gates: open CRITICAL findings, then vendor transparency.
        for f in store.findings.values():
            if (
                f["model_id"] == model_id
                and f["status"] in risk.OPEN_FINDING_STATES
                and f["severity"] == "CRITICAL"
            ):
                raise ApiError(
                    "ERR_OPEN_CRITICAL_FINDINGS",
                    409,
                    "Model has open CRITICAL findings",
                )
        if model["is_vendor_model"]:
            vendor_ok = any(
                a["model_id"] == model_id
                and a["status"] == "CURRENT"
                and a["completeness_score"] >= risk.VENDOR_MIN_COMPLETENESS
                for a in store.assessments.values()
            )
            if not vendor_ok:
                raise ApiError(
                    "ERR_VENDOR_ASSESSMENT_NOT_CURRENT",
                    403,
                    "Vendor model lacks a CURRENT transparency assessment with "
                    "completeness_score >= 70",
                )
        # Temporal gate: overdue strictly after validation_due_at.
        if store.now() > model["validation_due_at"]:
            raise ApiError(
                "ERR_VALIDATION_OVERDUE",
                409,
                "Model validation is overdue",
            )
        # Referential evidence gates.
        if not any(
            d["model_id"] == model_id and d["status"] == "APPROVED"
            for d in store.documentations.values()
        ):
            raise ApiError(
                "ERR_NO_APPROVED_DOCUMENTATION",
                409,
                "Model has no APPROVED documentation package",
            )
        if not any(
            e["model_id"] == model_id
            and e["status"] == "COMPLETED"
            and e["outcome"] != "INEFFECTIVE"
            for e in store.engagements.values()
        ):
            raise ApiError(
                "ERR_NO_COMPLETED_VALIDATION",
                409,
                "Model has no COMPLETED validation engagement with outcome other "
                "than INEFFECTIVE",
            )
        model["status"] = "APPROVED_FOR_USE"
        workflow.mutate(model)
        return success(model_json(model))


@bp.post("/mrm/models/<model_id>/retire")
def retire_model(model_id):
    body = get_body()
    replacement_id = v_str(body, "replacement_model_id")
    require_roles("ModelRiskOfficer")
    with store.lock:
        model = get_model_or_404(model_id)
        # Body-referenced identifier resolves at its own existence step.
        replacement = store.models.get(replacement_id)
        if replacement is None:
            raise ApiError(
                "ERR_NOT_FOUND",
                404,
                "Replacement model '%s' does not exist" % replacement_id,
            )
        # State gate
        if model["status"] not in ("APPROVED_FOR_USE", "SUSPENDED"):
            raise ApiError(
                "ERR_MODEL_NOT_RETIRABLE",
                409,
                "Only an APPROVED_FOR_USE or SUSPENDED model can be retired",
            )
        # Referential gate
        if replacement["status"] != "APPROVED_FOR_USE":
            raise ApiError(
                "ERR_REPLACEMENT_MODEL_NOT_APPROVED",
                409,
                "Replacement model is not APPROVED_FOR_USE",
            )
        # Constraint gate
        if replacement_id == model_id:
            raise ApiError(
                "ERR_SELF_REPLACEMENT",
                409,
                "A model cannot be its own replacement",
            )

        # Deadlines of transferred findings are pinned against the replacement's
        # tier BEFORE the transferred findings count into its penalty.
        pinned_tier = replacement["risk_tier"]

        for mt in workflow.metrics_of(model_id):
            if mt["status"] in ("ACTIVE", "PAUSED"):
                mt["status"] = "DECOMMISSIONED"
                workflow.mutate(mt)

        transferred = sorted(
            workflow.open_findings_of(model_id),
            key=lambda f: (f["created_at"], f["_seq"]),
        )
        for f in transferred:
            f["model_id"] = replacement_id
            f["remediation_due_at"] = f["created_at"] + timedelta(
                days=risk.deadline_days(f["severity"], pinned_tier, f["source"])
            )
            workflow.mutate(f)

        model["status"] = "RETIRED"
        model["replaced_by_model_id"] = replacement_id
        workflow.mutate(model)

        risk.recompute_risk(replacement)
        workflow.mutate(replacement)
        return success(model_json(model))
