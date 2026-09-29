"""Forward pricing contracts and their commitment lines (PRD §3.2)."""
from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import authenticate, require_owner
from common import fk_lookup, path_lookup
from errors import fail

bp = Blueprint("contracts", __name__)

PRICING_MODES = ("ORDER_DATE_INDEX", "DELIVERY_DATE_INDEX")
CONTRACT_STATES = ("DRAFT", "OFFERED", "COUNTERED", "ACTIVE",
                   "EXHAUSTED", "EXPIRED", "TERMINATED")
READ_ROLES = ("AccountManager", "PricingController", "CustomerBuyer", "PlatformAdmin")


@bp.post("/forward-contracts")
def create_contract():
    authenticate(("AccountManager",))
    body = v.body()
    customer_id = v.string(body, "customer_id", min_len=1)
    term_start = v.date(body, "term_start_on")
    term_end = v.date(body, "term_end_on")
    pricing_mode = v.enum(body, "pricing_mode", PRICING_MODES)
    fk_lookup("customers", customer_id)
    rec = store.base_record()
    rec.update({
        "customer_id": customer_id,
        "status": "DRAFT",
        "authored_by_user_id": None,
        "approved_by_user_id": None,
        "negotiation_round": 0,
        "term_start_on": term_start,
        "term_end_on": term_end,
        "pricing_mode": pricing_mode,
        "committed_volume_lb": store.D("0.00"),
        "drawn_volume_lb": store.D("0.00"),
    })
    store.insert("contracts", rec)
    return envelope.created(serialize.contract(rec))


@bp.get("/forward-contracts/<cid>")
def read_contract(cid):
    authenticate(READ_ROLES)
    return envelope.ok(serialize.contract(path_lookup("contracts", cid)))


@bp.get("/forward-contracts")
def list_contracts():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    customer_id = v.q_str("customer_id")
    status = v.q_enum("status", CONTRACT_STATES)
    rows = [c for c in store.all_of("contracts")
            if (customer_id is None or c["customer_id"] == customer_id)
            and (status is None or c["status"] == status)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.contract)
    return envelope.listing(data, limit, offset, total)


@bp.post("/forward-contracts/<cid>/lines")
def create_contract_line(cid):
    authenticate(("AccountManager",))
    body = v.body()
    product_id = v.string(body, "product_id", min_len=1)
    volume = v.integer(body, "volume_committed_lb", minimum=1000)
    basis = v.integer(body, "basis_cents_per_lb", minimum=-500, maximum=500)
    cap = v.integer(body, "cap_cents_per_lb", required=False, default=None)
    contract = path_lookup("contracts", cid)
    fk_lookup("products", product_id)
    for existing in calc.contract_lines_of(contract["id"]):
        if existing["product_id"] == product_id:
            fail("ERR_DUPLICATE_RESOURCE",
                 "This contract already carries a line for that SKU")
    rec = store.base_record()
    rec.update({
        "contract_id": contract["id"],
        "product_id": product_id,
        "volume_committed_lb": store.lb(volume),
        "volume_drawn_lb": store.D("0.00"),
        "basis_cents_per_lb": basis,
        "cap_cents_per_lb": cap,
    })
    store.insert("contract_lines", rec)
    calc.recompute_contract_volumes(contract)
    store.bump(contract)
    return envelope.created(serialize.contract_line(rec))


@bp.get("/forward-contracts/<cid>/lines")
def list_contract_lines_of(cid):
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    contract = path_lookup("contracts", cid)
    rows = calc.contract_lines_of(contract["id"])
    data, total = v.page(rows, limit, offset, serialize.contract_line)
    return envelope.listing(data, limit, offset, total)


@bp.get("/contract-lines")
def list_contract_lines():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    contract_id = v.q_str("contract_id")
    product_id = v.q_str("product_id")
    rows = [l for l in store.all_of("contract_lines")
            if (contract_id is None or l["contract_id"] == contract_id)
            and (product_id is None or l["product_id"] == product_id)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.contract_line)
    return envelope.listing(data, limit, offset, total)


