"""SKU definition, surface marking, release and inventory positioning (PRD 3.4)."""

from flask import Blueprint

import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import all_sorted, db, new_record, touch
from serializers import view, views
from services import pricing
from util import D

bp = Blueprint("products", __name__)


def _required_marking_text(cert, awg_size, application_rating, temp_rating_c, voltage_rating_v):
    """`UL E12345 12AWG THHN 90C 600V` — exact, case-sensitive (PRD 3.4)."""
    return "%s %s %sAWG %s %dC %dV" % (
        cert["agency"],
        cert["file_number"],
        awg_size,
        application_rating,
        temp_rating_c,
        voltage_rating_v,
    )


@bp.route("/catalog-products", methods=["POST"])
def create_product():
    require_auth("ProcessEngineer", "PlantAdmin")
    b = validation.body()
    product_code = validation.f_str(b, "product_code")
    awg_size = validation.f_str(b, "awg_size")
    conductor_metal = validation.f_enum(b, "conductor_metal", C.METALS)
    construction = validation.f_enum(b, "conductor_construction", C.CONSTRUCTIONS)
    application_rating = validation.f_enum(b, "application_rating", C.APPLICATION_RATINGS)
    voltage_class = validation.f_enum(b, "voltage_class", C.VOLTAGE_CLASSES)
    temp_rating_c = validation.f_int(b, "temp_rating_c", choices=C.TEMP_RATINGS)
    thickness = validation.f_num(b, "insulation_thickness_mils", gt=0)
    lbs_per_kft = validation.f_num(b, "conductor_lbs_per_kft", gt=0)
    insulation_id = validation.f_str(b, "insulation_compound_id")
    jacket_id = validation.f_str(b, "jacket_compound_id", required=False, default=None)
    cert_id = validation.f_str(b, "listing_certification_id")
    base_target = validation.f_num(b, "base_target_kft", gt=0)
    min_wall_pct = validation.f_num(b, "min_wall_pct", required=False, default=D("90"), ge=80, le=100)
    concentricity_min = validation.f_num(
        b, "concentricity_min_pct", required=False, default=D("85"), ge=50, le=100
    )
    demand_index = validation.f_num(b, "demand_index", required=False, default=D("1.0"), gt=0)

    # Body references resolve in the order fixed by PRD 2.10.
    insulation = lookups.compound(insulation_id)
    jacket = lookups.compound(jacket_id) if jacket_id is not None else None
    cert = lookups.certification(cert_id)

    if insulation["layer_role"] != "INSULATION":
        validation.bad("insulation_compound_id must name a compound whose layer_role is INSULATION")
    if jacket is not None and jacket["layer_role"] != "JACKET":
        validation.bad("jacket_compound_id must name a compound whose layer_role is JACKET")

    for p in db.catalog_products.values():
        if p["product_code"] == product_code:
            errors.fail(
                errors.ERR_DUPLICATE_PRODUCT_CODE,
                "product_code %s already exists in the catalog" % product_code,
            )

    voltage_rating_v = C.VOLTAGE_MAP[voltage_class]
    rec = new_record()
    rec.update({
        "product_code": product_code,
        "awg_size": awg_size,
        "conductor_metal": conductor_metal,
        "conductor_construction": construction,
        "application_rating": application_rating,
        "voltage_class": voltage_class,
        "temp_rating_c": temp_rating_c,
        "insulation_thickness_mils": thickness,
        "min_wall_pct": min_wall_pct,
        "concentricity_min_pct": concentricity_min,
        "conductor_lbs_per_kft": lbs_per_kft,
        "insulation_compound_id": insulation_id,
        "jacket_compound_id": jacket_id,
        "listing_certification_id": cert_id,
        "base_target_kft": base_target,
        "demand_index": demand_index,
        "pinned_insulation_compound_version": None,
        "pinned_jacket_compound_version": None,
        "voltage_rating_v": voltage_rating_v,
        "marking_required": application_rating in C.BUILDING_WIRE_RATINGS,
        "pd_test_required": voltage_class in C.PD_REQUIRED_CLASSES,
        "required_marking_text": _required_marking_text(
            cert, awg_size, application_rating, temp_rating_c, voltage_rating_v
        ),
        "volatility_index": D("0.0000"),
        "target_inventory_kft": base_target,
        "status": "DRAFT",
    })
    db.catalog_products[rec["id"]] = rec
    return response.created(view("catalog_product", rec))


_READ_ROLES = (
    "ProcessEngineer",
    "QualityEngineer",
    "CertificationOfficer",
    "ShippingClerk",
    "BillingAnalyst",
    "PlantAdmin",
)


@bp.route("/catalog-products/<product_id>", methods=["GET"])
def get_product(product_id):
    require_auth(*_READ_ROLES)
    rec = lookups.product(product_id)
    return response.ok(view("catalog_product", rec))


