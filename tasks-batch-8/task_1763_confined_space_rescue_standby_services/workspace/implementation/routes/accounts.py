"""Client account registry (PRD section 3.1)."""

from flask import Blueprint, request

import db
import serializers
from errors import ERR_ACCOUNT_NOT_FOUND, ERR_INVALID_REQUEST, raise_error
from helpers import (
    body, list_response, opt_int, opt_number, reject_unknown, req_enum,
    req_int, req_string, stamp_new,
)
from middleware import ALL_ROLES, require_auth
from response import success_object

bp = Blueprint("accounts", __name__)

BILLING_MODES = ("HOURLY_STANDBY", "EVENT")


def get_account(account_id):
    account = db.client_accounts.get(account_id)
    if account is None:
        raise_error(ERR_ACCOUNT_NOT_FOUND, "Client account not found")
    return account


def _non_negative(value, field):
    if value < 0:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be non-negative")
    return value


@bp.route("/rescue-ops/client-accounts", methods=["POST"])
def create_account():
    require_auth(("OperationsManager",))
    data = body()
    reject_unknown(data, {
        "name", "billing_mode", "hourly_standby_rate_cents", "event_base_fee_cents",
        "event_per_rescuer_cents", "credit_limit_cents", "deployment_surcharge_cents",
        "minimum_billable_hours", "tier1_hours_threshold", "tier2_multiplier",
        "after_hours_multiplier", "weekend_multiplier",
    })
    account = {
        "name": req_string(data, "name"),
        "billing_mode": req_enum(data, "billing_mode", BILLING_MODES),
        "hourly_standby_rate_cents": _non_negative(req_int(data, "hourly_standby_rate_cents"), "hourly_standby_rate_cents"),
        "event_base_fee_cents": _non_negative(req_int(data, "event_base_fee_cents"), "event_base_fee_cents"),
        "event_per_rescuer_cents": _non_negative(req_int(data, "event_per_rescuer_cents"), "event_per_rescuer_cents"),
        "credit_limit_cents": _non_negative(req_int(data, "credit_limit_cents"), "credit_limit_cents"),
        "deployment_surcharge_cents": _non_negative(opt_int(data, "deployment_surcharge_cents", 50000), "deployment_surcharge_cents"),
        "minimum_billable_hours": _non_negative(opt_number(data, "minimum_billable_hours", 4), "minimum_billable_hours"),
        "tier1_hours_threshold": _non_negative(opt_number(data, "tier1_hours_threshold", 8), "tier1_hours_threshold"),
        "tier2_multiplier": _non_negative(opt_number(data, "tier2_multiplier", 1.5), "tier2_multiplier"),
        "after_hours_multiplier": _non_negative(opt_number(data, "after_hours_multiplier", 1.5), "after_hours_multiplier"),
        "weekend_multiplier": _non_negative(opt_number(data, "weekend_multiplier", 2.0), "weekend_multiplier"),
        "balance_cents": 0,
        "on_credit_hold": False,
    }
    stamp_new(account)
    db.client_accounts[account["id"]] = account
    return success_object(serializers.client_account(account), 201)


@bp.route("/rescue-ops/client-accounts", methods=["GET"])
def list_accounts():
    require_auth(ALL_ROLES)
    return list_response(list(db.client_accounts.values()), serializers.client_account, {
        "billing_mode": request.args.get("billing_mode"),
        "on_credit_hold": request.args.get("on_credit_hold"),
    })


@bp.route("/rescue-ops/client-accounts/<account_id>", methods=["GET"])
def get_one_account(account_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.client_account(get_account(account_id)))
