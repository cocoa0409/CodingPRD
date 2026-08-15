"""RecoupmentDemand: read, list, pay."""
from flask import Blueprint

import serializers
from db import STORE
from errors import ApiError
from helpers import (
    apply_filters, as_int, body, get_contract, get_demand,
    paginate, req_field, sorted_created, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list

bp = Blueprint("demands", __name__)


@bp.get("/eqip/recoupment-demands/<did>")
@require_roles(*ANY_ROLE)
def get_one_demand(did, _uid, _role):
    return ok(serializers.demand(get_demand(did)))


@bp.get("/eqip/recoupment-demands")
@require_roles(*ANY_ROLE)
def list_demands(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.demands.values()),
        [("contract_id", "contract_id"),
         ("maintenance_obligation_id", "maintenance_obligation_id"),
         ("advance_payment_id", "advance_payment_id"),
         ("payment_request_id", "payment_request_id"),
         ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.demand(d) for d in page], meta)


@bp.post("/eqip/recoupment-demands/<did>/pay")
@require_roles("Applicant")
def pay_demand(did, _uid, _role):
    d = get_demand(did)
    contract = get_contract(d["contract_id"])
    check_owner(contract["applicant_id"], _uid)
    if d["status"] not in ("DEMANDED", "ESCALATED"):
        raise ApiError(
            "ERR_DEMAND_NOT_PAYABLE", 409,
            "pay requires DEMANDED or ESCALATED",
        )
    data = body()
    amount = as_int(req_field(data, "amount_cents"), "amount_cents")
    if amount != d["amount_cents"]:
        raise ApiError(
            "ERR_REPAYMENT_AMOUNT_MISMATCH", 422,
            "amount_cents must equal the demand's amount_cents exactly",
        )
    d["status"] = "PAID"
    touch(d)
    pool = STORE.pools.get(contract["pool_id"])
    if pool is not None:
        pool["paid_cents"] -= amount
        touch(pool)
    # Advance-sourced demand: the payment closes the advance out.
    if d["advance_payment_id"] is not None:
        adv = STORE.advances.get(d["advance_payment_id"])
        if adv is not None:
            adv["returned_cents"] += amount
            adv["outstanding_cents"] = (
                adv["issued_cents"] - adv["applied_cents"] - adv["returned_cents"]
            )
            adv["status"] = "CLOSED"
            touch(adv)
    # Linked item leaves RECOUPMENT_PENDING for its terminal RECOUPED state.
    item_id = None
    if d["payment_request_id"] is not None:
        req_row = STORE.payment_requests.get(d["payment_request_id"])
        if req_row is not None:
            item_id = req_row["practice_item_id"]
    elif d["maintenance_obligation_id"] is not None:
        ob = STORE.obligations.get(d["maintenance_obligation_id"])
        if ob is not None:
            item_id = ob["practice_item_id"]
    elif d["advance_payment_id"] is not None:
        adv = STORE.advances.get(d["advance_payment_id"])
        if adv is not None:
            item_id = adv["practice_item_id"]
    if item_id is not None:
        item = STORE.items.get(item_id)
        if item is not None and item["payment_status"] == "RECOUPMENT_PENDING":
            item["payment_status"] = "RECOUPED"
            touch(item)
    return ok(serializers.demand(d))
