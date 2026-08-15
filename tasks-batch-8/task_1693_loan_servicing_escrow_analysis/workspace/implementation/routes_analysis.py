"""Escrow analysis cycles and payment change notices."""

from datetime import timedelta

from flask import Blueprint, request

from auth import any_role, check_borrower_owner, require_roles
from domain import (
    account_of_loan,
    compute_analysis_fields,
    entries_of_account,
    line_items_of_account,
    make_notice,
    post_ledger,
    replay,
    void_notices_of_analysis,
)
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_EFFECTIVE_NOT_REACHED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LUMP_SUM_MISSING,
    ERR_ON_HOLD,
    ERR_OPTION_N_A,
    ERR_OPTION_REQUIRED,
    ERR_PROJECTION_START,
    ERR_SPREAD_MANDATORY,
    ERR_STALE_VERSION,
    ERR_WINDOW_OVERLAP,
    not_found,
)
from routes_core import get_account_or_404
from serializers import analysis_out, notice_out
from store import store
from util import (
    add_months,
    bump,
    fmt_date,
    new_record,
    now_ts,
    ok,
    ok_list,
    parse_date,
    today,
)
from validate import body, req_enum, req_int

bp = Blueprint("analysis", __name__)

METHODS = ("PROSPECTIVE", "LEDGER_ACTUAL")
TERMINAL = ("SUPERSEDED", "VOIDED")
SHORTAGE_OPTIONS = ("LUMP_SUM", "SPREAD_12")


def get_analysis_or_404(aid):
    a = store.analyses.get(aid)
    if a is None:
        raise not_found("EscrowAnalysisCycle not found")
    return a


def get_notice_or_404(nid):
    n = store.notices.get(nid)
    if n is None:
        raise not_found("PaymentChangeNotice not found")
    return n


# ----------------------------------------------------------------------------
# Analysis cycles
# ----------------------------------------------------------------------------

@bp.post("/servicing/escrow-accounts/<aid>/analyses")
def create_analysis(aid):
    require_roles("EscrowAnalyst")
    account = get_account_or_404(aid)
    data = body()
    year = req_int(data, "analysis_year")
    start_s = data.get("projection_start_date")
    start = parse_date(start_s)
    if start is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "projection_start_date must be an ISO YYYY-MM-DD date")
    method = req_enum(data, "method", METHODS)
    expected = data.get("expected_escrow_account_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_escrow_account_version is required")
    # OCC (priority 7)
    if expected != account["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale escrow account version")
    # Temporal: projection start must be day 1 of a month (priority 15)
    if start.day != 1:
        raise ApiError(ERR_PROJECTION_START, 422,
                       "projection_start_date must be the first day of a month")
    window_end = start + timedelta(days=364)
    # Window overlap (closed intervals) vs non-terminal, non-DRAFT cycles
    for c in store.analyses.values():
        if c["escrow_account_id"] != aid or c["status"] in TERMINAL or c["status"] == "DRAFT":
            continue
        s2 = parse_date(c["projection_start_date"])
        e2 = parse_date(c["window_end_date"])
        if start <= e2 and s2 <= window_end:
            raise ApiError(ERR_WINDOW_OVERLAP, 409,
                           "Projection window overlaps another non-terminal cycle")
    # A still-DRAFT predecessor is superseded by this creation
    for c in sorted(store.analyses.values(), key=lambda r: r["_seq"]):
        if c["escrow_account_id"] == aid and c["status"] == "DRAFT":
            c["status"] = "SUPERSEDED"
            bump(c)
    cycle = new_record({
        "escrow_account_id": aid,
        "analysis_year": year,
        "projection_start_date": start_s,
        "method": method,
        "status": "DRAFT",
        "window_end_date": fmt_date(window_end),
        "computed_at": None,
        "statement_issued_at": None,
        "statement_due_date": None,
        "statement_timeliness": None,
        "start_balance_cents": None,
        "projected_annual_disbursements_cents": None,
        "cushion_target_cents": None,
        "lowest_projected_balance_cents": None,
        "shortage_cents": 0,
        "deficiency_cents": 0,
        "surplus_cents": 0,
        "base_monthly_escrow_cents": None,
        "spread_monthly_cents": 0,
        "spread_first_month_cents": 0,
        "new_monthly_escrow_cents": None,
    })
    store.analyses[cycle["id"]] = cycle
    bump(account)
    return ok(analysis_out(cycle), 201)


