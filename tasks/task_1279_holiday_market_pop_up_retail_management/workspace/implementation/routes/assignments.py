"""BoothAssignment endpoints: create (fee computation), get/list, activate,
release, forfeit (PRD 3.4)."""
from flask import Blueprint

import clock
import db
from errors import ApiError, invalid_state, posture_forbidden, validation
from middleware import auth, require_roles
from response import success
from services import calc, cascades, posture
from services.core import (
    FORFEIT_REASONS,
    arg,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("assignments", __name__)

MO = ("MarketOperator",)
GET_ONE = ("MarketOperator", "VendorRole", "FinanceOfficer")
GET_LIST = ("MarketOperator", "FinanceOfficer")


def build_assignment(market, booth, application):
    """Shared BoothAssignment constructor with fee computation."""
    rec = base_record()
    base_rent = calc.compute_base_rent_cents(booth, market, rec["created_at"])
    heating = calc.compute_heating_surcharge_cents(application, booth)
    rec.update(
        {
            "market_id": market["id"],
            "booth_id": booth["id"],
            "application_id": application["id"],
            "base_rent_cents": base_rent,
            "heating_surcharge_cents": heating,
            "total_fee_cents": base_rent + heating,
            "status": "PENDING_PAYMENT",
            "_ops_index_at_creation": market["run_ops_index"],
        }
    )
    db.STORES["assignments"][rec["id"]] = rec
    return rec


@bp.post("/markets/<marketId>/assignments")
def create_assignment(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    data = body()
    booth_id = as_str(required(data, "booth_id"), "booth_id")
    application_id = as_str(required(data, "application_id"), "application_id")
    booth = get_child("booths", booth_id, marketId)
    application = get_child("applications", application_id, marketId)
    if booth["status"] != "AVAILABLE":
        raise ApiError("ERR_BOOTH_UNAVAILABLE", "booth is not AVAILABLE", 409)
    rec = build_assignment(market, booth, application)
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/assignments/<assignmentId>")
def get_assignment(marketId, assignmentId):
    user = auth()
    require_roles(user, GET_ONE)
    get_market(marketId)
    return success(serialize(get_child("assignments", assignmentId, marketId)))


@bp.get("/markets/<marketId>/assignments")
def list_assignments(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    status = arg("status")
    booth_id = arg("booth_id")
    application_id = arg("application_id")
    records = []
    for a in db.STORES["assignments"].values():
        if a["market_id"] != marketId:
            continue
        if status is not None and a["status"] != status:
            continue
        if booth_id is not None and a["booth_id"] != booth_id:
            continue
        if application_id is not None and a["application_id"] != application_id:
            continue
        records.append(a)
    return list_response(records)


@bp.post("/markets/<marketId>/assignments/<assignmentId>/activate")
def activate_assignment(marketId, assignmentId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    assignment = get_child("assignments", assignmentId, marketId)
    if posture.derive_posture(market) not in ("SETUP", "OPEN"):
        raise posture_forbidden("activation requires market posture SETUP or OPEN")
    if assignment["status"] != "PENDING_PAYMENT":
        raise invalid_state("only a PENDING_PAYMENT assignment can be activated")
    booth = db.STORES["booths"].get(assignment["booth_id"])
    other_active = any(
        a["booth_id"] == assignment["booth_id"]
        and a["status"] == "ACTIVE"
        and a["id"] != assignment["id"]
        for a in db.STORES["assignments"].values()
    )
    reserved_for_this = (
        booth is not None
        and booth["status"] == "RESERVED"
        and booth.get("_reserved_for_assignment_id") == assignment["id"]
    )
    booth_ok = booth is not None and (
        booth["status"] == "AVAILABLE" or (reserved_for_this and not other_active)
    )
    if other_active or not booth_ok:
        raise ApiError("ERR_BOOTH_UNAVAILABLE", "booth is not AVAILABLE", 409)
    application = db.STORES["applications"].get(assignment["application_id"])
    if application is None or application["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_PAYMENT_NOT_SATISFIED",
            "assignment cannot activate because the application is not ACCEPTED",
            409,
        )
    assignment["status"] = "ACTIVE"
    touch(assignment)
    booth["status"] = "RESERVED"
    booth["_reserved_for_assignment_id"] = assignment["id"]
    touch(booth)
    return success(serialize(assignment))


@bp.post("/markets/<marketId>/assignments/<assignmentId>/release")
def release_assignment(marketId, assignmentId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    assignment = get_child("assignments", assignmentId, marketId)
    if assignment["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE assignment can be released")
    open_settlements = any(
        s["assignment_id"] == assignmentId and s["status"] not in ("RECONCILED", "PAID")
        for s in db.STORES["settlements"].values()
    )
    if open_settlements:
        raise invalid_state(
            "all settlements for the assignment must be RECONCILED or PAID before release"
        )
    assignment["status"] = "RELEASED"
    touch(assignment)
    cascades.release_booth(db.STORES["booths"].get(assignment["booth_id"]))
    return success(serialize(assignment))


@bp.post("/markets/<marketId>/assignments/<assignmentId>/forfeit")
def forfeit_assignment_endpoint(marketId, assignmentId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    assignment = get_child("assignments", assignmentId, marketId)
    if assignment["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE assignment can be forfeited")
    data = body()
    reason = as_str(required(data, "reason"), "reason")
    if reason not in FORFEIT_REASONS:
        raise validation("reason must be one of %s" % sorted(FORFEIT_REASONS))
    is_no_show = reason == "NO_SHOW"
    cascades.forfeit_assignment(assignment, strike=is_no_show, recompute=is_no_show)
    return success(serialize(assignment))