@bp.get("/contract-lines/<lid>")
def read_contract_line(lid):
    authenticate(READ_ROLES)
    return envelope.ok(serialize.contract_line(path_lookup("contract_lines", lid)))


@bp.post("/forward-contracts/<cid>/offer")
def offer_contract(cid):
    actor = authenticate(("AccountManager",))
    v.body()
    contract = path_lookup("contracts", cid)
    status = contract["status"]
    if status == "DRAFT":
        lines = calc.contract_lines_of(contract["id"])
        if not lines:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A contract needs at least one commitment line before it can be offered")
        if not (store.day_of(contract["term_end_on"]) > store.day_of(contract["term_start_on"])):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "term_end_on must be strictly later than term_start_on")
        contract["status"] = "OFFERED"
        contract["authored_by_user_id"] = actor.user_id
        calc.recompute_contract_volumes(contract)
        store.bump(contract)
    elif status == "COUNTERED":
        if contract["negotiation_round"] >= 3:
            fail("ERR_ROUND_LIMIT_REACHED", "The negotiation round cap has been reached")
        contract["negotiation_round"] += 1
        contract["status"] = "OFFERED"
        contract["authored_by_user_id"] = actor.user_id
        store.bump(contract)
    else:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A contract in %s cannot be offered" % status)
    return envelope.ok(serialize.contract(contract))


@bp.post("/forward-contracts/<cid>/counter")
def counter_contract(cid):
    actor = authenticate(("CustomerBuyer",))
    body = v.body()
    basis = v.integer(body, "counter_basis_cents_per_lb", minimum=-500, maximum=500)
    contract = path_lookup("contracts", cid)
    require_owner(actor, contract["customer_id"])
    if contract["status"] != "OFFERED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A contract in %s cannot be countered" % contract["status"])
    for line in calc.contract_lines_of(contract["id"]):
        line["basis_cents_per_lb"] = basis
        store.bump(line)
    contract["status"] = "COUNTERED"
    store.bump(contract)
    return envelope.ok(serialize.contract(contract))


@bp.post("/forward-contracts/<cid>/activate")
def activate_contract(cid):
    actor = authenticate(("PricingController",))
    v.body()
    contract = path_lookup("contracts", cid)
    if contract["status"] != "OFFERED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A contract in %s cannot be activated" % contract["status"])
    customer = store.get("customers", contract["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "The bakery account is not ACTIVE")
    if actor.user_id == contract["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The activating controller may not be the authoring operator")
    own_products = {l["product_id"] for l in calc.contract_lines_of(contract["id"])}
    for other in store.all_of("contracts"):
        if other["id"] == contract["id"] or other["customer_id"] != contract["customer_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if store.day_of(other["term_start_on"]) > store.day_of(contract["term_end_on"]):
            continue
        if store.day_of(contract["term_start_on"]) > store.day_of(other["term_end_on"]):
            continue
        other_products = {l["product_id"] for l in calc.contract_lines_of(other["id"])}
        if own_products & other_products:
            fail("ERR_CONTRACT_TERM_OVERLAP",
                 "An ACTIVE contract already covers one of these SKUs over an overlapping term")
    contract["status"] = "ACTIVE"
    contract["approved_by_user_id"] = actor.user_id
    store.bump(contract)
    return envelope.ok(serialize.contract(contract))


@bp.post("/forward-contracts/<cid>/terminate")
def terminate_contract(cid):
    authenticate(("PricingController",))
    body = v.body()
    v.string(body, "reason", min_len=1)
    contract = path_lookup("contracts", cid)
    if contract["status"] not in ("DRAFT", "OFFERED", "COUNTERED", "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A contract in %s cannot be terminated" % contract["status"])
    contract["status"] = "TERMINATED"
    store.bump(contract)
    return envelope.ok(serialize.contract(contract))
