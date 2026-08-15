"""Beneficial owner and borrower endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles, check_list_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import (
    _touch, offboard_owner, suspend_borrower, default_borrower,
)
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    get_or_404, paginate, serialize_common,
)

bp_owners = Blueprint("owners", __name__)
bp_borrowers = Blueprint("borrowers", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


# ---------------------------------------------------------------------------
# Beneficial Owners
# ---------------------------------------------------------------------------

@bp_owners.route("/api/beneficial-owners", methods=["POST"])
def create_owner():
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    body = get_json_body()
    require_fields(body, ["display_name", "revenue_share_bps", "indemnification_opt_in"])
    if not isinstance(body["revenue_share_bps"], int) or isinstance(body["revenue_share_bps"], bool):
        raise errors.make_error(errors.ERR_VALIDATION, "revenue_share_bps must be an integer")
    if not isinstance(body["indemnification_opt_in"], bool):
        raise errors.make_error(errors.ERR_VALIDATION, "indemnification_opt_in must be a boolean")

    owner = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "display_name": body["display_name"],
        "revenue_share_bps": body["revenue_share_bps"],
        "indemnification_opt_in": body["indemnification_opt_in"],
        "status": "ACTIVE",
    }
    db.beneficial_owners[owner["id"]] = owner
    return success_object(serialize_common(owner), 201)


@bp_owners.route("/api/beneficial-owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    owner = get_or_404(db.beneficial_owners, owner_id, "BeneficialOwner")
    return success_object(serialize_common(owner))


@bp_owners.route("/api/beneficial-owners", methods=["GET"])
def list_owners():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.beneficial_owners.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(o) for o in page], limit, offset, total)


@bp_owners.route("/api/beneficial-owners/<owner_id>/suspend", methods=["POST"])
def suspend_owner(owner_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    owner = get_or_404(db.beneficial_owners, owner_id, "BeneficialOwner")
    if owner["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Owner is not ACTIVE")
    owner["status"] = "SUSPENDED"
    _touch(owner)
    return success_object(serialize_common(owner))


@bp_owners.route("/api/beneficial-owners/<owner_id>/resume", methods=["POST"])
def resume_owner(owner_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    owner = get_or_404(db.beneficial_owners, owner_id, "BeneficialOwner")
    if owner["status"] != "SUSPENDED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Owner is not SUSPENDED")
    owner["status"] = "ACTIVE"
    _touch(owner)
    return success_object(serialize_common(owner))


@bp_owners.route("/api/beneficial-owners/<owner_id>/offboard", methods=["POST"])
def offboard_owner_endpoint(owner_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    owner = get_or_404(db.beneficial_owners, owner_id, "BeneficialOwner")
    if owner["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Owner is not ACTIVE or SUSPENDED")

    # Guard: no loans in BOOKED or RECALLED
    for loan in db.loans.values():
        if loan["owner_id"] == owner_id and loan["status"] in ("BOOKED", "RECALLED"):
            raise errors.make_error(errors.ERR_OWNER_HAS_OPEN_LOANS, "Owner has open loans")

    # Guard: all positions have zero on-loan and zero reserved
    for pos in db.lendable_positions.values():
        if pos["owner_id"] == owner_id:
            calc.recompute_position_derived(pos)
            if pos["quantity_on_loan"] != 0 or pos["quantity_reserved"] != 0:
                raise errors.make_error(errors.ERR_OWNER_HAS_OPEN_LOANS, "Owner has positions with open quantities")

    offboard_owner(owner)
    return success_object(serialize_common(owner))


# ---------------------------------------------------------------------------
# Borrowers
# ---------------------------------------------------------------------------

@bp_borrowers.route("/api/borrowers", methods=["POST"])
def create_borrower():
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    body = get_json_body()
    require_fields(body, ["display_name", "credit_limit_cents"])
    validate_positive_int(body["credit_limit_cents"], "credit_limit_cents")

    borrower = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "display_name": body["display_name"],
        "credit_limit_cents": body["credit_limit_cents"],
        "effective_limit_cents": body["credit_limit_cents"],
        "utilization_cents": 0,
        "utilization_bps": 0,
        "status": "ACTIVE",
    }
    db.borrowers[borrower["id"]] = borrower
    return success_object(serialize_common(borrower), 201)


@bp_borrowers.route("/api/borrowers/<borrower_id>", methods=["GET"])
def get_borrower(borrower_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    borrower = get_or_404(db.borrowers, borrower_id, "Borrower")
    calc.recompute_borrower_derived(borrower)
    return success_object(serialize_common(borrower))


@bp_borrowers.route("/api/borrowers", methods=["GET"])
def list_borrowers():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.borrowers.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    for b in items:
        calc.recompute_borrower_derived(b)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(b) for b in page], limit, offset, total)


@bp_borrowers.route("/api/borrowers/<borrower_id>/suspend", methods=["POST"])
def suspend_borrower_endpoint(borrower_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    borrower = get_or_404(db.borrowers, borrower_id, "Borrower")
    if borrower["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Borrower is not ACTIVE")
    suspend_borrower(borrower)
    return success_object(serialize_common(borrower))


@bp_borrowers.route("/api/borrowers/<borrower_id>/resume", methods=["POST"])
def resume_borrower(borrower_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    borrower = get_or_404(db.borrowers, borrower_id, "Borrower")
    if borrower["status"] != "SUSPENDED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Borrower is not SUSPENDED")
    borrower["status"] = "ACTIVE"
    _touch(borrower)
    return success_object(serialize_common(borrower))


@bp_borrowers.route("/api/borrowers/<borrower_id>/default", methods=["POST"])
def default_borrower_endpoint(borrower_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    borrower = get_or_404(db.borrowers, borrower_id, "Borrower")
    if borrower["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Borrower is not ACTIVE or SUSPENDED")
    default_borrower(borrower)
    return success_object(serialize_common(borrower))
