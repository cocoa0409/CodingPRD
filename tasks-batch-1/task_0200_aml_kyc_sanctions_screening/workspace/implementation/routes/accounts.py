"""Accounts, transactions, alerts (PRD §3.6, §3.7)."""

from flask import Blueprint, request

import db
import calculations as calc
import services
import clock
from errors import (
    err,
    ERR_DUPLICATE_ACCOUNT_REF,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ACCOUNT_NOT_TRANSACTABLE,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_string,
    require_enum,
    require_country,
    require_int,
    require_field,
    parse_pagination,
    sort_and_paginate,
)

bp = Blueprint("accounts", __name__)

READ_ROLES = {"ComplianceOfficer", "Analyst", "QualityReviewer", "PlatformAdmin"}
DIRECTIONS = {"CASH_IN", "CASH_OUT", "WIRE_IN", "WIRE_OUT"}
CREDIT_DIRECTIONS = {"CASH_IN", "WIRE_IN"}


def mint_alert(account, rule_code, user_id, role):
    """Mint an Alert(status=OPEN) for an account and advance monitoring if ACTIVE.

    Severity uses the owning customer's risk_rating at mint time (PRD §3.7).
    Shared by transaction monitoring and lookback-item escalation.
    """
    customer = db.customers.get(account["customer_id"])
    risk_rating = customer["risk_rating"] if customer else None
    base = db.common_create_fields()
    alert = {
        **base,
        "account_id": account["id"],
        "customer_id": account["customer_id"],
        "rule_code": rule_code,
        "severity_score": calc.alert_severity(rule_code, risk_rating),
        "status": "OPEN",
        "case_id": None,
    }
    db.alerts[alert["id"]] = alert
    # cross-entity cascade: account ACTIVE -> UNDER_INVESTIGATION (PRD §3.6)
    if account["monitoring_status"] == "ACTIVE":
        account["monitoring_status"] = "UNDER_INVESTIGATION"
        db.touch(account)
    services.audit("Alert", alert["id"], "ALERT_CREATED", user_id, role)
    return alert


