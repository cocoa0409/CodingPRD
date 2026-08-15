from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_FEE_NOT_WAIVABLE, ERR_ACCOUNT_CLOSED,
                    ERR_OWNERSHIP, ERR_SELF_APPROVAL, ERR_FEE_STATE_CHANGED,
                    ERR_EXCEEDS_AUTHORITY, ERR_WAIVER_AMOUNT)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_int, v_enum, ALL_ROLES, sort_created)
from serializers import waiver_request_to_dict, waiver_item_to_dict
from services import (compute_allocation, routing_band, apply_waiver,
                      TELLER_CAP_CENTS, SUPERVISOR_CAP_CENTS, MANAGER_CAP_CENTS)

bp = Blueprint("waivers", __name__)

KINDS = ["FULL", "FIXED_AMOUNT", "PERCENT_BPS"]
REASON_CODES = ["HARDSHIP", "BANK_ERROR", "FIRST_TIME", "GOODWILL"]
PENDING_STATUSES = ("PENDING_SUPERVISOR", "PENDING_MANAGER", "PENDING_COMPLIANCE")

# Roles whose band authority covers each pending status.
BAND_APPROVERS = {
    "PENDING_SUPERVISOR": ("Supervisor", "Manager", "ComplianceOfficer"),
    "PENDING_MANAGER": ("Manager", "ComplianceOfficer"),
    "PENDING_COMPLIANCE": ("ComplianceOfficer",),
}


def get_request_or_404(wid):
    w = db.store["waiver_requests"].get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Waiver request %s not found" % wid)
    return w


