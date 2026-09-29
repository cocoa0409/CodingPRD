from flask import Blueprint, g, request

import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, own
from routes.common import check_version, filter_eq, listing, lookup, unique
from services import projections as proj

bp = Blueprint("accounts", __name__)

CREDIT_ACTIONS = ("WITHDRAW", "MANUAL_GRANT", "CLAWBACK")
ENTRY_TYPE = {
    "WITHDRAW": "PAYOUT_WITHDRAWAL",
    "MANUAL_GRANT": "MANUAL_GRANT",
    "CLAWBACK": "CLAWBACK",
}
STATUS_ACTIONS = ("FLAG", "UNFLAG", "CLOSE")
STATUS_TRANSITIONS = {
    "FLAG": (("ACTIVE",), "FLAGGED"),
    "UNFLAG": (("FLAGGED",), "ACTIVE"),
    "CLOSE": (("ACTIVE", "FLAGGED"), "CLOSED"),
}
UNSETTLED_BAG_STATES = ("DROPPED", "COUNTED", "DISPUTED")


@bp.post("/redeemer-accounts")
def create_account():
    authenticate("ProgramAdmin", "CenterOperator")
    body = v.body()
    holder_name = v.req_str(body, "holder_name")
    account_code = v.req_str(body, "account_code")
    enrolled = v.opt_bool(body, "bag_drop_enrolled", False)
    unique(db.accounts, "account_code", account_code, "ERR_DUPLICATE_ACCOUNT_CODE")
    rec = db.new_record({
        "holder_name": holder_name,
        "account_code": account_code,
        "bag_drop_enrolled": enrolled,
        "status": "ACTIVE",
        "credit_balance_cents": 0,
        "redemption_day": None,
        "containers_redeemed_today": 0,
        "cap_reached_today": False,
        "fraud_strikes": 0,
        "last_strike_reason": None,
    })
    db.accounts[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/redeemer-accounts/<rid>")
def get_account(rid):
    authenticate("ProgramAdmin", "CenterOperator", "AccountHolder")
    own(account_id=rid)
    rec = lookup("account", rid)
    return response.obj(db.public(rec))


@bp.post("/redeemer-accounts/<rid>/credit-actions")
def credit_action(rid):
    authenticate("CenterOperator", "ProgramAdmin")
    own(account_id=rid)
    account = lookup("account", rid)
    body = v.body()
    action = v.req_enum(body, "action", CREDIT_ACTIONS)
    amount = v.req_int(body, "amount_cents", minimum=0)
    expected = v.req_int(body, "expected_account_version")
    memo = v.opt_str(body, "memo")

    check_version(expected, account, "ERR_STALE_ACCOUNT_VERSION")

    if account["status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
    if account["status"] == "FLAGGED":
        fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is flagged.")

    if action in ("WITHDRAW", "CLAWBACK"):
        if account["credit_balance_cents"] < amount:
            fail("ERR_INSUFFICIENT_CREDIT_BALANCE",
                 "The account balance is smaller than the requested amount.")
        signed = -amount
    else:
        signed = amount

    entry = proj.append_credit_entry(account, ENTRY_TYPE[action], signed,
                                    "PROGRAM_ACTION", g.user_id, memo)
    return response.obj(db.public(entry), 201)


@bp.post("/redeemer-accounts/<rid>/status-changes")
def status_change(rid):
    authenticate("ProgramAdmin")
    account = lookup("account", rid)
    body = v.body()
    action = v.req_enum(body, "action", STATUS_ACTIONS)
    v.opt_str(body, "reason")

    froms, target = STATUS_TRANSITIONS[action]
    if account["status"] not in froms:
        fail("ERR_INVALID_ACCOUNT_STATE",
             "Action %s is not available from %s." % (action, account["status"]))

    if action == "UNFLAG":
        account["fraud_strikes"] = 0
        account["last_strike_reason"] = None
    elif action == "CLOSE":
        if account["credit_balance_cents"] != 0:
            fail("ERR_ACCOUNT_BALANCE_NONZERO",
                 "The account still carries a non-zero credit balance.")
        for bag in proj.account_bag_drops(account["id"]):
            if bag["status"] in UNSETTLED_BAG_STATES:
                fail("ERR_ACCOUNT_BALANCE_NONZERO",
                     "The account still has an unsettled drop bag.")
        account["bag_drop_enrolled"] = False

    account["status"] = target
    touch(account)
    return response.obj(db.public(account))


@bp.get("/redeemer-accounts/<rid>/credit-entries")
def list_credit_entries(rid):
    authenticate("ProgramAdmin", "CenterOperator", "AccountHolder")
    own(account_id=rid)
    account = lookup("account", rid)
    rows = proj.account_entries(account["id"])
    rows = filter_eq(rows, "entry_type", request.args.get("entry_type"))
    return listing(rows)
