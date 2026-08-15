"""Routes: report requirements, LOC drawdown requests, receivables + aging."""
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, page_params,
                        require_role, sh_dt, sh_int, sh_str)
from response import ok, ok_created, ok_list
from services import posted_nonshare_exps, recompute_award, recompute_posture, receivable_live
from util import D, rhu, whole_days

bp = Blueprint("cash", __name__)

REPORT_TYPES = {"ANNUAL_PROGRESS", "TECHNICAL_QUARTERLY", "MILESTONE", "FINAL_TECHNICAL"}
REPORT_STATUSES = {"PENDING", "OVERDUE", "SUBMITTED", "ACCEPTED"}
DRAW_STATUSES = {"DRAFT", "SUBMITTED", "SETTLED", "REJECTED_BY_SPONSOR", "CANCELLED"}
RECV_STATUSES = {"OPEN", "PARTIALLY_PAID", "PAID", "DISPUTED"}
BUCKETS = {"CURRENT", "D31_60", "D61_90", "D91_120", "OVER_120"}


# ---------------------------------------------------------------------------
# report requirements
# ---------------------------------------------------------------------------

@bp.post("/api/report-requirements")
def create_report():
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    rtype = sh_str(b, "report_type", sh)
    if rtype is not None and rtype not in REPORT_TYPES:
        sh.bad = True
    due = sh_dt(b, "due_date", sh)
    get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    sh.raise_if_bad()
    r = stamp_new({
        "id": new_id(), "award_id": award_id, "report_type": rtype, "due_date": due,
        "status": "PENDING", "submitted_at": None, "days_overdue": 0, "reject_reason": None,
    })
    STORES["reports"][r["id"]] = r
    return ok_created(sz.report(r))


