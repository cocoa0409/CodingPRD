"""Manufacturer warranty registration (PRD 3.8). Immutable records: id and
created_at only, no updated_at / version (PRD 2.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_NOT_CONFIRMED,
    ERR_ORDER_NOT_FULLY_DELIVERED,
    ERR_CERTIFICATION_REQUIRED,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import render_list, render_one
from services.core import create_record, get_or_404
from services.calculations import order_lines_of
from util import CLOCK

bp = Blueprint("warranties", __name__)

WARRANTY_READ_ROLES = ["PlatformAdmin", "BranchManager", "Contractor"]


@bp.post("/roofing/orders/<rid>/warranty-registrations")
def register_warranty(rid):
    caller = authorized(["Contractor"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job = db["job_accounts"].get(order["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
    if order["status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED,
                    "warranty registration requires a CONFIRMED order")
    if order["fulfillment_status"] not in ("DELIVERED", "RETURN_ADJUSTED"):
        raise_error(ERR_ORDER_NOT_FULLY_DELIVERED,
                    "warranty registration requires a delivered order")
    lines = order_lines_of(order["id"])
    certs = account["manufacturer_certifications"] if account else []
    for line in lines:
        product = db["products"].get(line["product_id"])
        if product is not None and product["requires_certified_installer"]:
            if product["manufacturer_name"] not in certs:
                raise_error(ERR_CERTIFICATION_REQUIRED,
                            "product requires a manufacturer-certified installer")
    manufacturer_name = None
    for line in lines:
        product = db["products"].get(line["product_id"])
        if product is not None:
            manufacturer_name = product["manufacturer_name"]
            break
    registered_bundles = sum(
        max(0, l["delivered_bundles"] - l["returned_bundles"]) for l in lines)
    rec = create_record("warranty_registrations", {
        "order_id": order["id"],
        "manufacturer_name": manufacturer_name,
        "registered_bundles": registered_bundles,
        "certification_verified": True,
        "registered_at": CLOCK.now_ts(),
    }, common=False)
    return render_one("warranty_registrations", rec, status=201)


@bp.get("/roofing/orders/<rid>/warranty-registrations")
def list_warranties(rid):
    caller = authorized(WARRANTY_READ_ROLES)
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job = db["job_accounts"].get(order["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    regs = [w for w in db["warranty_registrations"].values() if w["order_id"] == order["id"]]
    return render_list(caller, "warranty_registrations", base_records=regs)
