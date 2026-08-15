"""Consignment agreements and consumption events."""

from flask import Blueprint, request

import domain
from db import store
from errors import err
from helpers import (get_body, new_id, now, opt_enum, req_int, req_str,
                     stamp_new, touch)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list

bp = Blueprint("consignment", __name__)


def get_agreement(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", f"agreement {aid} not found")
    return a


def get_consumption(cid):
    c = store.consumptions.get(cid)
    if c is None:
        raise err("ERR_CONSUMPTION_NOT_FOUND", f"consumption {cid} not found")
    return c


# -------------------------------------------------------------- agreements --

@bp.route("/motion/consignment-agreements", methods=["POST"])
@require_roles("ContractAdministrator")
def create_agreement(user_id, role):
    body = get_body()
    customer_id = req_str(body, "customer_id") if "customer_id" in body else None
    branch_id = req_str(body, "branch_id") if "branch_id" in body else None
    product_id = req_str(body, "product_id") if "product_id" in body else None
    # body FK existence (priority 3)
    for val, coll, eid in (
        (customer_id, store.customers, "ERR_CUSTOMER_NOT_FOUND"),
        (branch_id, store.branches, "ERR_BRANCH_NOT_FOUND"),
        (product_id, store.products, "ERR_PRODUCT_NOT_FOUND"),
    ):
        if val is not None and val not in coll:
            raise err(eid, f"referenced resource {val} not found")
    # shape (priority 7)
    if customer_id is None or branch_id is None or product_id is None:
        raise err("ERR_INVALID_REQUEST", "customer_id, branch_id, product_id are required")
    qty = req_int(body, "consigned_qty", minimum=1)
    variant = opt_enum(body, "billing_variant", ("CONSUMPTION_FIFO", "MONTHLY_SNAPSHOT"),
                       "CONSUMPTION_FIFO")
    # uniqueness (priority 7): at most one non-CLOSED agreement per triple
    if any(a["customer_id"] == customer_id and a["branch_id"] == branch_id
           and a["product_id"] == product_id and a["status"] != "CLOSED"
           for a in store.agreements.values()):
        raise err("ERR_DUPLICATE_AGREEMENT",
                  "a non-CLOSED agreement already exists for this customer/branch/product")
    # fiscal (priority 10): availability on the branch stock record
    stock = domain.find_stock(branch_id, product_id)
    if stock is None or domain.available_qty(stock) < qty:
        raise err("ERR_INSUFFICIENT_AVAILABLE_STOCK",
                  "available_qty < consigned_qty for consignment placement")
    product = store.products[product_id]
    pinned, _ = domain.contract_lag_unit_price(customer_id, product, now())
    stock["on_hand_qty"] -= qty
    touch(stock)
    rec = stamp_new({
        "id": new_id(),
        "customer_id": customer_id,
        "branch_id": branch_id,
        "product_id": product_id,
        "consigned_qty": qty,
        "pinned_unit_price_cents": pinned,
        "billing_variant": variant,
        "status": "ACTIVE",
    })
    store.agreements[rec["id"]] = rec
    return ok(serialize("ConsignmentAgreement", rec), 201)


@bp.route("/motion/consignment-agreements", methods=["GET"])
@require_any
def list_agreements(user_id, role):
    items = list(store.agreements.values())
    q = request.args
    for param in ("customer_id", "branch_id", "product_id", "status"):
        if q.get(param) is not None:
            items = [a for a in items if a[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("ConsignmentAgreement", page), limit, offset, total)


@bp.route("/motion/consignment-agreements/<aid>", methods=["GET"])
@require_any
def get_agreement_route(user_id, role, aid):
    return ok(serialize("ConsignmentAgreement", get_agreement(aid)))


@bp.route("/motion/consignment-agreements/<aid>", methods=["PATCH"])
@require_roles("ContractAdministrator")
def amend_agreement(user_id, role, aid):
    ag = get_agreement(aid)
    body = get_body()
    new_qty = req_int(body, "consigned_qty")
    expected = req_int(body, "expected_agreement_version")
    # OCC
    if expected != ag["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_agreement_version does not match the agreement's current version")
    # referential (priority 9)
    if new_qty < domain.consumed_qty(ag):
        raise err("ERR_CONSIGNMENT_QTY_BELOW_CONSUMED",
                  "amended consigned_qty must be >= consumed_qty")
    delta = new_qty - ag["consigned_qty"]
    if delta != 0:
        stock = domain.find_stock(ag["branch_id"], ag["product_id"])
        if stock is not None:
            stock["on_hand_qty"] -= delta
            touch(stock)
    ag["consigned_qty"] = new_qty
    touch(ag)
    return ok(serialize("ConsignmentAgreement", ag))


@bp.route("/motion/consignment-agreements/<aid>/suspend", methods=["POST"])
@require_roles("ContractAdministrator")
def suspend_agreement(user_id, role, aid):
    ag = get_agreement(aid)
    if ag["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "suspend requires agreement ACTIVE")
    ag["status"] = "SUSPENDED"
    touch(ag)
    return ok(serialize("ConsignmentAgreement", ag))


@bp.route("/motion/consignment-agreements/<aid>/resume", methods=["POST"])
@require_roles("ContractAdministrator")
def resume_agreement(user_id, role, aid):
    ag = get_agreement(aid)
    if ag["status"] != "SUSPENDED":
        raise err("ERR_AGREEMENT_NOT_SUSPENDED", "resume requires agreement SUSPENDED")
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok(serialize("ConsignmentAgreement", ag))


@bp.route("/motion/consignment-agreements/<aid>/close", methods=["POST"])
@require_roles("ContractAdministrator")
def close_agreement(user_id, role, aid):
    ag = get_agreement(aid)
    # state (priority 5)
    if ag["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_AGREEMENT_NOT_CLOSABLE", "close requires ACTIVE or SUSPENDED")
    # referential (priority 9): no REPORTED or DISPUTED consumptions
    if any(c["agreement_id"] == aid and c["status"] in ("REPORTED", "DISPUTED")
           for c in store.consumptions.values()):
        raise err("ERR_AGREEMENT_CLOSE_BLOCKED",
                  "consumptions in REPORTED or DISPUTED status block close")
    stock = domain.find_stock(ag["branch_id"], ag["product_id"])
    remaining = domain.remaining_qty(ag)
    if stock is not None and remaining != 0:
        stock["on_hand_qty"] += remaining
        touch(stock)
    ag["status"] = "CLOSED"
    touch(ag)
    return ok(serialize("ConsignmentAgreement", ag))


# ------------------------------------------------------------ consumptions --

@bp.route("/motion/consignment-agreements/<aid>/consumptions", methods=["POST"])
@require_roles("CustomerPlant")
def report_consumption(user_id, role, aid):
    ag = get_agreement(aid)
    # identity (priority 4)
    if ag["customer_id"] != user_id:
        raise err("ERR_IDENTITY_MISMATCH",
                  "CustomerPlant may report consumption only on its own agreements")
    # state (priority 5)
    if ag["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "consumption report requires agreement ACTIVE")
    body = get_body()
    qty = req_int(body, "qty", minimum=1)
    # referential (priority 9)
    if qty > domain.remaining_qty(ag):
        raise err("ERR_CONSUMPTION_EXCEEDS_REMAINING",
                  "consumption qty exceeds agreement remaining_qty")
    rec = stamp_new({
        "id": new_id(),
        "agreement_id": aid,
        "qty": qty,
        "reported_at": now(),
        "unit_price_cents": None,
        "billed_amount_cents": 0,
        "offset_applied_cents": 0,
        "status": "REPORTED",
    })
    store.consumptions[rec["id"]] = rec
    touch(ag)  # consumed_qty/remaining_qty changed -> agreement version bumps
    return ok(serialize("ConsignmentConsumption", rec), 201)


@bp.route("/motion/consignment-consumptions", methods=["GET"])
@require_any
def list_consumptions(user_id, role):
    items = list(store.consumptions.values())
    q = request.args
    for param in ("agreement_id", "status"):
        if q.get(param) is not None:
            items = [c for c in items if c[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("ConsignmentConsumption", page), limit, offset, total)


@bp.route("/motion/consignment-consumptions/<cid>", methods=["GET"])
@require_any
def get_consumption_route(user_id, role, cid):
    return ok(serialize("ConsignmentConsumption", get_consumption(cid)))


@bp.route("/motion/consignment-consumptions/<cid>/invoice", methods=["POST"])
@require_roles("BranchManager")
def invoice_consumption(user_id, role, cid):
    c = get_consumption(cid)
    if c["status"] != "REPORTED":
        raise err("ERR_CONSUMPTION_NOT_REPORTED", "invoice requires consumption REPORTED")
    ag = store.agreements[c["agreement_id"]]
    if ag["billing_variant"] == "CONSUMPTION_FIFO":
        unit = ag["pinned_unit_price_cents"]
    else:  # MONTHLY_SNAPSHOT: list price effective at month-end of report month
        product = store.products[ag["product_id"]]
        unit = domain.list_price_at(product, domain.month_end_instant(c["reported_at"]))
    c["unit_price_cents"] = unit
    c["billed_amount_cents"] = unit * c["qty"]
    c["status"] = "INVOICED"
    touch(c)
    return ok(serialize("ConsignmentConsumption", c))


@bp.route("/motion/consignment-consumptions/<cid>/dispute", methods=["POST"])
@require_roles("CustomerPlant")
def dispute_consumption(user_id, role, cid):
    c = get_consumption(cid)
    ag = store.agreements[c["agreement_id"]]
    # identity (priority 4)
    if ag["customer_id"] != user_id:
        raise err("ERR_IDENTITY_MISMATCH",
                  "CustomerPlant may dispute only its own account's billings")
    if c["status"] != "INVOICED":
        raise err("ERR_CONSUMPTION_NOT_INVOICED", "dispute requires consumption INVOICED")
    c["status"] = "DISPUTED"
    touch(c)
    return ok(serialize("ConsignmentConsumption", c))


@bp.route("/motion/consignment-consumptions/<cid>/credit", methods=["POST"])
@require_roles("BranchManager")
def credit_consumption(user_id, role, cid):
    c = get_consumption(cid)
    if c["status"] not in ("DISPUTED", "INVOICED"):
        raise err("ERR_CONSUMPTION_NOT_CREDITABLE", "credit requires DISPUTED or INVOICED")
    c["status"] = "CREDITED"
    touch(c)
    # agreement consumed_qty recomputes excluding CREDITED -> version bump
    ag = store.agreements.get(c["agreement_id"])
    if ag is not None:
        touch(ag)
    return ok(serialize("ConsignmentConsumption", c))
