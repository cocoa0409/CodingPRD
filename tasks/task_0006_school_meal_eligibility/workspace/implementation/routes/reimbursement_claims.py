"""ReimbursementClaim routes + aggregation."""
from datetime import timedelta
from flask import Blueprint, request
import db
from response import success_object, success_array, iso_utc, parse_iso_utc
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, bump_version, get_or_404, sort_by_created_at, paginate, clean,
)
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CLAIM_PERIOD_OVERLAP,
    ERR_PERIOD_NOT_SETTLED, raise_err,
)

bp = Blueprint("reimbursement_claims", __name__)


VALID_BASES = {"CASH", "ACCRUAL"}


@bp.post("/school-meals/reimbursement-claims")
def create_claim():
    require_role({"SchoolStaff"})
    body = get_json_body()
    enforce_keys(
        body,
        required={"school_code", "period_start_utc", "period_end_utc", "accounting_basis"},
        optional=set(),
    )
    require_str(body["school_code"], "school_code")
    require_str(body["period_start_utc"], "period_start_utc")
    require_str(body["period_end_utc"], "period_end_utc")
    require_str(body["accounting_basis"], "accounting_basis")
    if body["accounting_basis"] not in VALID_BASES:
        raise_err(ERR_INVALID_REQUEST, "accounting_basis must be CASH or ACCRUAL")
    try:
        ps = parse_iso_utc(body["period_start_utc"])
        pe = parse_iso_utc(body["period_end_utc"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "period_start_utc / period_end_utc must be ISO 8601 UTC")
    if not (ps <= pe):
        raise_err(ERR_INVALID_REQUEST, "period_start_utc must be <= period_end_utc")

    # Validation priority 7: no overlap with another claim for same school_code,
    # AND a 1-day gap between consecutive periods.
    for other in db.reimbursement_claims.values():
        if other["school_code"] != body["school_code"]:
            continue
        ops = other["_period_start_dt"]
        ope = other["_period_end_dt"]
        # Inclusive period intervals: overlap if ps <= ope AND ops <= pe.
        if ps <= ope and ops <= pe:
            raise_err(ERR_CLAIM_PERIOD_OVERLAP, "claim period overlaps existing claim")
        # Gap check: new period_start must be >= prior period_end + 1 day,
        #            OR new period_end must be <= prior period_start - 1 day.
        if ps > ope:
            if (ps - ope) < timedelta(days=1):
                raise_err(ERR_CLAIM_PERIOD_OVERLAP, "consecutive claim periods must be >=1 day apart")
        elif pe < ops:
            if (ops - pe) < timedelta(days=1):
                raise_err(ERR_CLAIM_PERIOD_OVERLAP, "consecutive claim periods must be >=1 day apart")

    rec = {
        **common_fields_init(),
        "school_code": body["school_code"],
        "period_start_utc": iso_utc(ps),
        "period_end_utc": iso_utc(pe),
        "_period_start_dt": ps,
        "_period_end_dt": pe,
        "status": "DRAFT",
        "accounting_basis": body["accounting_basis"],
        "total_reimbursement_cents": 0,
        "included_transaction_count": 0,
    }
    db.reimbursement_claims[rec["id"]] = rec
    return success_object(clean(rec), status=201)


@bp.get("/school-meals/reimbursement-claims/<cid>")
def read_claim(cid):
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.reimbursement_claims, cid, "ReimbursementClaim")
    return success_object(clean(rec))


@bp.get("/school-meals/reimbursement-claims")
def list_claims():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    school_code = request.args.get("school_code")
    status_f = request.args.get("status")
    items = list(db.reimbursement_claims.values())
    if school_code is not None:
        items = [c for c in items if c["school_code"] == school_code]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


def _txns_in_period(claim):
    """Return ServiceTransactions served at this school within the claim period (inclusive)."""
    ps = claim["_period_start_dt"]
    pe = claim["_period_end_dt"]
    school_code = claim["school_code"]
    out = []
    for t in db.service_transactions.values():
        s = db.students.get(t["student_id"])
        if s is None or s["school_code"] != school_code:
            continue
        served = t["_served_at_dt"]
        if ps <= served <= pe:
            out.append(t)
    return out


@bp.post("/school-meals/reimbursement-claims/<cid>/submit")
def submit_claim(cid):
    require_role({"SchoolStaff"})
    rec = get_or_404(db.reimbursement_claims, cid, "ReimbursementClaim")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"claim status is {rec['status']}, expected DRAFT")
    candidates = _txns_in_period(rec)
    for t in candidates:
        if t["status"] in ("PENDING", "DISPUTED"):
            raise_err(ERR_PERIOD_NOT_SETTLED, "claim period contains unsettled transactions")

    basis = rec["accounting_basis"]
    if basis == "CASH":
        included = [t for t in candidates if t["status"] == "SETTLED"]
    else:  # ACCRUAL
        included = [t for t in candidates if t["status"] in ("SETTLED", "DISPUTED", "REFUNDED")]

    total = sum(t["federal_reimbursement_cents"] for t in included)
    rec["total_reimbursement_cents"] = total
    rec["included_transaction_count"] = len(included)
    rec["status"] = "SUBMITTED"
    bump_version(rec)
    return success_object(clean(rec))


@bp.post("/school-meals/reimbursement-claims/<cid>/finalize")
def finalize_claim(cid):
    require_role({"USDAAuditor"})
    rec = get_or_404(db.reimbursement_claims, cid, "ReimbursementClaim")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"claim status is {rec['status']}, expected SUBMITTED")
    rec["status"] = "FINALIZED"
    bump_version(rec)
    return success_object(clean(rec))


@bp.post("/school-meals/reimbursement-claims/<cid>/reject")
def reject_claim(cid):
    require_role({"USDAAuditor"})
    rec = get_or_404(db.reimbursement_claims, cid, "ReimbursementClaim")
    body = get_json_body()
    enforce_keys(body, required={"rejection_reason"}, optional=set())
    require_str(body["rejection_reason"], "rejection_reason")
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"claim status is {rec['status']}, expected SUBMITTED")
    rec["status"] = "REJECTED"
    bump_version(rec)
    return success_object(clean(rec))
