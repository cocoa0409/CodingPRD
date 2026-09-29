from flask import Blueprint, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own
from routes.common import filter_eq, fk, listing, lookup, unique

bp = Blueprint("products", __name__)

ACTIONS = ("SUBMIT", "APPROVE", "REJECT", "SUSPEND", "REINSTATE", "WITHDRAW")
ADMIN_ONLY = ("APPROVE", "REJECT", "SUSPEND", "REINSTATE")

TRANSITIONS = {
    "SUBMIT": (("DRAFT", "REJECTED"), "SUBMITTED"),
    "APPROVE": (("SUBMITTED",), "REGISTERED"),
    "REJECT": (("SUBMITTED",), "REJECTED"),
    "SUSPEND": (("REGISTERED",), "SUSPENDED"),
    "REINSTATE": (("SUSPENDED",), "REGISTERED"),
    "WITHDRAW": (("REGISTERED", "SUSPENDED"), "WITHDRAWN"),
}


@bp.post("/beverage-products")
def create_product():
    authenticate("DistributorAgent", "ProgramAdmin")
    body = v.body()
    raw_dist = body.get("distributor_id")
    if isinstance(raw_dist, str):
        own(distributor_id=raw_dist)
    dist = fk("distributor", body, "distributor_id")
    v.req_str(body, "distributor_id")
    brand_name = v.req_str(body, "brand_name")
    beverage_type = v.req_enum(body, "beverage_type", calc.BEVERAGE_TYPES)
    material = v.req_enum(body, "container_material", calc.CONTAINER_MATERIALS)
    fill_volume_ml = v.req_int(body, "fill_volume_ml", minimum=1)
    upc = v.req_str(body, "upc")
    label_state_code = v.req_str(body, "label_state_code", pattern=v.STATE_RE)
    unique(db.products, "upc", upc, "ERR_DUPLICATE_UPC")
    rec = db.new_record({
        "distributor_id": dist["id"],
        "brand_name": brand_name,
        "beverage_type": beverage_type,
        "container_material": material,
        "fill_volume_ml": fill_volume_ml,
        "upc": upc,
        "label_state_code": label_state_code,
        "coverage_status": None,
        "coverage_reason": None,
        "deposit_cents": 0,
        "registration_state": "DRAFT",
        "rejection_reason": None,
        "registered_at": None,
    })
    db.products[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/beverage-products/<rid>")
def get_product(rid):
    authenticate("ProgramAdmin", "DistributorAgent", "CenterOperator", "PlantCounter")
    rec = db.products.get(rid)
    if rec is not None:
        own(distributor_id=rec.get("distributor_id"))
    rec = lookup("product", rid)
    return response.obj(db.public(rec))


@bp.get("/beverage-products")
def list_products():
    authenticate("ProgramAdmin", "DistributorAgent", "CenterOperator", "PlantCounter")
    rows = db.ordered(db.products)
    rows = filter_eq(rows, "distributor_id", request.args.get("distributor_id"))
    rows = filter_eq(rows, "upc", request.args.get("upc"))
    rows = filter_eq(rows, "registration_state", request.args.get("registration_state"))
    rows = filter_eq(rows, "coverage_status", request.args.get("coverage_status"))
    return listing(rows)


@bp.post("/beverage-products/<rid>/registration-actions")
def registration_action(rid):
    authenticate("DistributorAgent", "ProgramAdmin")
    product = db.products.get(rid)
    if product is not None:
        own(distributor_id=product.get("distributor_id"))
    body = v.body()
    raw_action = body.get("action")
    if isinstance(raw_action, str):
        narrow(raw_action, program_admin_only=ADMIN_ONLY)
    product = lookup("product", rid)
    action = v.req_enum(body, "action", ACTIONS)
    reason = v.opt_str(body, "reason")

    froms, target = TRANSITIONS[action]
    if product["registration_state"] not in froms:
        fail("ERR_INVALID_REGISTRATION_STATE",
             "Action %s is not available from %s." % (action, product["registration_state"]))

    if action == "SUBMIT":
        dist = db.distributors.get(product["distributor_id"])
        if dist is None or dist["status"] != "ACTIVE":
            fail("ERR_DISTRIBUTOR_SUSPENDED", "The owning distributor is suspended.")
        status, coverage_reason, deposit = calc.coverage(
            product["beverage_type"], product["container_material"],
            product["fill_volume_ml"])
        product["coverage_status"] = status
        product["coverage_reason"] = coverage_reason
        product["deposit_cents"] = deposit
    elif action == "APPROVE":
        if product["coverage_status"] != "COVERED":
            fail("ERR_PRODUCT_NOT_COVERED", "The label is not a covered container.")
        product["registered_at"] = clock.now_iso()
        product["rejection_reason"] = None
    elif action == "REJECT":
        product["rejection_reason"] = reason
    elif action == "SUSPEND":
        product["rejection_reason"] = reason
    elif action == "REINSTATE":
        product["registered_at"] = clock.now_iso()
        product["rejection_reason"] = None
    elif action == "WITHDRAW":
        product["deposit_cents"] = 0

    product["registration_state"] = target
    touch(product)
    return response.obj(db.public(product))


@bp.get("/beverage-products/<rid>/container-lots")
def list_product_lots(rid):
    authenticate("ProgramAdmin", "DistributorAgent", "CenterOperator")
    product = db.products.get(rid)
    if product is not None:
        own(distributor_id=product.get("distributor_id"))
    product = lookup("product", rid)
    rows = db.ordered(db.lots, lambda l: l["product_id"] == product["id"])
    return listing(rows)
