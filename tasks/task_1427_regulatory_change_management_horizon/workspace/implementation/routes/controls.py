"""Controls: creation, review recording, retirement (PRD §3.3)."""

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_CONTROL_IN_USE, ERR_DUPLICATE_CONTROL_CODE,
                    invalid_state)
from middleware import (auth_context, get_or_404, opt_dt, req_int, req_str,
                        require_roles, get_body)
from response import paginate, success_object
from serializers import control_to_api, created_sorted
from services.audit import append_audit
from services.cascades import recompute_open_gaps_for_control

bp = Blueprint("controls", __name__)


@bp.post("/compliance/controls")
def create_control():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    control_code = req_str(body, "control_code")
    title = req_str(body, "title")
    owner_department = req_str(body, "owner_department")
    review_frequency_days = req_int(body, "review_frequency_days", minimum=1)
    last_reviewed_at = opt_dt(body, "last_reviewed_at")

    # Priority 7: control_code globally unique.
    if any(c["control_code"] == control_code for c in store.controls.values()):
        raise ApiError(ERR_DUPLICATE_CONTROL_CODE, 409,
                       "control_code already exists")

    control = stamp_new({
        "id": new_id(),
        "control_code": control_code,
        "title": title,
        "owner_department": owner_department,
        "review_frequency_days": review_frequency_days,
        "last_reviewed_at": last_reviewed_at,
        "policy_version": 1,
        "status": "ACTIVE",
    })
    store.controls[control["id"]] = control
    append_audit(user_id, role, "POST /compliance/controls",
                 "Control", control["id"])
    return success_object(control_to_api(control), status=201)


@bp.get("/compliance/controls")
def list_controls():
    auth_context()
    items = created_sorted(store.controls.values())
    for param in ("status", "owner_department"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    return paginate(items, control_to_api)


@bp.get("/compliance/controls/<control_id>")
def get_control(control_id):
    auth_context()
    control = get_or_404(store.controls, control_id, "control")
    return success_object(control_to_api(control))


@bp.post("/compliance/controls/<control_id>/record-review")
def record_review(control_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    control = get_or_404(store.controls, control_id, "control")
    control["last_reviewed_at"] = now_clock()
    touch(control)
    # Coverage moves when effectiveness moves.
    recompute_open_gaps_for_control(control["id"])
    append_audit(user_id, role, "POST /compliance/controls/{id}/record-review",
                 "Control", control["id"])
    return success_object(control_to_api(control))


@bp.post("/compliance/controls/<control_id>/retire")
def retire_control(control_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    control = get_or_404(store.controls, control_id, "control")
    if control["status"] != "ACTIVE":
        raise invalid_state("retire requires status ACTIVE")
    in_use = any(
        m["control_id"] == control["id"] and m["status"] in ("PROPOSED", "APPROVED")
        for m in store.mappings.values())
    if in_use:
        raise ApiError(ERR_CONTROL_IN_USE, 409,
                       "Control retire blocked by PROPOSED/APPROVED mappings")
    control["status"] = "RETIRED"
    touch(control)
    append_audit(user_id, role, "POST /compliance/controls/{id}/retire",
                 "Control", control["id"])
    return success_object(control_to_api(control))
