"""BeneficiaryDesignation endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_BENEFICIARY_SHARES_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_api,
)
from helpers import (
    get_account_or_404,
    get_beneficiary_or_404,
    get_json_body,
    get_pagination_params,
    paginate,
    require_enum,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import beneficiary_to_json


bp = Blueprint("beneficiaries", __name__, url_prefix="/ira/beneficiary-designations")


RELATIONSHIPS = {"SPOUSE", "MINOR_CHILD", "DISABLED", "CHRONIC_ILL", "ELIGIBLE_TRUST", "NON_ELIGIBLE_INDIVIDUAL"}
BENEFICIARY_STATUSES = {"PENDING", "ACTIVE", "REVOKED", "INHERITED"}


@bp.route("", methods=["POST"])
def create_beneficiary():
    parse_auth_headers()
    require_roles("AccountOwner")
    body = get_json_body()
    account_id = require_str(body, "account_id")
    beneficiary_full_name = require_str(body, "beneficiary_full_name")
    relationship = require_enum(body, "relationship", RELATIONSHIPS)
    percentage_bps = require_int(body, "percentage_bps")
    if percentage_bps <= 0 or percentage_bps > 10000:
        raise_api(ERR_INVALID_REQUEST, "percentage_bps must be in (0, 10000].")

    acct = get_account_or_404(account_id)
    require_owner_match(acct["owner_id"])

    now = db.now_utc()
    b = {
        "id": db.new_id(),
        "account_id": account_id,
        "beneficiary_full_name": beneficiary_full_name,
        "relationship": relationship,
        "percentage_bps": percentage_bps,
        "status": "PENDING",
        "secure_deadline_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.beneficiary_designations[b["id"]] = b
    return success_object(beneficiary_to_json(b), status_code=201)


@bp.route("/<b_id>", methods=["GET"])
def get_beneficiary(b_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    b = get_beneficiary_or_404(b_id)
    if g.role == "AccountOwner":
        acct = db.accounts.get(b["account_id"])
        if acct is None:
            from errors import ERR_NOT_FOUND
            raise_api(ERR_NOT_FOUND)
        require_owner_match(acct["owner_id"])
    return success_object(beneficiary_to_json(b))


@bp.route("", methods=["GET"])
def list_beneficiaries():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    relationship = request.args.get("relationship")
    rows = list(db.beneficiary_designations.values())
    if account_id is not None:
        rows = [b for b in rows if b["account_id"] == account_id]
    if status is not None:
        if status not in BENEFICIARY_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [b for b in rows if b["status"] == status]
    if relationship is not None:
        if relationship not in RELATIONSHIPS:
            raise_api(ERR_INVALID_REQUEST, "relationship filter is not a recognized value.")
        rows = [b for b in rows if b["relationship"] == relationship]
    if g.role == "AccountOwner":
        owned_accounts = {a["id"] for a in db.accounts.values() if a["owner_id"] == g.user_id}
        rows = [b for b in rows if b["account_id"] in owned_accounts]
    page, total = paginate(rows, limit, offset)
    return success_array([beneficiary_to_json(b) for b in page], limit, offset, total)


@bp.route("/<b_id>/activate", methods=["POST"])
def activate_beneficiary(b_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    b = get_beneficiary_or_404(b_id)
    acct = get_account_or_404(b["account_id"])
    require_owner_match(acct["owner_id"])
    if b["status"] != "PENDING":
        raise_api(ERR_INVALID_STATE, "Beneficiary designation is not PENDING.")
    # Share sum check: including this one's percentage_bps plus existing ACTIVE rows == 10000.
    existing_active_sum = sum(
        x["percentage_bps"]
        for x in db.beneficiary_designations.values()
        if x["account_id"] == b["account_id"] and x["status"] == "ACTIVE"
    )
    if existing_active_sum + b["percentage_bps"] != 10000:
        raise_api(ERR_BENEFICIARY_SHARES_INVALID)
    now = db.now_utc()
    b["status"] = "ACTIVE"
    b["updated_at"] = now
    b["version"] += 1
    return success_object(beneficiary_to_json(b))


@bp.route("/<b_id>/revoke", methods=["POST"])
def revoke_beneficiary(b_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    b = get_beneficiary_or_404(b_id)
    acct = get_account_or_404(b["account_id"])
    require_owner_match(acct["owner_id"])
    if b["status"] not in ("PENDING", "ACTIVE"):
        raise_api(ERR_INVALID_STATE, "Beneficiary designation is not PENDING or ACTIVE.")
    now = db.now_utc()
    b["status"] = "REVOKED"
    b["updated_at"] = now
    b["version"] += 1
    return success_object(beneficiary_to_json(b))
