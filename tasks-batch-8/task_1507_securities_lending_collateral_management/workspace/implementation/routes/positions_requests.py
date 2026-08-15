"""Lendable position and borrow request endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles, check_entity_scope, check_list_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import _touch, cancel_loan, _find_linked_proposal
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    validate_date_string, get_or_404, paginate, serialize_common,
)

bp_positions = Blueprint("positions", __name__)
bp_requests = Blueprint("borrow_requests", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


# ---------------------------------------------------------------------------
# Lendable Positions
# ---------------------------------------------------------------------------

@bp_positions.route("/api/lendable-positions", methods=["POST"])
def create_position():
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    body = get_json_body()
    require_fields(body, ["owner_id", "security_id", "quantity_total", "min_fee_bps"])
    check_entity_scope(role, user_id, owner_id=body["owner_id"])
    validate_positive_int(body["quantity_total"], "quantity_total")
    if not isinstance(body["min_fee_bps"], int) or isinstance(body["min_fee_bps"], bool) or body["min_fee_bps"] < 0:
        raise errors.make_error(errors.ERR_VALIDATION, "min_fee_bps must be a non-negative integer")

    owner = get_or_404(db.beneficial_owners, body["owner_id"], "BeneficialOwner")
    security = get_or_404(db.securities, body["security_id"], "Security")

    if owner["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_OWNER_SUSPENDED, "Owner is not ACTIVE")

    position = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "owner_id": body["owner_id"],
        "security_id": body["security_id"],
        "quantity_total": body["quantity_total"],
        "min_fee_bps": body["min_fee_bps"],
        "quantity_reserved": 0,
        "quantity_on_loan": 0,
        "quantity_available": body["quantity_total"],
        "status": "OPEN",
    }
    db.lendable_positions[position["id"]] = position
    return success_object(serialize_common(position), 201)


@bp_positions.route("/api/lendable-positions/<position_id>", methods=["GET"])
def get_position(position_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    pos = get_or_404(db.lendable_positions, position_id, "LendablePosition")
    calc.recompute_position_derived(pos)
    return success_object(serialize_common(pos))


@bp_positions.route("/api/lendable-positions", methods=["GET"])
def list_positions():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "owner_id": request.args.get("owner_id"),
        "security_id": request.args.get("security_id"),
        "status": request.args.get("status"),
    }
    filters = check_list_scope(role, user_id, filters)
    items = list(db.lendable_positions.values())
    if filters["owner_id"]:
        items = [p for p in items if p["owner_id"] == filters["owner_id"]]
    if filters["security_id"]:
        items = [p for p in items if p["security_id"] == filters["security_id"]]
    if filters["status"]:
        items = [p for p in items if p["status"] == filters["status"]]
    for p in items:
        calc.recompute_position_derived(p)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(p) for p in page], limit, offset, total)


@bp_positions.route("/api/lendable-positions/<position_id>/suspend", methods=["POST"])
def suspend_position(position_id):
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    pos = get_or_404(db.lendable_positions, position_id, "LendablePosition")
    check_entity_scope(role, user_id, owner_id=pos["owner_id"])
    if pos["status"] != "OPEN":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Position is not OPEN")
    pos["status"] = "SUSPENDED"
    _touch(pos)
    return success_object(serialize_common(pos))


@bp_positions.route("/api/lendable-positions/<position_id>/resume", methods=["POST"])
def resume_position(position_id):
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    pos = get_or_404(db.lendable_positions, position_id, "LendablePosition")
    check_entity_scope(role, user_id, owner_id=pos["owner_id"])
    if pos["status"] != "SUSPENDED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Position is not SUSPENDED")
    pos["status"] = "OPEN"
    _touch(pos)
    return success_object(serialize_common(pos))


# ---------------------------------------------------------------------------
# Borrow Requests
# ---------------------------------------------------------------------------

@bp_requests.route("/api/borrow-requests", methods=["POST"])
def create_request():
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])
    body = get_json_body()
    require_fields(body, ["borrower_id", "security_id", "quantity", "max_rate_bps", "collateral_type", "needed_by_date"])
    check_entity_scope(role, user_id, borrower_id=body["borrower_id"])
    validate_positive_int(body["quantity"], "quantity")
    if not isinstance(body["max_rate_bps"], int) or isinstance(body["max_rate_bps"], bool) or body["max_rate_bps"] < 0:
        raise errors.make_error(errors.ERR_VALIDATION, "max_rate_bps must be a non-negative integer")
    validate_enum(body["collateral_type"], ["CASH", "SECURITIES"], "collateral_type")
    validate_date_string(body["needed_by_date"], "needed_by_date")
    term_days = body.get("term_days")
    if term_days is not None:
        validate_positive_int(term_days, "term_days")

    borrower = get_or_404(db.borrowers, body["borrower_id"], "Borrower")
    security = get_or_404(db.securities, body["security_id"], "Security")

    req = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "borrower_id": body["borrower_id"],
        "security_id": body["security_id"],
        "quantity": body["quantity"],
        "max_rate_bps": body["max_rate_bps"],
        "collateral_type": body["collateral_type"],
        "term_days": term_days,
        "needed_by_date": body["needed_by_date"],
        "status": "SUBMITTED",
    }
    db.borrow_requests[req["id"]] = req
    return success_object(serialize_common(req), 201)


@bp_requests.route("/api/borrow-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    req = get_or_404(db.borrow_requests, request_id, "BorrowRequest")
    return success_object(serialize_common(req))


@bp_requests.route("/api/borrow-requests", methods=["GET"])
def list_requests():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "borrower_id": request.args.get("borrower_id"),
        "security_id": request.args.get("security_id"),
        "status": request.args.get("status"),
    }
    filters = check_list_scope(role, user_id, filters)
    items = list(db.borrow_requests.values())
    if filters["borrower_id"]:
        items = [r for r in items if r["borrower_id"] == filters["borrower_id"]]
    if filters["security_id"]:
        items = [r for r in items if r["security_id"] == filters["security_id"]]
    if filters["status"]:
        items = [r for r in items if r["status"] == filters["status"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(r) for r in page], limit, offset, total)


@bp_requests.route("/api/borrow-requests/<request_id>/cancel", methods=["POST"])
def cancel_request(request_id):
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])
    req = get_or_404(db.borrow_requests, request_id, "BorrowRequest")
    check_entity_scope(role, user_id, borrower_id=req["borrower_id"])
    if req["status"] not in ("SUBMITTED", "MATCHED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Request cannot be cancelled from this state")

    if req["status"] == "MATCHED":
        # Cascade: cancel linked proposal, release reservation
        linked = _find_linked_proposal(req["id"])
        if linked:
            cancel_loan(linked)
        # cancel_loan already sets request back to SUBMITTED, so we now cancel it
        req["status"] = "CANCELLED"
        _touch(req)
    else:
        req["status"] = "CANCELLED"
        _touch(req)

    return success_object(serialize_common(req))


@bp_requests.route("/api/borrow-requests/<request_id>/match", methods=["POST"])
def match_request(request_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    req = get_or_404(db.borrow_requests, request_id, "BorrowRequest")
    if req["status"] != "SUBMITTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Request is not SUBMITTED")

    body = get_json_body()
    borrower = db.borrowers[req["borrower_id"]]
    security = db.securities[req["security_id"]]

    # Gates
    if borrower["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_BORROWER_SUSPENDED, "Borrower is not ACTIVE")
    if security["status"] != "LENDABLE":
        raise errors.make_error(errors.ERR_SECURITY_HALTED, "Security is HALTED")
    if req["needed_by_date"] < db.current_date_str():
        raise errors.make_error(errors.ERR_REQUEST_EXPIRED, "Request has expired")

    position_id = body.get("position_id")

    if position_id:
        # Explicit position
        position = get_or_404(db.lendable_positions, position_id, "LendablePosition")
        _validate_match_position(position, req)
    else:
        # Selector
        position = _select_position(req)

    # Create loan in PROPOSED
    loan = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "borrow_request_id": req["id"],
        "position_id": position["id"],
        "owner_id": position["owner_id"],
        "borrower_id": req["borrower_id"],
        "security_id": req["security_id"],
        "quantity": req["quantity"],
        "outstanding_quantity": req["quantity"],
        "collateral_type": req["collateral_type"],
        "rate_bps": position["min_fee_bps"],
        "term_days": req.get("term_days"),
        "original_price_cents": None,
        "market_value_cents": 0,
        "required_collateral_cents": 0,
        "posted_collateral_cents": 0,
        "cash_uninvested_cents": 0,
        "status": "PROPOSED",
        "margin_status": "CURRENT",
        "_window_start_date": db.clock.now().date(),
    }
    db.loans[loan["id"]] = loan

    # Update request
    req["status"] = "MATCHED"
    _touch(req)

    # Reserve on position
    position["quantity_reserved"] += req["quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan), 201)


def _validate_match_position(position, req):
    """Validate an explicitly nominated position."""
    if position["security_id"] != req["security_id"]:
        raise errors.make_error(errors.ERR_VALIDATION, "Position security does not match request security")
    if position["status"] != "OPEN":
        raise errors.make_error(errors.ERR_POSITION_SUSPENDED, "Position is not OPEN")
    owner = db.beneficial_owners[position["owner_id"]]
    if owner["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_OWNER_SUSPENDED, "Owner is not ACTIVE")
    if position["min_fee_bps"] > req["max_rate_bps"]:
        raise errors.make_error(errors.ERR_NO_INVENTORY, "Position min_fee exceeds request max_rate")
    # Forward capacity
    if not calc.check_forward_capacity(position, req["quantity"], req.get("term_days")):
        raise errors.make_error(errors.ERR_FORWARD_CAPACITY_EXCEEDED, "Forward capacity exceeded")


def _select_position(req):
    """Selector: rank by min_fee_bps ASC, created_at ASC, quantity_total DESC."""
    candidates = []
    for pos in db.lendable_positions.values():
        if pos["security_id"] != req["security_id"]:
            continue
        if pos["status"] != "OPEN":
            continue
        owner = db.beneficial_owners[pos["owner_id"]]
        if owner["status"] != "ACTIVE":
            continue
        if pos["min_fee_bps"] > req["max_rate_bps"]:
            continue
        # Forward capacity check
        calc.recompute_position_derived(pos)
        if not calc.check_forward_capacity(pos, req["quantity"], req.get("term_days")):
            continue
        candidates.append(pos)

    if not candidates:
        raise errors.make_error(errors.ERR_NO_INVENTORY, "No eligible position found")

    # Sort: min_fee_bps ASC, created_at ASC, quantity_total DESC
    candidates.sort(key=lambda p: (p["min_fee_bps"], p["created_at"], -p["quantity_total"]))

    # Check for tie at top
    if len(candidates) > 1:
        top = candidates[0]
        second = candidates[1]
        if (top["min_fee_bps"] == second["min_fee_bps"]
                and top["created_at"] == second["created_at"]
                and top["quantity_total"] == second["quantity_total"]):
            raise errors.make_error(errors.ERR_AMBIGUOUS_MATCH, "Selector tie unresolved")

    return candidates[0]
