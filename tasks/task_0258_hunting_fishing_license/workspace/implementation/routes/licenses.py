"""License endpoints incl. OTC issuance compliance stack (PRD §3.7) and
the bag-budget read (PRD §3.9)."""
from flask import Blueprint, request

import serialize
from db import store
from errors import (
    err, ERR_DRAW_REQUIRED, ERR_EDUCATION_REQUIRED, ERR_MINIMUM_AGE,
)
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, parse_pagination, paginate,
)
from services.core import (
    get_applicant_or_404, get_license_product_or_404, get_license_or_404,
    check_residency_restriction, compute_license_fee, age_in_years,
    counted_quantity_for_season,
)

bp = Blueprint("licenses", __name__)


@bp.route("/licenses", methods=["POST"])
@require_roles("LicenseAgent", "DrawOfficer")
def issue_license():
    body = get_json_body()
    applicant_id = as_nonempty_str(body, "applicant_id", required=True)
    license_product_id = as_nonempty_str(body, "license_product_id", required=True)

    # FK existence in body order (PRD §2.5).
    applicant = get_applicant_or_404(applicant_id)
    product = get_license_product_or_404(license_product_id)

    # Compliance stack, fixed order (PRD §3.7):
    # 1) draw-only rule
    if product["product_kind"] == "TAG" and product["species_season_id"] is not None:
        season = store.species_seasons.get(product["species_season_id"])
        if season is not None and season["draw_required"]:
            raise err(ERR_DRAW_REQUIRED, "Draw-required TAG cannot be sold over the counter")
    # 2) education prerequisite
    if product["requires_education"] and not applicant["education_certified"]:
        raise err(ERR_EDUCATION_REQUIRED, "Applicant is not education-certified")
    # 3) minimum age on the issuance date (current clock)
    if product["min_age_years"] > 0:
        age = age_in_years(applicant["birth_date"], store.now())
        if age < product["min_age_years"]:
            raise err(ERR_MINIMUM_AGE, "Applicant is below the product minimum age")
    # 4) residency restriction (also the pricing precondition, PRD §3.5)
    check_residency_restriction(product, applicant)

    fee = compute_license_fee(product, applicant, "OVER_THE_COUNTER")
    record = {
        "applicant_id": applicant_id,
        "license_product_id": license_product_id,
        "draw_application_id": None,
        "issued_via": "OVER_THE_COUNTER",
        "fee_charged_cents": fee,
        "status": "ISSUED",
        "superseded_by_id": None,
    }
    store.stamp_new(record)
    store.licenses[record["id"]] = record
    return success(serialize.license(record), status=201, response_type="object")


@bp.route("/licenses/<id>", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "GameWarden", "Applicant")
def get_license(id):
    record = get_license_or_404(id)
    return success(serialize.license(record), status=200, response_type="object")


@bp.route("/licenses", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "GameWarden", "Applicant")
def list_licenses():
    limit, offset = parse_pagination()
    items = list(store.licenses.values())
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        items = [r for r in items if r["applicant_id"] == applicant_id]
    product_id = request.args.get("license_product_id")
    if product_id is not None:
        items = [r for r in items if r["license_product_id"] == product_id]
    draw_app_id = request.args.get("draw_application_id")
    if draw_app_id is not None:
        items = [r for r in items if r["draw_application_id"] == draw_app_id]
    superseded_by_id = request.args.get("superseded_by_id")
    if superseded_by_id is not None:
        items = [r for r in items if r["superseded_by_id"] == superseded_by_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.license(r) for r in page], limit, offset, total
    )


@bp.route("/licenses/<id>/bag-budget", methods=["GET"])
@require_roles("DrawOfficer", "GameWarden", "Applicant")
def bag_budget(id):
    record = get_license_or_404(id)
    product = store.license_products.get(record["license_product_id"])
    season_id = product["species_season_id"] if product else None
    if season_id is None:
        # No bound season -> nothing to budget against.
        data = {
            "season_id": None,
            "bag_limit": 0,
            "counted": 0,
            "remaining": 0,
        }
        return success(data, status=200, response_type="object")
    season = store.species_seasons.get(season_id)
    bag_limit = season["bag_limit"] if season else 0
    counted = counted_quantity_for_season(record["applicant_id"], season_id)
    data = {
        "season_id": season_id,
        "bag_limit": bag_limit,
        "counted": counted,
        "remaining": bag_limit - counted,
    }
    return success(data, status=200, response_type="object")
