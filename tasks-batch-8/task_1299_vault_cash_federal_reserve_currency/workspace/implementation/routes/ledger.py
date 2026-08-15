"""CashLedgerEntry endpoints."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import public, append_ledger
from util import body, required, as_int, as_str, as_enum, as_ymd, pagination_args

bp = Blueprint("ledger", __name__)

BUCKETS = {"FIT", "UNFIT"}


@bp.post("/vault-cash/cash-ledger-entries")
def create_entry():
    principal = auth(["VaultCustodian", "CashOperationsAdmin"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    if site_id not in DB["vault_sites"]:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    require_site_scope(principal, site_id)
    business_date = as_ymd(required(data, "business_date"), "business_date")
    amount = as_int(required(data, "signed_amount_cents"), "signed_amount_cents")
    bucket = as_enum(data.get("bucket", "FIT"), "bucket", BUCKETS)
    note = data.get("note", "")
    if note is None:
        note = ""
    note = as_str(note, "note")

    # Manual posts are always ADJUSTMENT; backdated business dates are allowed.
    entry = append_ledger(site_id, business_date, "ADJUSTMENT", amount, bucket, note)
    return ok(public(entry), status=201)


@bp.get("/vault-cash/cash-ledger-entries")
def list_entries():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    business_date = request.args.get("business_date")
    entry_type = request.args.get("entry_type")
    rows = list(DB["cash_ledger_entries"].values())
    if site_id is not None:
        rows = [e for e in rows if e["site_id"] == site_id]
    if business_date is not None:
        rows = [e for e in rows if e["business_date"] == business_date]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [e for e in rows if e["site_id"] == principal.home_site_id]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(rows)
    return ok_list([public(e) for e in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/cash-ledger-entries/<entryId>")
def get_entry(entryId):
    principal = auth(ALL_ROLES)
    entry = DB["cash_ledger_entries"].get(entryId)
    if entry is None:
        raise ApiError(
            "ERR_CASH_LEDGER_ENTRY_NOT_FOUND", 404, "Ledger entry not found"
        )
    require_site_scope(principal, entry["site_id"])
    return ok(public(entry))
