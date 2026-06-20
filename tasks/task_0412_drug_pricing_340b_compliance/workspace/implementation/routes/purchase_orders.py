"""PurchaseOrder: create (GPO-prohibition guarded), fetch, list."""
import re

from flask import Blueprint

import lookup
from db import db, base_record
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import require_string, require_int, require_enum, parse_pagination, paginate
from filters import filter_eq

bp = Blueprint("purchase_orders", __name__)

CHANNELS = {"GPO", "WAC", "B340B"}
QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


@bp.route("/purchase-orders", methods=["POST"])
def create_purchase_order():
    _, role = get_identity()
    require_role(role, {"PharmacyOperator", "ComplianceOfficer"})
    body = get_json_body()

    covered_entity_id = require_string(body, "covered_entity_id")
    drug_product_id = require_string(body, "drug_product_id")
    channel = require_enum(body, "channel", CHANNELS)
    packages_ordered = require_int(body, "packages_ordered", minimum=1)
    quarter = require_string(body, "quarter")
    if not QUARTER_RE.match(quarter):
        raise err("ERR_INVALID_REQUEST", "quarter must match YYYYQn")
    unit_price_paid_cents = require_int(body, "unit_price_paid_cents", minimum=0)

    accumulator_id = body.get("accumulator_id")
    if accumulator_id is not None and not isinstance(accumulator_id, str):
        raise err("ERR_INVALID_REQUEST", "accumulator_id must be a string")

    ce = lookup.covered_entity(covered_entity_id)
    dp = lookup.drug_product(drug_product_id)
    if accumulator_id is not None:
        lookup.accumulator(accumulator_id)

    # GPO prohibition guard.
    if channel == "GPO" and ce["gpo_prohibited"] and dp["is_covered_outpatient_drug"]:
        raise err("ERR_GPO_PROHIBITED", "GPO channel prohibited for this entity/drug")

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "drug_product_id": dp["id"],
            "accumulator_id": accumulator_id,
            "channel": channel,
            "packages_ordered": packages_ordered,
            "quarter": quarter,
            "unit_price_paid_cents": unit_price_paid_cents,
        }
    )
    db.purchase_orders.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/purchase-orders/<po_id>", methods=["GET"])
def get_purchase_order(po_id):
    get_identity()
    po = lookup.purchase_order(po_id)
    return success(serialize(po))


@bp.route("/purchase-orders", methods=["GET"])
def list_purchase_orders():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.purchase_orders.all())
    items = filter_eq(items, "covered_entity_id")
    items = filter_eq(items, "drug_product_id")
    items = filter_eq(items, "accumulator_id")
    items = filter_eq(items, "channel")
    items = filter_eq(items, "quarter")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
