"""Catalog products (PRD section 3.1)."""

from flask import Blueprint

import envelope
from auth import auth_and_roles
from db import STORES
from errors import ApiError
from util import base_record, body, get_or_404, pub, v_bool, v_enum, v_int, v_str

bp = Blueprint("products", __name__)

PRODUCT_KINDS = {"CONSUMABLE", "EQUIPMENT", "PART", "REGULATED"}


@bp.post("/products")
def create_product():
    auth_and_roles(["DistributionAdmin"])
    data = body()
    sku = v_str(data, "sku")
    name = v_str(data, "name")
    kind = v_enum(data, "kind", PRODUCT_KINDS)
    unit_price = v_int(data, "unit_price_cents", min_val=0)
    manufacturer = v_str(data, "manufacturer")
    max_qty = v_int(data, "max_qty_per_order", required=False, default=None, min_val=1)
    sterile = v_bool(data, "sterilization_cycle_required", required=False, default=False)
    warranty_months = v_int(data, "warranty_months", required=False, default=0, min_val=0)

    # sku is unique across the catalog.
    for existing in STORES["products"].values():
        if existing["sku"] == sku:
            raise ApiError("ERR_INVALID_REQUEST", 400, "sku must be unique")

    record = base_record()
    record.update(
        {
            "sku": sku,
            "name": name,
            "kind": kind,
            "unit_price_cents": unit_price,
            "manufacturer": manufacturer,
            "max_qty_per_order": max_qty,
            "sterilization_cycle_required": sterile,
            "warranty_months": warranty_months,
        }
    )
    STORES["products"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/products/<rid>")
def get_product(rid):
    auth_and_roles(
        [
            "DistributionAdmin",
            "SalesRep",
            "PracticeManager",
            "ServiceDispatcher",
            "FieldTechnician",
            "ManufacturerAgent",
        ]
    )
    return envelope.success(pub(get_or_404("products", rid)))
