"""SubAccountAllocation endpoints (VARIABLE only) — PRD §3.2."""

from flask import Blueprint

import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import lookups

bp = Blueprint("allocations", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def serialize(a):
    return {
        "id": a["id"],
        "contract_id": a["contract_id"],
        "division_name": a["division_name"],
        "allocation_bps": a["allocation_bps"],
        "unit_value_cents": a["unit_value_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/sub-account-allocations")
def create_allocation():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    division_name = v.require_string(body, "division_name")
    allocation_bps = v.require_int(body, "allocation_bps", minimum=1, maximum=10000)
    unit_value_cents = v.require_int(body, "unit_value_cents", minimum=0)

    lookups.ref_contract(contract_id)

    now = store.clock.now()
    aid = store.new_id()
    alloc = {
        "id": aid,
        "contract_id": contract_id,
        "division_name": division_name,
        "allocation_bps": allocation_bps,
        "unit_value_cents": unit_value_cents,
        "status": "ACTIVE",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.sub_account_allocations[aid] = alloc
    return object_response(serialize(alloc), 201, now)


@bp.get("/sub-account-allocations/<rid>")
def get_allocation(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    alloc = lookups.path_allocation(rid)
    return object_response(serialize(alloc), 200, store.clock.now())
