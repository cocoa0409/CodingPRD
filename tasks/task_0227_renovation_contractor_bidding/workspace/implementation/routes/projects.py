"""Project routes: CRUD, scope/milestones, estimate, open/award/cancel/complete/rate."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_principal
from services import common, lookups, calculations

bp = Blueprint("projects", __name__)

TRADES = {"GENERAL", "ELECTRICAL", "PLUMBING", "HVAC", "ROOFING"}
UNITS = {"SQFT", "UNIT", "HOUR", "LUMP"}


def _owner_check(project, user_id, role):
    """Homeowner ownership: project.homeowner_id == X-User-ID."""
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this project.")


# ---------------------------------------------------------------------------
# Create / fetch / list
# ---------------------------------------------------------------------------
@bp.route("/projects", methods=["POST"])
def create_project():
    user_id, role = require_roles("Homeowner")
    body = common.get_body()
    homeowner_id = common.as_str(common.require_field(body, "homeowner_id"), "homeowner_id")
    title = common.as_str(common.require_field(body, "title"), "title")
    budget = common.as_int(common.require_field(body, "budget_cap_cents"), "budget_cap_cents")
    if budget <= 0:
        raise errors.invalid_request("budget_cap_cents must be > 0.")
    bid_deadline_raw = common.require_field(body, "bid_deadline")
    bid_deadline = common.parse_iso(bid_deadline_raw, "bid_deadline")
    required_trade = common.as_enum(
        common.require_field(body, "required_trade"), "required_trade", TRADES)
    min_rating = 0
    if "min_rating" in body and body["min_rating"] is not None:
        min_rating = common.as_number(body["min_rating"], "min_rating")
        if min_rating < 0 or min_rating > 5:
            raise errors.invalid_request("min_rating must be between 0 and 5.")

    # Ownership: a homeowner creates projects under their own id.
    lookups.get_homeowner(homeowner_id)
    if role == "Homeowner" and homeowner_id != user_id:
        raise errors.not_owner("Homeowner can only create projects for themselves.")

    rec = {
        "homeowner_id": homeowner_id,
        "title": title,
        "budget_cap_cents": budget,
        "bid_deadline": bid_deadline_raw,
        "_bid_deadline_dt": bid_deadline,
        "required_trade": required_trade,
        "min_rating": min_rating,
        "status": "DRAFT",
        "awarded_bid_id": None,
        "contract_value_cents": 0,
        "scope_locked": False,
    }
    common.stamp_new(rec)
    db.projects[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/projects/<rid>", methods=["GET"])
def get_project(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    rec = lookups.get_project(rid)
    return response.success(common.public(rec), 200)


@bp.route("/projects", methods=["GET"])
def list_projects():
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    items = list(db.projects.values())
    ho = request.args.get("homeowner_id")
    if ho is not None:
        items = [p for p in items if p["homeowner_id"] == ho]
    ab = request.args.get("awarded_bid_id")
    if ab is not None:
        items = [p for p in items if p.get("awarded_bid_id") == ab]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Scope line items
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/scope-line-items", methods=["POST"])
def add_scope_item(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    # scope_locked => no further scope creation (PRD §3.2). Project must be DRAFT.
    if project["scope_locked"] or project["status"] != "DRAFT":
        raise errors.invalid_state("Scope can only be added to a DRAFT, unlocked project.")
    body = common.get_body()
    description = common.as_str(common.require_field(body, "description"), "description")
    quantity = common.as_number(common.require_field(body, "quantity"), "quantity")
    if quantity <= 0:
        raise errors.invalid_request("quantity must be > 0.")
    unit = common.as_enum(common.require_field(body, "unit"), "unit", UNITS)
    unit_cost = common.as_int(
        common.require_field(body, "estimated_unit_cost_cents"), "estimated_unit_cost_cents")
    if unit_cost < 0:
        raise errors.invalid_request("estimated_unit_cost_cents must be >= 0.")

    rec = {
        "project_id": rid,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "estimated_unit_cost_cents": unit_cost,
        "estimated_total_cents": calculations.scope_line_estimate(quantity, unit_cost),
    }
    common.stamp_new(rec)
    db.scope_line_items[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/projects/<rid>/scope-line-items", methods=["GET"])
def list_scope_items(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    lookups.get_project(rid)
    items = lookups.scope_items_for_project(rid)
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/milestones", methods=["POST"])
def add_milestone(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    if project["status"] != "DRAFT":
        raise errors.invalid_state("Milestones can only be added to a DRAFT project.")
    body = common.get_body()
    sequence = common.as_int(common.require_field(body, "sequence"), "sequence")
    if sequence < 1:
        raise errors.invalid_request("sequence must be >= 1.")
    title = common.as_str(common.require_field(body, "title"), "title")
    release_pct = common.as_number(common.require_field(body, "release_pct"), "release_pct")
    if not (release_pct > 0 and release_pct <= 1):
        raise errors.invalid_request("release_pct must be > 0 and <= 1.")
    # sequence uniqueness within project (ERR_MILESTONE_SEQUENCE_TAKEN, 409)
    for m in lookups.milestones_for_project(rid):
        if m["sequence"] == sequence:
            raise errors.ApiError(errors.ERR_MILESTONE_SEQUENCE_TAKEN, 409,
                                  "A milestone with this sequence already exists.")
    rec = {
        "project_id": rid,
        "sequence": sequence,
        "title": title,
        "release_pct": release_pct,
        "status": "PENDING",
    }
    common.stamp_new(rec)
    db.milestones[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/projects/<rid>/milestones", methods=["GET"])
def list_milestones(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    lookups.get_project(rid)
    items = lookups.milestones_for_project(rid)
    # Ascending sequence order (PRD §4 endpoint description).
    limit, offset = common.parse_pagination()
    ordered = sorted(items, key=lambda m: m["sequence"])
    total = len(ordered)
    page = [common.public(m) for m in ordered[offset:offset + limit]]
    return response.success_list(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/estimate", methods=["GET"])
def project_estimate(rid):
    require_roles("Homeowner", "PlatformAdmin")
    project = lookups.get_project(rid)
    # Ownership not required for estimate per RBAC (Homeowner, PlatformAdmin), but
    # a Homeowner reads their own; PRD does not impose owner gate here beyond role.
    total, count = calculations.project_estimate(rid)
    return response.success({"estimated_total_cents": total, "line_count": count}, 200)


# ---------------------------------------------------------------------------
# Open for bids
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/open", methods=["POST"])
def open_project(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    if project["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT project can be opened.")
    scope = lookups.scope_items_for_project(rid)
    milestones = lookups.milestones_for_project(rid)
    if len(scope) < 1:
        raise errors.invalid_state("At least one scope line item is required to open.")
    if len(milestones) < 1:
        raise errors.invalid_state("At least one milestone is required to open.")
    pct_sum = sum(Decimal(str(m["release_pct"])) for m in milestones)
    if pct_sum != Decimal("1.0"):
        raise errors.ApiError(errors.ERR_MILESTONE_PCT_INVALID, 422,
                              "Milestone release_pct values must sum to exactly 1.0.")
    if db.clock.now() >= project["_bid_deadline_dt"]:
        raise errors.invalid_state("Cannot open a project past its bid_deadline.")
    project["status"] = "OPEN_FOR_BIDS"
    common.touch(project)
    return response.success(common.public(project), 200)


# ---------------------------------------------------------------------------
# Bid comparison (advisory) — estimated_rank variant
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/bid-comparison", methods=["GET"])
def bid_comparison(rid):
    require_roles("Homeowner", "PlatformAdmin")
    lookups.get_project(rid)
    submitted = [b for b in lookups.bids_for_project(rid) if b["status"] == "SUBMITTED"]
    ranked, _ = calculations.rank_bids(submitted)  # best-first; rank_score annotated, not persisted
    limit, offset = common.parse_pagination()
    total = len(ranked)
    page = [common.public(b) for b in ranked[offset:offset + limit]]
    return response.success_list(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Award — OCC-guarded cascade
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/award", methods=["POST"])
def award_project(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    body = common.get_body()
    bid_id = common.as_str(common.require_field(body, "bid_id"), "bid_id")
    expected_version = common.as_int(
        common.require_field(body, "expected_project_version"), "expected_project_version")
    # existence of named bid (priority 4) before state check
    bid = lookups.get_bid(bid_id)

    # OCC (PRD §2.9): a stale version is reported as ERR_STALE_PROJECT_VERSION
    # even when the project has already left OPEN_FOR_BIDS — §2.9 explicitly
    # describes this case ("the project may already have left its open-for-bids
    # state") and dictates ERR_STALE_PROJECT_VERSION. The OCC check therefore
    # precedes the OPEN_FOR_BIDS state requirement: any award that moved the
    # project out of OPEN_FOR_BIDS also bumped its version, so a client holding
    # the pre-award version is caught here first.
    if expected_version != project["version"]:
        raise errors.ApiError(errors.ERR_STALE_PROJECT_VERSION, 412,
                              "expected_project_version does not match current project version.")
    # state: project must be OPEN_FOR_BIDS
    if project["status"] != "OPEN_FOR_BIDS":
        raise errors.invalid_state("Project must be OPEN_FOR_BIDS to award.")
    # named bid belongs to project and is SUBMITTED (state)
    if bid["project_id"] != rid or bid["status"] != "SUBMITTED":
        raise errors.invalid_state("Named bid must belong to this project and be SUBMITTED.")
    # budget (priority 15)
    if bid["total_cents"] > project["budget_cap_cents"]:
        raise errors.ApiError(errors.ERR_BUDGET_EXCEEDED, 409,
                              "Awarded bid total exceeds budget_cap_cents.")

    # ---- atomic cascade ----
    submitted_pool = [b for b in lookups.bids_for_project(rid) if b["status"] == "SUBMITTED"]
    _, scores = calculations.rank_bids(submitted_pool)
    # persist rank_score on each pooled bid
    for b in submitted_pool:
        b["rank_score"] = scores[b["id"]]
        common.touch(b)

    # named bid -> AWARDED
    bid["status"] = "AWARDED"
    common.touch(bid)

    # sibling SUBMITTED/REVISING bids -> REJECTED
    for b in lookups.bids_for_project(rid):
        if b["id"] == bid_id:
            continue
        if b["status"] in ("SUBMITTED", "REVISING"):
            b["status"] = "REJECTED"
            common.touch(b)

    project["awarded_bid_id"] = bid_id
    project["scope_locked"] = True
    project["contract_value_cents"] = bid["total_cents"]
    project["status"] = "AWARDED"

    # create Escrow UNFUNDED
    escrow = {
        "project_id": rid,
        "funded_cents": 0,
        "released_cents": 0,
        "retained_cents": 0,
        "available_cents": 0,
        "status": "UNFUNDED",
    }
    common.stamp_new(escrow)
    db.escrows[escrow["id"]] = escrow

    # increment project version by 1
    common.touch(project)
    return response.success(common.public(project), 200)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/cancel", methods=["POST"])
def cancel_project(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    if project["status"] != "OPEN_FOR_BIDS":
        raise errors.invalid_state("Only an OPEN_FOR_BIDS project can be cancelled.")
    project["status"] = "CANCELLED"
    common.touch(project)
    for b in lookups.bids_for_project(rid):
        if b["status"] in ("SUBMITTED", "REVISING"):
            b["status"] = "REJECTED"
            common.touch(b)
    return response.success(common.public(project), 200)


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/complete", methods=["POST"])
def complete_project(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Only an IN_PROGRESS project can be completed.")
    milestones = lookups.milestones_for_project(rid)
    if not all(m["status"] == "PAID" for m in milestones):
        raise errors.invalid_state("All milestones must be PAID to complete.")
    escrow = lookups.escrow_for_project(rid)
    if escrow is None or escrow["retained_cents"] != 0:
        raise errors.invalid_state("All retainage must be released before completion.")
    project["status"] = "COMPLETED"
    common.touch(project)
    escrow["status"] = "CLOSED"
    common.touch(escrow)
    return response.success(common.public(project), 200)


# ---------------------------------------------------------------------------
# Rate contractor
# ---------------------------------------------------------------------------
@bp.route("/projects/<rid>/rate-contractor", methods=["POST"])
def rate_contractor(rid):
    user_id, role = require_roles("Homeowner")
    project = lookups.get_project(rid)
    _owner_check(project, user_id, role)
    if project["status"] != "COMPLETED":
        raise errors.invalid_state("Only a COMPLETED project's contractor can be rated.")
    body = common.get_body()
    stars = common.as_int(common.require_field(body, "stars"), "stars")
    if stars < 1 or stars > 5:
        raise errors.invalid_request("stars must be between 1 and 5.")
    awarded_bid = lookups.get_bid(project["awarded_bid_id"])
    contractor = lookups.get_contractor(awarded_bid["contractor_id"])
    contractor["rating_sum"] += stars
    contractor["rating_count"] += 1
    contractor["average_rating"] = calculations.average_rating(
        contractor["rating_sum"], contractor["rating_count"])
    common.touch(contractor)
    return response.success(common.public(contractor), 200)
