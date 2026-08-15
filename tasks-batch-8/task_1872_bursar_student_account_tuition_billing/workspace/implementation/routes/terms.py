from flask import Blueprint

from db import store, base_fields, touch, clock_date
from dates import req_date, parse_date
from errors import (err, ERR_INVALID_REQUEST, ERR_TERM_NOT_FOUND,
                    ERR_TERM_STATE_INVALID, ERR_TERM_NOT_CLOSABLE,
                    ERR_DUPLICATE_CODE, ERR_FORBIDDEN)
from middleware import auth_context, require_roles
from response import success, json_body, req_str, req_int, req_enum, req_number, list_response
from serialize import ser_term, ser_account
from services.domain import run_billing_cycle

bp = Blueprint("terms", __name__)


@bp.post("/bursar/terms")
def create_term():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff")
    body = json_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")
    census = req_date(body, "census_date")
    full_end = req_date(body, "full_refund_end_date")
    mid_end = req_date(body, "mid_refund_end_date")
    wd = req_date(body, "withdrawal_deadline")
    policy = req_enum(body, "refund_policy", ("SCHEDULE_TIERED", "PRO_RATA"))
    flat_fee = req_int(body, "flat_fee_cents")
    hold_threshold = req_int(body, "hold_threshold_cents")
    plan_fee = req_int(body, "plan_setup_fee_cents")
    late_fee_pct = req_number(body, "late_fee_pct")
    grace_days = req_int(body, "grace_days")

    # Temporal: start < end; start <= census <= end; mid > full;
    # withdrawal_deadline > mid and <= end.
    if not (start < end):
        raise err(ERR_INVALID_REQUEST, "start_date must precede end_date")
    if not (start <= census <= end):
        raise err(ERR_INVALID_REQUEST, "census_date must lie within the term span")
    if not (mid_end > full_end):
        raise err(ERR_INVALID_REQUEST, "mid_refund_end_date must follow full_refund_end_date")
    if not (wd > mid_end and wd <= end):
        raise err(ERR_INVALID_REQUEST,
                  "withdrawal_deadline must follow mid_refund_end_date and not exceed end_date")

    # Uniqueness: term code unique across all terms.
    for t in store.terms.values():
        if t["code"] == code:
            raise err(ERR_DUPLICATE_CODE, "Term code already exists")

    t = base_fields()
    t.update({
        "code": code, "name": name,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "census_date": census.isoformat(),
        "full_refund_end_date": full_end.isoformat(),
        "mid_refund_end_date": mid_end.isoformat(),
        "withdrawal_deadline": wd.isoformat(),
        "refund_policy": policy, "flat_fee_cents": flat_fee,
        "hold_threshold_cents": hold_threshold,
        "plan_setup_fee_cents": plan_fee, "late_fee_pct": late_fee_pct,
        "grace_days": grace_days, "status": "DRAFT",
    })
    store.terms[t["id"]] = t
    return success(ser_term(t), status=201)


@bp.get("/bursar/terms/<tid>")
def get_term(tid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    t = store.terms.get(tid)
    if t is None:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    return success(ser_term(t))


@bp.post("/bursar/terms/<tid>/transition")
def term_transition(tid):
    uid, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarManager")
    t = store.terms.get(tid)
    if t is None:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    body = json_body()
    action = req_enum(body, "action", ("OPEN", "LOCK_CENSUS", "CLOSE"))

    # Per-transition actors: RegistrarStaff performs OPEN / LOCK_CENSUS;
    # CLOSE is reserved for a BursarManager.
    if action in ("OPEN", "LOCK_CENSUS") and role != "RegistrarStaff":
        raise err(ERR_FORBIDDEN, "Only RegistrarStaff may perform this term transition")
    if action == "CLOSE" and role != "BursarManager":
        raise err(ERR_FORBIDDEN, "Only BursarManager may close a term")

    if action == "OPEN":
        if t["status"] != "DRAFT":
            raise err(ERR_TERM_STATE_INVALID, "OPEN requires the term to be DRAFT")
        t["status"] = "OPEN"
        touch(t)
        return success(ser_term(t))

    if action == "LOCK_CENSUS":
        if t["status"] != "OPEN":
            raise err(ERR_TERM_STATE_INVALID, "LOCK_CENSUS requires the term to be OPEN")
        if clock_date() < parse_date(t["census_date"]):
            raise err(ERR_TERM_STATE_INVALID,
                      "LOCK_CENSUS requires the current date to be at or past census_date")
        t["status"] = "CENSUS_LOCKED"
        touch(t)
        return success(ser_term(t))

    # CLOSE
    if t["status"] != "CENSUS_LOCKED":
        raise err(ERR_TERM_STATE_INVALID, "CLOSE requires the term to be CENSUS_LOCKED")
    term_accounts = [a for a in store.accounts.values() if a["term_id"] == t["id"]]
    for a in term_accounts:
        if not (a["balance_cents"] <= 0 or a["status"] == "WRITTEN_OFF"):
            raise err(ERR_TERM_NOT_CLOSABLE,
                      "Term has accounts with positive balance that are not written off")
    for a in term_accounts:
        if a["balance_cents"] <= 0 and a["status"] in ("OPEN", "PAST_DUE"):
            a["status"] = "CLOSED"
            touch(a)
    for ag in store.agreements.values():
        if ag["term_id"] == t["id"] and ag["status"] == "ACTIVE":
            ag["status"] = "TERMINATED"
            touch(ag)
    t["status"] = "CLOSED"
    touch(t)
    return success(ser_term(t))


@bp.post("/bursar/terms/<tid>/run-billing-cycle")
def billing_cycle(tid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    t = store.terms.get(tid)
    if t is None:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    counts = run_billing_cycle(t)
    return success(counts, status=200)


@bp.get("/bursar/terms/<tid>/accounts")
def term_accounts(tid):
    uid, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    t = store.terms.get(tid)
    if t is None:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    rows = [a for a in store.accounts.values() if a["term_id"] == t["id"]]
    rows.sort(key=lambda a: a["_seq"])
    return list_response(rows, ser_account)
