"""Account endpoints. PRD §3.1."""
from flask import Blueprint

import db
import errors
import response
import middleware as mw
from services import core
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("accounts", __name__)

VALID_ACCOUNT_ROLES = {"SELLER", "BUYER"}


@bp.route("/accounts", methods=["POST"])
def create_account():
    # PRD §3.1 / RBAC: registration is the Anonymous-exclusive op, but any
    # authenticated caller may also register. Auth headers still required (§2.1).
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    body = get_json_body()

    email = body.get("email")
    display_name = body.get("display_name")
    roles = body.get("roles")

    # Field-shape validation (PRD §3.1).
    if not isinstance(email, str) or email.strip() == "":
        raise errors.invalid_request("email is required and must be non-empty.")
    if not isinstance(display_name, str) or display_name == "":
        raise errors.invalid_request("display_name is required.")
    if not isinstance(roles, list) or len(roles) == 0:
        raise errors.invalid_request("roles is required and must be non-empty.")
    for r in roles:
        if r not in VALID_ACCOUNT_ROLES:
            raise errors.invalid_request("roles values must be SELLER or BUYER.")

    # Email uniqueness (PRD §3.1).
    for a in db.accounts.values():
        if a["email"] == email:
            raise errors.invalid_request("email must be unique across all accounts.")

    aid = db.new_id()
    acct = {
        "id": aid,
        "email": email,
        "display_name": display_name,
        "roles": list(roles),
        "fee_balance_cents": 0,
        "feedback_score": 0,
        "standing": "GOOD",
        "status": "ACTIVE",
    }
    core.stamp_new(acct)
    db.accounts[aid] = acct
    return response.success(core.ser_account(acct), status=201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    return response.success(core.ser_account(acct), status=200)


@bp.route("/accounts/<account_id>/feedback", methods=["GET"])
def list_account_feedback(account_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    items = [f for f in db.feedback.values() if f["ratee_account_id"] == account_id]
    return paginate_list(items, core.ser_feedback)


@bp.route("/accounts/<account_id>/invoices", methods=["GET"])
def list_account_invoices(account_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Seller", "PlatformAdmin"})
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    items = [i for i in db.seller_fee_invoices.values()
             if i["seller_account_id"] == account_id]
    return paginate_list(items, core.ser_invoice)


@bp.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"PlatformAdmin"})
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    # PRD §3.1: admin closes an account, ACTIVE -> CLOSED.
    acct["status"] = "CLOSED"
    core.touch(acct)
    return response.success(core.ser_account(acct), status=200)
