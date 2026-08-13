"""PaymentRequest pipeline: create, review, approve, reject, disburse."""
from datetime import timedelta

from flask import Blueprint

import serializers
from db import STORE, new_id, now
from errors import ApiError
from helpers import (
    apply_filters, as_int, as_list, body, get_contract, get_item,
    get_request, paginate, req_field, sorted_created, stamp_new, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list
from services import calc, ledger

bp = Blueprint("payment_requests", __name__)

ACTIVE_REQUEST_STATES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DISBURSED")


@bp.post("/eqip/payment-requests")
@require_roles("Applicant")
def create_payment_request(_uid, _role):
    data = body()
    contract_id = req_field(data, "contract_id")
    item_id = req_field(data, "practice_item_id")
    contract = get_contract(contract_id)
    item = get_item(item_id)
    if item["contract_id"] != contract["id"]:
        raise ApiError(
            "ERR_PRACTICE_ITEM_NOT_FOUND", 404,
            "practice item does not belong to the referenced contract",
        )
    check_owner(contract["applicant_id"], _uid)
    if item["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_ITEM_NOT_CERTIFIED", 409, "payment request requires item CERTIFIED")
    if contract["status"] != "OBLIGATED":
        raise ApiError(
            "ERR_CONTRACT_NOT_PAYABLE", 409,
            "payment request requires contract OBLIGATED",
        )
    documented = req_field(data, "documented_cost_cents")
    documented = as_int(documented, "documented_cost_cents")
    if documented < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "documented_cost_cents must be >= 1")
    refs = as_list(req_field(data, "documentation_refs"), "documentation_refs")
    if len(refs) == 0:
        raise ApiError(
            "ERR_DOCUMENTATION_INCOMPLETE", 422,
            "documentation_refs must contain at least one reference",
        )
    for r in STORE.payment_requests.values():
        if r["practice_item_id"] == item["id"] and r["status"] in ACTIVE_REQUEST_STATES:
            raise ApiError(
                "ERR_PAYMENT_REQUEST_ACTIVE", 409,
                "the item already has a payment request in flight",
            )
    program = STORE.programs[contract["program_id"]]
    seq = 1 + sum(1 for r in STORE.payment_requests.values()
                  if r["program_id"] == program["id"])
    sampled = (seq % program["spot_check_modulus"]) == 0
    computed = calc.certified_payment_cents(item, documented)
    r = {
        "id": new_id(),
        "program_id": contract["program_id"],
        "contract_id": contract["id"],
        "practice_item_id": item["id"],
        "documented_cost_cents": documented,
        "documentation_refs": list(refs),
        "sequence_number": seq,
        "sampled": sampled,
        "computed_amount_cents": computed,
        "advance_offset_cents": 0,
        "disbursed_amount_cents": 0,
        "reviewed_by_user_id": None,
        "status": "SUBMITTED",
    }
    stamp_new(r)
    STORE.payment_requests[r["id"]] = r
    return ok(serializers.payment_request(r), 201)


@bp.get("/eqip/payment-requests/<rid>")
@require_roles(*ANY_ROLE)
def get_one_request(rid, _uid, _role):
    return ok(serializers.payment_request(get_request(rid)))


@bp.get("/eqip/payment-requests")
@require_roles(*ANY_ROLE)
def list_requests(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.payment_requests.values()),
        [("program_id", "program_id"), ("contract_id", "contract_id"),
         ("practice_item_id", "practice_item_id"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.payment_request(r) for r in page], meta)


@bp.post("/eqip/payment-requests/<rid>/review")
@require_roles("PaymentOfficer")
def review_request(rid, _uid, _role):
    r = get_request(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_REQUEST_NOT_SUBMITTED", 409, "review requires status SUBMITTED")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return ok(serializers.payment_request(r))


@bp.post("/eqip/payment-requests/<rid>/approve")
@require_roles("PaymentOfficer")
def approve_request(rid, _uid, _role):
    r = get_request(rid)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_UNDER_REVIEW", 409, "approve requires status UNDER_REVIEW")
    item = STORE.items.get(r["practice_item_id"])
    if item is not None and item.get("certified_by_user_id") is not None \
            and item["certified_by_user_id"] == _uid:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "the payment approver must differ from the certifying planner",
        )
    r["reviewed_by_user_id"] = _uid
    r["status"] = "APPROVED"
    touch(r)
    return ok(serializers.payment_request(r))


@bp.post("/eqip/payment-requests/<rid>/reject")
@require_roles("PaymentOfficer")
def reject_request(rid, _uid, _role):
    r = get_request(rid)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_UNDER_REVIEW", 409, "reject requires status UNDER_REVIEW")
    r["status"] = "REJECTED"
    touch(r)
    return ok(serializers.payment_request(r))


@bp.post("/eqip/payment-requests/<rid>/disburse")
@require_roles("PaymentOfficer")
def disburse_request(rid, _uid, _role):
    r = get_request(rid)
    if r["status"] != "APPROVED":
        raise ApiError("ERR_REQUEST_NOT_APPROVED", 409, "disburse requires status APPROVED")
    item = STORE.items[r["practice_item_id"]]
    contract = STORE.contracts[r["contract_id"]]
    if r["sampled"]:
        passed = any(
            s["payment_request_id"] == r["id"] and s["status"] == "PASSED"
            for s in STORE.spot_checks.values()
        )
        if not passed:
            raise ApiError(
                "ERR_SPOT_CHECK_REQUIRED", 409,
                "a sampled request requires a linked PASSED spot check before disbursement",
            )
    if now() > item["certified_at"] + timedelta(days=365):
        raise ApiError(
            "ERR_CERTIFICATION_STALE", 409,
            "disbursement is more than 365 days after certification",
        )
    # Pinned order: computed amount -> advance offset -> cash movement.
    computed = r["computed_amount_cents"]
    adv = ledger.advance_for_item(item["id"])
    outstanding = adv["outstanding_cents"] if adv is not None else 0
    offset = min(computed, outstanding) if outstanding > 0 else 0
    disbursed = max(0, computed - offset)
    r["advance_offset_cents"] = offset
    r["disbursed_amount_cents"] = disbursed

    pool = STORE.pools[contract["pool_id"]]
    # Release the item's remaining obligation (scheduled less the advance
    # amount already moved to paid at issuance); only the new cash hits paid.
    held = item.get("_held_cents", 0)
    if held:
        pool["obligated_cents"] -= held
        item["_held_cents"] = 0
    pool["paid_cents"] += disbursed
    touch(pool)

    if adv is not None and offset > 0:
        adv["applied_cents"] += offset
        adv["outstanding_cents"] = adv["issued_cents"] - adv["applied_cents"] - adv["returned_cents"]
        if adv["status"] in ("ISSUED", "RETURN_DUE"):
            if adv["outstanding_cents"] == 0:
                adv["status"] = "CLOSED"
            else:
                adv["status"] = "RETURN_DUE"
                adv["expenditure_due_date"] = now()
        elif adv["outstanding_cents"] == 0:
            adv["status"] = "CLOSED"
        touch(adv)

    item["payment_status"] = "PAID"
    item["paid_amount_cents"] = computed
    touch(item)
    contract["paid_amount_cents"] += computed
    touch(contract)
    r["status"] = "DISBURSED"
    touch(r)
    return ok(serializers.payment_request(r))
