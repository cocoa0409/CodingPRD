"""InstallProject endpoints (PRD §3.8)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import install_view
import common as C

bp = Blueprint("installs", __name__)


@bp.post("/aquatics/installs")
def create_install():
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    contract_id = C.req_str(data, "contract_id")
    system_id = C.req_str(data, "system_id")
    labor_estimate_cents = C.req_int(data, "labor_estimate_cents", minimum=0)
    equipment_estimate_cents = C.req_int(data, "equipment_estimate_cents", minimum=0)

    # existence left-to-right: contract then system
    if contract_id not in store.contracts:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    system = store.systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    # system being built must be PROVISIONING
    if system["status"] != "PROVISIONING":
        raise ApiError("ERR_SYSTEM_NOT_PROVISIONING", "System must be PROVISIONING for an install quote.")

    rec = C.make_record({
        "contract_id": contract_id,
        "system_id": system_id,
        "labor_estimate_cents": labor_estimate_cents,
        "equipment_estimate_cents": equipment_estimate_cents,
        "actual_labor_minutes": 0,
        "actual_equipment_cents": 0,
        "change_order_cents": 0,
        "quote_total_cents": 0,
        "deposit_cents": 0,
        "final_total_cents": 0,
        "status": "QUOTED",
    })
    store.installs[rec["id"]] = rec
    return object_response(install_view(rec), 201)


@bp.get("/aquatics/installs/<iid>")
def get_install(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "FieldTech", "CustomerOwner"})
    rec = store.installs.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Install project not found.")
    return object_response(install_view(rec))


@bp.get("/aquatics/contracts/<cid>/installs")
def list_contract_installs(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "CustomerOwner"})
    if cid not in store.contracts:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [i for i in store.installs.values() if i["contract_id"] == cid]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([install_view(r) for r in page], limit, offset, total)


@bp.post("/aquatics/installs/<iid>/approve")
def approve_install(iid):
    user_id, role = get_auth()
    require_roles(role, {"CustomerOwner"})
    rec = store.installs.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Install project not found.")
    # ownership (priority 3)
    contract = store.contracts.get(rec["contract_id"])
    if contract is None or contract["customer_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this contract.")
    if rec["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED project may be approved.")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Owning contract must be ACTIVE.")
    quote_total, deposit = C.compute_install_provisional(rec)
    rec["quote_total_cents"] = quote_total
    rec["deposit_cents"] = deposit
    rec["status"] = "APPROVED"
    C.touch(rec)
    # deposit invoice
    C.create_invoice(contract["id"], "INSTALL", rec["id"], deposit)
    C.recompute_account_balance(contract)
    return object_response(install_view(rec))


@bp.post("/aquatics/installs/<iid>/start-build")
def start_build(iid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.installs.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Install project not found.")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED project may start build.")
    system = store.systems.get(rec["system_id"])
    if system is None or system["status"] != "PROVISIONING":
        raise ApiError("ERR_SYSTEM_NOT_PROVISIONING", "Target system must be PROVISIONING.")
    rec["status"] = "IN_BUILD"
    C.touch(rec)
    return object_response(install_view(rec))


@bp.post("/aquatics/installs/<iid>/handoff")
def handoff_install(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.installs.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Install project not found.")
    if rec["status"] != "IN_BUILD":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_BUILD project may be handed off.")
    data = C.require_body(request.get_json(silent=True))
    actual_labor_minutes = C.req_int(data, "actual_labor_minutes", minimum=0)
    actual_equipment_cents = C.req_int(data, "actual_equipment_cents", minimum=0)
    change_order_cents = C.req_int(data, "change_order_cents", allow_missing=True,
                                   default=0, minimum=0)
    rec["actual_labor_minutes"] = actual_labor_minutes
    rec["actual_equipment_cents"] = actual_equipment_cents
    rec["change_order_cents"] = change_order_cents
    final_total = C.compute_install_final(rec)
    rec["final_total_cents"] = final_total
    rec["status"] = "HANDED_OFF"
    C.touch(rec)
    contract = store.contracts.get(rec["contract_id"])
    balance = final_total - rec["deposit_cents"]
    C.create_invoice(contract["id"], "INSTALL", rec["id"], balance)
    C.recompute_account_balance(contract)
    return object_response(install_view(rec))


@bp.post("/aquatics/installs/<iid>/cancel")
def cancel_install(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.installs.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Install project not found.")
    if rec["status"] not in ("QUOTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED or APPROVED project may be cancelled.")
    was_approved = rec["status"] == "APPROVED"
    rec["status"] = "CANCELLED"
    C.touch(rec)
    if was_approved:
        contract = store.contracts.get(rec["contract_id"])
        # void the deposit invoice for this install
        for inv in store.invoices.values():
            if (inv["source_kind"] == "INSTALL" and inv["source_id"] == rec["id"]
                    and inv["status"] in ("ISSUED", "OVERDUE")):
                inv["status"] = "VOID"
                C.touch(inv)
        if contract is not None:
            C.recompute_account_balance(contract)
    return object_response(install_view(rec))
