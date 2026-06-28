from decimal import Decimal

from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, touch, new_id, now_iso
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import (
    get_body, req_str, req_int, req_enum, opt_enum, req_datetime,
    pagination_params,
)

bp = Blueprint("solicitations", __name__)

VEHICLE_TYPES = {"RFP", "RFQ", "IFB"}
SET_ASIDE_TYPES = {"NONE", "SMALL_BUSINESS", "EIGHT_A", "SDVOSB", "WOSB", "HUBZONE"}
FACTOR_KINDS = {"TECHNICAL", "PAST_PERFORMANCE", "PRICE"}


@bp.route("/solicitations", methods=["POST"])
def create_solicitation():
    auth(["ContractingOfficer"])
    body = get_body()
    title = req_str(body, "title")
    vehicle_type = req_enum(body, "vehicle_type", VEHICLE_TYPES)
    set_aside_type = opt_enum(body, "set_aside_type", SET_ASIDE_TYPES, default="NONE")
    naics = req_int(body, "naics_size_threshold", minimum=1)
    open_at = req_datetime(body, "open_at")
    close_at = req_datetime(body, "close_at")
    if not (close_at > open_at):
        raise err("ERR_INVALID_REQUEST", "close_at must be strictly after open_at.")

    entity = {
        "title": title,
        "vehicle_type": vehicle_type,
        "set_aside_type": set_aside_type,
        "naics_size_threshold": naics,
        "evaluation_method": None,
        "open_at": body["open_at"],
        "close_at": body["close_at"],
        "_open_dt": open_at,
        "_close_dt": close_at,
        "status": "DRAFT",
        "amendment_count": 0,
        "winning_proposal_id": None,
        "_evaluation_chair": None,
    }
    stamp_create(entity)
    db.solicitations[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/solicitations/<sol_id>", methods=["GET"])
def get_solicitation(sol_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.solicitations, sol_id))


@bp.route("/solicitations", methods=["GET"])
def list_solicitations():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    status = request.args.get("status")
    vehicle_type = request.args.get("vehicle_type")
    winning = request.args.get("winning_proposal_id")
    limit, offset = pagination_params()
    items = list(db.solicitations.values())
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if vehicle_type is not None:
        items = [s for s in items if s["vehicle_type"] == vehicle_type]
    if winning is not None:
        items = [s for s in items if s["winning_proposal_id"] == winning]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- Evaluation factors ----

@bp.route("/solicitations/<sol_id>/factors", methods=["POST"])
def add_factor(sol_id):
    auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Factors can only be added to a DRAFT solicitation.")
    body = get_body()
    name = req_str(body, "name")
    kind = req_enum(body, "kind", FACTOR_KINDS)
    weight = _req_weight(body, "weight")

    factor = {
        "solicitation_id": sol_id,
        "name": name,
        "kind": kind,
        "weight": weight,
    }
    # EvaluationFactor carries only id + created_at (no updated_at / version).
    factor["id"] = new_id()
    factor["created_at"] = now_iso()
    factor["_seq"] = db.next_seq()
    db.factors[factor["id"]] = factor
    return object_response(factor, status=201)


