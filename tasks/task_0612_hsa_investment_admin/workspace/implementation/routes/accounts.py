"""HsaAccount lifecycle: open, get, list, verify, freeze, unfreeze, close,
limit-variant (PRD §3.2, §3.3)."""
from flask import Blueprint

import serializers
from db import db, new_id, stamp_create, touch
from errors import err
from helpers import (get_json_body, paginate, qarg, require_enum,
                     require_int, require_positive_int, require_string)
from lookups import get_account, get_accountholder, get_employer, assert_account_owner
from middleware import caller, require_role
from response import success
from services.account_calc import (catch_up_eligible, compute_applicable_limit,
                                    derive_posture, recompute_derived)

bp = Blueprint("accounts", __name__)


@bp.route("/hsa/accounts", methods=["POST"])
def open_account():
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    body = get_json_body()
    accountholder_id = require_string(body, "accountholder_id")
    plan_year = require_int(body, "plan_year")
    employer_id = require_string(body, "employer_id", required=False)
    invest_threshold = require_positive_int(body, "invest_threshold_cents", required=False)
    sweep_increment = require_positive_int(body, "sweep_increment_cents", required=False)

    # Referential existence of named FKs (treated as not-found before create).
    get_accountholder(accountholder_id)
    if employer_id is not None:
        get_employer(employer_id)

    o = {
        "accountholder_id": accountholder_id,
        "employer_id": employer_id,  # nullable
        "plan_year": plan_year,
        "lifecycle_status": "PENDING_VERIFICATION",
        "contribution_posture": "LOCKED",  # LOCKED until ACTIVE
        "cash_balance_cents": 0,
        "invested_balance_cents": 0,
        "contributions_ytd_cents": 0,
        "applicable_limit_cents": 0,
        "excess_contribution_cents": 0,
        "invest_threshold_cents": invest_threshold if invest_threshold is not None else 200000,
        "sweep_increment_cents": sweep_increment if sweep_increment is not None else 10000,
        "verification_token": new_id(),
        # internal: active limit variant (default LAST_MONTH_RULE), not serialized.
        "limit_variant": "LAST_MONTH_RULE",
    }
    stamp_create(o)
    db.accounts[o["id"]] = o
    return success(serializers.account(o), status=201)


@bp.route("/hsa/accounts/<account_id>", methods=["GET"])
def get_account_route(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    o = get_account(account_id)
    return success(serializers.account(o), status=200)


@bp.route("/hsa/accounts", methods=["GET"])
def list_accounts():
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    accountholder_id = qarg("accountholder_id")
    employer_id = qarg("employer_id")
    items = [
        a for a in db.accounts.values()
        if (accountholder_id is None or a["accountholder_id"] == accountholder_id)
        and (employer_id is None or a["employer_id"] == employer_id)
    ]
    page, meta = paginate(items)
    return success([serializers.account(a) for a in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/verify", methods=["POST"])
def verify_account(account_id):
    user_id, role = caller()
    require_role(role, {"Accountholder"})
    account = get_account(account_id)
    assert_account_owner(account, user_id)

    body = get_json_body()
    token = require_string(body, "verification_token")

    # State: only from PENDING_VERIFICATION.
    if account["lifecycle_status"] != "PENDING_VERIFICATION":
        raise err("ERR_INVALID_STATE", "Account is not PENDING_VERIFICATION")

    # Token check.
    if token != account["verification_token"]:
        raise err("ERR_INVALID_TOKEN", "verification_token does not match")

    # HDHP eligibility: at least one ATTESTED CoveragePeriod.
    has_attested = any(
        cp["account_id"] == account_id and cp["status"] == "ATTESTED"
        for cp in db.coverage_periods.values()
    )
    if not has_attested:
        raise err("ERR_HDHP_REQUIRED", "No ATTESTED coverage period")

    # Lazily compute the holder's catch-up flag against this account's plan_year.
    holder = db.accountholders.get(account["accountholder_id"])
    if holder is not None:
        holder["turns_55_or_older_in_plan_year"] = catch_up_eligible(account)
        touch(holder)

    account["lifecycle_status"] = "ACTIVE"
    recompute_derived(account)  # limit recomputed; posture re-derived; bump version
    return success(serializers.account(account), status=200)


@bp.route("/hsa/accounts/<account_id>/freeze", methods=["POST"])
def freeze_account(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    if account["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    account["lifecycle_status"] = "FROZEN"
    # FROZEN forces LOCKED regardless of excess.
    account["contribution_posture"] = "LOCKED"
    touch(account)
    return success(serializers.account(account), status=200)


@bp.route("/hsa/accounts/<account_id>/unfreeze", methods=["POST"])
def unfreeze_account(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    if account["lifecycle_status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Account is not FROZEN")
    account["lifecycle_status"] = "ACTIVE"
    derive_posture(account)  # OPEN unless excess > 0
    touch(account)
    return success(serializers.account(account), status=200)


@bp.route("/hsa/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    if account["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")

    # No REQUESTED distribution and no CLEARED-unsubstantiated distribution.
    for d in db.distributions.values():
        if d["account_id"] != account_id:
            continue
        if d["status"] == "REQUESTED":
            raise err("ERR_OPEN_DISTRIBUTION", "A REQUESTED distribution exists")
        if d["status"] == "CLEARED" and d["substantiation_status"] == "UNSUBSTANTIATED":
            raise err("ERR_OPEN_DISTRIBUTION", "A CLEARED-unsubstantiated distribution exists")

    account["lifecycle_status"] = "CLOSED"
    account["contribution_posture"] = "LOCKED"
    # Cascade: every ACTIVE debit card -> CLOSED (each child gets its own bump).
    for card in db.debit_cards.values():
        if card["account_id"] == account_id and card["status"] == "ACTIVE":
            card["status"] = "CLOSED"
            touch(card)
    touch(account)
    return success(serializers.account(account), status=200)


@bp.route("/hsa/accounts/<account_id>/limit-variant", methods=["POST"])
def set_limit_variant(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    body = get_json_body()
    variant = require_enum(body, "variant", {"LAST_MONTH_RULE", "PRORATED"})
    account["limit_variant"] = variant
    # Recompute limit, excess, posture (may LOCK/OPEN). recompute bumps version.
    recompute_derived(account)
    return success(serializers.account(account), status=200)
