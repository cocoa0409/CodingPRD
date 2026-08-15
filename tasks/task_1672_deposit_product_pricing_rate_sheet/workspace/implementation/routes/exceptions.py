"""ExceptionPricingRequest endpoints (PRD 3.6)."""

from flask import Blueprint, g

from db import STORE
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_BASELINE_SHEET_NOT_EFFECTIVE,
    ERR_EXCEPTION_AUTHORITY_INSUFFICIENT,
    ERR_EXCEPTION_DELTA_EXCEEDS_MAX,
    ERR_EXCEPTION_DOCS_MISSING,
    ERR_EXCEPTION_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SHEET_NOT_FOUND,
    bad_request,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.rates import recompute_account_rates, tiered_rate
from utils import (
    add_days_iso,
    bump,
    opt_int,
    opt_str,
    req_int,
    req_str,
    stamp_new,
    today_iso,
)

bp = Blueprint("exceptions", __name__)

EXCEPTION_STATUSES = (
    "UNDER_REVIEW", "RETURNED", "REBASE_REQUIRED", "APPROVED",
    "APPLIED", "DECLINED", "REVOKED", "EXPIRED",
)
DECISIONS = ("APPROVE", "DECLINE", "RETURN", "REVOKE")


def _get_or_404(exc_id):
    row = STORE["exceptions"].get(exc_id)
    if row is None:
        raise not_found("Exception pricing request not found")
    return row


def _authority_tier(delta_bp):
    return "BRANCH" if delta_bp <= 25 else "COMMITTEE"


def _current_effective_sheet(product_id, market_code):
    for s in STORE["sheets"].values():
        if (s["product_id"] == product_id and s["market_code"] == market_code
                and s["status"] == "EFFECTIVE"):
            return s
    return None


@bp.post("/exception-pricing-requests")
@require_roles("BranchBanker")
def create_exception():
    data = get_body()
    account_id = req_str(data, "account_id")
    sheet_id = req_str(data, "sheet_id")
    requested_rate_bp = req_int(data, "requested_rate_bp", minimum=0)
    term_days = req_int(data, "term_days", minimum=1)
    justification = opt_str(data, "justification_doc_ref", None)
    account = STORE["accounts"].get(account_id)
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 422, "Referenced account_id does not exist")
    sheet = STORE["sheets"].get(sheet_id)
    if sheet is None:
        raise ApiError(ERR_SHEET_NOT_FOUND, 422, "Referenced sheet_id does not exist")
    product = STORE["products"][account["product_id"]]
    # Business order (PRD 2.10): permission, docs, baseline effectiveness, ceiling.
    if not product["allows_exceptions"]:
        raise bad_request("Product does not allow exception pricing")
    baseline = tiered_rate(product, sheet["tiers"], account["balance_cents"])
    delta = requested_rate_bp - baseline
    tier = _authority_tier(delta)
    if tier == "COMMITTEE" and not justification:
        raise ApiError(ERR_EXCEPTION_DOCS_MISSING, 422,
                       "justification_doc_ref is mandatory for COMMITTEE-tier requests")
    if sheet["status"] != "EFFECTIVE":
        raise ApiError(ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422,
                       "Baseline sheet is not EFFECTIVE")
    if delta > 75:
        raise ApiError(ERR_EXCEPTION_DELTA_EXCEEDS_MAX, 422,
                       "delta_bp exceeds the 75 bp ceiling")
    row = {
        "account_id": account_id,
        "sheet_id": sheet_id,
        "requested_rate_bp": requested_rate_bp,
        "baseline_rate_bp": baseline,
        "delta_bp": delta,
        "authority_tier": tier,
        "term_days": term_days,
        "justification_doc_ref": justification,
        "submitted_by_user_id": g.user_id,
        "decided_by_user_id": None,
        "status": "UNDER_REVIEW",
        "_decided_date": None,
    }
    stamp_new(row)
    STORE["exceptions"][row["id"]] = row
    return ok_object(serialize("exceptions", row), 201)


