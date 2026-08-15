"""Term endpoints and term lifecycle cascades (PRD 3.3, 3.4, 3.7)."""

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_DUPLICATE_NATURAL_KEY,
    ERR_INVALID_STATE_TRANSITION, ERR_TERM_NOT_YET_STARTED, ERR_TERM_NOT_ENDED,
    ERR_TERM_WEEKS_EXHAUSTED, ERR_REFUNDS_OUTSTANDING,
    ERR_SETTLEMENTS_OUTSTANDING,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_enum, v_dt,
    find_or_404, pub, paginate, fmt_dt,
)
from response import success
from services.core import (
    new_row, touch, clock, dt_of, get_or_create_campus_cash,
    get_or_create_dining_account,
)
from services.cascades import (
    activate_enrollment, term_close_cascade, term_settle_cascade,
)
from services.ledger import post_entry
from response import now_iso

bp = Blueprint("terms", __name__)

PRORATION_MODES = {"WEEKLY", "DAILY"}


@bp.route("/api/terms", methods=["POST"])
def create_term():
    authenticate()
    require_roles("DiningServicesManager")
    body = get_body()
    term_code = v_str(body, "term_code")
    name = v_str(body, "name")
    start_date = v_dt(body, "start_date")
    end_date = v_dt(body, "end_date")
    add_drop_deadline = v_dt(body, "add_drop_deadline")
    total_weeks = v_int(body, "total_weeks", min_v=1)
    proration_mode = v_enum(body, "proration_mode", PRORATION_MODES)
    if not start_date < end_date:
        err(ERR_VALIDATION, "start_date must be before end_date")
    if not (start_date <= add_drop_deadline <= end_date):
        err(ERR_VALIDATION,
            "add_drop_deadline must satisfy start_date <= add_drop_deadline <= end_date")
    for t in store.terms.values():
        if t["term_code"] == term_code:
            err(ERR_DUPLICATE_NATURAL_KEY, "term_code already exists")
    term = new_row()
    term.update({
        "term_code": term_code,
        "name": name,
        "start_date": fmt_dt(start_date),
        "end_date": fmt_dt(end_date),
        "add_drop_deadline": fmt_dt(add_drop_deadline),
        "total_weeks": total_weeks,
        "proration_mode": proration_mode,
        "current_week_index": 0,
        "status": "SCHEDULED",
    })
    store.terms[term["id"]] = term
    return success(pub(term), 201)


@bp.route("/api/terms", methods=["GET"])
def list_terms():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "FraudAnalyst", "CardHolder")
    rows = list(store.terms.values())
    status = request.args.get("status")
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/terms/<tid>", methods=["GET"])
def get_term(tid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "FraudAnalyst", "CardHolder")
    term = find_or_404(store.terms, tid)
    return success(pub(term), 200)


