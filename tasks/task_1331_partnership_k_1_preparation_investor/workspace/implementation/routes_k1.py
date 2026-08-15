"""K-1 packages, amendments, investor tickets."""
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, ADMIN_ROLES, TRIO_ROLES, require_roles
from db import db, now, new_entity, touch, fmt_ts
from util import ApiError, envelope, paginate, sort_created
from validate import body_json, as_str, as_int, as_enum
import services as S
from routes import (get_tax_year_or_404, get_partner_or_404, list_response,
                    investor_owns_or_403)
from routes_state_wh import require_locked_final_run

bp = Blueprint("k1", __name__)


def get_k1_or_404(kid):
    k = db.k1_packages.get(kid)
    if k is None:
        raise ApiError("ERR_NOT_FOUND", 404, "K-1 package not found")
    return k


def get_amendment_or_404(aid):
    a = db.k1_amendments.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "K-1 amendment not found")
    return a


# ---------------------------------------------------------------------------
# K-1 generation and lifecycle
# ---------------------------------------------------------------------------

@bp.post("/funds/k1-generation")
def generate_k1s():
    require_roles("TaxPreparer")
    body = body_json()
    tax_year_id = as_str(body, "tax_year_id")
    ty = get_tax_year_or_404(tax_year_id)
    if ty["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not APPROVED")
    live = [k for k in db.k1_packages.values()
            if k["tax_year_id"] == ty["id"] and k["prep_status"] != "SUPERSEDED"]
    if live:
        raise ApiError("ERR_K1_ALREADY_GENERATED", 409,
                       "Non-SUPERSEDED K-1 packages already exist for this tax year")
    run = require_locked_final_run(ty)
    partners = sort_created([p for p in db.partners.values()
                             if p["fund_id"] == ty["fund_id"] and p["status"] == "ACTIVE"])
    created = []
    for p in partners:
        k = new_entity()
        k.update({
            "partner_id": p["id"],
            "tax_year_id": ty["id"],
            "run_id": run["id"],
            "generation": 1,
            "supersedes_k1_id": None,
            "prep_status": "GENERATED",
            "delivery_status": "PENDING",
            "line_snapshot": S.k1_snapshot(p, ty, run),
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "delivery_method": None,
            "delivered_at": None,
            "is_late": False,
        })
        db.k1_packages[k["id"]] = k
        created.append((p, k))
    # cascade hop 2a: Q4 CURRENT_ACTUAL withholding accrual per foreign partner with a new K-1
    for p, _k in created:
        if not p["is_foreign"]:
            continue
        exists = any(wr for wr in db.withholding_records.values()
                     if (wr["partner_id"], wr["tax_year_id"], wr["quarter"]) == (p["id"], ty["id"], 4))
        if not exists:
            S.accrue_withholding_record(p, ty, 4, "CURRENT_ACTUAL")
    # cascade hop 2b: DRAFT composite filings recompute totals
    for cf in db.composite_filings.values():
        if cf["tax_year_id"] == ty["id"] and cf["status"] == "DRAFT":
            S.recompute_composite_filing(cf)
            touch(cf)
    return envelope([S.serialize_k1(k) for _p, k in created], 201)


@bp.get("/funds/k1-packages/<k1Id>")
def get_k1(k1Id):
    uid, role = require_roles(*ALL_ROLES)
    k = get_k1_or_404(k1Id)
    if role == "Investor":
        investor_owns_or_403(uid, k["partner_id"])
    return envelope(S.serialize_k1(k), 200)


@bp.get("/funds/k1-packages")
def list_k1_packages():
    require_roles(*ADMIN_ROLES)
    items = list(db.k1_packages.values())
    for param in ("partner_id", "tax_year_id", "supersedes_k1_id", "run_id", "prep_status"):
        v = request.args.get(param)
        if v is not None:
            items = [k for k in items if k[param] == v]
    return list_response(items, S.serialize_k1)


def check_snapshot_run_locked(k):
    run = db.allocation_runs.get(k["run_id"])
    if run is None or run["status"] != "LOCKED":
        raise ApiError("ERR_ALLOCATION_STALE", 409, "The snapshot allocation run is not LOCKED")
    return run


