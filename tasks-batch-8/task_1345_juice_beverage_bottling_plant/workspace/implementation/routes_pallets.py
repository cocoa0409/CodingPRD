"""PalletAccount / PalletEntry endpoints."""
from flask import Blueprint

from domain import ser_pallet_account, ser_pallet_entry
from errors import err
from services import post_pallet_entry
from store import db
from util import body, ok, paginate, req_field, require_any, require_roles

bp = Blueprint("pallets", __name__)


def get_pallet_account_or_404(account_id):
    account = db.pallet_accounts.get(account_id)
    if account is None:
        raise err("ERR_PALLET_ACCOUNT_NOT_FOUND", f"PalletAccount {account_id} not found")
    return account


@bp.get("/v1/pallet-accounts/<account_id>")
def get_pallet_account(account_id):
    require_any()
    return ok(ser_pallet_account(get_pallet_account_or_404(account_id)))


@bp.post("/v1/pallet-accounts/<account_id>/returns")
def post_return(account_id):
    require_roles("WarehouseLead")
    account = get_pallet_account_or_404(account_id)
    data = body()
    pallet_count = req_field(data, "pallet_count", "int")
    if pallet_count <= 0:
        raise err("ERR_INVALID_REQUEST", "pallet_count must be a positive integer")
    outstanding = (account["pallets_out_total"] - account["pallets_returned_total"]
                   - account["pallets_converted_total"])
    if pallet_count > outstanding:
        raise err("ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING",
                  "Return count exceeds pallets outstanding")
    entry = post_pallet_entry(account, "RETURN", pallet_count)
    customer = db.customers.get(account["customer_id"])
    if customer is not None:
        from store import touch
        customer["outstanding_balance_cents"] -= pallet_count * customer["pallet_deposit_cents"]
        touch(customer)
    return ok(ser_pallet_entry(entry), 201)


@bp.get("/v1/pallet-accounts/<account_id>/entries")
def list_entries(account_id):
    require_any()
    get_pallet_account_or_404(account_id)
    items = [e for e in db.pallet_entries.values() if e["pallet_account_id"] == account_id]
    items.sort(key=lambda e: (e["entry_date"], e["_seq"]))
    # chronological ordering is the list's defined order; paginate preserves it
    from util import pagination, ok_list
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser_pallet_entry(e) for e in page], limit, offset, total)
