"""DrugProduct, CeilingPriceRecord, effective-ceiling read, and OCC-guarded
ceiling-price reconciliation."""
import re

from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import (
    require_string,
    require_int,
    require_bool,
    parse_pagination,
    paginate,
)
from filters import filter_eq
from services.pricing import (
    compute_ceiling,
    effective_ceiling,
    effective_published_ceiling,
    ceiling_records_for,
)
from services.compliance import recompute_ce_posture

bp = Blueprint("drug_products", __name__)

QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


def _require_quarter(body, field="quarter"):
    q = require_string(body, field)
    if not QUARTER_RE.match(q):
        raise err("ERR_INVALID_REQUEST", "quarter must match YYYYQn")
    return q


# --------------------------------------------------------------------------
# DrugProduct
# --------------------------------------------------------------------------
@bp.route("/drug-products", methods=["POST"])
def create_drug_product():
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    body = get_json_body()

    ndc = require_string(body, "ndc")
    drug_name = require_string(body, "drug_name")
    package_size_units = require_int(body, "package_size_units", minimum=1)
    wac_price_per_unit_cents = require_int(body, "wac_price_per_unit_cents", minimum=0)
    is_covered_outpatient_drug = require_bool(body, "is_covered_outpatient_drug", default=True)

    for d in db.drug_products.all():
        if d["ndc"] == ndc:
            raise err("ERR_DUPLICATE_NDC", "ndc already in use")

    rec = base_record(full_meta=True)
    rec.update(
        {
            "ndc": ndc,
            "drug_name": drug_name,
            "package_size_units": package_size_units,
            "is_covered_outpatient_drug": is_covered_outpatient_drug,
            "wac_price_per_unit_cents": wac_price_per_unit_cents,
        }
    )
    db.drug_products.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/drug-products/<dp_id>", methods=["GET"])
def get_drug_product(dp_id):
    get_identity()
    dp = lookup.drug_product(dp_id)
    return success(serialize(dp))


# --------------------------------------------------------------------------
# CeilingPriceRecord
# --------------------------------------------------------------------------
@bp.route("/drug-products/<dp_id>/ceiling-prices", methods=["POST"])
def create_ceiling_price(dp_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    dp = lookup.drug_product(dp_id)
    body = get_json_body()

    quarter = _require_quarter(body)
    amp = require_int(body, "amp_per_unit_cents", minimum=0)
    ura = require_int(body, "ura_per_unit_cents", minimum=0)
    is_published = require_bool(body, "is_published", default=True)

    # At most one published record per (drug_product_id, quarter).
    if is_published:
        for c in ceiling_records_for(dp["id"], quarter):
            if c["is_published"]:
                raise err(
                    "ERR_CEILING_QUARTER_OVERLAP",
                    "A published ceiling record already exists for this quarter",
                )

    ceiling_price, pricing_variant = compute_ceiling(amp, ura)

    rec = base_record(full_meta=True)
    rec.update(
        {
            "drug_product_id": dp["id"],
            "quarter": quarter,
            "amp_per_unit_cents": amp,
            "ura_per_unit_cents": ura,
            "is_published": is_published,
            "ceiling_price_per_unit_cents": ceiling_price,
            "pricing_variant": pricing_variant,
        }
    )
    db.ceiling_prices.put(rec)
    # Adding a ceiling record bumps the parent drug product version.
    touch(dp)
    return success(serialize(rec), status=201)


@bp.route("/drug-products/<dp_id>/ceiling-prices", methods=["GET"])
def list_ceiling_prices(dp_id):
    get_identity()
    dp = lookup.drug_product(dp_id)
    limit, offset = parse_pagination()
    items = [c for c in db.ceiling_prices.all() if c["drug_product_id"] == dp["id"]]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "quarter")
    items = filter_eq(items, "is_published", bool_field=True)
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/drug-products/<dp_id>/ceiling-prices/effective", methods=["GET"])
def effective_ceiling_read(dp_id):
    from flask import request

    get_identity()
    dp = lookup.drug_product(dp_id)
    quarter = request.args.get("quarter")
    if not quarter:
        raise err("ERR_INVALID_REQUEST", "quarter query param is required")
    if not QUARTER_RE.match(quarter):
        raise err("ERR_INVALID_REQUEST", "quarter must match YYYYQn")
    rec, variant = effective_ceiling(dp["id"], quarter)
    if rec is None:
        raise err("ERR_NOT_FOUND", "No ceiling-price record for that quarter")
    out = serialize(rec)
    out = dict(out)
    out["effective_variant"] = variant
    return success(out)


# --------------------------------------------------------------------------
# Reconcile (OCC-guarded overcharge reconciliation)
# --------------------------------------------------------------------------
@bp.route("/drug-products/<dp_id>/reconcile", methods=["POST"])
def reconcile(dp_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    dp = lookup.drug_product(dp_id)
    body = get_json_body()

    quarter = _require_quarter(body)
    expected_version = require_int(body, "expected_drug_product_version", minimum=0)

    # OCC check (priority 15) before the published-ceiling check (priority 16).
    if expected_version != dp["version"]:
        raise err("ERR_STALE_VERSION", "drug product version is stale")

    published = effective_published_ceiling(dp["id"], quarter)
    if published is None:
        raise err("ERR_NO_PUBLISHED_CEILING", "No published ceiling for that quarter")

    ceiling = published["ceiling_price_per_unit_cents"]
    package_size = dp["package_size_units"]

    pos = [
        po
        for po in db.purchase_orders.all()
        if po["drug_product_id"] == dp["id"]
        and po["quarter"] == quarter
        and po["channel"] == "B340B"
    ]
    pos = lookup.sorted_by_created(pos)

    total_overcharge = 0
    for po in pos:
        units = po["packages_ordered"] * package_size
        per_unit_over = max(0, po["unit_price_paid_cents"] - ceiling)
        total_overcharge += per_unit_over * units

    obligation = None
    if total_overcharge > 0:
        obligation = base_record(full_meta=True)
        obligation.update(
            {
                "covered_entity_id": _resolve_ce_for_reconcile(dp["id"], quarter),
                "source_kind": "CEILING_RECONCILIATION",
                "source_ref_id": published["id"],
                "assessed_cents": total_overcharge,
                "paid_cents": 0,
                "remaining_balance_cents": total_overcharge,
                "status": "OWED",
            }
        )
        db.repayment_obligations.put(obligation)
        ce = db.covered_entities.get(obligation["covered_entity_id"])
        if ce is not None:
            recompute_ce_posture(ce)

    # Reconcile bumps the drug product version.
    touch(dp)

    if obligation is not None:
        return success(serialize(obligation), status=201)
    # No overcharge: no obligation created. Return an empty-data 201 per the
    # endpoint contract (create-shaped endpoint).
    return success({}, status=201)


def _resolve_ce_for_reconcile(drug_product_id, quarter):
    """Determine which covered entity owes a ceiling-reconciliation obligation.

    The B340B purchase orders for (drug, quarter) all carry a covered_entity_id;
    use the first chronological one. (In practice a reconcile run targets a
    single CE's replenishment orders.)"""
    for po in lookup.sorted_by_created(
        [
            p
            for p in db.purchase_orders.all()
            if p["drug_product_id"] == drug_product_id
            and p["quarter"] == quarter
            and p["channel"] == "B340B"
        ]
    ):
        return po["covered_entity_id"]
    return None
