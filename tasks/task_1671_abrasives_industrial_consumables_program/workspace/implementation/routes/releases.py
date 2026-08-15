"""Release endpoints (PRD 3.6/3.7): nested creation with OCC, FEFO pick,
ship (final pricing + billing), branching cancel."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_CONTRACT_NOT_ACTIVE, ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_NO_ELIGIBLE_LOT,
    ERR_PRODUCT_DISCONTINUED, ERR_RELEASE_EXCEEDS_REMAINING,
    ERR_RELEASE_WINDOW_OUTSIDE_TERM, ERR_STALE_VERSION, ERR_SUBSTITUTION_PENDING,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import (
    fefo_candidates, fefo_waterfall, find_contract_line, price_at,
    release_billing_total,
)
from services.core import (
    auto_close_check, cancel_single_release, new_record, recompute_order_value,
    serialize, touch,
)
from util import CLOCK, parse_date
from validate import get_body, req_date, req_int, require_path_resource

bp = Blueprint("releases", __name__)


@bp.post("/api/blanket-orders/<oid>/releases")
def create_release(oid):
    authorized(["AccountManager"])
    # PRD 2.9: the only nested creation route — the path id is resolved first,
    # before any payload evaluation.
    order = require_path_resource("blanket_orders", oid, "blanket order")
    # Priority 3: request shape.
    body = get_body()
    qty = req_int(body, "qty", min_value=1)
    ship_date = req_date(body, "scheduled_ship_date")
    expected = body.get("expected_blanket_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_blanket_order_version is required and must be an integer")
    # Priority 5 (OCC): before any state or business check.
    if expected != order["version"]:
        raise_error(ERR_STALE_VERSION, "expected_blanket_order_version does not match the current version")
    # Priority 6: the order's own state — releases schedule only against OPEN.
    if order["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE_TRANSITION, "releases can only be scheduled against an OPEN order")
    # Priority 8: a substitution awaiting acceptance freezes new scheduling;
    # ACCEPTED orders accept new releases again (error catalog: PENDING only).
    if order["substitution_status"] == "PENDING":
        raise_error(ERR_SUBSTITUTION_PENDING, "order has a PENDING substitution")
    product = db["products"].get(order["product_id"])
    if product is None or product["status"] != "ACTIVE":
        raise_error(ERR_PRODUCT_DISCONTINUED, "order product is not ACTIVE")
    # Priority 9: ship date inside the contract term [term_start, term_end] inclusive.
    contract = db["contracts"].get(order["contract_id"])
    ship_d = parse_date(ship_date)
    if ship_d < parse_date(contract["term_start"]) or ship_d > parse_date(contract["term_end"]):
        raise_error(ERR_RELEASE_WINDOW_OUTSIDE_TERM, "scheduled_ship_date is outside the contract term")
    # Priority 10: qty must not exceed the remaining pool (== allowed).
    if qty > order["remaining_qty"]:
        raise_error(ERR_RELEASE_EXCEEDS_REMAINING, "qty exceeds the order's remaining_qty")

    # Provisional (forward-looking) stamp: price evaluated at scheduled_ship_date.
    line = find_contract_line(order["contract_id"], order["product_id"])
    provisional = price_at(ship_d, line, contract)
    rel = new_record("releases", {
        "blanket_order_id": oid,
        "qty": qty,
        "scheduled_ship_date": ship_date,
        "provisional_unit_price_cents": provisional,
        "final_unit_price_cents": None,
        "allocations": [],
        "billed_total_cents": None,
        "status": "SCHEDULED",
    })
    order["remaining_qty"] -= qty
    recompute_order_value(order)
    touch(order)
    return success_object(serialize(rel), status=201)


@bp.get("/api/releases/<rid>")
def get_release(rid):
    return get_one("releases", rid, "release")


@bp.get("/api/releases")
def list_releases():
    return list_response("releases", {
        "blanket_order_id": arg("blanket_order_id"),
        "status": arg("status"),
    })


@bp.post("/api/releases/<rid>/pick")
def pick_release(rid):
    authorized(["AccountManager"])
    rel = require_path_resource("releases", rid, "release")
    if rel["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a SCHEDULED release can be picked")
    order = db["blanket_orders"][rel["blanket_order_id"]]
    ship_d = parse_date(rel["scheduled_ship_date"])
    # FEFO candidate pool (priority 10: eligibility before sufficiency).
    pool = fefo_candidates(order["product_id"], ship_d)
    if not pool:
        raise_error(ERR_NO_ELIGIBLE_LOT, "no eligible lots for FEFO allocation")
    if sum(l["qty_on_hand"] for l in pool) < rel["qty"]:
        # Atomic rejection: no partial allocation is persisted.
        raise_error(ERR_INSUFFICIENT_STOCK, "eligible pool total is below the release qty")

    lines = fefo_waterfall(pool, rel["qty"])
    for line in lines:
        lot = line.pop("_lot")
        lot["qty_on_hand"] -= line["qty"]
        if lot["qty_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    rel["allocations"] = [{"lot_id": l["lot_id"], "qty": l["qty"]} for l in lines]
    rel["status"] = "PICKED"
    touch(rel)
    # The parent order's version is NOT bumped by a pick.
    return success_object(serialize(rel))


@bp.post("/api/releases/<rid>/ship")
def ship_release(rid):
    authorized(["AccountManager"])
    rel = require_path_resource("releases", rid, "release")
    if rel["status"] != "PICKED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a PICKED release can be shipped")
    order = db["blanket_orders"][rel["blanket_order_id"]]
    contract = db["contracts"].get(order["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise_error(ERR_CONTRACT_NOT_ACTIVE, "governing contract is not ACTIVE")

    # Final variant: price evaluated at the current logical-clock date.
    line = find_contract_line(order["contract_id"], order["product_id"])
    final_price = price_at(CLOCK.today(), line, contract)
    rel["final_unit_price_cents"] = final_price
    rel["billed_total_cents"] = release_billing_total(
        final_price, rel["allocations"], order["committed_qty"]
    )
    rel["status"] = "SHIPPED"
    touch(rel)
    auto_close_check(order)
    return success_object(serialize(rel))


@bp.post("/api/releases/<rid>/cancel")
def cancel_release(rid):
    authorized(["AccountManager"])
    rel = require_path_resource("releases", rid, "release")
    if rel["status"] not in ("SCHEDULED", "ON_HOLD", "PICKED"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "a SHIPPED or CANCELLED release cannot be cancelled")
    cancel_single_release(rel)
    return success_object(serialize(rel))
