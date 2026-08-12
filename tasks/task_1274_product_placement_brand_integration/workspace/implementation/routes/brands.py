"""Brand & brief endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util

bp = Blueprint("brands", __name__)

CATEGORIES = ["BEVERAGE", "AUTOMOTIVE", "TECH", "FOOD", "BEAUTY", "OTHER"]


def brand_view(b):
    return {k: b[k] for k in ("id", "name", "category", "watchlist_flag", "status",
                              "created_at", "updated_at", "version")}


def brief_view(b):
    return {k: b[k] for k in ("id", "brand_id", "title", "objective", "budget_cents",
                              "remaining_budget_cents", "status",
                              "created_at", "updated_at", "version")}


def clearance_view(c):
    return {k: c[k] for k in ("id", "episode_id", "brand_id", "category", "risk_score",
                              "decided_by_user_id", "status",
                              "created_at", "updated_at", "version")}


@bp.route("/brands", methods=["POST"])
def create_brand():
    middleware.require_roles("AgencyAdmin")
    body = middleware.get_json_body()
    name = util.req_str(body, "name")
    category = util.req_enum(body, "category", CATEGORIES)
    watchlist = util.opt_bool(body, "watchlist_flag", False)
    ent = util.new_entity()
    ent.update({"name": name, "category": category, "watchlist_flag": watchlist,
                "status": "ACTIVE"})
    db.brands[ent["id"]] = ent
    return response.success_object(brand_view(ent), 201)


@bp.route("/brands/<bid>", methods=["GET"])
def get_brand(bid):
    middleware.require_roles(*middleware.ALL_ROLES)
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    return response.success_object(brand_view(b))


@bp.route("/brands/<bid>/suspend", methods=["POST"])
def suspend_brand(bid):
    middleware.require_roles("AgencyAdmin")
    middleware.get_json_body(required=False)
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    if b["status"] != "ACTIVE":
        raise errors.invalid_state("Brand is not ACTIVE")
    b["status"] = "SUSPENDED"
    util.touch(b)
    return response.success_object(brand_view(b))


@bp.route("/brands/<bid>/resume", methods=["POST"])
def resume_brand(bid):
    middleware.require_roles("AgencyAdmin")
    middleware.get_json_body(required=False)
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    if b["status"] != "SUSPENDED":
        raise errors.invalid_state("Brand is not SUSPENDED")
    b["status"] = "ACTIVE"
    util.touch(b)
    return response.success_object(brand_view(b))


@bp.route("/brands/<bid>/briefs", methods=["POST"])
def create_brief(bid):
    user_id, _ = middleware.require_roles("BrandRep")
    body = middleware.get_json_body()
    title = util.req_str(body, "title")
    objective = util.req_str(body, "objective")
    budget = util.req_int(body, "budget_cents", minimum=0)
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    if user_id != bid:
        raise errors.forbidden_ownership("BrandRep may only create briefs for their own brand")
    ent = util.new_entity()
    ent.update({"brand_id": bid, "title": title, "objective": objective,
                "budget_cents": budget, "remaining_budget_cents": budget,
                "status": "DRAFT"})
    db.briefs[ent["id"]] = ent
    return response.success_object(brief_view(ent), 201)


@bp.route("/brands/<bid>/briefs", methods=["GET"])
def list_briefs(bid):
    middleware.require_roles(*middleware.ALL_ROLES)
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.briefs.values() if x["brand_id"] == bid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([brief_view(x) for x in page], limit, offset, total)


@bp.route("/brands/<bid>/clearances", methods=["GET"])
def list_brand_clearances(bid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep", "ClearanceOfficer")
    b = db.brands.get(bid)
    if b is None:
        raise errors.not_found("Brand not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.clearances.values() if x["brand_id"] == bid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([clearance_view(x) for x in page], limit, offset, total)


# ---- brief-scoped endpoints ----

@bp.route("/briefs/<bid>", methods=["GET"])
def get_brief(bid):
    middleware.require_roles(*middleware.ALL_ROLES)
    b = db.briefs.get(bid)
    if b is None:
        raise errors.not_found("Brief not found")
    return response.success_object(brief_view(b))


@bp.route("/briefs/<bid>/submit", methods=["POST"])
def submit_brief(bid):
    user_id, _ = middleware.require_roles("BrandRep")
    middleware.get_json_body(required=False)
    b = db.briefs.get(bid)
    if b is None:
        raise errors.not_found("Brief not found")
    if user_id != b["brand_id"]:
        raise errors.forbidden_ownership("BrandRep may only submit their own brand's brief")
    if b["status"] == "CLOSED":
        raise errors.already_terminal("Brief is CLOSED")
    if b["status"] != "DRAFT":
        raise errors.invalid_state("Brief is not DRAFT")
    if not b["budget_cents"] > 0:
        raise errors.invalid_state("Brief budget must be > 0 to submit")
    b["status"] = "OPEN"
    util.touch(b)
    return response.success_object(brief_view(b))


@bp.route("/briefs/<bid>/close", methods=["POST"])
def close_brief(bid):
    user_id, _ = middleware.require_roles("BrandRep")
    middleware.get_json_body(required=False)
    b = db.briefs.get(bid)
    if b is None:
        raise errors.not_found("Brief not found")
    if user_id != b["brand_id"]:
        raise errors.forbidden_ownership("BrandRep may only close their own brand's brief")
    if b["status"] == "CLOSED":
        raise errors.already_terminal("Brief is CLOSED")
    if b["status"] != "OPEN":
        raise errors.invalid_state("Brief is not OPEN")
    from services import calc
    for p in db.proposals.values():
        if p["brief_id"] == bid and p["status"] in calc.IN_FLIGHT_PROPOSAL_STATUSES:
            raise errors.invalid_state("Brief has in-flight proposals")
    b["status"] = "CLOSED"
    util.touch(b)
    return response.success_object(brief_view(b))


@bp.route("/briefs/<bid>/proposals", methods=["GET"])
def list_brief_proposals(bid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer")
    b = db.briefs.get(bid)
    if b is None:
        raise errors.not_found("Brief not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.proposals.values() if x["brief_id"] == bid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    from routes.proposals import proposal_view
    return response.success_list([proposal_view(x) for x in page], limit, offset, total)