def _req_weight(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number.")
    if v < 0 or v > 1:
        raise err("ERR_INVALID_REQUEST", f"{field} must be between 0 and 1 inclusive.")
    return v


@bp.route("/solicitations/<sol_id>/factors", methods=["GET"])
def list_factors(sol_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    get_or_404(db.solicitations, sol_id)
    limit, offset = pagination_params()
    items = [f for f in db.factors.values() if f["solicitation_id"] == sol_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- lifecycle transitions ----

@bp.route("/solicitations/<sol_id>/open", methods=["POST"])
def open_solicitation(sol_id):
    auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] not in ("DRAFT", "AMENDED"):
        raise err("ERR_INVALID_STATE", "Only DRAFT or AMENDED solicitations can be opened.")

    if sol["status"] == "DRAFT":
        factors = [f for f in db.factors.values() if f["solicitation_id"] == sol_id]
        if len(factors) < 1:
            raise err("ERR_FACTOR_WEIGHTS_INVALID", "At least one evaluation factor is required.")
        price_factors = [f for f in factors if f["kind"] == "PRICE"]
        if len(price_factors) != 1:
            raise err("ERR_FACTOR_WEIGHTS_INVALID", "Exactly one PRICE factor is required.")
        non_price = [f for f in factors if f["kind"] != "PRICE"]
        weight_sum = sum(Decimal(str(f["weight"])) for f in non_price)
        if weight_sum != Decimal("1.0"):
            raise err("ERR_FACTOR_WEIGHTS_INVALID",
                      "Non-PRICE factor weights must sum to 1.0.")
        if not (sol["_open_dt"] <= clock.now()):
            raise err("ERR_INVALID_STATE", "open_at must be at or before the current clock.")
        sol["evaluation_method"] = "TRADEOFF" if sol["vehicle_type"] == "RFP" else "LPTA"
    else:  # AMENDED -> OPEN re-open
        if not (clock.now() <= sol["_close_dt"]):
            raise err("ERR_INVALID_STATE", "Cannot re-open after close_at.")

    sol["status"] = "OPEN"
    touch(sol)
    return object_response(sol)


@bp.route("/solicitations/<sol_id>/amend", methods=["POST"])
def amend_solicitation(sol_id):
    auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN solicitation can be amended.")
    if not (clock.now() <= sol["_close_dt"]):
        raise err("ERR_INVALID_STATE", "Cannot amend after close_at.")
    sol["status"] = "AMENDED"
    sol["amendment_count"] += 1
    touch(sol)
    return object_response(sol)


@bp.route("/solicitations/<sol_id>/close", methods=["POST"])
def close_solicitation(sol_id):
    auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] not in ("OPEN", "AMENDED"):
        raise err("ERR_INVALID_STATE", "Only OPEN or AMENDED solicitations can be closed.")
    if not (clock.now() >= sol["_close_dt"]):
        raise err("ERR_INVALID_STATE", "Cannot close before close_at.")
    sol["status"] = "CLOSED"
    touch(sol)
    return object_response(sol)


@bp.route("/solicitations/<sol_id>/finalize-evaluation", methods=["POST"])
def finalize_evaluation(sol_id):
    user_id, _ = auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Only a CLOSED solicitation can be finalized.")

    props = [p for p in db.proposals.values() if p["solicitation_id"] == sol_id]
    # Every proposal that was SUBMITTED must now be evaluated.
    if any(p["status"] == "SUBMITTED" for p in props):
        raise err("ERR_INVALID_STATE", "All submitted proposals must be evaluated first.")
    if not any(p["status"] == "ACCEPTABLE" for p in props):
        raise err("ERR_INVALID_STATE", "At least one ACCEPTABLE proposal is required.")

    sol["status"] = "EVALUATED"
    sol["_evaluation_chair"] = user_id
    touch(sol)
    return object_response(sol)


@bp.route("/solicitations/<sol_id>/cancel", methods=["POST"])
def cancel_solicitation(sol_id):
    auth(["ContractingOfficer"])
    sol = get_or_404(db.solicitations, sol_id)
    if sol["status"] not in ("DRAFT", "OPEN"):
        raise err("ERR_INVALID_STATE", "Only DRAFT or OPEN solicitations can be cancelled.")
    was_open = sol["status"] == "OPEN"
    sol["status"] = "CANCELLED"
    touch(sol)
    if was_open:
        for p in db.proposals.values():
            if p["solicitation_id"] != sol_id:
                continue
            if p["status"] in ("SUBMITTED", "UNDER_EVALUATION", "ACCEPTABLE", "UNACCEPTABLE"):
                p["status"] = "WITHDRAWN"
                touch(p)
    return object_response(sol)
