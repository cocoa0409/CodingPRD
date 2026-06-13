"""MoneyRequest endpoints: create, fetch, list, pay/decline/cancel."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import transfer as transfer_svc

bp = Blueprint("money_requests", __name__)


@bp.route("/money-requests", methods=["POST"])
def create_money_request():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        requester_id = validate.require_str(body, "requester_account_id")
        payer_id = validate.require_str(body, "payer_account_id")
        amount = validate.require_int(body, "amount_cents", minimum=1)
        requester = db.accounts.get(requester_id)
        if not requester:
            raise err("ERR_NOT_FOUND", "Requester account not found.")
        payer = db.accounts.get(payer_id)
        if not payer:
            raise err("ERR_NOT_FOUND", "Payer account not found.")
        # ownership: only the requester may create the request on their own behalf
        if p.user_id != requester_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the requester account owner.")
        if requester_id == payer_id:
            raise err("ERR_SELF_TRANSFER", "Requester and payer must differ.")
        mr = {
            "requester_account_id": requester_id,
            "payer_account_id": payer_id,
            "amount_cents": amount,
            "status": "PENDING",
        }
        models._stamp_create(mr)
        db.money_requests[mr["id"]] = mr
        return response.ok(models.serialize(mr), 201)


@bp.route("/money-requests/<mr_id>", methods=["GET"])
def get_money_request(mr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        mr = db.money_requests.get(mr_id)
        if not mr:
            raise err("ERR_NOT_FOUND", "Money request not found.")
        return response.ok(models.serialize(mr))


@bp.route("/money-requests", methods=["GET"])
def list_money_requests():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.money_requests.values())
        for key in ("requester_account_id", "payer_account_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [m for m in items if m.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/money-requests/<mr_id>/pay", methods=["POST"])
def pay_money_request(mr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        mr = db.money_requests.get(mr_id)
        if not mr:
            raise err("ERR_NOT_FOUND", "Money request not found.")
        if p.user_id != mr["payer_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the payer may pay this request.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Money request is not PENDING.")
        body = validate.get_json_body()
        memo = validate.optional_str(body, "memo", "")
        payer = db.accounts[mr["payer_account_id"]]
        requester = db.accounts[mr["requester_account_id"]]
        # frozen check before spawning the transfer
        if payer["status"] == "FROZEN" or requester["status"] == "FROZEN":
            raise err("ERR_ACCOUNT_FROZEN", "An account in this payment is frozen.")
        # spawn transfer payer->requester (runs limit/funds/risk fork)
        transfer_svc.create_transfer(payer, requester, mr["amount_cents"],
                                     memo=memo, source_money_request_id=mr_id)
        mr["status"] = "FULFILLED"
        models.touch(mr)
        return response.ok(models.serialize(mr))


@bp.route("/money-requests/<mr_id>/decline", methods=["POST"])
def decline_money_request(mr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        mr = db.money_requests.get(mr_id)
        if not mr:
            raise err("ERR_NOT_FOUND", "Money request not found.")
        if p.user_id != mr["payer_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the payer may decline.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Money request is not PENDING.")
        mr["status"] = "DECLINED"
        models.touch(mr)
        return response.ok(models.serialize(mr))


@bp.route("/money-requests/<mr_id>/cancel", methods=["POST"])
def cancel_money_request(mr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        mr = db.money_requests.get(mr_id)
        if not mr:
            raise err("ERR_NOT_FOUND", "Money request not found.")
        if p.user_id != mr["requester_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the requester may cancel.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Money request is not PENDING.")
        mr["status"] = "CANCELLED"
        models.touch(mr)
        return response.ok(models.serialize(mr))
