"""Joint-account cost entries (PRD 3.5)."""
from flask import Blueprint

from calc import get_afe, get_cost_entry, get_well, guard_terminal
from common import ok, ok_list, touch
from errors import fail
from store import by_created, insert, out_cost, rows
from validate import (READ_INTERNAL, ROLE_JIA, authenticate, authorize, body,
                      filt, pagination, present, require, v_cents, v_date,
                      v_enum, v_id, window)

bp = Blueprint("costs", __name__)

COST_CATEGORIES = ("DRILLING", "COMPLETION", "LEASE_OPERATING", "WORKOVER",
                   "PLUGGING")
COST_CLASSES = ("CAPITAL", "OPERATING")


@bp.route("/wells/<well_id>/cost-entries", methods=["POST"])
def book_cost(well_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["cost_category", "cost_class", "amount_cents", "incurred_date"])
    cost_category = v_enum(data, "cost_category", COST_CATEGORIES)
    cost_class = v_enum(data, "cost_class", COST_CLASSES)
    amount_cents = v_cents(data, "amount_cents", strictly_positive=True)
    incurred_date = v_date(data, "incurred_date")
    afe_id = v_id(data, "afe_id")
    paid_date = v_date(data, "paid_date")

    well = get_well(well_id)
    afe = get_afe(afe_id) if afe_id is not None else None
    guard_terminal("well", well)
    if afe is not None and afe["well_id"] != well["id"]:
        fail("ERR_COST_AFE_MISMATCH")

    entry = insert("cost_entries", {
        "well_id": well["id"],
        "afe_id": afe["id"] if afe is not None else None,
        "cost_category": cost_category,
        "cost_class": cost_class,
        "amount_cents": amount_cents,
        "incurred_date": incurred_date,
        "paid_date": paid_date,
        "cost_status": "PAID" if paid_date is not None else "ACCRUED",
    })
    return ok(out_cost(entry), 201)


@bp.route("/cost-entries", methods=["GET"])
def list_costs():
    authenticate()
    authorize(*READ_INTERNAL)
    limit, offset = pagination()
    found = rows("cost_entries")
    for name in ("well_id", "afe_id", "cost_status", "cost_class"):
        value = filt(name)
        if value is not None:
            found = [c for c in found if c[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_cost(c) for c in page], limit, offset, total)


@bp.route("/cost-entries/<cost_entry_id>", methods=["GET"])
def read_cost(cost_entry_id):
    authenticate()
    authorize(*READ_INTERNAL)
    return ok(out_cost(get_cost_entry(cost_entry_id)))


@bp.route("/cost-entries/<cost_entry_id>/payment", methods=["POST"])
def pay_cost(cost_entry_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["paid_date"])
    paid_date = v_date(data, "paid_date")
    entry = get_cost_entry(cost_entry_id)
    entry["paid_date"] = paid_date
    entry["cost_status"] = "PAID"
    touch(entry)
    return ok(out_cost(entry))
