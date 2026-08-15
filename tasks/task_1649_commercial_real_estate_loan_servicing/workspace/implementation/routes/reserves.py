from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services.common import stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import disbursement as ser_draw, reserve as ser_reserve
from services.validate import (
    body_json, opt_number, require_fields, req_enum, req_int,
)

bp = Blueprint("reserves", __name__)

ACCOUNT_TYPES = ("TI_LC", "REPLACEMENT")
PURPOSES = ("TENANT_IMPROVEMENT", "LEASING_COMMISSION", "CAPITAL_REPAIR")


@bp.post("/loans/<lid>/reserve-accounts")
def create_reserve(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    data = body_json()
    require_fields(data, ["account_type", "target_balance_cents"])
    atype = req_enum(data, "account_type", ACCOUNT_TYPES)
    target = req_int(data, "target_balance_cents", minimum=0)
    for r in db.reserve_accounts.values():
        if r["loan_id"] == lid and r["account_type"] == atype:
            raise errors.ApiError(
                errors.ERR_DUPLICATE_RESERVE_ACCOUNT,
                "A reserve account of this type already exists for the loan", 409)
    elevated = loan["servicing_status"] != "PERFORMING"
    frozen = loan["servicing_status"] == "SPECIAL_SERVICING"
    r = {
        "id": db.new_id(),
        "loan_id": lid,
        "account_type": atype,
        "balance_cents": 0,
        "held_cents": 0,
        "retained_cents": 0,
        "target_balance_cents": target,
        "elevated_retainage": elevated,
        "disbursement_frozen": frozen,
    }
    stamp_new(r)
    db.reserve_accounts[r["id"]] = r
    return success(ser_reserve(r), status=201)


@bp.get("/reserve-accounts/<rid>")
def get_reserve(rid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    r = db.reserve_accounts.get(rid)
    if not mw.read_scope_allows(actor, "reserve", r):
        raise errors.not_found("ReserveAccount not found")
    return success(ser_reserve(r))


@bp.get("/loans/<lid>/reserve-accounts")
def list_reserves(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [r for r in db.reserve_accounts.values() if r["loan_id"] == lid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, pg = paginate([ser_reserve(r) for r in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/reserve-accounts/<rid>/deposits")
def deposit(rid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "Borrower"])
    r = db.reserve_accounts.get(rid)
    if r is None:
        raise errors.not_found("ReserveAccount not found")
    if actor["role"] == "Borrower":
        mw.require_borrower_ownership(actor, "reserve", r)
    data = body_json()
    require_fields(data, ["amount_cents"])
    amount = req_int(data, "amount_cents", gt=0)
    r["balance_cents"] += amount
    touch(r)
    return success(ser_reserve(r), status=201)


@bp.post("/reserve-accounts/<rid>/disbursement-requests")
def create_draw(rid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    r = db.reserve_accounts.get(rid)
    if r is None:
        raise errors.not_found("ReserveAccount not found")
    mw.require_borrower_ownership(actor, "reserve", r)
    data = body_json()
    require_fields(data, ["purpose", "line_items", "expected_reserve_account_version"])
    purpose = req_enum(data, "purpose", PURPOSES)
    line_items = data.get("line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise errors.invalid_request("line_items must be a non-empty array")
    normalized = []
    for item in line_items:
        if not isinstance(item, dict):
            raise errors.invalid_request("each line item must be an object")
        desc = item.get("description")
        amt = item.get("amount_cents")
        if not isinstance(desc, str) or not desc:
            raise errors.invalid_request("line item description must be a non-empty string")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise errors.invalid_request("line item amount_cents must be a positive integer")
        normalized.append({"description": desc, "amount_cents": amt})
    retainage = opt_number(data, "retainage_pct", default=0.10, minimum=0, maximum=1)
    expected = data.get("expected_reserve_account_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_reserve_account_version must be an integer")
    # OCC check (priority 6)
    if expected != r["version"]:
        raise errors.stale_version("Reserve account version has advanced since last read")
    amount = sum(i["amount_cents"] for i in normalized)
    d = {
        "id": db.new_id(),
        "reserve_account_id": rid,
        "purpose": purpose,
        "line_items": normalized,
        "amount_cents": amount,
        "retainage_pct": retainage,
        "status": "SUBMITTED",
        "funded_cents": 0,
        "retained_cents": 0,
        "funded_at": None,
        "funded_at_dt": None,
    }
    stamp_new(d)
    db.disbursement_requests[d["id"]] = d
    touch(r)  # creating a draw advances the reserve's version
    return success(ser_draw(d), status=201)


@bp.get("/reserve-accounts/<rid>/disbursement-requests")
def list_draws(rid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    r = db.reserve_accounts.get(rid)
    if not mw.read_scope_allows(actor, "reserve", r):
        raise errors.not_found("ReserveAccount not found")
    limit, offset = get_pagination()
    items = [d for d in db.disbursement_requests.values() if d["reserve_account_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, pg = paginate([ser_draw(d) for d in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


def _load_draw(did):
    d = db.disbursement_requests.get(did)
    if d is None:
        raise errors.not_found("DisbursementRequest not found")
    return d, db.reserve_accounts.get(d["reserve_account_id"])


@bp.post("/disbursement-requests/<did>/review")
def review_draw(did):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    d, r = _load_draw(did)
    data = body_json()
    require_fields(data, ["decision"])
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    if d["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED request can be reviewed")
    if decision == "APPROVE":
        if r["disbursement_frozen"]:
            raise errors.ApiError(
                errors.ERR_RESERVE_DISBURSEMENTS_FROZEN,
                "Reserve disbursements are frozen under SPECIAL_SERVICING", 409)
        available = r["balance_cents"] - r["held_cents"]
        if d["amount_cents"] > available:
            raise errors.ApiError(
                errors.ERR_INSUFFICIENT_RESERVE_FUNDS,
                "amount_cents exceeds available_cents", 422)
        d["status"] = "APPROVED"
        touch(d)
        r["held_cents"] += d["amount_cents"]
        touch(r)
    else:
        d["status"] = "REJECTED"
        touch(d)
    return success(ser_draw(d))


@bp.post("/disbursement-requests/<did>/fund")
def fund_draw(did):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    d, r = _load_draw(did)
    if d["status"] != "APPROVED":
        raise errors.invalid_state("Only an APPROVED request can be funded")
    if r["disbursement_frozen"]:
        raise errors.ApiError(
            errors.ERR_RESERVE_DISBURSEMENTS_FROZEN,
            "Reserve disbursements are frozen under SPECIAL_SERVICING", 409)
    available = r["balance_cents"] - r["held_cents"]
    if d["amount_cents"] > available + d["amount_cents"]:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_RESERVE_FUNDS,
            "Reserve cash no longer covers outstanding holds", 422)
    effective = d["retainage_pct"]
    if r["elevated_retainage"]:
        effective = max(d["retainage_pct"], 0.20)
    eff_dec = Decimal(str(effective))
    funded = 0
    retained = 0
    for line in d["line_items"]:
        retain_i = int(
            (Decimal(line["amount_cents"]) * eff_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        retained += retain_i
        funded += line["amount_cents"] - retain_i
    d["status"] = "FUNDED"
    d["funded_cents"] = funded
    d["retained_cents"] = retained
    d["funded_at_dt"] = db.get_clock()
    d["funded_at"] = db.fmt_ts(db.get_clock())
    touch(d)
    r["held_cents"] -= d["amount_cents"]
    r["balance_cents"] -= funded
    r["retained_cents"] += retained
    touch(r)
    return success(ser_draw(d))


@bp.post("/disbursement-requests/<did>/cancel")
def cancel_draw(did):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    d, r = _load_draw(did)
    mw.require_borrower_ownership(actor, "disbursement", d)
    if d["status"] not in ("SUBMITTED", "APPROVED"):
        raise errors.invalid_state("Only SUBMITTED or APPROVED requests can be cancelled")
    was_approved = d["status"] == "APPROVED"
    d["status"] = "CANCELLED"
    touch(d)
    if was_approved:
        r["held_cents"] -= d["amount_cents"]
        touch(r)
    return success(ser_draw(d))


@bp.post("/disbursement-requests/<did>/release-retainage")
def release_retainage(did):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    d, r = _load_draw(did)
    if d["status"] != "FUNDED" or d["retained_cents"] <= 0:
        raise errors.invalid_state("Request must be FUNDED with positive retained_cents")
    loan = db.loans.get(r["loan_id"])
    ok = False
    for insp in db.inspections.values():
        prop = db.properties.get(insp["property_id"])
        if not prop or prop["loan_id"] != loan["id"]:
            continue
        if insp["status"] == "COMPLETED" and insp["completed_at_dt"] >= d["funded_at_dt"]:
            ok = True
            break
    if not ok:
        raise errors.ApiError(
            errors.ERR_RETAINAGE_RELEASE_BLOCKED,
            "No COMPLETED inspection on or after funded_at on the loan's properties", 409)
    amt = d["retained_cents"]
    r["balance_cents"] -= amt
    r["retained_cents"] -= amt
    d["retained_cents"] = 0
    touch(d)
    touch(r)
    return success(ser_draw(d))
