"""Canteen store accounts and transactions. PRD §3.9."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute, calc
from services.store import base_fields, event_fields, require, touch, paginate, guardian_owns_camper

bp = Blueprint("canteen", __name__)

TXN_KINDS = {"DEPOSIT", "PURCHASE"}


def _guardian_owns_application(uid, role, application):
    if application is None:
        return
    camper = db.campers.get(application["camper_id"])
    if camper is not None:
        guardian_owns_camper(uid, role, camper)


@bp.route("/canteen-accounts", methods=["POST"])
def open_account():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    body = get_json_body()

    if "application_id" not in body or not isinstance(body.get("application_id"), str):
        raise validate.bad_request("application_id is required.")
    application = db.applications.get(body["application_id"])
    if application is None:
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409, "Application does not resolve.")
    _guardian_owns_application(uid, role, application)

    a = base_fields()
    a.update({
        "application_id": application["id"],
        "balance_cents": 0,
        "is_low": True,  # balance 0 <= low threshold -> low (PRD §3.9)
    })
    db.canteen_accounts[a["id"]] = a
    recompute.recompute_canteen_account(a)
    return response.success(serialize.canteen_account(a), 201)


@bp.route("/canteen-accounts", methods=["GET"])
def list_accounts():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    limit, offset = parse_pagination()

    app_f = request.args.get("application_id")
    items = list(db.canteen_accounts.values())
    if role == "Guardian":
        owned_campers = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
        owned_apps = {ap["id"] for ap in db.applications.values() if ap["camper_id"] in owned_campers}
        items = [a for a in items if a["application_id"] in owned_apps]
    if app_f is not None:
        items = [a for a in items if a["application_id"] == app_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.canteen_account(a) for a in page], limit, offset, total)


@bp.route("/canteen-accounts/<acid>", methods=["GET"])
def get_account(acid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    a = require(db.canteen_accounts, acid)
    if role == "Guardian":
        _guardian_owns_application(uid, role, db.applications.get(a["application_id"]))
    return response.success(serialize.canteen_account(a), 200)


@bp.route("/canteen-accounts/<acid>/transactions", methods=["POST"])
def create_transaction(acid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    account = require(db.canteen_accounts, acid)
    if role == "Guardian":
        _guardian_owns_application(uid, role, db.applications.get(account["application_id"]))
    body = get_json_body()

    kind = validate.require_enum(body, "kind", TXN_KINDS)
    amount = validate.require_positive_int(body, "amount_cents")

    # Overdraft forbidden (ERR_CANTEEN_INSUFFICIENT_FUNDS, p11): purchase amount
    # may not exceed current balance; == balance allowed.
    if kind == "PURCHASE":
        current = calc.compute_canteen_balance(account["id"])
        if amount > current:
            raise ApiError(errors.ERR_CANTEEN_INSUFFICIENT_FUNDS, 422, "Insufficient canteen funds.")

    t = event_fields()
    t.update({
        "account_id": account["id"],
        "kind": kind,
        "amount_cents": amount,
        "status": "APPLIED",
    })
    db.canteen_transactions[t["id"]] = t

    recompute.recompute_canteen_account(account)
    touch(account)

    return response.success(serialize.canteen_transaction(t), 201)


@bp.route("/canteen-accounts/<acid>/transactions", methods=["GET"])
def list_transactions(acid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    account = require(db.canteen_accounts, acid)
    if role == "Guardian":
        _guardian_owns_application(uid, role, db.applications.get(account["application_id"]))
    limit, offset = parse_pagination()

    items = [t for t in db.canteen_transactions.values() if t["account_id"] == acid]
    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.canteen_transaction(t) for t in page], limit, offset, total)
