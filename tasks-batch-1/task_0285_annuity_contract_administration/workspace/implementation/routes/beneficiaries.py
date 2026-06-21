"""Beneficiary endpoints (PRD §3.7)."""

from flask import Blueprint

import errors
import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import lookups

bp = Blueprint("beneficiaries", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}
RELATIONSHIPS = {"SPOUSE", "CHILD", "TRUST", "ESTATE", "OTHER"}


def serialize(b):
    return {
        "id": b["id"],
        "contract_id": b["contract_id"],
        "full_name": b["full_name"],
        "relationship": b["relationship"],
        "share_bps": b["share_bps"],
        "payout_cents": b["payout_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/beneficiaries")
def create_beneficiary():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    full_name = v.require_string(body, "full_name")
    relationship = v.require_enum(body, "relationship", RELATIONSHIPS)
    share_bps = v.require_int(body, "share_bps", minimum=1, maximum=10000)

    lookups.ref_contract(contract_id)

    now = store.clock.now()
    bid = store.new_id()
    beneficiary = {
        "id": bid,
        "contract_id": contract_id,
        "full_name": full_name,
        "relationship": relationship,
        "share_bps": share_bps,
        "payout_cents": 0,
        "status": "ACTIVE",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.beneficiaries[bid] = beneficiary
    return object_response(serialize(beneficiary), 201, now)


@bp.get("/beneficiaries/<rid>")
def get_beneficiary(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    beneficiary = lookups.path_beneficiary(rid)
    return object_response(serialize(beneficiary), 200, store.clock.now())


@bp.post("/beneficiaries/<rid>/revoke")
def revoke_beneficiary(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    beneficiary = lookups.path_beneficiary(rid)
    if beneficiary["status"] != "ACTIVE":
        raise errors.invalid_state("Beneficiary is not ACTIVE.")
    now = store.clock.now()
    beneficiary["status"] = "REVOKED"
    beneficiary["version"] += 1
    beneficiary["updated_at"] = iso8601(now)
    return object_response(serialize(beneficiary), 200, now)
