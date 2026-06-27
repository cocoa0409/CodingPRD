"""ReturnedItem routes: get, list, recover, write-off (PRD §3.9).

Recovery is a waterfall against the fixed total_owed (face + return_fee), fixed
at return time and never re-derived. Overpayment is refused outright, not
silently capped."""
from flask import Blueprint, request

import errors
from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, touch, serialize
from helpers import get_json_body, parse_pagination, paginate, sort_by_creation, require_int
import lookups
from response import ok, listed
from services import calculations as calc
from services import domain

bp = Blueprint("returned_items", __name__)


@bp.route("/returned-items/<rid>", methods=["GET"])
def get_returned_item(rid):
    require_auth(BOTH)
    item = lookups.get_returned_item(rid)
    return ok(serialize(item))


@bp.route("/returned-items", methods=["GET"])
def list_returned_items():
    require_auth(BOTH)
    limit, offset = parse_pagination()
    items = list(db.returned_items.values())

    for field in ("transaction_id", "customer_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]

    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(r) for r in page], limit, offset, total)


@bp.route("/returned-items/<rid>/recover", methods=["POST"])
def recover_returned_item(rid):
    require_auth(BOTH)
    item = lookups.get_returned_item(rid)
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")

    # priority 4: must be OUTSTANDING or PARTIALLY_RECOVERED
    if item["status"] not in ("OUTSTANDING", "PARTIALLY_RECOVERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "ReturnedItem is not recoverable")

    total_owed = item["_total_owed"]
    remaining = total_owed - item["recovered_cents"]

    # priority 14: amount must be > 0 and not exceed remaining (no silent cap)
    if amount_cents <= 0 or amount_cents > remaining:
        raise errors.err(
            errors.ERR_RECOVERY_OVERPAYMENT,
            "Recovery amount must be > 0 and not exceed the remaining balance",
        )

    item["recovered_cents"] += amount_cents
    if item["recovered_cents"] == total_owed:
        item["status"] = "RECOVERED"
    else:
        item["status"] = "PARTIALLY_RECOVERED"
    touch(item)

    # cascade: customer outstanding_recovery_cents -= applied
    customer = lookups.get_customer(item["customer_id"])
    customer["outstanding_recovery_cents"] -= amount_cents
    touch(customer)

    # on full recovery: linked Transaction.settlement_state -> RECOVERED
    if item["status"] == "RECOVERED":
        txn = lookups.get_transaction(item["transaction_id"])
        txn["settlement_state"] = "RECOVERED"
        touch(txn)

    return ok(serialize(item))


@bp.route("/returned-items/<rid>/write-off", methods=["POST"])
def write_off_returned_item(rid):
    require_auth(MANAGER_ONLY)
    item = lookups.get_returned_item(rid)

    # priority 4: must be OUTSTANDING or PARTIALLY_RECOVERED
    if item["status"] not in ("OUTSTANDING", "PARTIALLY_RECOVERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "ReturnedItem is not writable-off")

    remaining = item["_total_owed"] - item["recovered_cents"]

    item["status"] = "WRITTEN_OFF"
    touch(item)

    # cascade: clear remaining from customer outstanding; confirm risk delta
    customer = lookups.get_customer(item["customer_id"])
    customer["outstanding_recovery_cents"] -= remaining
    touch(customer)
    domain.apply_risk_delta(customer, calc.WRITE_OFF_RISK_DELTA)

    return ok(serialize(item))
