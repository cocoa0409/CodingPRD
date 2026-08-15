"""Contractor credit accounts, job accounts, payments, and the lien
lifecycle (PRD 3.2 and 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_JOB_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_ACCOUNT_NOT_SUSPENDED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_LIEN_ALREADY_ACTIVE,
    ERR_NO_OUTSTANDING_BALANCE,
    ERR_INVALID_LIEN_AMOUNT,
    ERR_LIEN_NOT_IN_NOTICE,
    ERR_LIEN_CURE_PERIOD_ACTIVE,
    ERR_LIEN_NOT_ACTIVE,
    ERR_BALANCE_STILL_OUTSTANDING,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, check_contractor_owns
from response import success_object
from routes.helpers import body, body_field, render_list, render_one, require_int
from services.core import (
    create_record, get_or_404, mutate, credit_available_invoiced_only,
)
from util import CLOCK, parse_dt
from datetime import timedelta

bp = Blueprint("accounts", __name__)

ACCOUNT_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "CreditAnalyst", "Contractor"]
LIEN_CURE_PERIOD_DAYS = 10


def _account_or_404(rid):
    return get_or_404("contractor_accounts", rid, ERR_ACCOUNT_NOT_FOUND)


def _job_or_404(rid):
    return get_or_404("job_accounts", rid, ERR_JOB_ACCOUNT_NOT_FOUND)


# ---------------------------------------------------------------------------
# Contractor accounts
# ---------------------------------------------------------------------------

@bp.post("/roofing/contractor-accounts")
def create_account():
    authorized(["CreditAnalyst", "PlatformAdmin"])
    data = body()
    tier = data.get("pricing_tier", "STANDARD")
    if tier not in ("STANDARD", "PREFERRED", "VOLUME"):
        raise_error(ERR_INVALID_REQUEST, "pricing_tier must be STANDARD, PREFERRED or VOLUME")
    certs = data.get("manufacturer_certifications") or []
    if not isinstance(certs, list):
        raise_error(ERR_INVALID_REQUEST, "manufacturer_certifications must be a list")
    rec = create_record("contractor_accounts", {
        "company_name": body_field(data, "company_name", required=True),
        "credit_limit_cents": require_int(body_field(data, "credit_limit_cents", required=True),
                                          "credit_limit_cents", minimum=0),
        "open_balance_cents": 0,
        "pending_delivery_hold_cents": 0,
        "lien_hold_cents": 0,
        "pricing_tier": tier,
        "manufacturer_certifications": certs,
        "status": "ACTIVE",
    })
    return render_one("contractor_accounts", rec, status=201)


@bp.get("/roofing/contractor-accounts")
def list_accounts():
    caller = authorized(["PlatformAdmin", "BranchManager", "SalesRep", "CreditAnalyst"])
    return render_list(caller, "contractor_accounts",
                       filters={"status": request.args.get("status")})


@bp.get("/roofing/contractor-accounts/<rid>")
def get_account(rid):
    caller = authorized(ACCOUNT_READ_ROLES)
    rec = _account_or_404(rid)
    check_contractor_owns(caller, rec["id"])
    return render_one("contractor_accounts", rec)


@bp.get("/roofing/contractor-accounts/<rid>/statement")
def get_statement(rid):
    """Post-delivery position: credit_available uses the invoiced_only variant
    (pending delivery hold excluded) per PRD 2.8."""
    caller = authorized(["CreditAnalyst", "Contractor", "PlatformAdmin"])
    rec = _account_or_404(rid)
    check_contractor_owns(caller, rec["id"])
    return success_object({
        "open_balance_cents": rec["open_balance_cents"],
        "pending_delivery_hold_cents": rec["pending_delivery_hold_cents"],
        "lien_hold_cents": rec["lien_hold_cents"],
        "credit_available_cents": credit_available_invoiced_only(rec),
    })


@bp.post("/roofing/contractor-accounts/<rid>/suspend")
def suspend_account(rid):
    authorized(["CreditAnalyst"])
    rec = _account_or_404(rid)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_ACCOUNT_NOT_ACTIVE, "suspend requires status ACTIVE")
    rec["status"] = "SUSPENDED"
    mutate(rec)
    return render_one("contractor_accounts", rec)


@bp.post("/roofing/contractor-accounts/<rid>/reinstate")
def reinstate_account(rid):
    authorized(["CreditAnalyst"])
    rec = _account_or_404(rid)
    if rec["status"] != "SUSPENDED":
        raise_error(ERR_ACCOUNT_NOT_SUSPENDED, "reinstate requires status SUSPENDED")
    if rec["open_balance_cents"] >= rec["credit_limit_cents"]:
        raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                    "open_balance_cents must be strictly below credit_limit_cents")
    rec["status"] = "ACTIVE"
    mutate(rec)
    return render_one("contractor_accounts", rec)


@bp.post("/roofing/contractor-accounts/<rid>/payments")
def post_payment(rid):
    """Oldest unpaid invoice first (created_at ASC), optional job direction
    (PRD 3.7, job_account_aging)."""
    caller = authorized(["CreditAnalyst", "Contractor"])
    account = _account_or_404(rid)
    check_contractor_owns(caller, account["id"])
    data = body()
    amount = require_int(body_field(data, "amount_cents", required=True),
                         "amount_cents", minimum=1)
    job_filter = data.get("job_account_id")
    if job_filter is not None:
        job = _job_or_404(job_filter)
        if job["contractor_account_id"] != account["id"]:
            raise_error(ERR_JOB_ACCOUNT_NOT_FOUND,
                        "job account does not belong to this contractor account")

    candidates = []
    for order in db["orders"].values():
        job = db["job_accounts"].get(order["job_account_id"])
        if job is None or job["contractor_account_id"] != account["id"]:
            continue
        if order["payment_status"] != "INVOICED":
            continue
        if job_filter is not None and order["job_account_id"] != job_filter:
            continue
        candidates.append(order)
    candidates.sort(key=lambda o: (o["created_at"], o["_seq"]))

    remaining = amount
    applied_to_order_ids = []
    for order in candidates:
        if remaining <= 0:
            break
        outstanding = order.get("_invoice_outstanding_cents", order["total_cents"])
        if outstanding <= 0:
            continue
        pay = min(remaining, outstanding)
        remaining -= pay
        outstanding -= pay
        order["_invoice_outstanding_cents"] = outstanding
        if outstanding == 0:
            order["payment_status"] = "PAID"
        applied_to_order_ids.append(order["id"])
        job = db["job_accounts"].get(order["job_account_id"])
        if job is not None:
            job["job_balance_cents"] = max(0, job["job_balance_cents"] - pay)
            mutate(job)
        mutate(order)

    account["open_balance_cents"] = max(0, account["open_balance_cents"] - amount)
    mutate(account)
    return success_object({
        "applied_to_order_ids": applied_to_order_ids,
        "new_open_balance_cents": account["open_balance_cents"],
    }, status=201)


# ---------------------------------------------------------------------------
# Job accounts
# ---------------------------------------------------------------------------

@bp.post("/roofing/contractor-accounts/<rid>/job-accounts")
def create_job_account(rid):
    caller = authorized(["CreditAnalyst", "Contractor", "PlatformAdmin"])
    account = _account_or_404(rid)
    check_contractor_owns(caller, account["id"])
    data = body()
    rec = create_record("job_accounts", {
        "contractor_account_id": account["id"],
        "job_name": body_field(data, "job_name", required=True),
        "site_address": body_field(data, "site_address", required=True),
        "job_balance_cents": 0,
        "lien_status": "NONE",
        "lien_notice_amount_cents": 0,
        "notice_filed_at": None,
    })
    return render_one("job_accounts", rec, status=201)


@bp.get("/roofing/contractor-accounts/<rid>/job-accounts")
def list_job_accounts(rid):
    caller = authorized(ACCOUNT_READ_ROLES)
    account = _account_or_404(rid)
    check_contractor_owns(caller, account["id"])
    jobs = [j for j in db["job_accounts"].values()
            if j["contractor_account_id"] == account["id"]]
    return render_list(caller, "job_accounts", base_records=jobs)


@bp.get("/roofing/job-accounts/<rid>")
def get_job_account(rid):
    caller = authorized(ACCOUNT_READ_ROLES)
    rec = _job_or_404(rid)
    check_contractor_owns(caller, rec["contractor_account_id"])
    return render_one("job_accounts", rec)


# ---------------------------------------------------------------------------
# Lien lifecycle (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/roofing/job-accounts/<rid>/file-lien-notice")
def file_lien_notice(rid):
    authorized(["CreditAnalyst"])
    job = _job_or_404(rid)
    if job["lien_status"] != "NONE":
        raise_error(ERR_LIEN_ALREADY_ACTIVE, "a lien notice is already active for this job")
    if job["job_balance_cents"] <= 0:
        raise_error(ERR_NO_OUTSTANDING_BALANCE, "lien notice requires job_balance_cents > 0")
    data = body()
    amount = require_int(body_field(data, "lien_notice_amount_cents", required=True),
                         "lien_notice_amount_cents")
    if amount <= 0 or amount > job["job_balance_cents"]:
        raise_error(ERR_INVALID_LIEN_AMOUNT,
                    "lien_notice_amount_cents must be > 0 and <= job_balance_cents")
    job["lien_status"] = "NOTICE_FILED"
    job["lien_notice_amount_cents"] = amount
    job["notice_filed_at"] = CLOCK.now_ts()
    mutate(job)
    account = db["contractor_accounts"].get(job["contractor_account_id"])
    if account is not None:
        account["lien_hold_cents"] += amount
        mutate(account)
    return render_one("job_accounts", job)


@bp.post("/roofing/job-accounts/<rid>/record-lien")
def record_lien(rid):
    authorized(["CreditAnalyst"])
    job = _job_or_404(rid)
    if job["lien_status"] != "NOTICE_FILED":
        raise_error(ERR_LIEN_NOT_IN_NOTICE, "record-lien requires lien_status NOTICE_FILED")
    deadline = parse_dt(job["notice_filed_at"]) + timedelta(days=LIEN_CURE_PERIOD_DAYS)
    if CLOCK.now() < deadline:
        raise_error(ERR_LIEN_CURE_PERIOD_ACTIVE,
                    "cure period runs ten days from notice_filed_at")
    job["lien_status"] = "LIEN_RECORDED"
    mutate(job)
    account = db["contractor_accounts"].get(job["contractor_account_id"])
    if account is not None and account["status"] != "LIEN_DEFAULT":
        account["status"] = "LIEN_DEFAULT"
        mutate(account)
    return render_one("job_accounts", job)


@bp.post("/roofing/job-accounts/<rid>/release-lien")
def release_lien(rid):
    authorized(["CreditAnalyst"])
    job = _job_or_404(rid)
    if job["lien_status"] not in ("NOTICE_FILED", "LIEN_RECORDED"):
        raise_error(ERR_LIEN_NOT_ACTIVE,
                    "release-lien requires NOTICE_FILED or LIEN_RECORDED")
    if job["job_balance_cents"] != 0:
        raise_error(ERR_BALANCE_STILL_OUTSTANDING,
                    "release-lien requires job_balance_cents == 0")
    account = db["contractor_accounts"].get(job["contractor_account_id"])
    if account is not None:
        account["lien_hold_cents"] -= job["lien_notice_amount_cents"]
    job["lien_status"] = "RELEASED"
    job["lien_notice_amount_cents"] = 0
    job["notice_filed_at"] = None
    mutate(job)
    if account is not None:
        still_active = any(
            j["contractor_account_id"] == account["id"]
            and j["lien_status"] in ("NOTICE_FILED", "LIEN_RECORDED")
            for j in db["job_accounts"].values()
        )
        if not still_active and account["status"] == "LIEN_DEFAULT":
            account["status"] = "ACTIVE"
        mutate(account)
    return render_one("job_accounts", job)
