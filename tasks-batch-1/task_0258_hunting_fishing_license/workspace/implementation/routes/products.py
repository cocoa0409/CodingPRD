"""LicenseProduct endpoints (PRD §3.3)."""
from flask import Blueprint, request

import serialize
from db import store
from errors import err, ERR_DUPLICATE_SKU
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_enum, as_int, as_bool,
    parse_pagination, paginate,
)
from services.core import (
    get_license_product_or_404, get_species_season_or_404,
)

bp = Blueprint("products", __name__)

PRODUCT_KINDS = {"LICENSE", "TAG", "STAMP"}
RESIDENCY_RESTRICTIONS = {"ANY", "RESIDENT_ONLY", "NONRESIDENT_ONLY"}


@bp.route("/license-products", methods=["POST"])
@require_roles("DrawOfficer")
def create_license_product():
    body = get_json_body()
    sku = as_nonempty_str(body, "sku", required=True)
    product_kind = as_enum(body, "product_kind", PRODUCT_KINDS, required=True)
    base_fee_cents = as_int(body, "base_fee_cents", required=True, minimum=0)
    species_season_id = as_nonempty_str(
        body, "species_season_id", required=False, default=None
    )
    requires_education = as_bool(
        body, "requires_education", required=False, default=False
    )
    residency_restriction = as_enum(
        body, "residency_restriction", RESIDENCY_RESTRICTIONS,
        required=False, default="ANY",
    )
    min_age_years = as_int(
        body, "min_age_years", required=False, default=0, minimum=0
    )

    # FK existence (PRD §2.5): species_season_id when supplied.
    if species_season_id is not None:
        get_species_season_or_404(species_season_id)

    # sku must be unique among ACTIVE products (PRD §3.3).
    for p in store.license_products.values():
        if p["status"] == "ACTIVE" and p["sku"] == sku:
            raise err(ERR_DUPLICATE_SKU, "sku already used by an ACTIVE product")

    record = {
        "sku": sku,
        "product_kind": product_kind,
        "species_season_id": species_season_id,
        "requires_education": requires_education,
        "residency_restriction": residency_restriction,
        "base_fee_cents": base_fee_cents,
        "min_age_years": min_age_years,
        "status": "ACTIVE",
    }
    store.stamp_new(record)
    store.license_products[record["id"]] = record
    return success(serialize.license_product(record), status=201, response_type="object")


@bp.route("/license-products/<id>", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "Applicant")
def get_license_product(id):
    record = get_license_product_or_404(id)
    return success(serialize.license_product(record), status=200, response_type="object")


@bp.route("/license-products", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "Applicant")
def list_license_products():
    limit, offset = parse_pagination()
    items = list(store.license_products.values())
    season_id = request.args.get("species_season_id")
    if season_id is not None:
        items = [r for r in items if r["species_season_id"] == season_id]
    kind = request.args.get("product_kind")
    if kind is not None:
        items = [r for r in items if r["product_kind"] == kind]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.license_product(r) for r in page], limit, offset, total
    )


@bp.route("/license-products/<id>/retire", methods=["POST"])
@require_roles("DrawOfficer")
def retire_license_product(id):
    record = get_license_product_or_404(id)
    record["status"] = "RETIRED"
    store.touch(record)
    return success(serialize.license_product(record), status=200, response_type="object")
