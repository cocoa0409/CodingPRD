"""IRAAccount endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    raise_api,
)
from helpers import (
    get_account_or_404,
    get_json_body,
    get_owner_or_404,
    get_pagination_params,
    paginate,
    require_enum,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import account_to_json


bp = Blueprint("accounts", __name__, url_prefix="/ira/accounts")


ACCOUNT_TYPES = {"TRADITIONAL", "ROTH"}
ACCOUNT_STATUSES = {"ACTIVE", "FROZEN", "CONVERSION_IN_PROGRESS", "INHERITED", "CLOSED"}


@bp.route("", methods=["POST"])
def create_account():
    parse_auth_headers()
    require_roles("PlanAdministrator")
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    # Existence check for the owner.
    get_owner_or_404(owner_id)

    now = db.now_utc()
    acct = {
        "id": db.new_id(),
        "owner_id": owner_id,
        "account_type": account_type,
        "status": "ACTIVE",
        "cash_balance_cents": 0,
        "pretax_basis_cents": 0,
        "aftertax_basis_cents": 0,
        "ytd_contribution_cents": 0,
        "tax_year_marker": db.system_clock["current_tax_year"],
        "opened_at": now,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.accounts[acct["id"]] = acct
    return success_object(account_to_json(acct), status_code=201)


@bp.route("/<account_id>", methods=["GET"])
def get_account(account_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    acct = get_account_or_404(account_id)
    if g.role == "AccountOwner":
        require_owner_match(acct["owner_id"])
    return success_object(account_to_json(acct))


@bp.route("", methods=["GET"])
def list_accounts():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    owner_id = request.args.get("owner_id")
    account_type = request.args.get("account_type")
    status = request.args.get("status")
    rows = list(db.accounts.values())
    if owner_id is not None:
        rows = [a for a in rows if a["owner_id"] == owner_id]
    if account_type is not None:
        if account_type not in ACCOUNT_TYPES:
            raise_api(ERR_INVALID_REQUEST, "account_type filter must be TRADITIONAL or ROTH.")
        rows = [a for a in rows if a["account_type"] == account_type]
    if status is not None:
        if status not in ACCOUNT_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [a for a in rows if a["status"] == status]
    if g.role == "AccountOwner":
        # Owner can list only their own accounts.
        rows = [a for a in rows if a["owner_id"] == g.user_id]
    page, total = paginate(rows, limit, offset)
    return success_array([account_to_json(a) for a in page], limit, offset, total)


@bp.route("/<account_id>/freeze", methods=["POST"])
def freeze_account(account_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    acct = get_account_or_404(account_id)
    body = get_json_body()
    expected = require_int(body, "expected_account_version")
    if acct["status"] != "ACTIVE":
        raise_api(ERR_INVALID_STATE, "Account is not ACTIVE.")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)
    # Precondition: no PENDING contribution/distribution against this account.
    has_pending_contribution = any(
        c["account_id"] == account_id and c["status"] == "PENDING"
        for c in db.contributions.values()
    )
    has_pending_distribution = any(
        d["account_id"] == account_id and d["status"] == "PENDING"
        for d in db.distributions.values()
    )
    if has_pending_contribution or has_pending_distribution:
        raise_api(ERR_INVALID_STATE, "Account has PENDING contributions or distributions.")
    acct["status"] = "FROZEN"
    acct["updated_at"] = db.now_utc()
    acct["version"] += 1
    return success_object(account_to_json(acct))


@bp.route("/<account_id>/unfreeze", methods=["POST"])
def unfreeze_account(account_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    acct = get_account_or_404(account_id)
    body = get_json_body()
    expected = require_int(body, "expected_account_version")
    if acct["status"] != "FROZEN":
        raise_api(ERR_INVALID_STATE, "Account is not FROZEN.")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)
    # Precondition: owner.deceased_at is null
    owner = db.owners.get(acct["owner_id"])
    if owner is None or owner["deceased_at"] is not None:
        raise_api(ERR_INVALID_STATE, "Cannot unfreeze account after owner has deceased.")
    acct["status"] = "ACTIVE"
    acct["updated_at"] = db.now_utc()
    acct["version"] += 1
    return success_object(account_to_json(acct))


@bp.route("/<account_id>/close", methods=["POST"])
def close_account(account_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner")
    acct = get_account_or_404(account_id)
    if g.role == "AccountOwner":
        require_owner_match(acct["owner_id"])
    body = get_json_body()
    expected = require_int(body, "expected_account_version")

    # State preconditions per PRD §3.2
    if g.role == "AccountOwner":
        # AccountOwner path: from ACTIVE
        if acct["status"] != "ACTIVE":
            raise_api(ERR_INVALID_STATE, "Account is not ACTIVE.")
    else:
        # PlanAdministrator may close ACTIVE or INHERITED.
        if acct["status"] not in ("ACTIVE", "INHERITED"):
            raise_api(ERR_INVALID_STATE, "Account is not ACTIVE or INHERITED.")

    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)

    if acct["cash_balance_cents"] != 0:
        raise_api(ERR_INVALID_STATE, "Account cash_balance_cents must be 0 to close.")

    owner = db.owners.get(acct["owner_id"])

    if acct["status"] == "ACTIVE":
        # AccountOwner-or-admin from ACTIVE: owner must not be deceased.
        if owner is None or owner["deceased_at"] is not None:
            raise_api(ERR_INVALID_STATE, "Cannot close ACTIVE account after owner has deceased.")
        # No OPEN RMDSchedule against this owner for a Traditional account.
        if acct["account_type"] == "TRADITIONAL":
            has_open_rmd = any(
                s["owner_id"] == acct["owner_id"] and s["status"] == "OPEN"
                for s in db.rmd_schedules.values()
            )
            if has_open_rmd:
                raise_api(ERR_INVALID_STATE, "Owner has an OPEN RMDSchedule for this Traditional account.")
    elif acct["status"] == "INHERITED":
        # All child contributions, distributions, conversions must be in terminal states.
        for c in db.contributions.values():
            if c["account_id"] == account_id and c["status"] == "PENDING":
                raise_api(ERR_INVALID_STATE, "Account has PENDING child contribution.")
        for d in db.distributions.values():
            if d["account_id"] == account_id and d["status"] == "PENDING":
                raise_api(ERR_INVALID_STATE, "Account has PENDING child distribution.")
        for cv in db.conversions.values():
            if (cv["source_account_id"] == account_id or cv["target_account_id"] == account_id) and cv["status"] == "INITIATED":
                raise_api(ERR_INVALID_STATE, "Account has INITIATED child conversion.")

    now = db.now_utc()
    acct["status"] = "CLOSED"
    acct["closed_at"] = now
    acct["updated_at"] = now
    acct["version"] += 1
    return success_object(account_to_json(acct))
