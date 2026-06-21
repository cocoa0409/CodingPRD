"""Account owners: add, list, deactivate, get — PRD §3.9."""
from flask import Blueprint, request, g

from db import db
from middleware import require_roles
from response import object_response
from models import stamp_new, touch, public
from services.validate import get_body, require_fields, require_enum
from services.resolve import get_account, get_owner, get_customer, active_owners
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("owners", __name__)

OWNERSHIP_ROLES = {"JOINT", "POD_BENEFICIARY"}


def serialize_owner(o):
    return public(o)


@bp.route("/accounts/<account_id>/owners", methods=["POST"])
@require_roles("AccountHolder", "ComplianceOfficer")
def add_owner(account_id):
    a = get_account(account_id)
    # AccountHolder must be an active owner to add owners (owner-management).
    if g.user_role == "AccountHolder":
        from services.resolve import require_account_owner
        require_account_owner(a, g.user_id)
    body = get_body()
    require_fields(body, "customer_id", "ownership_role")
    role = require_enum(body, "ownership_role", OWNERSHIP_ROLES)
    # Referenced customer must resolve (specialized not-found).
    get_customer(body["customer_id"], specialized=True)

    # POD: at most one ACTIVE POD_BENEFICIARY per account (priority 13).
    if role == "POD_BENEFICIARY":
        existing_pod = any(
            o["ownership_role"] == "POD_BENEFICIARY"
            for o in active_owners(account_id)
        )
        if existing_pod:
            raise ApiError(errors.ERR_POD_ALREADY_DESIGNATED, 409,
                           "Account already has an active POD beneficiary")

    owner = {
        "account_id": account_id,
        "customer_id": body["customer_id"],
        "ownership_role": role,
        "is_active": True,
    }
    stamp_new(owner)
    db.account_owners[owner["id"]] = owner
    return object_response(serialize_owner(owner), status=201)


@bp.route("/accounts/<account_id>/owners", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def list_owners(account_id):
    get_account(account_id)
    rows = [o for o in db.account_owners.values() if o["account_id"] == account_id]
    return paged_list(rows, serializer=serialize_owner)


@bp.route("/accounts/<account_id>/owners/<owner_id>", methods=["DELETE"])
@require_roles("AccountHolder", "ComplianceOfficer")
def remove_owner(account_id, owner_id):
    a = get_account(account_id)
    if g.user_role == "AccountHolder":
        from services.resolve import require_account_owner
        require_account_owner(a, g.user_id)
    owner = get_owner(owner_id)
    # Nested ownership: the owner must belong to this account.
    if owner["account_id"] != account_id:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Owner does not belong to this account")

    # Cannot remove the last active PRIMARY owner (priority 14).
    if owner["ownership_role"] == "PRIMARY" and owner["is_active"]:
        remaining_primary = [
            o for o in active_owners(account_id)
            if o["ownership_role"] == "PRIMARY" and o["id"] != owner_id
        ]
        if not remaining_primary:
            raise ApiError(errors.ERR_LAST_PRIMARY_OWNER, 409,
                           "Cannot remove the last active PRIMARY owner")

    owner["is_active"] = False
    touch(owner)
    return object_response(serialize_owner(owner))


@bp.route("/owners/<owner_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def get_owner_row(owner_id):
    o = get_owner(owner_id)
    return object_response(serialize_owner(o))


@bp.route("/owners", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_owner_rows():
    customer_id = request.args.get("customer_id")
    account_id = request.args.get("account_id")
    rows = list(db.account_owners.values())
    if customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if account_id is not None:
        rows = [o for o in rows if o["account_id"] == account_id]
    return paged_list(rows, serializer=serialize_owner)
