"""Loan endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles, check_entity_scope, check_list_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import (
    _touch, book_loan, cancel_loan, return_shares,
)
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("loans", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


@bp.route("/api/loans", methods=["POST"])
def create_loan():
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    body = get_json_body()
    require_fields(body, ["owner_id", "borrower_id", "security_id", "position_id", "quantity", "collateral_type", "rate_bps"])
    validate_positive_int(body["quantity"], "quantity")
    validate_enum(body["collateral_type"], ["CASH", "SECURITIES"], "collateral_type")
    if not isinstance(body["rate_bps"], int) or isinstance(body["rate_bps"], bool) or body["rate_bps"] < 0:
        raise errors.make_error(errors.ERR_VALIDATION, "rate_bps must be a non-negative integer")
    term_days = body.get("term_days")
    if term_days is not None:
        validate_positive_int(term_days, "term_days")

    # Existence checks (body FKs)
    owner = get_or_404(db.beneficial_owners, body["owner_id"], "BeneficialOwner")
    borrower = get_or_404(db.borrowers, body["borrower_id"], "Borrower")
    security = get_or_404(db.securities, body["security_id"], "Security")
    position = get_or_404(db.lendable_positions, body["position_id"], "LendablePosition")

    # Cross-reference consistency
    if body["security_id"] != position["security_id"]:
        raise errors.make_error(errors.ERR_VALIDATION, "Loan security_id must equal position security_id")
    if body["owner_id"] != position["owner_id"]:
        raise errors.make_error(errors.ERR_VALIDATION, "Loan owner_id must equal position owner_id")

    # Safety gates
    if security["status"] == "HALTED":
        raise errors.make_error(errors.ERR_SECURITY_HALTED, "Security is HALTED")
    if owner["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_OWNER_SUSPENDED, "Owner is not ACTIVE")
    if borrower["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_BORROWER_SUSPENDED, "Borrower is not ACTIVE")
    if position["status"] != "OPEN":
        raise errors.make_error(errors.ERR_POSITION_SUSPENDED, "Position is not OPEN")

    # Forward capacity
    calc.recompute_position_derived(position)
    if not calc.check_forward_capacity(position, body["quantity"], term_days):
        raise errors.make_error(errors.ERR_FORWARD_CAPACITY_EXCEEDED, "Forward capacity exceeded")

    loan = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "borrow_request_id": None,
        "position_id": body["position_id"],
        "owner_id": body["owner_id"],
        "borrower_id": body["borrower_id"],
        "security_id": body["security_id"],
        "quantity": body["quantity"],
        "outstanding_quantity": body["quantity"],
        "collateral_type": body["collateral_type"],
        "rate_bps": body["rate_bps"],
        "term_days": term_days,
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

    position["quantity_reserved"] += body["quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan), 201)


@bp.route("/api/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    loan = get_or_404(db.loans, loan_id, "Loan")
    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans", methods=["GET"])
def list_loans():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "owner_id": request.args.get("owner_id"),
        "borrower_id": request.args.get("borrower_id"),
        "security_id": request.args.get("security_id"),
        "position_id": request.args.get("position_id"),
        "borrow_request_id": request.args.get("borrow_request_id"),
        "status": request.args.get("status"),
    }
    filters = check_list_scope(role, user_id, filters)
    items = list(db.loans.values())
    for key in ("owner_id", "borrower_id", "security_id", "position_id", "borrow_request_id", "status"):
        if filters[key]:
            items = [l for l in items if l.get(key) == filters[key]]
    for l in items:
        calc.recompute_loan_derived(l)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(l) for l in page], limit, offset, total)


@bp.route("/api/loans/<loan_id>/counter", methods=["POST"])
def counter_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader", "BorrowerRep"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    body = get_json_body()
    require_fields(body, ["rate_bps"])
    if not isinstance(body["rate_bps"], int) or isinstance(body["rate_bps"], bool) or body["rate_bps"] < 0:
        raise errors.make_error(errors.ERR_VALIDATION, "rate_bps must be a non-negative integer")

    if role == "BorrowerRep":
        # BorrowerRep counters from PROPOSED -> COUNTERED
        check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])
        if loan["status"] != "PROPOSED":
            raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not PROPOSED")
        # Rate ceiling for request-linked loans
        if loan.get("borrow_request_id"):
            req = db.borrow_requests.get(loan["borrow_request_id"])
            if req and body["rate_bps"] > req["max_rate_bps"]:
                raise errors.make_error(errors.ERR_RATE_ABOVE_MAX, "Counter rate exceeds request max_rate_bps")
        loan["rate_bps"] = body["rate_bps"]
        loan["status"] = "COUNTERED"
    else:
        # DeskTrader counters from COUNTERED -> PROPOSED
        if loan["status"] != "COUNTERED":
            raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not COUNTERED")
        loan["rate_bps"] = body["rate_bps"]
        loan["status"] = "PROPOSED"

    _touch(loan)
    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans/<loan_id>/accept", methods=["POST"])
def accept_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])
    if loan["status"] != "PROPOSED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not PROPOSED")
    book_loan(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans/<loan_id>/confirm", methods=["POST"])
def confirm_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    if loan["status"] != "COUNTERED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not COUNTERED")
    book_loan(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans/<loan_id>/cancel", methods=["POST"])
def cancel_loan_endpoint(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader", "BorrowerRep"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    if role == "BorrowerRep":
        check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])
    if loan["status"] not in ("PROPOSED", "COUNTERED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan cannot be cancelled from this state")
    cancel_loan(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans/<loan_id>/amendments", methods=["POST"])
def amend_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    if loan["status"] != "BOOKED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED")

    body = get_json_body()
    require_fields(body, ["expected_loan_version"])

    # OCC check
    if body["expected_loan_version"] != loan["version"]:
        raise errors.make_error(errors.ERR_STALE_VERSION, "Loan version has advanced")

    # Margin call gate
    calc.recompute_loan_derived(loan)
    if loan["margin_status"] == "CALL_OPEN":
        raise errors.make_error(errors.ERR_MARGIN_CALL_OUTSTANDING, "Amendment blocked while margin call is open")

    # Apply amendments
    if "rate_bps" in body and body["rate_bps"] is not None:
        if not isinstance(body["rate_bps"], int) or isinstance(body["rate_bps"], bool) or body["rate_bps"] < 0:
            raise errors.make_error(errors.ERR_VALIDATION, "rate_bps must be a non-negative integer")
        loan["rate_bps"] = body["rate_bps"]
    if "term_days" in body and body["term_days"] is not None:
        validate_positive_int(body["term_days"], "term_days")
        loan["term_days"] = body["term_days"]

    _touch(loan)
    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan))


@bp.route("/api/loans/<loan_id>/returns", methods=["POST"])
def return_loan(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])
    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")

    body = get_json_body()
    require_fields(body, ["quantity"])
    validate_positive_int(body["quantity"], "quantity")

    return_shares(loan, body["quantity"])
    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(loan))