@bp.get("/exception-pricing-requests")
@require_roles("BranchBanker", "PricingCommittee", "ComplianceOfficer")
def list_exceptions():
    from flask import request
    account_id = request.args.get("account_id")
    sheet_id = request.args.get("sheet_id")
    status = query_enum("status", EXCEPTION_STATUSES)
    rows = list(STORE["exceptions"].values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if sheet_id is not None:
        rows = [r for r in rows if r["sheet_id"] == sheet_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("exceptions", rows))


@bp.get("/exception-pricing-requests/<exc_id>")
@require_roles("BranchBanker", "PricingCommittee", "ComplianceOfficer")
def get_exception(exc_id):
    return ok_object(serialize("exceptions", _get_or_404(exc_id)))


@bp.post("/exception-pricing-requests/<exc_id>/decision")
@require_roles("BranchBanker", "PricingCommittee")
def decide_exception(exc_id):
    data = get_body()
    decision = req_str(data, "decision")
    if decision not in DECISIONS:
        raise bad_request("decision must be APPROVE, DECLINE, RETURN, or REVOKE")
    exc = _get_or_404(exc_id)
    if decision == "REVOKE":
        if exc["status"] != "APPLIED":
            raise ApiError(ERR_EXCEPTION_INVALID_STATE, 409,
                           f"Cannot REVOKE a request in {exc['status']}")
        if g.user_role != "PricingCommittee":
            raise ApiError(ERR_EXCEPTION_AUTHORITY_INSUFFICIENT, 403,
                           "Revocation is a PricingCommittee prerogative")
        # Compensation: restore the account to sheet-derived pricing.
        account = STORE["accounts"].get(exc["account_id"])
        if account is not None and account["exception_request_id"] == exc["id"]:
            account["rate_source"] = "SHEET"
            account["exception_request_id"] = None
            account["exception_end_date"] = None
            account["exception_rate_bp"] = None
            recompute_account_rates(account)
            bump(account)
        exc["decided_by_user_id"] = g.user_id
        exc["status"] = "REVOKED"
        bump(exc)
        return ok_object(serialize("exceptions", exc))

    # APPROVE / DECLINE / RETURN from UNDER_REVIEW.
    if exc["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_EXCEPTION_INVALID_STATE, 409,
                       f"No {decision} decision possible from {exc['status']}")
    if g.user_id == exc["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The decider must differ from the submitter")
    if decision == "APPROVE":
        sheet = STORE["sheets"].get(exc["sheet_id"])
        if sheet is None or sheet["status"] != "EFFECTIVE":
            raise ApiError(ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422,
                           "Baseline sheet is not EFFECTIVE")
        if exc["authority_tier"] == "COMMITTEE" and g.user_role != "PricingCommittee":
            raise ApiError(ERR_EXCEPTION_AUTHORITY_INSUFFICIENT, 403,
                           "COMMITTEE-tier requests are the committee's alone")
        exc["status"] = "APPROVED"
        exc["_decided_date"] = today_iso()
    elif decision == "DECLINE":
        exc["status"] = "DECLINED"
    else:  # RETURN
        exc["status"] = "RETURNED"
    exc["decided_by_user_id"] = g.user_id
    bump(exc)
    return ok_object(serialize("exceptions", exc))


@bp.post("/exception-pricing-requests/<exc_id>/resubmit")
@require_roles("BranchBanker")
def resubmit_exception(exc_id):
    data = get_body()
    requested_rate_bp = opt_int(data, "requested_rate_bp", None, minimum=0)
    term_days = opt_int(data, "term_days", None, minimum=1)
    justification = opt_str(data, "justification_doc_ref", None)
    exc = _get_or_404(exc_id)
    if exc["status"] not in ("RETURNED", "REBASE_REQUIRED"):
        raise ApiError(ERR_EXCEPTION_INVALID_STATE, 409,
                       f"Cannot resubmit a request in {exc['status']}")
    if g.user_id != exc["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Only the original submitter may resubmit")
    account = STORE["accounts"].get(exc["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 422, "Referenced account_id does not exist")
    current = _current_effective_sheet(account["product_id"], account["market_code"])
    if current is None:
        raise ApiError(ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422,
                       "No EFFECTIVE sheet exists for the account's product+market")
    if requested_rate_bp is not None:
        exc["requested_rate_bp"] = requested_rate_bp
    if term_days is not None:
        exc["term_days"] = term_days
    if justification is not None:
        exc["justification_doc_ref"] = justification
    product = STORE["products"][account["product_id"]]
    baseline = tiered_rate(product, current["tiers"], account["balance_cents"])
    delta = exc["requested_rate_bp"] - baseline
    tier = _authority_tier(delta)
    # Resubmit checks (PRD 2.10): documentation completeness, then the ceiling.
    if tier == "COMMITTEE" and not exc["justification_doc_ref"]:
        raise ApiError(ERR_EXCEPTION_DOCS_MISSING, 422,
                       "justification_doc_ref is mandatory for COMMITTEE-tier requests")
    if delta > 75:
        raise ApiError(ERR_EXCEPTION_DELTA_EXCEEDS_MAX, 422,
                       "delta_bp exceeds the 75 bp ceiling")
    exc["baseline_rate_bp"] = baseline
    exc["delta_bp"] = delta
    exc["authority_tier"] = tier
    if exc["status"] == "RETURNED":
        exc["sheet_id"] = current["id"]
    exc["status"] = "UNDER_REVIEW"
    bump(exc)
    return ok_object(serialize("exceptions", exc))


@bp.post("/exception-pricing-requests/<exc_id>/apply")
@require_roles("BranchBanker")
def apply_exception(exc_id):
    get_body()
    exc = _get_or_404(exc_id)
    if exc["status"] != "APPROVED":
        raise ApiError(ERR_EXCEPTION_INVALID_STATE, 409,
                       f"Cannot apply a request in {exc['status']}")
    sheet = STORE["sheets"].get(exc["sheet_id"])
    if sheet is None or sheet["status"] != "EFFECTIVE":
        raise ApiError(ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422,
                       "Baseline sheet is not EFFECTIVE")
    account = STORE["accounts"].get(exc["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 422, "Referenced account_id does not exist")
    if account["lifecycle"] != "OPEN" or account["rate_source"] != "SHEET":
        raise ApiError("ERR_ACCOUNT_INVALID_STATE", 409,
                       "Account must be OPEN with rate_source SHEET")
    product = STORE["products"][account["product_id"]]
    if not product["allows_exceptions"]:
        raise bad_request("Product does not allow exception pricing")
    account["rate_source"] = "EXCEPTION"
    account["exception_request_id"] = exc["id"]
    account["exception_end_date"] = add_days_iso(today_iso(), exc["term_days"])
    account["exception_rate_bp"] = exc["requested_rate_bp"]
    recompute_account_rates(account)
    bump(account)
    exc["status"] = "APPLIED"
    bump(exc)
    return ok_object(serialize("exceptions", exc))
