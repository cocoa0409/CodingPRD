"""AdvancePayment: read, list, return."""
from flask import Blueprint

import serializers
from db import STORE
from errors import ApiError
from helpers import (
    apply_filters, as_int, body, get_advance, get_contract,
    paginate, req_field, sorted_created, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list

bp = Blueprint("advances", __name__)


@bp.get("/eqip/advance-payments/<aid>")
@require_roles(*ANY_ROLE)
def get_one_advance(aid, _uid, _role):
    return ok(serializers.advance(get_advance(aid)))


@bp.get("/eqip/advance-payments")
@require_roles(*ANY_ROLE)
def list_advances(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.advances.values()),
        [("contract_id", "contract_id"), ("applicant_id", "applicant_id"),
         ("practice_item_id", "practice_item_id"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.advance(a) for a in page], meta)


@bp.post("/eqip/advance-payments/<aid>/return")
@require_roles("Applicant")
def return_advance(aid, _uid, _role):
    adv = get_advance(aid)
    check_owner(adv["applicant_id"], _uid)
    if adv["status"] not in ("ISSUED", "RETURN_DUE"):
        raise ApiError(
            "ERR_ADVANCE_NOT_RETURNABLE", 409,
            "return requires advance ISSUED or RETURN_DUE",
        )
    data = body()
    amount = as_int(req_field(data, "amount_cents"), "amount_cents")
    if amount != adv["outstanding_cents"]:
        raise ApiError(
            "ERR_RETURN_AMOUNT_MISMATCH", 422,
            "amount_cents must equal the advance's outstanding balance",
        )
    adv["returned_cents"] += amount
    adv["outstanding_cents"] = adv["issued_cents"] - adv["applied_cents"] - adv["returned_cents"]
    adv["status"] = "CLOSED"
    touch(adv)
    contract = get_contract(adv["contract_id"])
    pool = STORE.pools.get(contract["pool_id"])
    if pool is not None:
        pool["paid_cents"] -= amount
        pool["obligated_cents"] += amount
        touch(pool)
    # Track the returned funds as residual obligation held for the contract's
    # item, so that contract completion (or expiry/cancellation) can release
    # them back to available per PRD 3.8.
    item = STORE.items.get(adv["practice_item_id"])
    if item is not None:
        item["_held_cents"] = item.get("_held_cents", 0) + amount
        touch(item)
    return ok(serializers.advance(adv))
