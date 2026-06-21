"""Logical clock endpoints + maturation / reserve-release sweeps (PRD §3.5,
§3.10, §3.12)."""
from flask import Blueprint

from common import get_json_body, require_fields, parse_iso8601
from db import db
from middleware import get_identity, require_roles, ROLE_REVIEWER, ROLE_FINANCE
from response import success
from services.entity import touch  # noqa: F401  (used by order maturation below)
from services.order import final_net
from services.ledger import HOLD_PENDING, HOLD_AVAILABLE
from services.seller import refresh_seller_derived
from services.reserve import release_reserve_row

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    db.set_clock(dt)
    return success({})


@bp.post("/_clock/advance")
def advance():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    db.set_clock(dt)

    affected_sellers = set()

    # ---- Maturation sweep (PRD §3.5) ----
    # An order matures when settlement PENDING, current >= settled_at +
    # maturation_days, and clawback_status NONE.
    for order in db.orders.values():
        if order["settlement_status"] != "PENDING":
            continue
        if order["clawback_status"] != "NONE":
            continue
        schedule = db.fee_schedules.get(order["fee_schedule_id"])
        if schedule is None:
            continue
        settled_at = parse_iso8601(order["settled_at"])
        due = settled_at + _days(schedule["maturation_days"])
        if dt >= due:
            order["net_earnings_cents"] = final_net(order, schedule)
            _flip_proceeds_available(order)
            order["settlement_status"] = "AVAILABLE"
            order["matured_at"] = db.now_iso()
            touch(order)
            affected_sellers.add(order["seller_id"])

    # ---- Reserve-release sweep (PRD §3.10) ----
    # Release every OPEN reserve whose release_due_at has elapsed.
    for reserve in db.reserves.values():
        if reserve["reserve_status"] != "OPEN":
            continue
        due_str = reserve.get("release_due_at")
        if not due_str:
            continue
        if dt >= parse_iso8601(due_str):
            seller = db.sellers.get(reserve["seller_id"])
            if seller is not None:
                release_reserve_row(seller, reserve)
                affected_sellers.add(reserve["seller_id"])

    # Reconcile affected sellers' derived balances. Do NOT bump seller.version
    # here: PRD §2.9 reserves version semantics for the payout-release OCC, and
    # derived balances are pure functions of the ledger recomputed on read.
    for seller_id in affected_sellers:
        seller = db.sellers.get(seller_id)
        if seller is not None:
            refresh_seller_derived(seller)

    return success({})


def _flip_proceeds_available(order):
    """Flip the order's ORDER_PROCEEDS ledger entry PENDING->AVAILABLE."""
    for e in db.ledger_entries.values():
        if (e["source_type"] == "ORDER_PROCEEDS" and e["source_id"] == order["id"]
                and e["hold_state"] == HOLD_PENDING):
            e["hold_state"] = HOLD_AVAILABLE


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)