@bp.post("/v1/fee-waiver-requests")
def create_waiver_request():
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller", "Supervisor", "Manager"])
    body = require_body()
    account_id = v_str(body, "account_id")
    fee_ids = body.get("fee_ids")
    if (not isinstance(fee_ids, list) or not fee_ids
            or any(not isinstance(x, str) for x in fee_ids)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "fee_ids must be a non-empty array of strings")
    kind = v_enum(body, "kind", KINDS)
    reason_code = v_enum(body, "reason_code", REASON_CODES)
    amount_cents = None
    percent_bps = None
    if kind == "FIXED_AMOUNT":
        amount_cents = v_int(body, "amount_cents")
    elif kind == "PERCENT_BPS":
        percent_bps = v_int(body, "percent_bps")
        if not (1 <= percent_bps <= 10000):
            raise ApiError(ERR_INVALID_REQUEST, 400, "percent_bps must be in 1..10000")
    # Tier 4: referenced ids exist (account first, then each fee in order).
    acct = db.store["accounts"].get(account_id)
    if acct is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Account %s not found" % account_id)
    fees = []
    for fid in fee_ids:
        f = db.store["fees"].get(fid)
        if f is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Fee %s not found" % fid)
        fees.append(f)
    # Tier 5: holder ownership.
    if role == "AccountHolder" and uid != account_id:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    # Tier 6: closed accounts block everything but recovery credits.
    if acct["status"] in ("CLOSED_VOLUNTARY", "CLOSED_CHARGEOFF"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    # Tier 7: every listed fee belongs to the account and is ASSESSED/POSTED.
    for f in fees:
        if f["account_id"] != account_id or f["status"] not in ("ASSESSED", "POSTED"):
            raise ApiError(ERR_FEE_NOT_WAIVABLE, 409,
                           "Fee %s is not waivable for this account" % f["id"])
    # Tier 12: FIXED_AMOUNT bounds.
    total_outstanding = sum(f["amount_cents"] - f["waived_cents"] for f in fees)
    if kind == "FIXED_AMOUNT" and (amount_cents <= 0 or amount_cents > total_outstanding):
        raise ApiError(ERR_WAIVER_AMOUNT, 422,
                       "amount_cents must be positive and not exceed listed outstanding")
    # Allocation drives routing (computed_total_cents, routing_band).
    allocs, total = compute_allocation(kind, amount_cents, percent_bps, fees)
    band = routing_band(total)
    staff = role in ("Teller", "Supervisor", "Manager")
    if staff and total <= TELLER_CAP_CENTS:
        status = "APPLIED"
    elif total <= SUPERVISOR_CAP_CENTS:
        status = "PENDING_SUPERVISOR"
    elif total <= MANAGER_CAP_CENTS:
        status = "PENDING_MANAGER"
    else:
        status = "PENDING_COMPLIANCE"
    wr = db.new_entity({
        "account_id": account_id,
        "fee_ids": list(fee_ids),
        "kind": kind,
        "amount_cents": amount_cents,
        "percent_bps": percent_bps,
        "reason_code": reason_code,
        "computed_total_cents": total,
        "routing_band": band,
        "status": status,
        "created_by_user_id": uid,
        "created_by_role": role,
        "decided_by_user_id": None,
        "denied_band": None,
    })
    db.store["waiver_requests"][wr["id"]] = wr
    for fid in fee_ids:
        item = db.new_item({
            "waiver_request_id": wr["id"],
            "fee_id": fid,
            "waived_cents": 0,
        })
        db.store["waiver_items"][item["id"]] = item
    if status == "APPLIED":
        apply_waiver(wr, decided_by=None)
    return ok(waiver_request_to_dict(wr), status=201)


@bp.get("/v1/fee-waiver-requests")
def list_waiver_requests():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["waiver_requests"].values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [w for w in items if w["account_id"] == account_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return ok_list([waiver_request_to_dict(w) for w in sort_created(items)])


@bp.get("/v1/fee-waiver-requests/<wid>")
def get_waiver_request(wid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(waiver_request_to_dict(get_request_or_404(wid)))


def _check_pending_and_guards(wr, uid, role, check_fees):
    """Shared guards for approve/deny: state -> self-decision -> [fee state] -> band.
    Fee-state revalidation (ERR_FEE_STATE_CHANGED) applies at approve only."""
    if wr["status"] not in PENDING_STATUSES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Request is not in a pending status")
    if uid == wr["created_by_user_id"]:
        raise ApiError(ERR_SELF_APPROVAL, 409,
                       "Approver/denier must differ from the request creator")
    if check_fees:
        for fid in wr["fee_ids"]:
            f = db.store["fees"].get(fid)
            if f is None or f["status"] not in ("ASSESSED", "POSTED"):
                raise ApiError(ERR_FEE_STATE_CHANGED, 409,
                               "A listed fee is no longer ASSESSED/POSTED")
    if role not in BAND_APPROVERS[wr["status"]]:
        raise ApiError(ERR_EXCEEDS_AUTHORITY, 409,
                       "Caller's authority band does not cover this request")


@bp.post("/v1/fee-waiver-requests/<wid>/approve")
def approve_waiver(wid):
    uid, role = auth()
    require_role(role, ["Supervisor", "Manager", "ComplianceOfficer"])
    wr = get_request_or_404(wid)
    _check_pending_and_guards(wr, uid, role, check_fees=True)
    apply_waiver(wr, decided_by=uid)
    wr["status"] = "APPLIED"
    db.touch(wr)
    return ok(waiver_request_to_dict(wr))


@bp.post("/v1/fee-waiver-requests/<wid>/deny")
def deny_waiver(wid):
    uid, role = auth()
    require_role(role, ["Supervisor", "Manager", "ComplianceOfficer"])
    wr = get_request_or_404(wid)
    _check_pending_and_guards(wr, uid, role, check_fees=False)
    if wr["status"] == "PENDING_SUPERVISOR":
        wr["status"] = "DENIED"
        wr["denied_band"] = "SUPERVISOR"
    elif wr["status"] == "PENDING_MANAGER":
        wr["status"] = "DENIED"
        wr["denied_band"] = "MANAGER"
    else:  # PENDING_COMPLIANCE
        wr["status"] = "DENIED_FINAL"
        wr["denied_band"] = "COMPLIANCE"
    wr["decided_by_user_id"] = uid
    db.touch(wr)
    return ok(waiver_request_to_dict(wr))


@bp.post("/v1/fee-waiver-requests/<wid>/escalate")
def escalate_waiver(wid):
    _, role = auth()
    require_role(role, ["Supervisor", "Manager"])
    wr = get_request_or_404(wid)
    if wr["status"] == "PENDING_SUPERVISOR":
        wr["status"] = "PENDING_MANAGER"
    elif wr["status"] == "PENDING_MANAGER":
        if role != "Manager":
            raise ApiError(ERR_EXCEEDS_AUTHORITY, 409,
                           "Only a Manager may escalate to compliance")
        wr["status"] = "PENDING_COMPLIANCE"
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a pending request can be escalated")
    db.touch(wr)
    return ok(waiver_request_to_dict(wr))


@bp.post("/v1/fee-waiver-requests/<wid>/appeal")
def appeal_waiver(wid):
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller", "Supervisor", "Manager"])
    wr = get_request_or_404(wid)
    if role == "AccountHolder" and uid != wr["account_id"]:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    if wr["status"] != "DENIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DENIED (non-final) request can be appealed")
    if wr["denied_band"] == "SUPERVISOR":
        wr["status"] = "PENDING_MANAGER"
    elif wr["denied_band"] == "MANAGER":
        wr["status"] = "PENDING_COMPLIANCE"
    else:
        raise ApiError(ERR_INVALID_STATE, 409, "Request cannot be appealed")
    db.touch(wr)
    return ok(waiver_request_to_dict(wr))


@bp.get("/v1/waiver-items")
def list_waiver_items():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["waiver_items"].values())
    waiver_request_id = request.args.get("waiver_request_id")
    fee_id = request.args.get("fee_id")
    if waiver_request_id is not None:
        items = [i for i in items if i["waiver_request_id"] == waiver_request_id]
    if fee_id is not None:
        items = [i for i in items if i["fee_id"] == fee_id]
    return ok_list([waiver_item_to_dict(i) for i in sort_created(items)])


@bp.get("/v1/waiver-items/<iid>")
def get_waiver_item(iid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    item = db.store["waiver_items"].get(iid)
    if item is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Waiver item %s not found" % iid)
    return ok(waiver_item_to_dict(item))
