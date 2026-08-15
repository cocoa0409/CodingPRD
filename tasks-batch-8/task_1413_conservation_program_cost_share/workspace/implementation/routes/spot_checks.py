"""SpotCheck: open, read, list, record-result (PASS / FAIL + revocation cascade)."""
from flask import Blueprint

import serializers
from db import STORE, new_id
from errors import ApiError
from helpers import (
    apply_filters, as_enum, body, get_contract, get_item, get_request,
    get_spot_check, paginate, req_field, sorted_created, stamp_new, touch,
)
from middleware import ANY_ROLE, require_roles
from response import ok, ok_list
from services import ledger

bp = Blueprint("spot_checks", __name__)


@bp.post("/eqip/spot-checks")
@require_roles("QualityAssuranceOfficer")
def create_spot_check(_uid, _role):
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
    request_id = data.get("payment_request_id")
    req_row = None
    if request_id is not None:
        req_row = get_request(request_id)
        if req_row["practice_item_id"] != item["id"]:
            raise ApiError(
                "ERR_PAYMENT_REQUEST_NOT_FOUND", 404,
                "payment request does not belong to the referenced item",
            )
    if item["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_ITEM_NOT_CERTIFIED", 409, "spot check requires item CERTIFIED")
    s = {
        "id": new_id(),
        "contract_id": contract["id"],
        "practice_item_id": item["id"],
        "payment_request_id": req_row["id"] if req_row is not None else None,
        "inspector_user_id": _uid,
        "failure_reason": None,
        "status": "PENDING",
    }
    stamp_new(s)
    STORE.spot_checks[s["id"]] = s
    return ok(serializers.spot_check(s), 201)


@bp.get("/eqip/spot-checks/<sid>")
@require_roles(*ANY_ROLE)
def get_one_spot_check(sid, _uid, _role):
    return ok(serializers.spot_check(get_spot_check(sid)))


@bp.get("/eqip/spot-checks")
@require_roles(*ANY_ROLE)
def list_spot_checks(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.spot_checks.values()),
        [("contract_id", "contract_id"), ("practice_item_id", "practice_item_id"),
         ("payment_request_id", "payment_request_id"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.spot_check(s) for s in page], meta)


@bp.post("/eqip/spot-checks/<sid>/record-result")
@require_roles("QualityAssuranceOfficer")
def record_result(sid, _uid, _role):
    s = get_spot_check(sid)
    if s["status"] != "PENDING":
        raise ApiError("ERR_SPOT_CHECK_NOT_PENDING", 409, "the spot check is not PENDING")
    if s["inspector_user_id"] != _uid:
        raise ApiError(
            "ERR_INSPECTOR_MISMATCH", 403,
            "only the officer who opened the check may record its result",
        )
    item = STORE.items.get(s["practice_item_id"])
    if item is not None and item.get("certified_by_user_id") is not None \
            and item["certified_by_user_id"] == _uid:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "the spot-check recorder must differ from the certifying planner",
        )
    data = body()
    result = as_enum(req_field(data, "result"), "result", {"PASS", "FAIL"})
    if result == "PASS":
        s["status"] = "PASSED"
        touch(s)
        return ok(serializers.spot_check(s))

    # FAIL requires a reason.
    reason = req_field(data, "failure_reason")
    if not isinstance(reason, str) or not reason:
        raise ApiError("ERR_INVALID_REQUEST", 400, "failure_reason is required when result is FAIL")
    s["failure_reason"] = reason
    s["status"] = "FAILED"
    touch(s)

    # Revocation cascade only fires when the linked request is already DISBURSED.
    req_row = None
    if s["payment_request_id"] is not None:
        req_row = STORE.payment_requests.get(s["payment_request_id"])
    if req_row is not None and req_row["status"] == "DISBURSED" and item is not None:
        # hop 1: request DISBURSED -> REVOKED
        req_row["status"] = "REVOKED"
        touch(req_row)
        # hop 2: item CERTIFIED -> CERTIFICATION_REVOKED, PAID -> RECOUPMENT_PENDING
        if item["certification_status"] == "CERTIFIED":
            item["certification_status"] = "CERTIFICATION_REVOKED"
        if item["payment_status"] == "PAID":
            item["payment_status"] = "RECOUPMENT_PENDING"
        touch(item)
        # hop 3: the item's ACTIVE maintenance obligation -> VOID
        for ob in STORE.obligations.values():
            if ob["practice_item_id"] == item["id"] and ob["status"] == "ACTIVE":
                ob["status"] = "VOID"
                touch(ob)
        # hop 4: recoupment demand for the request's full computed amount.
        # Pool funds are NOT restored until the demand is paid.
        ledger.create_demand(
            contract_id=req_row["contract_id"],
            amount_cents=req_row["computed_amount_cents"],
            payment_request_id=req_row["id"],
        )
    return ok(serializers.spot_check(s))