@bp.get("/servicing/escrow-accounts/<aid>/analyses")
def list_analyses(aid):
    any_role()
    get_account_or_404(aid)
    rows = [c for c in sorted(store.analyses.values(), key=lambda r: r["_seq"])
            if c["escrow_account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([analysis_out(r) for r in rows])


@bp.get("/servicing/analyses/<aid>")
def get_analysis(aid):
    any_role()
    return ok(analysis_out(get_analysis_or_404(aid)))


@bp.post("/servicing/analyses/<aid>/compute")
def compute_analysis(aid):
    require_roles("EscrowAnalyst")
    cycle = get_analysis_or_404(aid)
    if cycle["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Analysis is terminal")
    if cycle["status"] not in ("DRAFT", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Analysis must be DRAFT or REOPENED to compute")
    account = store.accounts.get(cycle["escrow_account_id"])
    if account is None:
        raise not_found("EscrowAccount not found")
    if account["hold_status"] != "NONE":
        raise ApiError(ERR_ON_HOLD, 409, "Escrow account is on compliance hold")
    if account["account_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Escrow account is not ACTIVE")
    if cycle["status"] == "DRAFT" and not line_items_of_account(account["id"], True):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "At least one ACTIVE line item is required")
    compute_analysis_fields(account, cycle)
    cycle["status"] = "COMPUTED"
    bump(cycle)
    return ok(analysis_out(cycle))


@bp.post("/servicing/analyses/<aid>/issue-statement")
def issue_statement(aid):
    require_roles("EscrowAnalyst")
    cycle = get_analysis_or_404(aid)
    if cycle["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Analysis is terminal")
    if cycle["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Analysis is not COMPUTED")
    issue_date = today()
    due = parse_date(cycle["computed_at"][:10]) + timedelta(days=30)
    cycle["statement_issued_at"] = now_ts()
    cycle["statement_due_date"] = fmt_date(due)
    cycle["statement_timeliness"] = "ON_TIME" if issue_date <= due else "LATE"
    cycle["status"] = "STATEMENT_ISSUED"
    bump(cycle)
    return ok(analysis_out(cycle))


@bp.post("/servicing/analyses/<aid>/finalize")
def finalize_analysis(aid):
    require_roles("EscrowAnalyst")
    cycle = get_analysis_or_404(aid)
    if cycle["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Analysis is terminal")
    if cycle["status"] != "STATEMENT_ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Analysis is not STATEMENT_ISSUED")
    account = store.accounts.get(cycle["escrow_account_id"])
    if account is None:
        raise not_found("EscrowAccount not found")
    if account["hold_status"] != "NONE":
        raise ApiError(ERR_ON_HOLD, 409, "Escrow account is on compliance hold")
    make_notice(account, cycle)
    surplus = cycle["surplus_cents"] or 0
    if surplus >= 5000:
        post_ledger(account, "SURPLUS_REFUND", -surplus, fmt_date(today()),
                    "EscrowAnalysisCycle", cycle["id"])
        replay(account)
    for c in sorted(store.analyses.values(), key=lambda r: r["_seq"]):
        if (c["escrow_account_id"] == cycle["escrow_account_id"]
                and c["id"] != cycle["id"] and c["status"] == "EFFECTIVE"):
            c["status"] = "SUPERSEDED"
            bump(c)
    cycle["status"] = "EFFECTIVE"
    bump(cycle)
    account["last_analysis_year"] = cycle["analysis_year"]
    if account["next_analysis_due_date"]:
        account["next_analysis_due_date"] = fmt_date(
            add_months(parse_date(account["next_analysis_due_date"]), 12))
    bump(account)
    return ok(analysis_out(cycle))


@bp.post("/servicing/analyses/<aid>/reopen")
def reopen_analysis(aid):
    require_roles("ComplianceOfficer")
    cycle = get_analysis_or_404(aid)
    if cycle["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Analysis is terminal")
    if cycle["status"] != "EFFECTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Analysis is not EFFECTIVE")
    cycle["status"] = "REOPENED"
    void_notices_of_analysis(cycle["id"], include_acknowledged=True)
    bump(cycle)
    return ok(analysis_out(cycle))


