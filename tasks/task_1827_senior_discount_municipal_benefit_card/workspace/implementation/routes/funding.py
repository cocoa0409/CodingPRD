from flask import Blueprint

import clock
import services
import store
from auth import authenticate, authorize, require_merchant_self
from errors import (
    ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_PERIOD_NOT_CLOSED,
    ERR_CLAIM_NOT_FOUND,
    ERR_DUPLICATE_FISCAL_YEAR,
    ERR_DUPLICATE_PENDING_CLAIM,
    ERR_FUND_INSUFFICIENT,
    ERR_FUND_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MERCHANT_MONTHLY_CAP_EXCEEDED,
    ERR_MERCHANT_NOT_ACTIVE,
    ERR_MERCHANT_NOT_FOUND,
    ERR_NO_FUND_FOR_PERIOD,
    raise_err,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_enum_query,
    req_int,
    req_str,
    success_object,
    valid_year_month,
)

bp = Blueprint("funding", __name__)

CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")


# ---------------------------------------------------------------------------
# program funds
# ---------------------------------------------------------------------------
@bp.route("/program-funds", methods=["POST"])
def create_fund():
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    body = body_json()
    fiscal_year = req_int(body, "fiscal_year")
    allocated = req_int(body, "allocated_cents")
    if allocated <= 0:
        raise_err(ERR_INVALID_REQUEST, "allocated_cents must be > 0")
    for f in store.funds.values():
        if f["fiscal_year"] == fiscal_year:
            raise_err(ERR_DUPLICATE_FISCAL_YEAR,
                      "A ProgramFund already exists for fiscal_year %s" % fiscal_year)
    rec = new_record()
    rec.update({
        "fiscal_year": fiscal_year,
        "allocated_cents": allocated,
        "paid_cents": 0,
    })
    store.funds[rec["id"]] = rec
    return success_object(services.fund_out(rec), 201)


@bp.route("/program-funds/<rid>", methods=["GET"])
def get_fund(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator", "FraudAnalyst"])
    rec = get_or_404(store.funds, rid, ERR_FUND_NOT_FOUND, "ProgramFund")
    return success_object(services.fund_out(rec))


# ---------------------------------------------------------------------------
# reimbursement claims
# ---------------------------------------------------------------------------
@bp.route("/merchants/<rid>/reimbursement-claims", methods=["POST"])
def file_claim(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator"])
    merchant = get_or_404(store.merchants, rid, ERR_MERCHANT_NOT_FOUND, "Merchant")
    if merchant["status"] != "ACTIVE":
        raise_err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    require_merchant_self(uid, rid)
    body = body_json()
    period = req_str(body, "period_month")
    if not valid_year_month(period):
        raise_err(ERR_INVALID_REQUEST, "period_month must be in YYYY-MM form")
    today = clock.today()
    if (int(period[:4]), int(period[5:7])) >= (today.year, today.month):
        raise_err(ERR_CLAIM_PERIOD_NOT_CLOSED,
                  "period_month must be strictly before the current month")
    for c in store.claims.values():
        if (c["merchant_id"] == merchant["id"] and c["period_month"] == period
                and c["status"] in ("SUBMITTED", "APPROVED")):
            raise_err(ERR_DUPLICATE_PENDING_CLAIM,
                      "A non-denied claim already exists for this period")
    provisional = services.claim_amount_cents(merchant, period, ("POSTED", "FLAGGED"))
    rec = new_record()
    rec.update({
        "merchant_id": merchant["id"],
        "period_month": period,
        "program_fund_id": None,
        "provisional_amount_cents": provisional,
        "final_amount_cents": None,
        "status": "SUBMITTED",
        "denial_reason": None,
    })
    store.claims[rec["id"]] = rec
    return success_object(services.claim_out(rec), 201)


@bp.route("/merchants/<rid>/reimbursement-claims", methods=["GET"])
def list_claims(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator", "ProgramAdministrator", "FraudAnalyst"])
    merchant = get_or_404(store.merchants, rid, ERR_MERCHANT_NOT_FOUND, "Merchant")
    if role == "MerchantOperator":
        require_merchant_self(uid, rid)
    status = opt_enum_query("status", CLAIM_STATUSES)
    items = [c for c in store.claims.values() if c["merchant_id"] == merchant["id"]]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, services.claim_out)


@bp.route("/reimbursement-claims/<rid>/approve", methods=["POST"])
def approve_claim(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    rec = get_or_404(store.claims, rid, ERR_CLAIM_NOT_FOUND, "ReimbursementClaim")
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_SUBMITTED, "Claim is not SUBMITTED")
    merchant = store.merchants.get(rec["merchant_id"])
    fiscal_year = int(rec["period_month"][:4])
    fund = next((f for f in store.funds.values()
                 if f["fiscal_year"] == fiscal_year), None)
    if fund is None:
        raise_err(ERR_NO_FUND_FOR_PERIOD,
                  "No ProgramFund for fiscal_year %d" % fiscal_year)
    final = services.claim_amount_cents(merchant, rec["period_month"], ("POSTED",))
    available = fund["allocated_cents"] - fund["paid_cents"]
    if final > available:
        raise_err(ERR_FUND_INSUFFICIENT,
                  "Claim final amount exceeds the fund's available_cents")
    month_total = sum(c["final_amount_cents"] or 0 for c in store.claims.values()
                      if c["merchant_id"] == merchant["id"]
                      and c["period_month"] == rec["period_month"]
                      and c["status"] == "APPROVED" and c["id"] != rec["id"])
    if month_total + final > merchant["monthly_reimbursement_cap_cents"]:
        raise_err(ERR_MERCHANT_MONTHLY_CAP_EXCEEDED,
                  "Approval would exceed the merchant's monthly reimbursement cap")
    rec["final_amount_cents"] = final
    rec["program_fund_id"] = fund["id"]
    rec["status"] = "APPROVED"
    bump(rec)
    fund["paid_cents"] += final
    bump(fund)
    return success_object(services.claim_out(rec))


@bp.route("/reimbursement-claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    rec = get_or_404(store.claims, rid, ERR_CLAIM_NOT_FOUND, "ReimbursementClaim")
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_SUBMITTED, "Claim is not SUBMITTED")
    body = body_json()
    reason = req_str(body, "reason")
    rec["status"] = "DENIED"
    rec["denial_reason"] = reason
    bump(rec)
    return success_object(services.claim_out(rec))
