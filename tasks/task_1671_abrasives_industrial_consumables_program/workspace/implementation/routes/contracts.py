"""Contract + contract-line endpoints (PRD 3.5): draft, activate, amend (OCC,
depth-3 cascade), terminate."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import find_contract_line, price_at
from services.core import new_record, recompute_order_value, serialize, touch
from util import CLOCK
from validate import (
    get_body, opt_date, opt_decimal, req_date, req_decimal, req_int, req_str,
    require_fk, require_path_resource,
)

bp = Blueprint("contracts", __name__)


@bp.post("/api/contracts")
def create_contract():
    authorized(["AccountManager"])
    body = get_body()
    customer_ref = req_str(body, "customer_ref")
    contract_number = req_str(body, "contract_number")
    term_start = req_date(body, "term_start")
    term_end = req_date(body, "term_end")
    price_hold_end = req_date(body, "price_hold_end")
    escalation_pct = req_decimal(body, "escalation_pct", gte=Decimal("0"))
    escalation_effective_date = req_date(body, "escalation_effective_date")
    lines = body.get("lines")
    if not isinstance(lines, list) or any(not isinstance(l, dict) for l in lines):
        raise_error(ERR_INVALID_REQUEST, "lines must be a list of {product_id, base_unit_price_cents}")
    parsed_lines = []
    for entry in lines:
        pid = req_str(entry, "product_id")
        base = req_int(entry, "base_unit_price_cents", min_value=1)
        parsed_lines.append((pid, base))
    # contract_number is unique across contracts.
    for c in db["contracts"].values():
        if c["contract_number"] == contract_number:
            raise_error(ERR_INVALID_REQUEST, f"contract_number {contract_number} already exists")
    # Priority 4: body FK existence — each line's product must exist.
    for pid, _ in parsed_lines:
        require_fk("products", pid, "product")

    contract = new_record("contracts", {
        "customer_ref": customer_ref,
        "contract_number": contract_number,
        "status": "DRAFT",
        "term_start": term_start,
        "term_end": term_end,
        "price_hold_end": price_hold_end,
        "escalation_pct": escalation_pct,
        "escalation_effective_date": escalation_effective_date,
    })
    for pid, base in parsed_lines:
        new_record("contract_lines", {
            "contract_id": contract["id"],
            "product_id": pid,
            "base_unit_price_cents": base,
            "current_unit_price_cents": base,
        })
    return success_object(serialize(contract), status=201)


@bp.get("/api/contracts/<cid>")
def get_contract(cid):
    return get_one("contracts", cid, "contract")


@bp.post("/api/contracts/<cid>/activate")
def activate_contract(cid):
    authorized(["ProgramAdmin"])
    contract = require_path_resource("contracts", cid, "contract")
    if contract["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a DRAFT contract can be activated")
    contract["status"] = "ACTIVE"
    touch(contract)
    # Stamp every line's current price at the current logical-clock date.
    today = CLOCK.today()
    for line in db["contract_lines"].values():
        if line["contract_id"] == cid:
            line["current_unit_price_cents"] = price_at(today, line, contract)
            touch(line)
    return success_object(serialize(contract))


@bp.patch("/api/contracts/<cid>")
def amend_contract(cid):
    authorized(["ProgramAdmin"])
    # Priority 3: shape — expected_contract_version required; amendable fields valid.
    body = get_body()
    expected = body.get("expected_contract_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_contract_version is required and must be an integer")
    new_esc = opt_decimal(body, "escalation_pct", gte=Decimal("0"))
    new_hold = opt_date(body, "price_hold_end")
    # Priority 4: path existence.
    contract = require_path_resource("contracts", cid, "contract")
    # Priority 5 (OCC): evaluated before state preconditions.
    if expected != contract["version"]:
        raise_error(ERR_STALE_VERSION, "expected_contract_version does not match the current version")
    # Priority 6: amend only on ACTIVE.
    if contract["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an ACTIVE contract can be amended")

    if new_esc is not None:
        contract["escalation_pct"] = new_esc
    if new_hold is not None:
        contract["price_hold_end"] = new_hold
    touch(contract)

    # Depth-3 cascade (PRD 3.5), atomic with the amend.
    # Hop 1: every line re-stamps current_unit_price_cents at the clock date.
    today = CLOCK.today()
    lines = [l for l in db["contract_lines"].values() if l["contract_id"] == cid]
    for line in lines:
        line["current_unit_price_cents"] = price_at(today, line, contract)
        touch(line)
    line_by_product = {l["product_id"]: l for l in lines}
    # Hop 2: every OPEN blanket order whose product matches a re-stamped line
    # re-stamps its provisional fields from the line's current price.
    restamped_orders = []
    for order in db["blanket_orders"].values():
        if order["status"] != "OPEN" or order["contract_id"] != cid:
            continue
        line = line_by_product.get(order["product_id"])
        if line is None:
            continue
        order["provisional_unit_price_cents"] = line["current_unit_price_cents"]
        recompute_order_value(order)
        touch(order)
        restamped_orders.append(order)
    # Hop 3: every SCHEDULED release of a re-stamped order re-stamps its
    # provisional price evaluated at its own scheduled_ship_date.
    from util import parse_date
    order_ids = {o["id"] for o in restamped_orders}
    for rel in db["releases"].values():
        if rel["blanket_order_id"] not in order_ids or rel["status"] != "SCHEDULED":
            continue
        order = db["blanket_orders"][rel["blanket_order_id"]]
        line = line_by_product.get(order["product_id"])
        if line is None:
            continue
        rel["provisional_unit_price_cents"] = price_at(
            parse_date(rel["scheduled_ship_date"]), line, contract
        )
        touch(rel)
    return success_object(serialize(contract))


@bp.post("/api/contracts/<cid>/terminate")
def terminate_contract(cid):
    authorized(["ProgramAdmin"])
    contract = require_path_resource("contracts", cid, "contract")
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a DRAFT or ACTIVE contract can be terminated")
    contract["status"] = "TERMINATED"
    touch(contract)
    return success_object(serialize(contract))


@bp.get("/api/contract-lines/<lid>")
def get_contract_line(lid):
    return get_one("contract_lines", lid, "contract line")


@bp.get("/api/contract-lines")
def list_contract_lines():
    return list_response("contract_lines", {
        "contract_id": arg("contract_id"),
        "product_id": arg("product_id"),
    })
