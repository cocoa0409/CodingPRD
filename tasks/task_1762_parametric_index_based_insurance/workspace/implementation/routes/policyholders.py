"""Policyholder endpoints (PRD §3.4)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_HOLDER_NOT_ACTIVE, ERR_HOLDER_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_holder_in_program,
)
from services import domain

bp = Blueprint("policyholders", __name__)

_FRAUD_MANUAL_FLAG = 25


@bp.post("/programs/<programId>/policyholders")
def create_holder(programId):
    require_roles("ServicingAgent")
    prog = get_program(programId)
    data = body()
    require_fields(data, ["legal_name", "tax_id"])
    ack = data.get("basis_risk_disclosure_acknowledged", False)
    if not isinstance(ack, bool):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "basis_risk_disclosure_acknowledged must be boolean")
    holder = domain.stamp_new({
        "program_id": prog["id"],
        "legal_name": data["legal_name"],
        "tax_id": data["tax_id"],
        "basis_risk_disclosure_acknowledged": ack,
        "fraud_score": 0,
        "status": "ACTIVE" if ack else "PROSPECT",
    })
    db.policyholders[holder["id"]] = holder
    return success_object(domain.serialize(holder), 201)


@bp.get("/programs/<programId>/policyholders")
def list_holders(programId):
    require_roles(*ALL_ROLES)
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        h for h in db.policyholders.values() if h["program_id"] == prog["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/policyholders/<holderId>")
def get_holder(programId, holderId):
    require_roles(*ALL_ROLES)
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    return success_object(domain.serialize(holder))


@bp.patch("/programs/<programId>/policyholders/<holderId>")
def update_holder(programId, holderId):
    require_roles("ServicingAgent")
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    data = body()
    if "legal_name" in data and data["legal_name"] is not None:
        holder["legal_name"] = data["legal_name"]
    if "basis_risk_disclosure_acknowledged" in data and data["basis_risk_disclosure_acknowledged"] is not None:
        new_ack = data["basis_risk_disclosure_acknowledged"]
        if not isinstance(new_ack, bool):
            from errors import ERR_INVALID_REQUEST
            raise err(ERR_INVALID_REQUEST, 400, "basis_risk_disclosure_acknowledged must be boolean")
        flipped = (not holder["basis_risk_disclosure_acknowledged"]) and new_ack
        holder["basis_risk_disclosure_acknowledged"] = new_ack
        if flipped and holder["status"] == "PROSPECT":
            holder["status"] = "ACTIVE"
    domain.touch(holder)
    return success_object(domain.serialize(holder))


@bp.post("/programs/<programId>/policyholders/<holderId>/blacklist")
def blacklist_holder(programId, holderId):
    require_roles("FraudAnalyst")
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    if holder["status"] not in ("ACTIVE", "PROSPECT"):
        raise err(ERR_HOLDER_NOT_ACTIVE, 409,
                  "Operation requires policyholder ACTIVE (or PROSPECT for blacklist)")
    was_active = holder["status"] == "ACTIVE"
    holder["status"] = "BLACKLISTED"
    domain.touch(holder)
    if was_active:
        # Cascade: claims of this policyholder in GENERATED/ADJUSTED -> VOIDED
        affected_policies = set()
        holder_policies = [p for p in db.policies.values() if p["policyholder_id"] == holder["id"]]
        pol_ids = {p["id"] for p in holder_policies}
        for c in db.claims.values():
            if c["policy_id"] in pol_ids and c["status"] in ("GENERATED", "ADJUSTED"):
                c["status"] = "VOIDED"
                domain.touch(c)
                affected_policies.add(c["policy_id"])
        for pid in affected_policies:
            pol = db.policies.get(pid)
            if pol:
                domain.reevaluate_policy_posture(pol)
    return success_object(domain.serialize(holder))


@bp.post("/programs/<programId>/policyholders/<holderId>/flag-fraud")
def flag_fraud(programId, holderId):
    require_roles("FraudAnalyst")
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    holder["fraud_score"] = max(0, min(100, int(holder["fraud_score"]) + _FRAUD_MANUAL_FLAG))
    domain.touch(holder)
    return success_object(domain.serialize(holder))


# --- Flat reads ---

@bp.get("/programs/policyholders")
def list_holders_flat():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.policyholders.values())
    if program_id is not None:
        items = [h for h in items if h["program_id"] == program_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/policyholders/<holderId>")
def get_holder_flat(holderId):
    require_roles(*ALL_ROLES)
    holder = db.policyholders.get(holderId)
    if not holder:
        raise err(ERR_HOLDER_NOT_FOUND, 404, "Policyholder id does not exist")
    return success_object(domain.serialize(holder))
