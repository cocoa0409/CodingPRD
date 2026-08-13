"""CommissionEntry endpoints: list, get, resolve-variance."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import resolve_variance, ser_entry
from util import apply_filters, as_nonneg_int, get_body, is_int, req, respond_list

bp = Blueprint("entries", __name__)


@bp.get("/agency/commission-entries")
def list_entries():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["entries"].values(),
        {
            "policy_id": "policy_id",
            "producer_id": "producer_id",
            "schedule_id": "schedule_id",
            "matched_statement_id": "matched_statement_id",
            "source_entry_id": "source_entry_id",
            "status": "status",
            "entry_type": "entry_type",
        },
    )
    return respond_list(items, ser_entry)


@bp.get("/agency/commission-entries/<entryId>")
def get_entry(entryId):
    auth(ALL_ROLES)
    e = DB["entries"].get(entryId)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CommissionEntry not found")
    return ok(ser_entry(e))


@bp.post("/agency/commission-entries/<entryId>/resolve-variance")
def resolve(entryId):
    auth(ADMIN_ACCT)
    e = DB["entries"].get(entryId)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CommissionEntry not found")
    # Priority 4: state admissibility.
    if e["status"] != "VARIANCE":
        raise ApiError("ERR_INVALID_STATE", 409, "Entry is not in VARIANCE")
    data = get_body()
    accept = data.get("accept_amount_cents")
    # Priority 10: shape (accept_amount_cents must be zero or greater).
    accept = as_nonneg_int(req(data, "accept_amount_cents"), "accept_amount_cents")
    resolve_variance(e, accept)
    return ok(ser_entry(e))
