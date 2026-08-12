"""Clients endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_NO_VERIFIED_ENTITLEMENT,
    ERR_INVALID_REQUEST,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_client
from services.cascade import (
    cascade_client_suspend,
    cascade_client_terminate,
    clock_now_iso,
)
from services.derived import recompute_client_rollups
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_bool,
    get_int,
    reject_unexpected,
    iso_ts,
)

bp = Blueprint("clients", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")


@bp.route("/clients", methods=["POST"])
def create_client():
    user_id, _ = require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {
        "legal_name", "date_of_birth", "ssn_last4", "county_of_residence",
        "medicaid_enrolled", "medicaid_resource_limit_cents",
    })
    legal_name = get_string(body, "legal_name")
    dob = parse_date(get_string(body, "date_of_birth"), "date_of_birth")
    ssn = get_string(body, "ssn_last4")
    if len(ssn) != 4 or not ssn.isdigit():
        raise err(ERR_INVALID_REQUEST, 400, "ssn_last4 must be exactly 4 digits")
    county = get_string(body, "county_of_residence")
    medicaid = get_bool(body, "medicaid_enrolled")
    limit = get_int(body, "medicaid_resource_limit_cents", required=False, min_value=1)
    if limit is None:
        limit = 200000

    now = clock_now_iso()
    cid = new_id()
    c = {
        "id": cid,
        "legal_name": legal_name,
        "date_of_birth": dob,
        "ssn_last4": ssn,
        "county_of_residence": county,
        "medicaid_enrolled": medicaid,
        "medicaid_resource_limit_cents": limit,
        "status": "INTAKE_REVIEW",
        "total_funds_cents": 0,
        "countable_resources_cents": 0,
        "medicaid_at_risk": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.clients[cid] = c
    recompute_client_rollups(cid)
    return success_object(serialize_client(c), status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    medicaid_enrolled = request.args.get("medicaid_enrolled")
    items = list(store.clients.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if medicaid_enrolled is not None:
        want = medicaid_enrolled.lower() == "true"
        items = [c for c in items if bool(c.get("medicaid_enrolled")) == want]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_client(c) for c in page], limit, offset, total)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    require_roles(*READ_ROLES)
    c = store.clients.get(cid)
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    return success_object(serialize_client(c))


def _get_client_or_404(cid):
    c = store.clients.get(cid)
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    return c


@bp.route("/clients/<cid>/activate", methods=["POST"])
def activate_client(cid):
    require_roles("FiduciaryAdmin")
    c = _get_client_or_404(cid)
    # terminal check first
    if c["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Client is TERMINATED")
    if c["status"] not in ("INTAKE_REVIEW", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, 409, "Client state machine rejects activate from this state")
    # verified entitlement required
    has_verified = any(
        e["client_id"] == cid and e["status"] == "VERIFIED"
        for e in store.entitlements.values()
    )
    if not has_verified:
        raise err(ERR_NO_VERIFIED_ENTITLEMENT, 409, "Client has no VERIFIED entitlement")
    now = clock_now_iso()
    c["status"] = "ACTIVE"
    c["updated_at"] = now
    c["version"] += 1
    # unfreeze FROZEN accounts
    from services.cascade import unfreeze_account
    for acct in list(store.accounts.values()):
        if acct["client_id"] == cid and acct["status"] == "FROZEN":
            unfreeze_account(acct["id"], now)
    recompute_client_rollups(cid)
    from services.derived import recompute_bond_rollups
    recompute_bond_rollups()
    return success_object(serialize_client(c))


@bp.route("/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    require_roles("FiduciaryAdmin")
    c = _get_client_or_404(cid)
    if c["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Client is TERMINATED")
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE -> SUSPENDED")
    now = clock_now_iso()
    c["status"] = "SUSPENDED"
    c["updated_at"] = now
    c["version"] += 1
    cascade_client_suspend(cid, now)
    return success_object(serialize_client(c))


@bp.route("/clients/<cid>/terminate", methods=["POST"])
def terminate_client(cid):
    require_roles("FiduciaryAdmin")
    c = _get_client_or_404(cid)
    if c["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Client is TERMINATED")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE/SUSPENDED -> TERMINATED")
    now = clock_now_iso()
    c["status"] = "TERMINATED"
    c["updated_at"] = now
    c["version"] += 1
    cascade_client_terminate(cid, now)
    return success_object(serialize_client(c))