@bp.route("/api/terms/<tid>/open", methods=["POST"])
def open_term(tid):
    authenticate()
    require_roles("DiningServicesManager")
    term = find_or_404(store.terms, tid)
    if term["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE_TRANSITION, "Only a SCHEDULED term can be opened")
    if clock() < dt_of(term, "start_date"):
        err(ERR_TERM_NOT_YET_STARTED, "Term cannot be opened before its start_date")
    term["status"] = "OPEN"
    term["current_week_index"] = 1
    touch(term)
    for enr in sorted(
            (e for e in store.enrollments.values()
             if e["term_id"] == term["id"] and e["status"] == "ASSIGNED"),
            key=lambda e: (e["created_at"], e["_seq"])):
        activate_enrollment(enr, store.plans[enr["plan_id"]], term)
    return success(pub(term), 200)


def _execute_change_request(cr):
    """Advance-week step 3: execute one APPROVED PlanChangeRequest, or VOID it
    when a precondition fails."""
    enrollment = store.enrollments.get(cr["enrollment_id"])
    if enrollment is None or enrollment["status"] != "ACTIVE":
        cr["status"] = "VOID"
        cr["void_reason"] = "ENROLLMENT_CANCELLED"
        touch(cr)
        return
    holder = store.holders[enrollment["holder_id"]]
    delta = cr["charge_delta_cents"]
    if delta is not None and delta > 0:
        cash = None
        for a in store.accounts.values():
            if (a["holder_id"] == holder["id"]
                    and a["account_type"] == "CAMPUS_CASH"
                    and a["status"] in ("OPEN", "FROZEN", "CLOSE_PENDING")):
                cash = a
                break
        balance = cash["balance_cents"] if cash is not None else 0
        if balance < delta:
            cr["status"] = "VOID"
            cr["void_reason"] = "INSUFFICIENT_FUNDS"
            touch(cr)
            return
    new_plan = store.plans[cr["new_plan_id"]]
    enrollment["status"] = "SUPERSEDED"
    enrollment["credit_cents"] = cr["_credit_from_old"]
    touch(enrollment)
    successor = new_row()
    successor.update({
        "holder_id": holder["id"],
        "plan_id": cr["new_plan_id"],
        "term_id": enrollment["term_id"],
        "supersedes_enrollment_id": enrollment["id"],
        "status": "ACTIVE",
        "charge_cents": cr["_new_due"],
        "credit_cents": 0,
        "weekly_swipe_allowance": new_plan["weekly_swipe_allowance"],
        "is_unlimited_swipes": new_plan["is_unlimited_swipes"],
        "swipes_used_this_week": 0,
        "enrolled_week_index": cr["effective_week_index"],
        "activated_at": now_iso(),
    })
    store.enrollments[successor["id"]] = successor
    if delta is not None and delta != 0:
        acct = get_or_create_campus_cash(holder["id"])
        if delta > 0:
            post_entry(acct, "PRORATION_DEBIT", delta,
                       f"Plan change proration debit for request {cr['id']}")
        else:
            post_entry(acct, "PRORATION_CREDIT", -delta,
                       f"Plan change proration credit for request {cr['id']}")
    funding = cr["funding_delta_cents"]
    if funding is not None and funding > 0:
        dining = get_or_create_dining_account(holder["id"], enrollment["term_id"])
        post_entry(dining, "ALLOCATION_GRANT", funding,
                   f"Plan change dining-dollar grant for request {cr['id']}")
    cr["status"] = "EXECUTED"
    touch(cr)


@bp.route("/api/terms/<tid>/advance-week", methods=["POST"])
def advance_week(tid):
    authenticate()
    require_roles("DiningServicesManager")
    term = find_or_404(store.terms, tid)
    if term["status"] != "OPEN":
        err(ERR_INVALID_STATE_TRANSITION, "Only an OPEN term can advance weeks")
    if term["current_week_index"] >= term["total_weeks"]:
        err(ERR_TERM_WEEKS_EXHAUSTED, "The term has no remaining weeks")
    # Step 1: advance the week index.
    term["current_week_index"] += 1
    touch(term)
    # Step 2: weekly swipe reset on ACTIVE enrollments.
    for enr in store.enrollments.values():
        if enr["term_id"] == term["id"] and enr["status"] == "ACTIVE":
            if enr["swipes_used_this_week"] != 0:
                enr["swipes_used_this_week"] = 0
                touch(enr)
    # Step 3: execute due plan changes in created_at ASC order.
    term_enrollment_ids = {e["id"] for e in store.enrollments.values()
                           if e["term_id"] == term["id"]}
    due = [cr for cr in store.change_requests.values()
           if cr["enrollment_id"] in term_enrollment_ids
           and cr["status"] == "APPROVED"
           and cr.get("effective_week_index") == term["current_week_index"]]
    for cr in sorted(due, key=lambda c: (c["created_at"], c["_seq"])):
        _execute_change_request(cr)
    return success(pub(term), 200)


@bp.route("/api/terms/<tid>/close", methods=["POST"])
def close_term(tid):
    authenticate()
    require_roles("DiningServicesManager")
    term = find_or_404(store.terms, tid)
    if term["status"] != "OPEN":
        err(ERR_INVALID_STATE_TRANSITION, "Only an OPEN term can be closed")
    if clock() < dt_of(term, "end_date"):
        err(ERR_TERM_NOT_ENDED, "Term cannot be closed before its end_date")
    term["status"] = "CLOSED"
    touch(term)
    term_close_cascade(term)
    return success(pub(term), 200)


@bp.route("/api/terms/<tid>/settle", methods=["POST"])
def settle_term(tid):
    authenticate()
    require_roles("DiningServicesManager")
    term = find_or_404(store.terms, tid)
    if term["status"] != "CLOSED":
        err(ERR_INVALID_STATE_TRANSITION, "Only a CLOSED term can be settled")
    term_account_ids = {a["id"] for a in store.accounts.values()
                        if a.get("term_id") == term["id"]}
    for rr in store.refund_requests.values():
        if (rr["account_id"] in term_account_ids
                and rr["status"] in ("REQUESTED", "APPROVED")):
            err(ERR_REFUNDS_OUTSTANDING,
                "Refund requests are still outstanding on accounts bound to this term")
    for st in store.settlements.values():
        if (st["term_id"] == term["id"]
                and st["status"] in ("DRAFT", "SUBMITTED", "APPROVED")):
            err(ERR_SETTLEMENTS_OUTSTANDING,
                "Merchant settlements are still outstanding for this term")
    term["status"] = "SETTLED"
    touch(term)
    term_settle_cascade(term)
    return success(pub(term), 200)
