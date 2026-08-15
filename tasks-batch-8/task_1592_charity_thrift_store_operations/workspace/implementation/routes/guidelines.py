"""PricingGuideline endpoints (PRD §3.3)."""
from flask import Blueprint

from db import db, new_record, touch
from errors import ApiError, invalid_request, not_found
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list

bp = Blueprint("guidelines", __name__)

ITEM_CATEGORIES = ["CLOTHING", "FURNITURE", "ELECTRONICS", "HOUSEWARES",
                   "BOOKS_MEDIA", "TOYS", "COLLECTIBLES"]


def guideline_view(g):
    return dict(g)


@bp.route("/api/pricing-guidelines", methods=["POST"])
def create_guideline():
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("category", "string"), ("base_cents", "integer")],
        optional=[("demand_multiplier", "number")],
        enums={"category": ITEM_CATEGORIES},
    )
    if payload["base_cents"] <= 0:
        raise invalid_request("base_cents must be > 0")
    demand = payload.get("demand_multiplier", 1.0)
    if float(demand) <= 0:
        raise invalid_request("demand_multiplier must be > 0")

    # supersede the prior ACTIVE guideline for the category
    prior = None
    for g in db.guidelines.values():
        if g["category"] == payload["category"] and g["status"] == "ACTIVE":
            prior = g
            break
    version_no = 1
    supersedes_id = None
    if prior is not None:
        prior["status"] = "RETIRED"
        touch(prior)
        version_no = prior["version_no"] + 1
        supersedes_id = prior["id"]

    rec = new_record()
    rec.update({
        "category": payload["category"],
        "base_cents": payload["base_cents"],
        "demand_multiplier": demand,
        "version_no": version_no,
        "status": "ACTIVE",
        "supersedes_id": supersedes_id,
    })
    db.guidelines[rec["id"]] = rec
    return success_object(guideline_view(rec), status=201)


@bp.route("/api/pricing-guidelines/<guideline_id>", methods=["GET"])
def get_guideline(guideline_id):
    require_roles(ALL_ROLES)
    g = db.guidelines.get(guideline_id)
    if g is None:
        raise not_found("pricing guideline")
    return success_object(guideline_view(g))


@bp.route("/api/pricing-guidelines", methods=["GET"])
def list_guidelines():
    require_roles(ALL_ROLES)
    filters = query_filters(["category", "status", "supersedes_id"])
    records = apply_filters(list(db.guidelines.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([guideline_view(g) for g in page], limit, offset, total)
