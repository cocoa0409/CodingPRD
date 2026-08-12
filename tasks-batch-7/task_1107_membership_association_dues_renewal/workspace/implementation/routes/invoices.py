"""Dues invoice routes: list/get, payments, refund, attempts, invoice-scoped reinstatement list."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import success
from services import lifecycle

bp = Blueprint("invoices", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _get_invoice(iid):
    inv = db.dues_invoices.get(iid)
    if not inv:
        raise errors.not_found()
    return inv


def _paginate(rows):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + limit) < total}


@bp.get("/api/members/<mid>/dues-invoices")
def list_member_invoices(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator", "DuesAdministrator")
    if mid not in db.members:
        raise errors.not_found()
    rows = [i for i in db.dues_invoices.values() if i["member_id"] == mid]
    ps = request.args.get("payment_status")
    if ps:
        rows = [i for i in rows if i["payment_status"] == ps]
    rows.sort(key=lambda i: i["created_at"])
    return success([lifecycle.invoice_out(i) for i in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.get("/api/dues-invoices/<iid>")
def get_invoice(iid):
    inv = _get_invoice(iid)
    middleware.require_owner_or_roles(inv["member_id"], "MembershipAdministrator", "DuesAdministrator")
    return success(lifecycle.invoice_out(inv))


@bp.get("/api/dues-invoices")
def list_invoices():
    middleware.require_roles("MembershipAdministrator", "DuesAdministrator")
    rows = list(db.dues_invoices.values())
    for key in ("member_id", "membership_term_id", "dues_schedule_id", "payment_status"):
        v = request.args.get(key)
        if v:
            rows = [i for i in rows if i.get(key) == v]
    rows.sort(key=lambda i: i["created_at"])
    page, meta = _paginate(rows)
    return success([lifecycle.invoice_out(i) for i in page], response_type="array", pagination=meta)


@bp.get("/api/dues-invoices/<iid>/reinstatement-requests")
def list_invoice_reinstatements(iid):
    inv = _get_invoice(iid)
    middleware.require_owner_or_roles(inv["member_id"], "MembershipAdministrator")
    rows = [r for r in db.reinstatement_requests.values() if r["back_dues_invoice_id"] == iid]
    rows.sort(key=lambda r: r["created_at"])
    return success([lifecycle.reinstatement_out(r) for r in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.get("/api/dues-invoices/<iid>/payment-attempts")
def list_attempts(iid):
    inv = _get_invoice(iid)
    middleware.require_owner_or_roles(inv["member_id"], "MembershipAdministrator")
    rows = [a for a in db.payment_attempts.values() if a["invoice_id"] == iid]
    rows.sort(key=lambda a: a["attempt_index"])
    return success([lifecycle.attempt_out(a) for a in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.post("/api/dues-invoices/<iid>/payments")
def submit_payment(iid):
    inv = _get_invoice(iid)
    middleware.require_owner_or_roles(inv["member_id"])
    member = db.members[inv["member_id"]]
    b = _body()
    outcome = b.get("simulated_outcome")

    # member-state guard (ERR_MEMBER_NOT_GRACE) — does not block the verification-flow
    # settle of the initial invoice for PENDING_VERIFICATION members (PRD §3.5).
    # Also does not block settling a back-dues invoice for a LAPSED member whose
    # reinstatement request is still PENDING (PRD §3.7 requires back-dues SETTLED
    # as a precondition for approve; the member is necessarily LAPSED at that point).
    term = db.membership_terms.get(inv["membership_term_id"])
    is_initial = term is not None and term["opened_by"] == "JOIN"
    is_back_dues = inv.get("membership_term_id") is None and any(
        r["member_id"] == member["id"]
        and r.get("back_dues_invoice_id") == inv["id"]
        and r["status"] == "PENDING"
        for r in db.reinstatement_requests.values()
    )
    if member["status"] not in ("ACTIVE", "GRACE"):
        allowed = (member["status"] == "PENDING_VERIFICATION" and is_initial) or (
            member["status"] == "LAPSED" and is_back_dues
        )
        if not allowed:
            raise errors.ApiError(errors.ERR_MEMBER_NOT_GRACE,
                                  "Member is not in a billable state", 409)

    # retry cap (priority 11)
    failed = lifecycle.failed_attempt_count(iid)
    if failed >= db.MAX_RETRY:
        raise errors.ApiError(errors.ERR_RETRY_EXHAUSTED,
                              "Failed payment attempts reached MAX_RETRY", 422)

    # invoice state
    if inv["payment_status"] not in ("PENDING", "FAILED_RETRYABLE"):
        raise errors.invalid_state("Invoice is not payable")

    idx = 1
    for a in db.payment_attempts.values():
        if a["invoice_id"] == iid:
            idx = max(idx, a["attempt_index"] + 1)
    attempt = lifecycle.new_entity({
        "invoice_id": iid,
        "attempt_index": idx,
        "attempted_at": db.iso(db.now_utc()),
        "outcome": outcome,
        "decline_code": b.get("decline_code") if outcome != "SUCCEEDED" else None,
    })
    db.payment_attempts[attempt["id"]] = attempt

    if outcome == "SUCCEEDED":
        lifecycle.settle_invoice(inv)
    elif outcome == "DECLINED_TRANSIENT":
        inv["payment_status"] = "FAILED_RETRYABLE"
        db.touch(inv)
        lifecycle.recompute_risk_score(member)
        db.touch(member)
    elif outcome == "DECLINED_HARD":
        inv["payment_status"] = "FAILED_FINAL"
        db.touch(inv)
        for a in db.auto_renew_authorizations.values():
            if a["member_id"] == member["id"] and a["status"] == "ACTIVE":
                a["status"] = "SUSPENDED_HARD_DECLINE"
                db.touch(a)
        lifecycle.recompute_risk_score(member)
        db.touch(member)
    return success(lifecycle.attempt_out(attempt), status=201)


@bp.post("/api/dues-invoices/<iid>/refund")
def refund_invoice(iid):
    middleware.require_roles("MembershipAdministrator")
    inv = _get_invoice(iid)
    member = db.members[inv["member_id"]]
    # refund window (priority 14): must be before current_period_end
    if member.get("current_period_end"):
        if db.now_utc() >= db.parse_dt(member["current_period_end"]):
            raise errors.ApiError(errors.ERR_REFUND_WINDOW_EXPIRED,
                                  "Refund attempted on or after current_period_end", 422)
    # settled check (priority 16)
    if inv["payment_status"] != "SETTLED":
        raise errors.ApiError(errors.ERR_INVOICE_NOT_SETTLED,
                              "Refund requires payment_status == SETTLED", 422)

    inv["payment_status"] = "REFUNDED"
    inv["fulfillment_status"] = "COVERAGE_ENDED"
    db.touch(inv)

    share = inv.get("chapter_share_cents") or 0
    ch = member["home_chapter_id"]
    db.chapter_share_ledger[ch] = db.chapter_share_ledger.get(ch, 0) - share

    member["lifetime_dues_paid_cents"] = member.get("lifetime_dues_paid_cents", 0) - inv["amount_cents"]
    # reset current_period_end to previous paid-through date (latest remaining settled term end, else None)
    remaining = [i for i in db.dues_invoices.values()
                 if i["member_id"] == member["id"] and i["payment_status"] == "SETTLED"]
    if remaining:
        ends = []
        for i in remaining:
            t = db.membership_terms.get(i["membership_term_id"])
            if t:
                ends.append((db.parse_dt(t["period_end"]), t))
        if ends:
            ends.sort(key=lambda x: x[0])
            member["current_period_end"] = ends[-1][1]["period_end"]
            member["current_period_start"] = ends[-1][1]["period_start"]
    else:
        # no remaining SETTLED coverage -> GRACE with immediate effect
        if member["status"] == "ACTIVE":
            member["status"] = "GRACE"
            lifecycle.propagate_benefits(member, "GRACE")
    lifecycle.recompute_risk_score(member)
    db.touch(member)
    return success(lifecycle.invoice_out(inv))
