"""Corporate account endpoints."""
from flask import Blueprint

import db
import errors
from auth import require_account_owner, require_roles
from respond import success
from services.domain import get_or_404
from validate import apply_filters, json_body, paginate, req_int, req_str

bp = Blueprint("corporate_accounts", __name__)


@bp.post("/chair-massage/corporate-accounts")
@require_roles("PlatformAdmin")
def create_account():
    body = json_body()
    company = req_str(body, "company_name")
    email = req_str(body, "billing_email")
    region_id = req_str(body, "region_id")
    credit = req_int(body, "credit_limit_cents", min_v=0)
    get_or_404("regions", region_id, "Region")
    account = db.stamp_new({
        "id": db.new_id(),
        "company_name": company,
        "billing_email": email,
        "region_id": region_id,
        "status": "ACTIVE",
        "credit_limit_cents": credit,
        "outstanding_balance_cents": 0,
        "lifetime_billed_cents": 0,
    })
    db.insert("corporate_accounts", account)
    return success(db.public(account), status=201)


@bp.get("/chair-massage/corporate-accounts")
@require_roles("PlatformAdmin")
def list_accounts():
    items = db.all_sorted("corporate_accounts")
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "region_id": (lambda e: e["region_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/corporate-accounts/<aid>")
@require_roles("PlatformAdmin", "Organizer")
def get_account(aid):
    account = get_or_404("corporate_accounts", aid, "CorporateAccount")
    require_account_owner(account["id"])
    return success(db.public(account))


@bp.post("/chair-massage/corporate-accounts/<aid>/suspend")
@require_roles("PlatformAdmin")
def suspend_account(aid):
    account = get_or_404("corporate_accounts", aid, "CorporateAccount")
    if account["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE account can be suspended")
    account["status"] = "SUSPENDED"
    db.touch(account)
    for program in db.stores["wellness_programs"].values():
        if program["corporate_account_id"] == aid and program["status"] == "ACTIVE":
            program["status"] = "PAUSED"
            program["next_occurrence_date"] = None
            db.touch(program)
    return success(db.public(account))


@bp.post("/chair-massage/corporate-accounts/<aid>/reactivate")
@require_roles("PlatformAdmin")
def reactivate_account(aid):
    account = get_or_404("corporate_accounts", aid, "CorporateAccount")
    if account["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED account can be reactivated")
    account["status"] = "ACTIVE"
    db.touch(account)
    return success(db.public(account))


@bp.post("/chair-massage/corporate-accounts/<aid>/close")
@require_roles("PlatformAdmin")
def close_account(aid):
    account = get_or_404("corporate_accounts", aid, "CorporateAccount")
    if account["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED account can be closed")
    if account["outstanding_balance_cents"] != 0:
        raise errors.invalid_state("Account cannot be closed with a non-zero outstanding balance")
    account["status"] = "CLOSED"
    db.touch(account)
    for program in db.stores["wellness_programs"].values():
        if program["corporate_account_id"] == aid and program["status"] == "PAUSED":
            program["status"] = "TERMINATED"
            program["next_occurrence_date"] = None
            db.touch(program)
    return success(db.public(account))


@bp.get("/chair-massage/corporate-accounts/<aid>/wellness-programs")
@require_roles("PlatformAdmin", "Organizer")
def list_account_programs(aid):
    get_or_404("corporate_accounts", aid, "CorporateAccount")
    require_account_owner(aid)
    items = [p for p in db.all_sorted("wellness_programs")
             if p["corporate_account_id"] == aid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/corporate-accounts/<aid>/bookings")
@require_roles("PlatformAdmin", "Organizer")
def list_account_bookings(aid):
    get_or_404("corporate_accounts", aid, "CorporateAccount")
    require_account_owner(aid)
    items = [b for b in db.all_sorted("bookings") if b["corporate_account_id"] == aid]
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "billing_status": (lambda e: e["billing_status"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/corporate-accounts/<aid>/invoices")
@require_roles("PlatformAdmin", "Organizer")
def list_account_invoices(aid):
    get_or_404("corporate_accounts", aid, "CorporateAccount")
    require_account_owner(aid)
    items = [i for i in db.all_sorted("invoices") if i["corporate_account_id"] == aid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)
