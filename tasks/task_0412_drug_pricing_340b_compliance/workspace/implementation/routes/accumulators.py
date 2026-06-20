"""Accumulator: create (one per CE/drug pair), list, virtual read, and the
OCC-guarded manual replenishment sweep."""
from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import require_int, parse_pagination, paginate
from filters import filter_eq
from services.accumulator import find_accumulator, run_replenishment
from services.pricing import effective_ceiling

bp = Blueprint("accumulators", __name__)


@bp.route("/covered-entities/<ce_id>/accumulators", methods=["POST"])
def create_accumulator(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "PharmacyOperator"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    from validation import require_string

    drug_product_id = require_string(body, "drug_product_id")
    dp = lookup.drug_product(drug_product_id)

    # At most one accumulator per (covered_entity_id, drug_product_id).
    if find_accumulator(ce["id"], dp["id"]) is not None:
        raise err("ERR_DUPLICATE_ACCUMULATOR", "Accumulator already exists for this pair")

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "drug_product_id": dp["id"],
            "accrued_units": 0,
            "replenished_packages_total": 0,
            "last_replenish_dispense_id": None,
        }
    )
    db.accumulators.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/accumulators", methods=["GET"])
def list_accumulators():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.accumulators.all())
    items = filter_eq(items, "drug_product_id")
    items = filter_eq(items, "covered_entity_id")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/accumulators/<acc_id>", methods=["GET"])
def get_accumulator(acc_id):
    get_identity()
    acc = lookup.accumulator(acc_id)
    return success(serialize(acc))


@bp.route("/accumulators/<acc_id>/replenish", methods=["POST"])
def replenish(acc_id):
    _, role = get_identity()
    require_role(role, {"PharmacyOperator"})
    acc = lookup.accumulator(acc_id)
    body = get_json_body()

    expected_version = require_int(body, "expected_accumulator_version", minimum=0)
    if expected_version != acc["version"]:
        raise err("ERR_STALE_VERSION", "accumulator version is stale")

    # Use the most recent published-or-provisional ceiling for the drug; the
    # B340B PO (if any) carries the effective ceiling per unit. Pick the quarter
    # from the last replenishing context is not tracked, so use the drug's most
    # recent effective ceiling across quarters. We choose the latest-created
    # ceiling record for this drug to price the emitted PO.
    ceiling_unit_price, quarter = _pick_ceiling_for_manual(acc["drug_product_id"])
    run_replenishment(acc, acc.get("last_replenish_dispense_id"), ceiling_unit_price, quarter)

    return success(serialize(acc))


def _pick_ceiling_for_manual(drug_product_id):
    """For a manual sweep, price the emitted B340B PO using the most recently
    created ceiling record for the drug (published preferred). Returns
    (unit_price_cents, quarter). Falls back to (0, None) if none exist."""
    records = [c for c in db.ceiling_prices.all() if c["drug_product_id"] == drug_product_id]
    if not records:
        return 0, None
    published = [c for c in records if c["is_published"]]
    pool = published if published else records
    chosen = max(pool, key=lambda c: c["_seq"])
    return chosen["ceiling_price_per_unit_cents"], chosen["quarter"]
