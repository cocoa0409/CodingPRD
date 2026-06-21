"""License pool & e-book loan endpoints (PRD §3.9)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from middleware import (
    authenticate, require_roles, require_owner_if_patron,
    ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER,
)
from services import serialize, derive
from routes import helpers
from timeutil import add_days

bp = Blueprint("license_pools", __name__)

EBOOK_STATUSES = {"ACTIVE", "RETURNED", "EXPIRED"}


# ---- LicensePool ---------------------------------------------------------

@bp.post("/library/license-pools")
def create_pool():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["title_id", "total_licenses"])
    title_id = helpers.require_string(body, "title_id")
    total_licenses = helpers.required_int(body, "total_licenses")
    if total_licenses < 0:
        raise errors.invalid_request("total_licenses must be >= 0.")

    helpers.find_or_404(db.titles, title_id)

    record = {
        "title_id": title_id,
        "total_licenses": total_licenses,
        "loan_term_days": helpers.optional_int(body, "loan_term_days", 14),
        "loaned_licenses": 0,
        "available_licenses": total_licenses,
    }
    db.stamp_create(record)
    db.license_pools[record["id"]] = record
    return response.object_response(serialize.license_pool(record), status=201)


@bp.get("/library/license-pools/<pid>")
def get_pool(pid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.license_pools, pid)
    derive.reconcile_pool(record)
    return response.object_response(serialize.license_pool(record))


@bp.get("/library/license-pools")
def list_pools():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    title_id = request.args.get("title_id")
    records = [
        p for p in db.license_pools.values()
        if title_id is None or p["title_id"] == title_id
    ]
    for p in records:
        derive.reconcile_pool(p)
    return helpers.list_response(records, serialize.license_pool)


@bp.post("/library/license-pools/<pid>/run-expiry")
def run_expiry(pid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    pool = helpers.find_or_404(db.license_pools, pid)
    now = clock.now()

    for e in db.ebook_loans.values():
        if e["pool_id"] == pid and e["status"] == "ACTIVE" and now >= e["expires_at"]:
            e["status"] = "EXPIRED"
            db.touch(e)

    derive.reconcile_pool(pool)
    return response.object_response(serialize.license_pool(pool))


# ---- EbookLoan -----------------------------------------------------------

@bp.post("/library/ebook-loans")
def checkout_ebook():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["pool_id", "patron_id"])
    pool_id = helpers.require_string(body, "pool_id")
    patron_id = helpers.require_string(body, "patron_id")

    # existence (priority 3), left-to-right: pool then patron
    pool = helpers.find_or_404(db.license_pools, pool_id)
    patron = helpers.find_or_404(db.patrons, patron_id)

    # ownership (priority 2): a Patron may only check out for themselves
    require_owner_if_patron(caller, patron_id)

    # priority 7: card ACTIVE
    if patron["card_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Patron card is not ACTIVE.")

    # priority 8: patron CLEAR
    derive.reconcile_patron(patron)
    if patron["borrowing_status"] == "BLOCKED":
        raise errors.ApiError(errors.ERR_PATRON_BLOCKED, 409, "Patron is BLOCKED.")

    # priority 11: at least one license available
    derive.reconcile_pool(pool)
    if pool["available_licenses"] < 1:
        raise errors.ApiError(errors.ERR_NO_LICENSE_AVAILABLE, 409, "No license available.")

    now = clock.now()
    record = {
        "pool_id": pool_id,
        "patron_id": patron_id,
        "status": "ACTIVE",
        "checked_out_at": now,
        "expires_at": add_days(now, pool["loan_term_days"]),
    }
    db.stamp_create(record)
    db.ebook_loans[record["id"]] = record

    derive.reconcile_pool(pool)
    return response.object_response(serialize.ebook_loan(record), status=201)


@bp.get("/library/ebook-loans/<eid>")
def get_ebook(eid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.ebook_loans, eid)
    return response.object_response(serialize.ebook_loan(record))


@bp.get("/library/ebook-loans")
def list_ebooks():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    pool_id = request.args.get("pool_id")
    patron_id = request.args.get("patron_id")
    status = helpers.enum_filter("status", EBOOK_STATUSES)
    records = [
        e for e in db.ebook_loans.values()
        if (pool_id is None or e["pool_id"] == pool_id)
        and (patron_id is None or e["patron_id"] == patron_id)
        and (status is None or e["status"] == status)
    ]
    return helpers.list_response(records, serialize.ebook_loan)


@bp.post("/library/ebook-loans/<eid>/return")
def return_ebook(eid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    record = helpers.find_or_404(db.ebook_loans, eid)

    # ownership (priority 2)
    require_owner_if_patron(caller, record["patron_id"])

    # state (priority 5)
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("E-book loan is not ACTIVE.")

    record["status"] = "RETURNED"
    db.touch(record)
    derive.reconcile_pool_by_id(record["pool_id"])
    return response.object_response(serialize.ebook_loan(record))
