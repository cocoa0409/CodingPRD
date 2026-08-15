"""Reference data: Analysts, Customers, Accounts, Transactions."""
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import (ALL_ROLES, authn, authz, get_body, pagination_params)
from util import (CHANNELS, DIRECTIONS, TXN_TYPES, base_entity, new_id,
                  req_enum, req_dt, req_int, req_str, opt_int, serialize,
                  sort_created)

bp = Blueprint("reference", __name__)


def _get_or_404(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


# ---------------------------------------------------------------------------
# Analysts
# ---------------------------------------------------------------------------

@bp.route("/analysts", methods=["POST"])
def create_analyst():
    body = get_body()
    full_name = req_str(body, "full_name")
    capacity = opt_int(body, "capacity_max_cases", default=10, minimum=0)
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    analyst = base_entity()
    analyst.update({
        "full_name": full_name,
        "capacity_max_cases": capacity,
        "assigned_open_cases": 0,
    })
    db.analysts[analyst["id"]] = analyst
    return response.success(serialize(analyst), status=201)


@bp.route("/analysts/<rid>", methods=["GET"])
def get_analyst(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    analyst = _get_or_404(db.analysts, rid, "Analyst")
    return response.success(serialize(analyst), status=200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    body = get_body()
    full_name = req_str(body, "full_name")
    country_code = req_str(body, "country_code")
    country_risk = req_enum(body, "country_risk", {"LOW", "HIGH"})
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    customer = base_entity()
    customer.update({
        "full_name": full_name,
        "country_code": country_code,
        "country_risk": country_risk,
        "status": "ACTIVE",
        "sar_filings_365d": 0,
        "open_le_inquiry_count": 0,
        "any_account_exited": False,
        # PRD section 2.6: creation initializes BOTH scores to the 100 base.
        "risk_score_standard": 100,
        "risk_score_enhanced": 100,
        "risk_rating": "LOW",
    })
    db.customers[customer["id"]] = customer
    return response.success(serialize(customer), status=201)


@bp.route("/customers/<rid>", methods=["GET"])
def get_customer(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    customer = _get_or_404(db.customers, rid, "Customer")
    return response.success(serialize(customer), status=200)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@bp.route("/customers/<rid>/accounts", methods=["POST"])
def create_account(rid):
    body = get_body()
    account_number = req_str(body, "account_number")
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    customer = _get_or_404(db.customers, rid, "Customer")
    for existing in db.accounts.values():
        if existing["account_number"] == account_number:
            raise ApiError("ERR_INVALID_REQUEST",
                           f"account_number '{account_number}' is already in use", 400)
    if customer["risk_rating"] == "PROHIBITED" or customer["status"] == "EXITED":
        raise ApiError("ERR_CUSTOMER_PROHIBITED",
                       "Account opening is blocked for PROHIBITED or EXITED customers", 409)
    account = base_entity()
    account.update({
        "customer_id": customer["id"],
        "account_number": account_number,
        "status": "OPEN",
        "restriction_reason": None,
    })
    db.accounts[account["id"]] = account
    return response.success(serialize(account), status=201)


@bp.route("/customers/<rid>/accounts", methods=["GET"])
def list_customer_accounts(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    customer = _get_or_404(db.customers, rid, "Customer")
    limit, offset = pagination_params()
    items = sort_created([a for a in db.accounts.values()
                          if a["customer_id"] == customer["id"]])
    return response.paginated([serialize(a) for a in items], limit, offset)


@bp.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    account = _get_or_404(db.accounts, rid, "Account")
    return response.success(serialize(account), status=200)


# ---------------------------------------------------------------------------
# Transactions (immutable posted events: id + created_at only)
# ---------------------------------------------------------------------------

@bp.route("/accounts/<rid>/transactions", methods=["POST"])
def create_transaction(rid):
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=1)
    txn_type = req_enum(body, "txn_type", TXN_TYPES)
    direction = req_enum(body, "direction", DIRECTIONS)
    counterparty_country = req_str(body, "counterparty_country")
    posted_at = req_dt(body, "posted_at")
    channel = req_enum(body, "channel", CHANNELS)
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    account = _get_or_404(db.accounts, rid, "Account")
    txn = {
        "id": new_id(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
        "account_id": account["id"],
        "amount_cents": amount_cents,
        "txn_type": txn_type,
        "direction": direction,
        "counterparty_country": counterparty_country,
        "posted_at": posted_at,
        "channel": channel,
    }
    db.transactions[txn["id"]] = txn
    return response.success(serialize(txn), status=201)


@bp.route("/accounts/<rid>/transactions", methods=["GET"])
def list_account_transactions(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    account = _get_or_404(db.accounts, rid, "Account")
    limit, offset = pagination_params()
    items = sorted([t for t in db.transactions.values()
                    if t["account_id"] == account["id"]],
                   key=lambda t: (t["posted_at"], t["_seq"]))
    return response.paginated([serialize(t) for t in items], limit, offset)