@bp.get("/api/report-requirements")
def list_reports():
    auth()
    filters = {
        lambda r: r["award_id"]: request.args.get("award_id"),
        lambda r: r["status"]: request.args.get("status"),
        lambda r: r["report_type"]: request.args.get("report_type"),
    }
    items, total, limit, offset = list_page("reports", sz.report, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/report-requirements/<rid>")
def get_report(rid):
    auth()
    return ok(sz.report(get_or_404("reports", rid, "ERR_REPORT_NOT_FOUND")))


@bp.post("/api/report-requirements/<rid>/submit")
def submit_report(rid):
    uid, role = auth()
    require_role(role, ["PrincipalInvestigator", "GrantCoordinator"])
    r = get_or_404("reports", rid, "ERR_REPORT_NOT_FOUND")
    a = STORES["awards"].get(r["award_id"])
    # ownership (3): a PI may only submit reports on their own awards
    if role == "PrincipalInvestigator" and (a is None or a["pi_id"] != uid):
        raise err("ERR_FORBIDDEN_OWNERSHIP", "A PI may only submit reports for awards where they are PI")
    b = body()
    sh = Shape()
    sh_str(b, "submission_note", sh, required=False)
    if r["status"] not in ("PENDING", "OVERDUE"):
        raise err("ERR_REPORT_NOT_SUBMITTABLE", "Report submit requires status PENDING or OVERDUE")
    sh.raise_if_bad()
    r["status"] = "SUBMITTED"
    r["submitted_at"] = now_clock()
    r["days_overdue"] = 0  # 0 while not overdue
    touch(r)
    if a is not None:
        recompute_posture(a)
    return ok(sz.report(r))


@bp.post("/api/report-requirements/<rid>/accept")
def accept_report(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    r = get_or_404("reports", rid, "ERR_REPORT_NOT_FOUND")
    if r["status"] != "SUBMITTED":
        raise err("ERR_REPORT_NOT_SUBMITTABLE", "Accept requires status SUBMITTED")
    r["status"] = "ACCEPTED"
    touch(r)
    a = STORES["awards"].get(r["award_id"])
    if a is not None:
        recompute_posture(a)
    return ok(sz.report(r))


@bp.post("/api/report-requirements/<rid>/reject")
def reject_report(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    r = get_or_404("reports", rid, "ERR_REPORT_NOT_FOUND")
    if r["status"] != "SUBMITTED":
        raise err("ERR_REPORT_NOT_SUBMITTABLE", "Reject requires status SUBMITTED")
    b = body()
    sh = Shape()
    revised = sh_dt(b, "revised_due_date", sh)
    reason = sh_str(b, "reject_reason", sh)
    sh.raise_if_bad()
    r["status"] = "PENDING"
    r["due_date"] = revised
    r["reject_reason"] = reason
    r["days_overdue"] = 0  # 0 while not overdue
    touch(r)
    a = STORES["awards"].get(r["award_id"])
    if a is not None:
        recompute_posture(a)
    return ok(sz.report(r))


# ---------------------------------------------------------------------------
# drawdown requests (letter of credit)
# ---------------------------------------------------------------------------

@bp.post("/api/drawdown-requests")
def create_drawdown():
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    amount = sh_int(b, "amount_cents", sh, min_v=1)
    expected = b.get("expected_award_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        sh.bad = True
        expected = None
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    if a is not None:
        # OCC (5)
        if expected is not None and expected != a["version"]:
            raise err("ERR_STALE_AWARD_VERSION",
                      "expected_award_version does not match the award's current version")
        # state (6): SUSPENDED blocks financial writes
        if a["status"] == "SUSPENDED":
            raise err("ERR_AWARD_NOT_ACTIVE", "Drawdown create is blocked while the award is SUSPENDED")
        # referential (11): drawdowns only on LETTER_OF_CREDIT awards
        if a["payment_method"] != "LETTER_OF_CREDIT":
            raise err("ERR_PAYMENT_METHOD_MISMATCH",
                      "Drawdown requests require payment_method LETTER_OF_CREDIT")
    sh.raise_if_bad()
    d = stamp_new({
        "id": new_id(), "award_id": award_id, "amount_cents": amount, "status": "DRAFT",
        "eligible_pool_at_submission": None, "reject_reason": None,
        "submitted_at": None, "settled_at": None,
    })
    STORES["drawdowns"][d["id"]] = d
    touch(a)  # drawdown create increments the award version
    return ok_created(sz.drawdown(d))


@bp.get("/api/drawdown-requests")
def list_drawdowns():
    auth()
    filters = {
        lambda d: d["award_id"]: request.args.get("award_id"),
        lambda d: d["status"]: request.args.get("status"),
    }
    items, total, limit, offset = list_page("drawdowns", sz.drawdown, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/drawdown-requests/<did>")
def get_drawdown(did):
    auth()
    return ok(sz.drawdown(get_or_404("drawdowns", did, "ERR_DRAWDOWN_NOT_FOUND")))


@bp.post("/api/drawdown-requests/<did>/submit")
def submit_drawdown(did):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    d = get_or_404("drawdowns", did, "ERR_DRAWDOWN_NOT_FOUND")
    if d["status"] != "DRAFT":
        raise err("ERR_DRAWDOWN_NOT_ACTIONABLE", "Submit requires status DRAFT")
    a = STORES["awards"][d["award_id"]]
    # state (6)
    if a["status"] not in ("ACTIVE", "CLOSEOUT_PENDING"):
        raise err("ERR_AWARD_NOT_ACTIVE", "Drawdown submit requires award ACTIVE or CLOSEOUT_PENDING")
    # posture (7): submit requires OPEN
    if a["posture"] == "RESTRICTED":
        raise err("ERR_AWARD_RESTRICTED", "Award posture RESTRICTED blocks drawdown submit")
    if a["posture"] == "FROZEN":
        raise err("ERR_AWARD_FROZEN", "Award posture FROZEN blocks drawdown submit")
    # fiscal (12)
    if d["amount_cents"] > a["available_draw_pool_cents"]:
        raise err("ERR_DRAWDOWN_EXCEEDS_ELIGIBLE", "amount_cents exceeds available_draw_pool_cents")
    d["eligible_pool_at_submission"] = a["available_draw_pool_cents"]  # available pool snapshot
    a["reserved_draw_cents"] += d["amount_cents"]                       # reservation
    recompute_award(a)                                                  # available -= amount
    d["submitted_at"] = now_clock()
    d["status"] = "SUBMITTED"
    touch(d)
    touch(a)
    return ok(sz.drawdown(d))


@bp.post("/api/drawdown-requests/<did>/settle")
def settle_drawdown(did):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    d = get_or_404("drawdowns", did, "ERR_DRAWDOWN_NOT_FOUND")
    if d["status"] != "SUBMITTED":
        raise err("ERR_DRAWDOWN_NOT_ACTIONABLE", "Settle requires status SUBMITTED")
    a = STORES["awards"][d["award_id"]]
    a["reserved_draw_cents"] -= d["amount_cents"]
    a["cumulative_drawn_cents"] += d["amount_cents"]
    recompute_award(a)
    d["settled_at"] = now_clock()
    d["status"] = "SETTLED"
    touch(d)
    touch(a)
    return ok(sz.drawdown(d))


@bp.post("/api/drawdown-requests/<did>/reject")
def reject_drawdown(did):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    d = get_or_404("drawdowns", did, "ERR_DRAWDOWN_NOT_FOUND")
    if d["status"] != "SUBMITTED":
        raise err("ERR_DRAWDOWN_NOT_ACTIONABLE", "Reject requires status SUBMITTED")
    b = body()
    sh = Shape()
    reason = sh_str(b, "reject_reason", sh)
    sh.raise_if_bad()
    a = STORES["awards"][d["award_id"]]
    a["reserved_draw_cents"] -= d["amount_cents"]  # reservation released
    recompute_award(a)
    d["reject_reason"] = reason
    d["status"] = "REJECTED_BY_SPONSOR"
    touch(d)
    touch(a)
    return ok(sz.drawdown(d))


# ---------------------------------------------------------------------------
# receivables (cost-reimbursable invoicing, accrual basis)
# ---------------------------------------------------------------------------

@bp.post("/api/receivables")
def create_receivable():
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    start = sh_dt(b, "period_start", sh)
    end = sh_dt(b, "period_end", sh)
    if start is not None and end is not None and not (end >= start):
        sh.bad = True
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    included = []
    if a is not None:
        # state (6): SUSPENDED blocks financial writes
        if a["status"] == "SUSPENDED":
            raise err("ERR_AWARD_NOT_ACTIVE", "Receivable create is blocked while the award is SUSPENDED")
        # referential (11): receivables only on COST_REIMBURSABLE_INVOICE awards
        if a["payment_method"] != "COST_REIMBURSABLE_INVOICE":
            raise err("ERR_PAYMENT_METHOD_MISMATCH",
                      "Receivables require payment_method COST_REIMBURSABLE_INVOICE")
        # fiscal (12): window must contain >= 1 uninvoiced posted cost
        if start is not None and end is not None and end >= start:
            included = [e for e in posted_nonshare_exps(a["id"])
                        if start <= e["transaction_date"] <= end
                        and e.get("invoiced_receivable_id") is None]
            if not included:
                raise err("ERR_NO_UNINVOICED_COSTS",
                          "Billing window contains no uninvoiced POSTED non-cost-share expenditures")
    sh.raise_if_bad()
    # accrual-basis amount: directs in window + F&A on the window's MTDC (cash_disbursed ignored)
    d_win = sum(e["amount_cents"] for e in included)
    m_win = sum(e["mtdc_eligible_cents"] for e in included)
    amount = d_win + rhu(D(a["f_and_a_rate_bps"]) * D(m_win) / D(10000))
    r = stamp_new({
        "id": new_id(), "award_id": award_id, "period_start": start, "period_end": end,
        "amount_cents": amount, "invoice_date": now_clock(),
        "disputed_at": None, "total_disputed_days": 0,
        "interest_paid_cents": 0, "principal_paid_cents": 0,
        "status": "OPEN", "dispute_reason": None, "_frozen_accrued_cents": 0,
    })
    STORES["receivables"][r["id"]] = r
    for e in included:  # stamp each billed expenditure (prevents double-billing)
        e["invoiced_receivable_id"] = r["id"]
        touch(e)
    touch(a)  # receivable create increments the award version
    return ok_created(sz.receivable(r))


@bp.get("/api/receivables")
def list_receivables():
    auth()
    f_award = request.args.get("award_id")
    f_status = request.args.get("status")
    f_bucket = request.args.get("aging_bucket")
    filters = {
        lambda r: r["award_id"]: f_award,
        lambda r: r["status"]: f_status,
        lambda r: receivable_live(r)[1]: f_bucket,
    }
    items, total, limit, offset = list_page("receivables", sz.receivable, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/receivables/<rid>")
def get_receivable(rid):
    auth()
    return ok(sz.receivable(get_or_404("receivables", rid, "ERR_RECEIVABLE_NOT_FOUND")))


@bp.post("/api/receivables/<rid>/payments")
def record_payment(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    r = get_or_404("receivables", rid, "ERR_RECEIVABLE_NOT_FOUND")
    if r["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise err("ERR_RECEIVABLE_NOT_OPEN", "Payments require status OPEN or PARTIALLY_PAID")
    b = body()
    sh = Shape()
    amount = sh_int(b, "amount_cents", sh)
    # fiscal (12): payment must not exceed the outstanding total
    _, _, accrued, outstanding = receivable_live(r)
    if amount is not None and amount > outstanding:
        raise err("ERR_RECEIVABLE_OVERPAYMENT", "Payment exceeds outstanding_total_cents")
    sh.raise_if_bad()
    # waterfall: accrued interest first, then principal
    interest_part = min(amount, accrued - r["interest_paid_cents"])
    principal_part = amount - interest_part
    r["interest_paid_cents"] += interest_part
    r["principal_paid_cents"] += principal_part
    a = STORES["awards"][r["award_id"]]
    a["cumulative_drawn_cents"] += principal_part
    touch(a)
    new_outstanding = (r["amount_cents"] + accrued
                       - r["interest_paid_cents"] - r["principal_paid_cents"])
    r["status"] = "PAID" if new_outstanding == 0 else "PARTIALLY_PAID"
    touch(r)
    return ok(sz.receivable(r))


@bp.post("/api/receivables/<rid>/dispute")
def dispute_receivable(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    r = get_or_404("receivables", rid, "ERR_RECEIVABLE_NOT_FOUND")
    if r["status"] != "OPEN":
        raise err("ERR_RECEIVABLE_NOT_OPEN", "Dispute requires status OPEN")
    b = body()
    sh = Shape()
    reason = sh_str(b, "dispute_reason", sh)
    sh.raise_if_bad()
    # freeze accrual at the value computed when the dispute opens
    _, _, accrued, _ = receivable_live(r)
    r["_frozen_accrued_cents"] = accrued
    r["disputed_at"] = now_clock()
    r["dispute_reason"] = reason
    r["status"] = "DISPUTED"
    touch(r)
    return ok(sz.receivable(r))


@bp.post("/api/receivables/<rid>/resolve-dispute")
def resolve_dispute(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    r = get_or_404("receivables", rid, "ERR_RECEIVABLE_NOT_FOUND")
    if r["status"] != "DISPUTED":
        raise err("ERR_RECEIVABLE_NOT_OPEN", "Resolve-dispute requires status DISPUTED")
    # dispute days never accrue, even after resolution
    r["total_disputed_days"] += max(0, whole_days(r["disputed_at"], now_clock()))
    r["dispute_reason"] = None
    r["status"] = "OPEN"
    touch(r)
    return ok(sz.receivable(r))


@bp.get("/api/awards/<aid>/receivables-aging")
def receivables_aging(aid):
    auth()
    get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    buckets = {"CURRENT": 0, "D31_60": 0, "D61_90": 0, "D91_120": 0, "OVER_120": 0}
    total_outstanding = 0
    total_interest = 0
    for r in STORES["receivables"].values():
        if r["award_id"] != aid:
            continue
        _, bucket, accrued, outstanding = receivable_live(r)
        buckets[bucket] += r["amount_cents"] - r["principal_paid_cents"]  # principal outstanding
        total_outstanding += outstanding
        total_interest += accrued  # sums per-receivable rounded values
    return ok({
        "award_id": aid,
        "current_cents": buckets["CURRENT"],
        "d31_60_cents": buckets["D31_60"],
        "d61_90_cents": buckets["D61_90"],
        "d91_120_cents": buckets["D91_120"],
        "over_120_cents": buckets["OVER_120"],
        "total_outstanding_cents": total_outstanding,
        "total_accrued_interest_cents": total_interest,
    })
