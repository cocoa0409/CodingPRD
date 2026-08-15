"""Collateral pledge endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles, check_entity_scope, check_list_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import _touch
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("pledges", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


def _validate_pledge_fields(body):
    """Validate pledge_type field consistency."""
    pledge_type = body.get("pledge_type")
    if pledge_type not in ("CASH", "SECURITY"):
        raise errors.make_error(errors.ERR_VALIDATION, "pledge_type must be CASH or SECURITY")

    if pledge_type == "CASH":
        if "amount_cents" not in body or body["amount_cents"] is None:
            raise errors.make_error(errors.ERR_PLEDGE_TYPE_MISMATCH, "CASH pledge requires amount_cents")
        if body.get("pledge_security_id") is not None or body.get("quantity") is not None:
            raise errors.make_error(errors.ERR_PLEDGE_TYPE_MISMATCH, "CASH pledge forbids pledge_security_id and quantity")
        validate_positive_int(body["amount_cents"], "amount_cents")
    else:
        if "pledge_security_id" not in body or body["pledge_security_id"] is None:
            raise errors.make_error(errors.ERR_PLEDGE_TYPE_MISMATCH, "SECURITY pledge requires pledge_security_id")
        if "quantity" not in body or body["quantity"] is None:
            raise errors.make_error(errors.ERR_PLEDGE_TYPE_MISMATCH, "SECURITY pledge requires quantity")
        if body.get("amount_cents") is not None:
            raise errors.make_error(errors.ERR_PLEDGE_TYPE_MISMATCH, "SECURITY pledge forbids amount_cents")
        validate_positive_int(body["quantity"], "quantity")


@bp.route("/api/loans/<loan_id>/pledges", methods=["POST"])
def create_pledge(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])

    # PRD §2.7 priority: request shape (4) precedes existence (5).
    # Validate body shape before resolving path identifiers.
    body = get_json_body()
    require_fields(body, ["pledge_type"])
    _validate_pledge_fields(body)

    loan = get_or_404(db.loans, loan_id, "Loan")
    check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])

    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")

    # For SECURITY pledges, check the pledged security exists and is not halted
    if body["pledge_type"] == "SECURITY":
        pledge_sec = get_or_404(db.securities, body["pledge_security_id"], "Security")
        if pledge_sec["status"] == "HALTED":
            raise errors.make_error(errors.ERR_SECURITY_HALTED, "Cannot pledge a HALTED security")

    pledge = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "loan_id": loan_id,
        "pledge_type": body["pledge_type"],
        "amount_cents": body.get("amount_cents"),
        "pledge_security_id": body.get("pledge_security_id"),
        "quantity": body.get("quantity"),
        "marked_value_cents": 0,
        "status": "ACTIVE",
    }
    pledge["marked_value_cents"] = calc.compute_pledge_marked_value(pledge)
    db.pledges[pledge["id"]] = pledge

    # Recompute loan derived fields and evaluate cure
    calc.recompute_loan_derived(loan)
    calc.evaluate_cure(loan)

    return success_object(serialize_common(pledge), 201)


@bp.route("/api/pledges/<pledge_id>", methods=["GET"])
def get_pledge(pledge_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    pledge = get_or_404(db.pledges, pledge_id, "CollateralPledge")
    if pledge["status"] == "ACTIVE":
        pledge["marked_value_cents"] = calc.compute_pledge_marked_value(pledge)
    return success_object(serialize_common(pledge))


@bp.route("/api/pledges", methods=["GET"])
def list_pledges():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "loan_id": request.args.get("loan_id"),
        "pledge_security_id": request.args.get("pledge_security_id"),
        "status": request.args.get("status"),
    }
    items = list(db.pledges.values())
    for key in ("loan_id", "pledge_security_id", "status"):
        if filters[key]:
            items = [p for p in items if p.get(key) == filters[key]]
    for p in items:
        if p["status"] == "ACTIVE":
            p["marked_value_cents"] = calc.compute_pledge_marked_value(p)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(p) for p in page], limit, offset, total)


@bp.route("/api/loans/<loan_id>/pledges/<pledge_id>/substitute", methods=["POST"])
def substitute_pledge(loan_id, pledge_id):
    user_id, role = get_auth()
    require_roles(role, ["BorrowerRep"])

    # Path resolution left to right
    loan = get_or_404(db.loans, loan_id, "Loan")
    pledge = get_or_404(db.pledges, pledge_id, "CollateralPledge")

    check_entity_scope(role, user_id, borrower_id=loan["borrower_id"])

    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")
    if pledge["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Pledge is not ACTIVE")
    if pledge["loan_id"] != loan_id:
        raise errors.make_error(errors.ERR_NOT_FOUND, "Pledge does not belong to this loan")

    body = get_json_body()
    require_fields(body, ["expected_loan_version", "pledge_type"])

    # OCC check
    if body["expected_loan_version"] != loan["version"]:
        raise errors.make_error(errors.ERR_STALE_VERSION, "Loan version has advanced")

    _validate_pledge_fields(body)

    # For SECURITY pledges, check halted
    if body["pledge_type"] == "SECURITY":
        pledge_sec = get_or_404(db.securities, body["pledge_security_id"], "Security")
        if pledge_sec["status"] == "HALTED":
            raise errors.make_error(errors.ERR_SECURITY_HALTED, "Cannot pledge a HALTED security")

    # Compute replacement value
    new_pledge = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "loan_id": loan_id,
        "pledge_type": body["pledge_type"],
        "amount_cents": body.get("amount_cents"),
        "pledge_security_id": body.get("pledge_security_id"),
        "quantity": body.get("quantity"),
        "marked_value_cents": 0,
        "status": "ACTIVE",
    }
    new_pledge["marked_value_cents"] = calc.compute_pledge_marked_value(new_pledge)

    # Check replacement >= substituted
    old_value = calc.compute_pledge_marked_value(pledge)
    if new_pledge["marked_value_cents"] < old_value:
        raise errors.make_error(errors.ERR_COLLATERAL_SHORTFALL, "Replacement value below substituted pledge")

    # Execute substitution
    pledge["status"] = "SUBSTITUTED"
    _touch(pledge)
    db.pledges[new_pledge["id"]] = new_pledge
    _touch(loan)

    calc.recompute_loan_derived(loan)
    calc.evaluate_cure(loan)

    return success_object(serialize_common(new_pledge))


@bp.route("/api/pledges/<pledge_id>/release", methods=["POST"])
def release_pledge(pledge_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    pledge = get_or_404(db.pledges, pledge_id, "CollateralPledge")
    if pledge["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Pledge is not ACTIVE")

    loan = db.loans[pledge["loan_id"]]
    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")

    # Check 1: post-release posted >= required (margin deficit check)
    calc.recompute_loan_derived(loan)
    pledge_value = calc.compute_pledge_marked_value(pledge)
    post_release_posted = loan["posted_collateral_cents"] - pledge_value
    if post_release_posted < loan["required_collateral_cents"]:
        raise errors.make_error(errors.ERR_MARGIN_DEFICIT, "Release would create margin deficit")

    # Check 2: for CASH pledge, uninvested cash must cover
    if pledge["pledge_type"] == "CASH":
        if loan["cash_uninvested_cents"] < pledge["amount_cents"]:
            raise errors.make_error(errors.ERR_INSUFFICIENT_UNINVESTED_CASH, "Insufficient uninvested cash")

    # Execute release
    pledge["status"] = "RELEASED"
    _touch(pledge)
    calc.recompute_loan_derived(loan)
    calc.evaluate_cure(loan)

    return success_object(serialize_common(pledge))
