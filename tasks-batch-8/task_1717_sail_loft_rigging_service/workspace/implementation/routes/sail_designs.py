"""SailDesign endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles, require_owner
from response import success_object, success_list
from services import domain, calculations as calc

bp = Blueprint("sail_designs", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
CLOTH_TIERS = ("CRUISE", "PERFORMANCE", "RACE", "GRAND_PRIX")
OPTION_CODES = ("BATTENS", "REEF_POINTS", "UV_STRIP", "NUMBERS", "LOGO")


@bp.post("/lofts/boats/<boatId>/sail-designs")
def create_design(boatId):
    require_roles("Sailmaker")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    measurement_sheet_id = util.as_string(util.require_field(body, "measurement_sheet_id"), "measurement_sheet_id")
    cloth_tier = util.as_enum(util.require_field(body, "cloth_tier"), "cloth_tier", CLOTH_TIERS)
    reinforcement_level = util.as_int(util.opt_field(body, "reinforcement_level", 1), "reinforcement_level")
    if reinforcement_level < 1 or reinforcement_level > 5:
        raise errors.invalid_request("reinforcement_level must be an integer 1-5")
    option_codes = util.as_enum_array(util.opt_field(body, "option_codes", []), "option_codes", OPTION_CODES)
    expected_boat_version = util.as_int(util.require_field(body, "expected_boat_version"), "expected_boat_version")
    # PRD §3.3 allocates the "sheet must exist and be FROZEN" rule (and its
    # ERR_MEASUREMENT_NOT_FROZEN error) to design SUBMISSION, not creation:
    # "the pinned measurement sheet must exist and be `FROZEN` at submission".
    # OCC check — last gate.
    if expected_boat_version != boat["version"]:
        raise errors.stale_boat_version()
    # Supersede prior APPROVED design for the boat.
    prior = None
    for d in db.sail_designs.values():
        if d["boat_id"] == boat["id"] and d["design_status"] == "APPROVED":
            prior = d
            break
    revision_number = 1
    supersedes_design_id = None
    if prior is not None:
        revision_number = prior["revision_number"] + 1
        supersedes_design_id = prior["id"]
        domain.supersede_approved_design_cascade(prior)
    design = util.stamp_new({
        "boat_id": boat["id"],
        "measurement_sheet_id": measurement_sheet_id,
        "revision_number": revision_number,
        "supersedes_design_id": supersedes_design_id,
        "cloth_tier": cloth_tier,
        "reinforcement_level": reinforcement_level,
        "option_codes": option_codes,
        "design_status": "DRAFT",
        "rejection_reason": None,
    })
    db.sail_designs[design["id"]] = design
    # Successful creation increments Boat.version by 1.
    util.touch(boat)
    return success_object(domain.serialize(design), 201)


@bp.get("/lofts/boats/<boatId>/sail-designs")
def list_boat_designs(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [d for d in db.sail_designs.values() if d["boat_id"] == boatId]
    items = util.filter_exact(items, "design_status", request.args.get("design_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(d) for d in page], limit, offset, total)


@bp.get("/lofts/sail-designs")
def list_designs():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.sail_designs.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "measurement_sheet_id", request.args.get("measurement_sheet_id"))
    items = util.filter_exact(items, "supersedes_design_id", request.args.get("supersedes_design_id"))
    items = util.filter_exact(items, "design_status", request.args.get("design_status"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(d) for d in page], limit, offset, total)


@bp.get("/lofts/sail-designs/<designId>")
def get_design(designId):
    require_roles(*READ_ROLES)
    design = domain.get_design_or_404(designId)
    return success_object(domain.serialize(design))


@bp.post("/lofts/boats/<boatId>/sail-designs/<designId>/submit")
def submit_design(boatId, designId):
    require_roles("Sailmaker")
    boat = domain.get_boat_or_404(boatId)
    design = domain.get_design_or_404(designId)
    domain.check_child_of(design, "boat_id", boat["id"])
    if design["design_status"] != "DRAFT":
        raise errors.invalid_state(f"Design must be DRAFT to submit (is {design['design_status']})")
    sheet = db.measurement_sheets.get(design["measurement_sheet_id"])
    if sheet is None or sheet["sheet_status"] != "FROZEN":
        raise errors.measurement_not_frozen()
    design["design_status"] = "SUBMITTED"
    util.touch(design)
    return success_object(domain.serialize(design))


@bp.post("/lofts/boats/<boatId>/sail-designs/<designId>/approve")
def approve_design(boatId, designId):
    user_id, _ = require_roles("Customer")
    boat = domain.get_boat_or_404(boatId)
    design = domain.get_design_or_404(designId)
    domain.check_child_of(design, "boat_id", boat["id"])
    # State gate runs before credit check (PRD §3.3).
    if design["design_status"] != "SUBMITTED":
        raise errors.design_not_in_required_state(
            f"SailDesign must be SUBMITTED for approve (is {design['design_status']})"
        )
    require_owner(user_id, boat["customer_id"])
    customer = domain.get_customer_or_404(boat["customer_id"])
    if customer["status"] != "ACTIVE":
        raise errors.invalid_state("Customer must be ACTIVE to approve a design")
    sheet = domain.get_sheet_or_404(design["measurement_sheet_id"])
    projected = calc.sail_price_provisional(design, sheet, boat)
    if customer["outstanding_balance_cents"] + projected > customer["credit_limit_cents"]:
        raise errors.credit_limit_exceeded()
    design["design_status"] = "APPROVED"
    util.touch(design)
    return success_object(domain.serialize(design))


@bp.post("/lofts/boats/<boatId>/sail-designs/<designId>/request-revision")
def request_revision(boatId, designId):
    user_id, _ = require_roles("Customer")
    boat = domain.get_boat_or_404(boatId)
    design = domain.get_design_or_404(designId)
    domain.check_child_of(design, "boat_id", boat["id"])
    if design["design_status"] != "SUBMITTED":
        raise errors.invalid_state(f"Design must be SUBMITTED to request revision (is {design['design_status']})")
    require_owner(user_id, boat["customer_id"])
    body = util.get_body()
    rejection_reason = util.as_string(util.require_field(body, "rejection_reason"), "rejection_reason")
    design["design_status"] = "REVISION_REQUESTED"
    design["rejection_reason"] = rejection_reason
    util.touch(design)
    return success_object(domain.serialize(design))


@bp.post("/lofts/boats/<boatId>/sail-designs/<designId>/redraft")
def redraft_design(boatId, designId):
    require_roles("Sailmaker")
    boat = domain.get_boat_or_404(boatId)
    design = domain.get_design_or_404(designId)
    domain.check_child_of(design, "boat_id", boat["id"])
    if design["design_status"] != "REVISION_REQUESTED":
        raise errors.invalid_state(f"Design must be REVISION_REQUESTED to redraft (is {design['design_status']})")
    design["design_status"] = "DRAFT"
    util.touch(design)
    return success_object(domain.serialize(design))
