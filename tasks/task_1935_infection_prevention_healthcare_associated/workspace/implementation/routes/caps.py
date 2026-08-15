"""CorrectiveActionPlans."""
from flask import Blueprint, request

import db
from errors import (
    ERR_CAP_NOT_ACTIVATABLE,
    ERR_CAP_NOT_FOUND,
    ERR_CAP_NOT_SUBMITTABLE,
    ERR_CAP_NOT_VERIFIABLE,
    ERR_CAP_SOURCE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTY,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, recompute_posture, touch
from services.serializers import cap_view
from validate import body, pagination_args, req_dt, req_enum, req_string

bp = Blueprint("caps", __name__)

SOURCE_TYPES = {"OUTBREAK", "ISOLATION_AUDIT", "HAND_HYGIENE", "SIR_HIGH"}


def _validate_source(source_type, source_ref_id):
    """Polymorphic reference existence check (ERR_CAP_SOURCE_INVALID)."""
    if source_ref_id is None or not isinstance(source_ref_id, str) or not source_ref_id:
        raise_err(ERR_CAP_SOURCE_INVALID, "source_ref_id missing or invalid")
    if source_type == "OUTBREAK":
        inv = db.outbreak_investigations.get(source_ref_id)
        if inv is None or inv["status"] != "CONFIRMED":
            raise_err(ERR_CAP_SOURCE_INVALID, "OUTBREAK source must reference a CONFIRMED OutbreakInvestigation")
    elif source_type == "ISOLATION_AUDIT":
        if source_ref_id not in db.isolation_compliance_audits:
            raise_err(ERR_CAP_SOURCE_INVALID, "ISOLATION_AUDIT source must reference an IsolationComplianceAudit")
    elif source_type == "SIR_HIGH":
        if source_ref_id not in db.monthly_summaries:
            raise_err(ERR_CAP_SOURCE_INVALID, "SIR_HIGH source must reference a MonthlySummary")
    elif source_type == "HAND_HYGIENE":
        if source_ref_id not in db.units:
            raise_err(ERR_CAP_SOURCE_INVALID, "HAND_HYGIENE source must reference a Unit")


@bp.post("/api/corrective-action-plans")
def create_cap():
    user_id, _ = require_roles(["InfectionPreventionist"])
    b = body()
    for f in ("unit_id", "source_type", "source_ref_id", "description", "due_date"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    source_type = req_enum(b, "source_type", SOURCE_TYPES)
    description = req_string(b, "description", min_len=10)
    due_date = req_dt(b, "due_date")
    source_ref_id = b.get("source_ref_id")

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    _validate_source(source_type, source_ref_id)

    cap = new_entity({
        "unit_id": unit_id,
        "source_type": source_type,
        "source_ref_id": source_ref_id,
        "description": description,
        "due_date": due_date,
        "evidence_notes": None,
        "failure_count": 0,
        "created_by_user_id": user_id,
        "verified_by_user_id": None,
        "status": "DRAFT",
    })
    db.corrective_action_plans[cap["id"]] = cap
    return success_object(cap_view(cap), 201)


@bp.get("/api/corrective-action-plans")
def list_caps():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    def _match(c):
        if unit_id is not None and c["unit_id"] != unit_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    items = [c for c in db.corrective_action_plans.values() if _match(c)]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([cap_view(c) for c in page], total, limit, offset)


@bp.get("/api/corrective-action-plans/<cid>")
def get_cap(cid):
    require_roles(ALL_ROLES)
    c = db.corrective_action_plans.get(cid)
    if c is None:
        raise_err(ERR_CAP_NOT_FOUND, "corrective action plan id does not exist")
    return success_object(cap_view(c))


@bp.post("/api/corrective-action-plans/<cid>/activate")
def activate_cap(cid):
    require_roles(["InfectionPreventionist"])
    c = db.corrective_action_plans.get(cid)
    if c is None:
        raise_err(ERR_CAP_NOT_FOUND, "corrective action plan id does not exist")
    if c["status"] != "DRAFT":
        raise_err(ERR_CAP_NOT_ACTIVATABLE, "activate requires status DRAFT")
    c["status"] = "ACTIVE"
    touch(c)
    recompute_posture(c["unit_id"])
    return success_object(cap_view(c))


@bp.post("/api/corrective-action-plans/<cid>/submit-for-verification")
def submit_cap(cid):
    require_roles(["InfectionPreventionist"])
    b = body()
    if "evidence_notes" not in b or b["evidence_notes"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: evidence_notes")
    notes = req_string(b, "evidence_notes", min_len=20)
    c = db.corrective_action_plans.get(cid)
    if c is None:
        raise_err(ERR_CAP_NOT_FOUND, "corrective action plan id does not exist")
    if c["status"] != "ACTIVE":
        raise_err(ERR_CAP_NOT_SUBMITTABLE, "submit-for-verification requires status ACTIVE")
    c["status"] = "VERIFICATION_PENDING"
    c["evidence_notes"] = notes
    touch(c)
    recompute_posture(c["unit_id"])
    return success_object(cap_view(c))


@bp.post("/api/corrective-action-plans/<cid>/verify")
def verify_cap(cid):
    user_id, _ = require_roles(["InfectionControlDirector"])
    c = db.corrective_action_plans.get(cid)
    if c is None:
        raise_err(ERR_CAP_NOT_FOUND, "corrective action plan id does not exist")
    if c["status"] != "VERIFICATION_PENDING":
        raise_err(ERR_CAP_NOT_VERIFIABLE, "verify requires status VERIFICATION_PENDING")
    if user_id == c["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY, "verifier must differ from created_by_user_id")
    c["status"] = "VERIFIED"
    c["verified_by_user_id"] = user_id
    touch(c)
    recompute_posture(c["unit_id"])
    return success_object(cap_view(c))


@bp.post("/api/corrective-action-plans/<cid>/fail-verification")
def fail_cap(cid):
    require_roles(["InfectionControlDirector"])
    b = body()
    if "reason" not in b or b["reason"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reason")
    c = db.corrective_action_plans.get(cid)
    if c is None:
        raise_err(ERR_CAP_NOT_FOUND, "corrective action plan id does not exist")
    if c["status"] != "VERIFICATION_PENDING":
        raise_err(ERR_CAP_NOT_VERIFIABLE, "fail-verification requires status VERIFICATION_PENDING")
    c["failure_count"] += 1
    if c["failure_count"] >= 2:
        c["status"] = "ESCALATED"
    else:
        c["status"] = "ACTIVE"
    touch(c)
    recompute_posture(c["unit_id"])
    return success_object(cap_view(c))
