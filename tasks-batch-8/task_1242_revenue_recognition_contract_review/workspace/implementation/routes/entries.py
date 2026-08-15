from flask import Blueprint, request

from db import STORE, mark, sort_created
from errors import ApiError, ERR_NOT_FOUND, ERR_ENTRY_LOCKED
from response import ok_object, ok_list
import serializers as ser
import services as svc
from clock import CLOCK
from validate import require_roles, body, opt_str, pagination

bp = Blueprint("entries", __name__)

ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


@bp.get("/revrec/revenue-entries/<entry_id>")
def get_entry(entry_id):
    require_roles(*ALL_READ)
    e = STORE.entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "entry_id does not identify an existing revenue entry")
    return ok_object(ser.entry(e))


@bp.get("/revrec/revenue-entries")
def list_entries():
    require_roles(*ALL_READ)
    limit, offset = pagination()
    items = list(STORE.entries.values())
    for f in ("contract_id", "pob_id", "accounting_period_id", "entry_type", "reversed_entry_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if str(e.get(f)) == v]
    items = sort_created(items)
    total = len(items)
    return ok_list([ser.entry(e) for e in items[offset:offset + limit]], limit, offset, total)


@bp.post("/revrec/revenue-entries/<entry_id>/reverse")
def reverse_entry(entry_id):
    require_roles("RevenueAccountant")
    e = STORE.entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "entry_id does not identify an existing revenue entry")
    body()  # optional reason; not persisted on the entry
    if e["status"] == "LOCKED":
        raise ApiError(ERR_ENTRY_LOCKED, 409, "a LOCKED entry cannot be reversed")
    svc.require_open_period(CLOCK.today())
    c = STORE.contracts.get(e["contract_id"])
    p = STORE.pobs.get(e["pob_id"])
    rec = svc.post_entry(c, p, "REVERSAL", "REVERSAL", -e["amount_cents"], CLOCK.today(),
                         reversed_entry_id=entry_id)
    if c is not None:
        mark(c)
        svc.evaluate_auto_completion(c)
    return ok_object(ser.entry(rec), 201)
