"""AssessmentInvoice endpoints: create, list, get, issue, pay, file-lien."""
from decimal import Decimal

from flask import Blueprint

import db
from db import store, new_id, new_common, touch, iso_out
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services import ledger, billing

bp = Blueprint("invoices", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser"]

_CREATE_SCHEMA = {
    "water_account_id": ("string", True, None, None),
    "season_id": ("string", True, None, None),
}


@bp.post("/district/assessment-invoices")
def create_invoice():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    require_roles(["DistrictAdmin"])
    account = resolve_fk(store.water_accounts, body["water_account_id"], "water_account_id")
    season = resolve_fk(store.seasons, body["season_id"], "season_id")
    for inv in store.invoices.values():
        if inv["water_account_id"] == account["id"] and inv["season_id"] == season["id"]:
            raise ApiError("ERR_DUPLICATE_INVOICE", 409,
                           "An invoice already exists for this account and season")
    snapshot = season["billing_method"]
    alloc = ledger.find_allocation(account["id"], season["id"])
    acreage, toll = billing.compute_lines(account, season, alloc)
    inv = new_common({
        "id": new_id(),
        "water_account_id": account["id"],
        "season_id": season["id"],
        "billing_method_snapshot": snapshot,
        "acreage_line_amount": acreage,
        "toll_line_amount": toll,
        "penalty_line_amount": Decimal("0"),
        "total_amount": acreage + toll,
        "issued_at": None,
        "due_date": None,
        "_due_dt": None,
        "paid_at": None,
        "status": "DRAFT",
    })
    store.invoices[inv["id"]] = inv
    return created(inv)


@bp.get("/district/assessment-invoices")
def list_invoices():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.invoices.values())
    for f in ("water_account_id", "season_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/assessment-invoices/<iid>")
def get_invoice(iid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.invoices, iid))


@bp.post("/district/assessment-invoices/<iid>/issue")
def issue_invoice(iid):
    uid, role = get_context()
    body = parse_body({"due_date": ("datetime", True, None, None)}, allow_empty=False)
    require_roles(["DistrictAdmin"])
    inv = require_path_entity(store.invoices, iid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_INVOICE_STATE", 409,
                       "Only a DRAFT invoice may be issued")
    inv["status"] = "ISSUED"
    inv["issued_at"] = iso_out(db.LOGICAL_CLOCK)
    inv["due_date"] = iso_out(body["_due_date_dt"])
    inv["_due_dt"] = body["_due_date_dt"]
    touch(inv)
    return ok(inv)


@bp.post("/district/assessment-invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = get_context()
    parse_body({})
    require_roles(["WaterUser"])
    inv = require_path_entity(store.invoices, iid)
    if uid != inv["water_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "WaterUser may pay only their own invoices")
    if inv["status"] not in ("ISSUED", "DELINQUENT", "LIEN_FILED"):
        raise ApiError("ERR_INVALID_INVOICE_STATE", 409,
                       "Invoice in status %s cannot be paid" % inv["status"])
    was_liened = inv["status"] == "LIEN_FILED"
    inv["status"] = "PAID"
    inv["paid_at"] = iso_out(db.LOGICAL_CLOCK)
    touch(inv)
    if was_liened:
        # Release the lien hold when no other LIEN_FILED invoice remains.
        remaining = any(i["water_account_id"] == inv["water_account_id"]
                        and i["status"] == "LIEN_FILED" and i["id"] != inv["id"]
                        for i in store.invoices.values())
        account = store.water_accounts.get(inv["water_account_id"])
        if not remaining and account is not None and account["status"] == "SUSPENDED":
            account["status"] = "ACTIVE"
            touch(account)
    return ok(inv)


@bp.post("/district/assessment-invoices/<iid>/file-lien")
def file_lien(iid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    inv = require_path_entity(store.invoices, iid)
    if inv["status"] != "DELINQUENT":
        raise ApiError("ERR_INVALID_INVOICE_STATE", 409,
                       "Only a DELINQUENT invoice may be lien-filed")
    inv["status"] = "LIEN_FILED"
    touch(inv)
    account = store.water_accounts.get(inv["water_account_id"])
    if account is not None:
        account["status"] = "SUSPENDED"
        touch(account)
    return ok(inv)
