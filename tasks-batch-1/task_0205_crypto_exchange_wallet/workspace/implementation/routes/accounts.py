"""Account registration, KYC, freeze/unfreeze (§3.1, §3.2)."""
from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import account_out
from services.common import touch, require_body, required_str, required_enum
from services.pagination import paginate

bp = Blueprint("accounts", __name__)

TIER_SEQUENCE = ["TIER_0", "TIER_1", "TIER_2", "TIER_3"]


def get_account_or_404(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    return acct


@bp.route("/accounts", methods=["POST"])
def create_account():
    # Public endpoint: still require valid Anonymous auth header set? PRD §2.1:
    # registration is public and exempt from auth. Accept any/no headers.
    body = require_body(request.get_json(silent=True))
    email = required_str(body, "email")
    full_name = required_str(body, "full_name")
    residence_country = required_str(body, "residence_country")
    method = body.get("cost_basis_method", "FIFO")
    if method is None:
        method = "FIFO"
    if method not in ("FIFO", "HIFO"):
        raise err("ERR_INVALID_REQUEST", "cost_basis_method must be FIFO or HIFO")
    if db.account_by_email(email) is not None:
        raise err("ERR_INVALID_REQUEST", "email already registered")

    now = db.clock.now()
    acct = {
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "residence_country": residence_country,
        "kyc_tier": "TIER_0",
        "kyc_status": "UNVERIFIED",
        "pending_tier": None,
        "account_status": "ACTIVE",
        "cost_basis_method": method,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.accounts[acct["id"]] = acct
    return success(account_out(acct, db), status=201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    return success(account_out(acct, db))


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    user_id, role = get_identity()
    require_roles(role, {"Operator", "ComplianceOfficer"})
    items = list(db.accounts.values())
    rc = request.args.get("residence_country")
    if rc is not None:
        items = [a for a in items if a["residence_country"] == rc]
    tier = request.args.get("kyc_tier")
    if tier is not None:
        items = [a for a in items if a["kyc_tier"] == tier]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, pag = paginate(items)
    return success([account_out(a, db) for a in page], pagination=pag)


@bp.route("/accounts/<account_id>/kyc-applications", methods=["POST"])
def kyc_application(account_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    acct = get_account_or_404(account_id)
    if user_id != acct["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this account")
    body = require_body(request.get_json(silent=True))
    requested = required_enum(body, "requested_tier", set(TIER_SEQUENCE))

    # State legality: kyc_status must allow a new application.
    if acct["kyc_status"] not in ("UNVERIFIED", "REJECTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "An application is already pending")

    # Tier progression: exactly one above current.
    cur_idx = TIER_SEQUENCE.index(acct["kyc_tier"])
    req_idx = TIER_SEQUENCE.index(requested)
    if req_idx != cur_idx + 1:
        raise err("ERR_INVALID_TIER_PROGRESSION", "Requested tier must be exactly one above current")

    acct["kyc_status"] = "PENDING"
    acct["pending_tier"] = requested
    touch(acct)
    return success(account_out(acct, db), status=201)


@bp.route("/accounts/<account_id>/kyc-decisions", methods=["POST"])
def kyc_decision(account_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    acct = get_account_or_404(account_id)
    body = require_body(request.get_json(silent=True))
    decision = required_enum(body, "decision", {"APPROVE", "REJECT"})

    if acct["kyc_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "No pending KYC application")

    if decision == "APPROVE":
        acct["kyc_tier"] = acct["pending_tier"]
        acct["kyc_status"] = "APPROVED"
        acct["pending_tier"] = None
    else:
        acct["kyc_status"] = "REJECTED"
        acct["pending_tier"] = None
    touch(acct)
    return success(account_out(acct, db))


@bp.route("/accounts/<account_id>/freeze", methods=["POST"])
def freeze(account_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    acct = get_account_or_404(account_id)
    if acct["account_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    acct["account_status"] = "FROZEN"
    touch(acct)
    # Cascade: cancel OPEN/PARTIALLY_FILLED orders, releasing reserves.
    from services.orders import cancel_order_internal
    for o in list(db.orders.values()):
        if o["account_id"] == account_id and o["lifecycle_status"] in ("OPEN", "PARTIALLY_FILLED"):
            cancel_order_internal(o)
    return success(account_out(acct, db))


@bp.route("/accounts/<account_id>/unfreeze", methods=["POST"])
def unfreeze(account_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    acct = get_account_or_404(account_id)
    if acct["account_status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Account is not FROZEN")
    acct["account_status"] = "ACTIVE"
    touch(acct)
    return success(account_out(acct, db))
