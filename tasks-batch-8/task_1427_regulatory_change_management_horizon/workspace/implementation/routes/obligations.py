"""Obligation register entries: lifecycle DRAFT/ACTIVE/RETIRED (PRD §3.2)."""

from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import (ApiError, ERR_CHANGE_NOT_TRIAGED_APPLICABLE,
                    ERR_DUPLICATE_OBLIGATION_CODE, ERR_OBLIGATION_IN_USE,
                    invalid_state)
from middleware import (auth_context, get_body, get_or_404, req_enum, req_str,
                        require_roles)
from response import paginate, success_object
from serializers import created_sorted, obligation_to_api
from services.audit import append_audit
from services.cascades import PLAN_NON_TERMINAL

bp = Blueprint("obligations", __name__)

CRITICALITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@bp.post("/compliance/obligations")
def create_obligation():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    obligation_code = req_str(body, "obligation_code")
    title = req_str(body, "title")
    change_id = req_str(body, "regulatory_change_id")
    criticality = req_enum(body, "criticality", CRITICALITIES)

    # Priority 3: body FK existence.
    change = get_or_404(store.regulatory_changes, change_id, "regulatory change")

    # Priority 7: obligation_code unique across all obligations ever created.
    if any(o["obligation_code"] == obligation_code
           for o in store.obligations.values()):
        raise ApiError(ERR_DUPLICATE_OBLIGATION_CODE, 409,
                       "obligation_code already exists")

    # Priority 8: referential state.
    if change["status"] != "TRIAGED_APPLICABLE":
        raise ApiError(ERR_CHANGE_NOT_TRIAGED_APPLICABLE, 409,
                       "Referenced change is not TRIAGED_APPLICABLE")

    obligation = stamp_new({
        "id": new_id(),
        "obligation_code": obligation_code,
        "title": title,
        "regulatory_change_id": change["id"],
        "criticality": criticality,
        "status": "DRAFT",
    })
    store.obligations[obligation["id"]] = obligation
    append_audit(user_id, role, "POST /compliance/obligations",
                 "Obligation", obligation["id"])
    return success_object(obligation_to_api(obligation), status=201)


@bp.get("/compliance/obligations")
def list_obligations():
    auth_context()
    items = created_sorted(store.obligations.values())
    for param in ("regulatory_change_id", "status", "criticality"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    return paginate(items, obligation_to_api)


@bp.get("/compliance/obligations/<obligation_id>")
def get_obligation(obligation_id):
    auth_context()
    obligation = get_or_404(store.obligations, obligation_id, "obligation")
    return success_object(obligation_to_api(obligation))


@bp.post("/compliance/obligations/<obligation_id>/activate")
def activate_obligation(obligation_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    obligation = get_or_404(store.obligations, obligation_id, "obligation")
    if obligation["status"] != "DRAFT":
        raise invalid_state("activate requires status DRAFT")
    obligation["status"] = "ACTIVE"
    touch(obligation)
    append_audit(user_id, role, "POST /compliance/obligations/{id}/activate",
                 "Obligation", obligation["id"])
    return success_object(obligation_to_api(obligation))


@bp.post("/compliance/obligations/<obligation_id>/retire")
def retire_obligation(obligation_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    obligation = get_or_404(store.obligations, obligation_id, "obligation")
    if obligation["status"] != "ACTIVE":
        raise invalid_state("retire requires status ACTIVE")
    in_use_gap = any(
        g["obligation_id"] == obligation["id"] and g["status"] in ("OPEN", "IN_REVIEW")
        for g in store.gap_analyses.values())
    in_use_plan = any(
        p["obligation_id"] == obligation["id"]
        and p["execution_status"] in PLAN_NON_TERMINAL
        for p in store.plans.values())
    if in_use_gap or in_use_plan:
        raise ApiError(ERR_OBLIGATION_IN_USE, 409,
                       "Obligation retire blocked by open gap analyses or "
                       "non-terminal plans")
    obligation["status"] = "RETIRED"
    touch(obligation)
    # Cascade: APPROVED mappings of this obligation -> RETIRED.
    for mapping in store.mappings.values():
        if (mapping["obligation_id"] == obligation["id"]
                and mapping["status"] == "APPROVED"):
            mapping["status"] = "RETIRED"
            touch(mapping)
    append_audit(user_id, role, "POST /compliance/obligations/{id}/retire",
                 "Obligation", obligation["id"])
    return success_object(obligation_to_api(obligation))


@bp.post("/compliance/obligations/<obligation_id>/reinstate")
def reinstate_obligation(obligation_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    req_str(body, "rationale")
    obligation = get_or_404(store.obligations, obligation_id, "obligation")
    if obligation["status"] != "RETIRED":
        raise invalid_state("reinstate requires status RETIRED")
    # Reinstatement does NOT resurrect retired mappings.
    obligation["status"] = "ACTIVE"
    touch(obligation)
    append_audit(user_id, role, "POST /compliance/obligations/{id}/reinstate",
                 "Obligation", obligation["id"])
    return success_object(obligation_to_api(obligation))
