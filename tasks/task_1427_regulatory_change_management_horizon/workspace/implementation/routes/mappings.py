"""Obligation-Control coverage mappings (PRD §3.3)."""

from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import (ApiError, ERR_CONTROL_NOT_ACTIVE, ERR_DUPLICATE_MAPPING,
                    ERR_OBLIGATION_NOT_ACTIVE, invalid_state, sod_violation)
from middleware import (auth_context, get_body, get_or_404, opt_str, req_int,
                        req_str, require_roles)
from response import paginate, success_object
from serializers import created_sorted, mapping_to_api
from services.audit import append_audit
from services.cascades import recompute_open_gaps_for_obligation

bp = Blueprint("mappings", __name__)


@bp.post("/compliance/obligation-control-mappings")
def create_mapping():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    obligation_id = req_str(body, "obligation_id")
    control_id = req_str(body, "control_id")
    coverage_weight = req_int(body, "coverage_weight", minimum=1, maximum=10)

    # Priority 3: body FK existence (obligation_id before control_id).
    obligation = get_or_404(store.obligations, obligation_id, "obligation")
    control = get_or_404(store.controls, control_id, "control")

    # Priority 7: at most one non-terminal mapping per (obligation, control).
    if any(m["obligation_id"] == obligation["id"]
           and m["control_id"] == control["id"]
           and m["status"] in ("PROPOSED", "APPROVED")
           for m in store.mappings.values()):
        raise ApiError(ERR_DUPLICATE_MAPPING, 409,
                       "A PROPOSED or APPROVED mapping already exists for the "
                       "(obligation_id, control_id) pair")

    # Priority 8: referential state.
    if obligation["status"] != "ACTIVE":
        raise ApiError(ERR_OBLIGATION_NOT_ACTIVE, 409,
                       "Referenced obligation is not ACTIVE")
    if control["status"] != "ACTIVE":
        raise ApiError(ERR_CONTROL_NOT_ACTIVE, 409,
                       "Referenced control is not ACTIVE")

    mapping = stamp_new({
        "id": new_id(),
        "obligation_id": obligation["id"],
        "control_id": control["id"],
        "coverage_weight": coverage_weight,
        "status": "PROPOSED",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
    })
    store.mappings[mapping["id"]] = mapping
    append_audit(user_id, role, "POST /compliance/obligation-control-mappings",
                 "ObligationControlMapping", mapping["id"])
    return success_object(mapping_to_api(mapping), status=201)


@bp.get("/compliance/obligation-control-mappings")
def list_mappings():
    auth_context()
    items = created_sorted(store.mappings.values())
    for param in ("obligation_id", "control_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [m for m in items if m[param] == value]
    return paginate(items, mapping_to_api)


@bp.get("/compliance/obligation-control-mappings/<mapping_id>")
def get_mapping(mapping_id):
    auth_context()
    mapping = get_or_404(store.mappings, mapping_id, "mapping")
    return success_object(mapping_to_api(mapping))


@bp.post("/compliance/obligation-control-mappings/<mapping_id>/approve")
def approve_mapping(mapping_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    mapping = get_or_404(store.mappings, mapping_id, "mapping")
    if mapping["status"] != "PROPOSED":
        raise invalid_state("approve requires status PROPOSED")
    if user_id == mapping["created_by_user_id"]:
        raise sod_violation()
    mapping["status"] = "APPROVED"
    mapping["approved_by_user_id"] = user_id
    touch(mapping)
    recompute_open_gaps_for_obligation(mapping["obligation_id"])
    append_audit(user_id, role,
                 "POST /compliance/obligation-control-mappings/{id}/approve",
                 "ObligationControlMapping", mapping["id"])
    return success_object(mapping_to_api(mapping))


@bp.post("/compliance/obligation-control-mappings/<mapping_id>/reject")
def reject_mapping(mapping_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    opt_str(get_body(), "reason")  # optional; type-checked when present
    mapping = get_or_404(store.mappings, mapping_id, "mapping")
    if mapping["status"] != "PROPOSED":
        raise invalid_state("reject requires status PROPOSED")
    mapping["status"] = "REJECTED"
    touch(mapping)
    append_audit(user_id, role,
                 "POST /compliance/obligation-control-mappings/{id}/reject",
                 "ObligationControlMapping", mapping["id"])
    return success_object(mapping_to_api(mapping))


@bp.post("/compliance/obligation-control-mappings/<mapping_id>/retire")
def retire_mapping(mapping_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    mapping = get_or_404(store.mappings, mapping_id, "mapping")
    if mapping["status"] != "APPROVED":
        raise invalid_state("retire requires status APPROVED")
    mapping["status"] = "RETIRED"
    touch(mapping)
    recompute_open_gaps_for_obligation(mapping["obligation_id"])
    append_audit(user_id, role,
                 "POST /compliance/obligation-control-mappings/{id}/retire",
                 "ObligationControlMapping", mapping["id"])
    return success_object(mapping_to_api(mapping))