# ===========================================================================
# Accounts
# ===========================================================================
@bp.route("/customers/<cid>/accounts", methods=["POST"])
def open_account(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer", "PlatformAdmin"})
    customer = require_found(db.customers.get(cid))
    body = get_body()

    account_ref = require_string(body, "account_ref")
    opening_balance = require_int(body, "opening_balance_cents", 0, None)

    # priority 6: account_ref unique across all accounts (PRD §3.6)
    for a in db.accounts.values():
        if a["account_ref"] == account_ref:
            raise err(ERR_DUPLICATE_ACCOUNT_REF, "account_ref already in use.")

    base = db.common_create_fields()
    account = {
        **base,
        "customer_id": cid,
        "account_ref": account_ref,
        "opening_balance_cents": opening_balance,
        "kyc_status": "PENDING_KYC",
        "monitoring_status": "ACTIVE",
        "aggregate_cash_in_cents": 0,
        "cumulative_credited_cents": 0,
        # internal: anchor day for the same-UTC-day CASH_IN window
        "_ctr_window_day": None,
    }
    db.accounts[account["id"]] = account
    services.audit("Account", account["id"], "ACCOUNT_OPENED", user_id, role)
    return object_response(db.public(account), 201)


@bp.route("/customers/<cid>/accounts", methods=["GET"])
def list_customer_accounts(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.customers.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [a for a in db.accounts.values() if a["customer_id"] == cid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(a) for a in page], limit, offset, total)


@bp.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    account = require_found(db.accounts.get(aid))
    return object_response(db.public(account))


@bp.route("/accounts/<aid>/freeze", methods=["POST"])
def freeze_account(aid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    account = require_found(db.accounts.get(aid))

    if account["monitoring_status"] != "UNDER_INVESTIGATION":
        raise err(ERR_INVALID_STATE, "freeze requires monitoring_status UNDER_INVESTIGATION.")
    account["monitoring_status"] = "FROZEN"
    db.touch(account)
    services.audit("Account", aid, "ACCOUNT_FROZEN", user_id, role)
    return object_response(db.public(account))


# ===========================================================================
# Transactions
# ===========================================================================
@bp.route("/accounts/<aid>/transactions", methods=["POST"])
def post_transaction(aid):
    user_id, role = authenticate()
    require_role(role, {"SystemFeed", "ComplianceOfficer"})
    account = require_found(db.accounts.get(aid))
    body = get_body()

    direction = require_enum(body, "direction", DIRECTIONS)
    amount = require_int(body, "amount_cents", 1, None)  # > 0
    posted_at_raw = require_field(body, "posted_at")
    if not isinstance(posted_at_raw, str):
        raise err(ERR_INVALID_REQUEST, "posted_at must be an ISO 8601 string.")
    try:
        posted_dt = clock.parse_iso8601(posted_at_raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "posted_at must be a valid ISO 8601 timestamp.")
    counterparty = require_country(body, "counterparty_country")

    # priority 19: not transactable when KYC_BLOCKED or FROZEN (PRD §3.6)
    if account["kyc_status"] == "KYC_BLOCKED" or account["monitoring_status"] == "FROZEN":
        raise err(ERR_ACCOUNT_NOT_TRANSACTABLE, "Account is KYC_BLOCKED or FROZEN.")

    posted_iso = clock.format_iso8601(posted_dt)
    posted_day = posted_dt.date().isoformat()

    # ---- same-UTC-day CASH_IN window with reset (PRD §3.6) ----
    prior_cumulative = account["cumulative_credited_cents"]
    window_cash_in_after = account["aggregate_cash_in_cents"]
    if direction == "CASH_IN":
        if account["_ctr_window_day"] != posted_day:
            # new UTC day: reset before folding this txn in
            account["aggregate_cash_in_cents"] = 0
            account["_ctr_window_day"] = posted_day
        account["aggregate_cash_in_cents"] += amount
        window_cash_in_after = account["aggregate_cash_in_cents"]

    # ---- cumulative_credited_cents (lifetime CASH_IN + WIRE_IN) ----
    if direction in CREDIT_DIRECTIONS:
        account["cumulative_credited_cents"] += amount

    # ---- evaluate monitoring rules (uses prior cumulative for RAPID) ----
    triggered = calc.evaluate_monitoring(
        direction=direction,
        amount_cents=amount,
        counterparty_country=counterparty,
        window_cash_in_after=window_cash_in_after,
        prior_cumulative_credited=prior_cumulative,
    )

    base = db.light_create_fields()
    txn = {
        **base,
        "account_id": aid,
        "direction": direction,
        "amount_cents": amount,
        "posted_at": posted_iso,
        "counterparty_country": counterparty,
        "triggered_rule": triggered,
    }
    db.transactions[txn["id"]] = txn
    db.touch(account)  # tallies changed -> account mutated (§2.4)

    if triggered is not None:
        mint_alert(account, triggered, user_id, role)

    services.audit("Transaction", txn["id"], "TRANSACTION_POSTED", user_id, role)
    return object_response(db.public(txn), 201)


@bp.route("/accounts/<aid>/transactions", methods=["GET"])
def list_account_transactions(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.accounts.get(aid))
    limit, offset = parse_pagination(request.args)
    rows = [t for t in db.transactions.values() if t["account_id"] == aid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(t) for t in page], limit, offset, total)


# ===========================================================================
# Alerts
# ===========================================================================
@bp.route("/accounts/<aid>/alerts", methods=["GET"])
def list_account_alerts(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.accounts.get(aid))
    limit, offset = parse_pagination(request.args)
    rows = [al for al in db.alerts.values() if al["account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [al for al in rows if al["status"] == status]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(al) for al in page], limit, offset, total)


@bp.route("/alerts", methods=["GET"])
def list_alerts():
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.alerts.values())
    for field in ("account_id", "customer_id", "case_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [al for al in rows if al.get(field) == val]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(al) for al in page], limit, offset, total)


@bp.route("/alerts/<alid>", methods=["GET"])
def get_alert(alid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    alert = require_found(db.alerts.get(alid))
    return object_response(db.public(alert))