@bp.post("/funds/k1-packages/<k1Id>/submit-review")
def k1_submit_review(k1Id):
    uid, _role = require_roles("TaxPreparer")
    body_json()
    k = get_k1_or_404(k1Id)
    if k["prep_status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "K-1 package is not GENERATED")
    check_snapshot_run_locked(k)
    k["prep_status"] = "REVIEWED"
    k["submitted_by_user_id"] = uid
    touch(k)
    return envelope(S.serialize_k1(k), 200)


@bp.post("/funds/k1-packages/<k1Id>/approve")
def k1_approve(k1Id):
    uid, _role = require_roles("TaxReviewer")
    body_json()
    k = get_k1_or_404(k1Id)
    if k["prep_status"] != "REVIEWED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "K-1 package is not REVIEWED")
    if uid == k["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Approver must differ from submitter")
    check_snapshot_run_locked(k)
    ty = db.tax_years[k["tax_year_id"]]
    if ty["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not APPROVED")
    k["prep_status"] = "APPROVED"
    k["approved_by_user_id"] = uid
    touch(k)
    return envelope(S.serialize_k1(k), 200)


@bp.post("/funds/k1-packages/<k1Id>/deliver")
def k1_deliver(k1Id):
    require_roles("InvestorServicesRep")
    body = body_json()
    method = as_enum(body, "delivery_method", S.DELIVERY_METHODS)
    k = get_k1_or_404(k1Id)
    if k["prep_status"] != "APPROVED" or k["delivery_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "K-1 package is not APPROVED with PENDING delivery")
    k["prep_status"] = "DELIVERED"
    k["delivery_status"] = "SENT"
    k["delivered_at"] = fmt_ts(now())
    k["delivery_method"] = method
    ty = db.tax_years[k["tax_year_id"]]
    deadline = S.k1_deadline(ty)
    from util import parse_datetime
    k["is_late"] = parse_datetime(k["delivered_at"]) > parse_datetime(deadline)
    touch(k)
    S.maybe_complete_tax_year(ty)
    return envelope(S.serialize_k1(k), 200)


@bp.post("/funds/k1-packages/<k1Id>/acknowledge")
def k1_acknowledge(k1Id):
    uid, _role = require_roles("Investor")
    k = get_k1_or_404(k1Id)
    investor_owns_or_403(uid, k["partner_id"])
    if k["delivery_status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "K-1 delivery is not SENT")
    k["delivery_status"] = "ACKNOWLEDGED"
    touch(k)
    return envelope(S.serialize_k1(k), 200)


@bp.post("/funds/k1-packages/<k1Id>/report-bounced")
def k1_report_bounced(k1Id):
    require_roles("InvestorServicesRep")
    body_json()
    k = get_k1_or_404(k1Id)
    if k["delivery_status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "K-1 delivery is not SENT")
    k["delivery_status"] = "BOUNCED"
    touch(k)
    return envelope(S.serialize_k1(k), 200)


@bp.post("/funds/k1-packages/<k1Id>/resend")
def k1_resend(k1Id):
    require_roles("InvestorServicesRep")
    body = body_json()
    method = body.get("delivery_method")
    if method is not None and method not in S.DELIVERY_METHODS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "delivery_method is invalid")
    k = get_k1_or_404(k1Id)
    if k["delivery_status"] != "BOUNCED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "K-1 delivery is not BOUNCED")
    k["delivery_status"] = "SENT"
    k["delivered_at"] = fmt_ts(now())
    if method is not None:
        k["delivery_method"] = method
    ty = db.tax_years[k["tax_year_id"]]
    from util import parse_datetime
    k["is_late"] = parse_datetime(k["delivered_at"]) > parse_datetime(S.k1_deadline(ty))
    touch(k)
    return envelope(S.serialize_k1(k), 200)


# ---------------------------------------------------------------------------
# K-1 amendments
# ---------------------------------------------------------------------------

@bp.post("/funds/k1-amendments")
def create_amendment():
    uid, _role = require_roles("TaxPreparer")
    body = body_json()
    k1_package_id = as_str(body, "k1_package_id")
    reason = as_enum(body, "reason", S.AMENDMENT_REASONS)
    k = get_k1_or_404(k1_package_id)
    if k["prep_status"] != "DELIVERED":
        raise ApiError("ERR_K1_NOT_DELIVERED", 409, "K-1 package has not been DELIVERED")
    active = [a for a in db.k1_amendments.values()
              if a["k1_package_id"] == k["id"] and a["status"] != "ISSUED"]
    if active:
        raise ApiError("ERR_AMENDMENT_ALREADY_ACTIVE", 409,
                       "An active amendment already exists for this K-1 package")
    a = new_entity()
    a.update({
        "k1_package_id": k["id"],
        "reason": reason,
        "opened_by_user_id": uid,
        "prepared_by_user_id": None,
        "issued_by_user_id": None,
        "new_k1_package_id": None,
        "status": "OPENED",
    })
    db.k1_amendments[a["id"]] = a
    return envelope(S.serialize_amendment(a), 201)


@bp.get("/funds/k1-packages/<k1Id>/amendments")
def list_amendments(k1Id):
    require_roles(*TRIO_ROLES)
    k = get_k1_or_404(k1Id)
    items = [a for a in db.k1_amendments.values() if a["k1_package_id"] == k["id"]]
    return list_response(items, S.serialize_amendment)


@bp.post("/funds/k1-amendments/<amendmentId>/start-prep")
def amendment_start_prep(amendmentId):
    require_roles("TaxPreparer")
    body_json()
    a = get_amendment_or_404(amendmentId)
    if a["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Amendment is not OPENED")
    a["status"] = "IN_PREP"
    touch(a)
    return envelope(S.serialize_amendment(a), 200)


@bp.post("/funds/k1-amendments/<amendmentId>/submit-review")
def amendment_submit_review(amendmentId):
    uid, _role = require_roles("TaxPreparer")
    body_json()
    a = get_amendment_or_404(amendmentId)
    if a["status"] != "IN_PREP":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Amendment is not IN_PREP")
    a["status"] = "IN_REVIEW"
    a["prepared_by_user_id"] = uid
    touch(a)
    return envelope(S.serialize_amendment(a), 200)


@bp.post("/funds/k1-amendments/<amendmentId>/return-to-prep")
def amendment_return_to_prep(amendmentId):
    require_roles("TaxReviewer")
    body_json()
    a = get_amendment_or_404(amendmentId)
    if a["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Amendment is not IN_REVIEW")
    a["status"] = "IN_PREP"
    touch(a)
    return envelope(S.serialize_amendment(a), 200)


@bp.post("/funds/k1-amendments/<amendmentId>/issue")
def amendment_issue(amendmentId):
    uid, _role = require_roles("TaxReviewer")
    body_json()
    a = get_amendment_or_404(amendmentId)
    if a["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Amendment is not IN_REVIEW")
    if uid == a["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Issuer must differ from preparer")
    k = db.k1_packages[a["k1_package_id"]]
    ty = db.tax_years[k["tax_year_id"]]
    partner = db.partners[k["partner_id"]]
    # hop 1: amended package prep -> SUPERSEDED
    k["prep_status"] = "SUPERSEDED"
    touch(k)
    # hop 2: replacement package from the current LOCKED run
    run = S.locked_final_run(ty["id"])
    if run is not None:
        snapshot = S.k1_snapshot(partner, ty, run)
        run_id = run["id"]
    else:
        snapshot = k["line_snapshot"]
        run_id = k["run_id"]
    repl = new_entity()
    repl.update({
        "partner_id": k["partner_id"],
        "tax_year_id": k["tax_year_id"],
        "run_id": run_id,
        "generation": k["generation"] + 1,
        "supersedes_k1_id": k["id"],
        "prep_status": "GENERATED",
        "delivery_status": "PENDING",
        "line_snapshot": snapshot,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "delivery_method": None,
        "delivered_at": None,
        "is_late": False,
    })
    db.k1_packages[repl["id"]] = repl
    a["new_k1_package_id"] = repl["id"]
    # hop 3: investor communication ticket
    ticket = new_entity()
    ticket.update({
        "partner_id": k["partner_id"],
        "tax_year_id": k["tax_year_id"],
        "category": "AMENDED_K1_QUESTION",
        "subject": "Amended K-1 issued",
        "due_at": fmt_ts(now() + timedelta(hours=24)),
        "is_escalated": False,
        "answer_text": None,
        "answered_by_user_id": None,
        "status": "OPEN",
    })
    db.tickets[ticket["id"]] = ticket
    # tax year COMPLETED -> APPROVED
    if ty["status"] == "COMPLETED":
        ty["status"] = "APPROVED"
        touch(ty)
    a["status"] = "ISSUED"
    a["issued_by_user_id"] = uid
    touch(a)
    return envelope(S.serialize_amendment(a), 200)


# ---------------------------------------------------------------------------
# Investor tickets
# ---------------------------------------------------------------------------

@bp.post("/funds/tickets")
def create_ticket():
    uid, role = require_roles("Investor", "InvestorServicesRep")
    body = body_json()
    partner_id = as_str(body, "partner_id")
    category = as_enum(body, "category", S.TICKET_CATEGORIES)
    subject = as_str(body, "subject")
    tax_year_id = body.get("tax_year_id")
    if tax_year_id is not None and not isinstance(tax_year_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "tax_year_id must be a string or null")
    if role == "Investor":
        investor_owns_or_403(uid, partner_id)
    partner = get_partner_or_404(partner_id)
    if tax_year_id is not None:
        ty = get_tax_year_or_404(tax_year_id)
        if ty["fund_id"] != partner["fund_id"]:
            raise ApiError("ERR_CROSS_FUND_REFERENCE", 409,
                           "Partner and tax year belong to different funds")
    sla_hours = 24 if category == "AMENDED_K1_QUESTION" else 72
    t = new_entity()
    t.update({
        "partner_id": partner_id,
        "tax_year_id": tax_year_id,
        "category": category,
        "subject": subject,
        "due_at": fmt_ts(now() + timedelta(hours=sla_hours)),
        "is_escalated": False,
        "answer_text": None,
        "answered_by_user_id": None,
        "status": "OPEN",
    })
    db.tickets[t["id"]] = t
    return envelope(S.serialize_ticket(t), 201)


def get_ticket_or_404(tid):
    t = db.tickets.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Ticket not found")
    return t


@bp.get("/funds/tickets/<ticketId>")
def get_ticket(ticketId):
    uid, role = require_roles(*ALL_ROLES)
    t = get_ticket_or_404(ticketId)
    if role == "Investor":
        investor_owns_or_403(uid, t["partner_id"])
    return envelope(S.serialize_ticket(t), 200)


@bp.get("/funds/tickets")
def list_tickets():
    require_roles(*ADMIN_ROLES)
    items = list(db.tickets.values())
    for param in ("partner_id", "tax_year_id", "status", "category"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t[param] == v]
    return list_response(items, S.serialize_ticket)


@bp.post("/funds/tickets/<ticketId>/answer")
def answer_ticket(ticketId):
    uid, _role = require_roles("InvestorServicesRep", "TaxPreparer")
    body = body_json()
    answer_text = body.get("answer_text")
    if not isinstance(answer_text, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "answer_text is required")
    t = get_ticket_or_404(ticketId)
    if t["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Ticket is not OPEN or REOPENED")
    t["status"] = "ANSWERED"
    t["answer_text"] = answer_text
    t["answered_by_user_id"] = uid
    touch(t)
    return envelope(S.serialize_ticket(t), 200)


@bp.post("/funds/tickets/<ticketId>/reopen")
def reopen_ticket(ticketId):
    uid, role = require_roles("Investor", "InvestorServicesRep")
    body_json()
    t = get_ticket_or_404(ticketId)
    if role == "Investor":
        investor_owns_or_403(uid, t["partner_id"])
    if t["status"] != "ANSWERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Ticket is not ANSWERED")
    t["status"] = "REOPENED"
    touch(t)
    return envelope(S.serialize_ticket(t), 200)


@bp.post("/funds/tickets/<ticketId>/close")
def close_ticket(ticketId):
    require_roles("InvestorServicesRep")
    body_json()
    t = get_ticket_or_404(ticketId)
    if t["status"] != "ANSWERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Ticket is not ANSWERED")
    t["status"] = "CLOSED"
    touch(t)
    return envelope(S.serialize_ticket(t), 200)