@bp.post("/servicing/analyses/<aid>/void")
def void_analysis(aid):
    require_roles("ComplianceOfficer")
    cycle = get_analysis_or_404(aid)
    if cycle["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Analysis is terminal")
    if cycle["status"] not in ("DRAFT", "COMPUTED", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only DRAFT, COMPUTED, or REOPENED analyses can be voided")
    cycle["status"] = "VOIDED"
    bump(cycle)
    return ok(analysis_out(cycle))


# ----------------------------------------------------------------------------
# Payment change notices
# ----------------------------------------------------------------------------

@bp.get("/servicing/analyses/<aid>/notices")
def list_notices(aid):
    any_role()
    get_analysis_or_404(aid)
    rows = [n for n in sorted(store.notices.values(), key=lambda r: r["_seq"])
            if n["analysis_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([notice_out(r) for r in rows])


@bp.get("/servicing/notices/<nid>")
def get_notice(nid):
    any_role()
    return ok(notice_out(get_notice_or_404(nid)))


@bp.post("/servicing/notices/<nid>/send")
def send_notice(nid):
    require_roles("EscrowAnalyst")
    n = get_notice_or_404(nid)
    if n["status"] in ("APPLIED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Notice is terminal")
    if n["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Notice is not DRAFT")
    sent_date = today()
    n["sent_at"] = now_ts()
    n["timeliness"] = (
        "ON_TIME" if sent_date <= parse_date(n["send_by_date"]) else "LATE")
    n["status"] = "SENT"
    bump(n)
    return ok(notice_out(n))


@bp.post("/servicing/notices/<nid>/acknowledge")
def acknowledge_notice(nid):
    uid, role = require_roles("Borrower")
    n = get_notice_or_404(nid)
    cycle = store.analyses.get(n["analysis_id"])
    account = store.accounts.get(cycle["escrow_account_id"]) if cycle else None
    owning_loan_id = account["loan_id"] if account else None
    check_borrower_owner(uid, owning_loan_id)
    data = body()
    option = data.get("shortage_option")
    if option is not None and option not in SHORTAGE_OPTIONS:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "shortage_option must be LUMP_SUM or SPREAD_12")
    if n["status"] in ("APPLIED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Notice is terminal")
    if n["status"] != "SENT":
        raise ApiError(ERR_INVALID_STATE, 409, "Notice is not SENT")
    short_def = (cycle["shortage_cents"] or 0) + (cycle["deficiency_cents"] or 0)
    if short_def > 0 and option is None:
        raise ApiError(ERR_OPTION_REQUIRED, 422, "shortage_option is required")
    if short_def == 0 and option is not None:
        raise ApiError(ERR_OPTION_N_A, 422, "shortage_option is not applicable")
    if option == "LUMP_SUM":
        if (cycle["deficiency_cents"] or 0) >= (n["old_monthly_escrow_cents"] or 0):
            raise ApiError(ERR_SPREAD_MANDATORY, 422,
                           "Deficiency of one full month of escrow must be spread")
        n["new_monthly_escrow_cents"] = cycle["base_monthly_escrow_cents"]
    n["shortage_option"] = option
    n["status"] = "ACKNOWLEDGED"
    bump(n)
    return ok(notice_out(n))


@bp.post("/servicing/notices/<nid>/apply")
def apply_notice(nid):
    require_roles("EscrowAnalyst")
    n = get_notice_or_404(nid)
    if n["status"] in ("APPLIED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Notice is terminal")
    if n["status"] not in ("SENT", "ACKNOWLEDGED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Notice must be SENT or ACKNOWLEDGED to apply")
    cycle = store.analyses.get(n["analysis_id"])
    if cycle is not None and cycle["status"] in ("REOPENED", "VOIDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Analysis is REOPENED or VOIDED")
    now_date = today()
    if now_date < parse_date(n["effective_date"]):
        raise ApiError(ERR_EFFECTIVE_NOT_REACHED, 409,
                       "Current date is before the notice effective_date")
    short_def = (cycle["shortage_cents"] or 0) + (cycle["deficiency_cents"] or 0)
    if n["status"] == "ACKNOWLEDGED" and n["shortage_option"] == "LUMP_SUM":
        # Deposits with effective_date in [sent date, today] must cover shortage+deficiency
        account = store.accounts.get(cycle["escrow_account_id"])
        sent_date = parse_date(n["sent_at"][:10])
        total = sum(
            e["amount_cents"]
            for e in entries_of_account(account["id"])
            if e["entry_type"] == "DEPOSIT"
            and parse_date(e["effective_date"]) >= sent_date
            and parse_date(e["effective_date"]) <= now_date
        )
        if total < short_def:
            raise ApiError(ERR_LUMP_SUM_MISSING, 422,
                           "Lump-sum deposit does not cover shortage plus deficiency")
    account = store.accounts.get(cycle["escrow_account_id"])
    account["monthly_escrow_cents"] = n["new_monthly_escrow_cents"]
    bump(account)
    n["status"] = "APPLIED"
    bump(n)
    return ok(notice_out(n))


@bp.post("/servicing/notices/<nid>/void")
def void_notice(nid):
    require_roles("ComplianceOfficer")
    n = get_notice_or_404(nid)
    if n["status"] in ("APPLIED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Notice is terminal")
    if n["status"] not in ("DRAFT", "SENT"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only DRAFT or SENT notices can be voided")
    n["status"] = "VOIDED"
    bump(n)
    return ok(notice_out(n))
