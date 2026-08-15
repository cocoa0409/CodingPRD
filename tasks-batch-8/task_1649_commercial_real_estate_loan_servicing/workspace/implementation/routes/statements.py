from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import covenants
from services.common import is_full_quarter, parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import assessment as ser_assessment, statement as ser_stmt
from services.validate import body_json, opt_int, opt_number, require_fields, req_enum, req_str

bp = Blueprint("statements", __name__)

STMT_TYPES = ("RENT_ROLL", "OPERATING_STATEMENT")


def _due_date(stmt_type, period_end):
    from datetime import timedelta
    offset = 15 if stmt_type == "RENT_ROLL" else 45
    return period_end + timedelta(days=offset)


@bp.post("/loans/<lid>/financial-statements")
def create_statement(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    mw.require_borrower_ownership(actor, "loan", loan)
    data = body_json()
    require_fields(data, ["statement_type", "period_start", "period_end"])
    stmt_type = req_enum(data, "statement_type", STMT_TYPES)
    period_start = parse_dt(data.get("period_start"), "period_start")
    period_end = parse_dt(data.get("period_end"), "period_end")
    if period_end < period_start:
        raise errors.invalid_request("period_end must not precede period_start")
    noi = None
    occ = None
    if stmt_type == "OPERATING_STATEMENT":
        if "net_operating_income_cents" not in data or data["net_operating_income_cents"] is None:
            raise errors.invalid_request("net_operating_income_cents required for OPERATING_STATEMENT")
        noi = req_int_stmt(data, "net_operating_income_cents")
    else:
        if "occupancy_pct" not in data or data["occupancy_pct"] is None:
            raise errors.invalid_request("occupancy_pct required for RENT_ROLL")
        occ = opt_number(data, "occupancy_pct", minimum=0, maximum=100)
    # Duplicate-period rule (priority 17) precedes alignment (priority 18).
    for s in db.financial_statements.values():
        if (
            s["loan_id"] == lid
            and s["statement_type"] == stmt_type
            and s["status"] in ("SUBMITTED", "ACCEPTED")
            and s["period_start_dt"].date() == period_start.date()
            and s["period_end_dt"].date() == period_end.date()
        ):
            raise errors.ApiError(
                errors.ERR_DUPLICATE_STATEMENT_PERIOD,
                "A SUBMITTED/ACCEPTED statement already exists for this loan, type, and period",
                409,
            )
    if not is_full_quarter(period_start, period_end):
        raise errors.ApiError(
            errors.ERR_STATEMENT_PERIOD_MISALIGNED,
            "Statement period must equal a full calendar quarter", 422)
    due = _due_date(stmt_type, period_end)
    stmt = {
        "id": db.new_id(),
        "loan_id": lid,
        "statement_type": stmt_type,
        "period_start": db.fmt_ts(period_start),
        "period_start_dt": period_start,
        "period_end": db.fmt_ts(period_end),
        "period_end_dt": period_end,
        "net_operating_income_cents": noi,
        "occupancy_pct": occ,
        "due_date": db.fmt_ts(due),
        "due_date_dt": due,
        "submitted_late": db.get_clock() > due,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "reviewed_by_user_id": None,
    }
    stamp_new(stmt)
    db.financial_statements[stmt["id"]] = stmt
    return success(ser_stmt(stmt), status=201)


def req_int_stmt(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"{field} must be an integer")
    return v


@bp.get("/loans/<lid>/financial-statements")
def list_statements(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [s for s in db.financial_statements.values() if s["loan_id"] == lid]
    st = request.args.get("statement_type")
    status = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["statement_type"] == st]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]), reverse=True)
    page, pg = paginate([ser_stmt(s) for s in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.get("/financial-statements/<sid>")
def get_statement(sid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    s = db.financial_statements.get(sid)
    if not mw.read_scope_allows(actor, "statement", s):
        raise errors.not_found("FinancialStatement not found")
    return success(ser_stmt(s))


@bp.post("/financial-statements/<sid>/review")
def review_statement(sid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    s = db.financial_statements.get(sid)
    if s is None:
        raise errors.not_found("FinancialStatement not found")
    data = body_json()
    require_fields(data, ["decision"])
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    rejection_reason = data.get("rejection_reason")
    if decision == "REJECT":
        if not isinstance(rejection_reason, str) or not rejection_reason:
            raise errors.invalid_request("rejection_reason is required when decision is REJECT")
    # Generic state precondition (7) precedes already-reviewed (8) semantically, but the
    # scaffold assigns ERR_STATEMENT_ALREADY_REVIEWED to non-SUBMITTED reviews.
    if s["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_STATEMENT_ALREADY_REVIEWED,
            "Statement has already been reviewed", 409)
    loan = db.loans.get(s["loan_id"])
    if decision == "ACCEPT":
        s["status"] = "ACCEPTED"
        s["reviewed_by_user_id"] = actor["user_id"]
        touch(s)
        if s["statement_type"] == "OPERATING_STATEMENT":
            covenants.run_dscr_assessment(loan, s)
    else:
        s["status"] = "REJECTED"
        s["reviewed_by_user_id"] = actor["user_id"]
        s["rejection_reason"] = rejection_reason
        touch(s)
    return success(ser_stmt(s))


@bp.get("/financial-statements/<sid>/covenant-assessments")
def statement_assessments(sid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    s = db.financial_statements.get(sid)
    if not mw.read_scope_allows(actor, "statement", s):
        raise errors.not_found("FinancialStatement not found")
    limit, offset = get_pagination()
    items = [a for a in db.covenant_assessments.values() if a.get("statement_id") == sid]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, pg = paginate([ser_assessment(a) for a in items], limit, offset)
    return success(page, pagination=pg, is_array=True)