@bp.route("/catalog-products", methods=["GET"])
def list_products():
    require_auth(*_READ_ROLES)
    limit, offset = validation.pagination()
    insulation_id = validation.q_str("insulation_compound_id")
    jacket_id = validation.q_str("jacket_compound_id")
    cert_id = validation.q_str("listing_certification_id")
    status = validation.q_enum("status", C.PRODUCT_STATUSES)
    application_rating = validation.q_enum("application_rating", C.APPLICATION_RATINGS)

    rows = all_sorted(db.catalog_products)
    if insulation_id is not None:
        rows = [r for r in rows if r["insulation_compound_id"] == insulation_id]
    if jacket_id is not None:
        rows = [r for r in rows if r["jacket_compound_id"] == jacket_id]
    if cert_id is not None:
        rows = [r for r in rows if r["listing_certification_id"] == cert_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if application_rating is not None:
        rows = [r for r in rows if r["application_rating"] == application_rating]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("catalog_product", page), limit, offset, total)


@bp.route("/catalog-products/<product_id>/release", methods=["POST"])
def release_product(product_id):
    require_auth("ProcessEngineer", "PlantAdmin")
    validation.body()
    product = lookups.product(product_id)
    if product["status"] not in ("DRAFT", "SUSPENDED"):
        errors.fail(
            errors.ERR_INVALID_PRODUCT_STATE,
            "A SKU at %s may not be released" % product["status"],
        )

    insulation = db.compounds.get(product["insulation_compound_id"])
    jacket = (
        db.compounds.get(product["jacket_compound_id"])
        if product["jacket_compound_id"] is not None
        else None
    )
    if insulation is None or insulation["status"] != "QUALIFIED":
        errors.fail(
            errors.ERR_COMPOUND_NOT_QUALIFIED,
            "The insulation compound must be QUALIFIED before the SKU is released",
        )
    if jacket is not None and jacket["status"] != "QUALIFIED":
        errors.fail(
            errors.ERR_COMPOUND_NOT_QUALIFIED,
            "The jacket compound must be QUALIFIED before the SKU is released",
        )

    if insulation["temp_rating_c"] < product["temp_rating_c"]:
        errors.fail(
            errors.ERR_COMPOUND_RATING_INSUFFICIENT,
            "The insulation compound's temperature rating does not cover the print",
        )
    if insulation["max_voltage_v"] < product["voltage_rating_v"]:
        errors.fail(
            errors.ERR_COMPOUND_RATING_INSUFFICIENT,
            "The insulation compound's voltage ceiling does not cover the print",
        )
    if product["application_rating"] in ("THHN", "THWN_2") and insulation["flame_test"] != "VW_1":
        errors.fail(
            errors.ERR_COMPOUND_RATING_INSUFFICIENT,
            "%s requires an insulation compound qualified to VW_1" % product["application_rating"],
        )

    cert = db.listing_certifications.get(product["listing_certification_id"])
    if cert is None or cert["status"] != "ACTIVE":
        errors.fail(
            errors.ERR_CERTIFICATION_NOT_ACTIVE,
            "The SKU's listing file must be ACTIVE to release it",
        )

    product["pinned_insulation_compound_version"] = insulation["version"]
    product["pinned_jacket_compound_version"] = jacket["version"] if jacket is not None else None
    product["status"] = "RELEASED"
    touch(product)
    return response.ok(view("catalog_product", product))


@bp.route("/inventory/reposition", methods=["POST"])
def reposition_inventory():
    require_auth("ProcessEngineer", "PlantAdmin")
    b = validation.body()
    as_of_date = validation.f_date(b, "as_of_date")
    product_ids = validation.f_str_array(b, "product_ids", required=False, default=None)

    if product_ids is None:
        scope = all_sorted(db.catalog_products)
    else:
        scope = [lookups.product(pid) for pid in product_ids]
        # De-duplicate while keeping the deterministic created_at ordering.
        seen = set()
        unique = []
        for p in scope:
            if p["id"] not in seen:
                seen.add(p["id"])
                unique.append(p)
        scope = sorted(unique, key=lambda r: (r["created_at"], r["_seq"]))

    evaluated = []
    skipped = 0
    for product in scope:
        if product["status"] != "RELEASED":
            skipped += 1
            continue
        product["volatility_index"] = pricing.metal_volatility_index(
            product["conductor_metal"], as_of_date
        )
        product["target_inventory_kft"] = pricing.inventory_reposition_target(product)
        touch(product)
        evaluated.append(product["id"])

    return response.ok({
        "as_of_date": as_of_date,
        "evaluated_count": len(evaluated),
        "skipped_count": skipped,
        "product_ids": evaluated,
    })
