"""Presented-item ingestion (synchronous matching) and reversal (PRD §3.4)."""
from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_ownership, scope_list
from errors import (
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_IDEMPOTENCY_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_ITEM_NOT_REVERSIBLE,
    raise_err,
)
from services import (
    CHANNELS,
    apply_reversal,
    guard_enrollment_mutable,
    ingest_presented_item,
    item_enrollment_id,
    item_out,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    opt_datetime,
    opt_str,
    req_enum,
    req_positive_int,
    req_str,
    success_object,
)

bp = Blueprint("presented_items", __name__)


def _item_payload_hash(body, account_id, key):
    import hashlib
    import json

    canon = json.dumps(
        {
            "account_id": account_id,
            "check_number": body.get("check_number"),
            "amount_cents": body.get("amount_cents"),
            "payee_name_raw": body.get("payee_name_raw"),
            "channel": body.get("channel"),
            "presented_at": body.get("presented_at"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@bp.route("/treasury/presented-items", methods=["POST"])
def ingest_item():
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body = body_json()
    account_id = req_str(body, "account_id")
    check_number = req_str(body, "check_number", non_empty=False)
    amount_cents = req_positive_int(body, "amount_cents")
    payee_name_raw = body.get("payee_name_raw")
    if not isinstance(payee_name_raw, str):
        raise_err(ERR_INVALID_REQUEST, "payee_name_raw is required and must be a string")
    channel = req_enum(body, "channel", CHANNELS)
    presented_at = opt_datetime(body, "presented_at", None)
    idempotency_key = opt_str(body, "idempotency_key")

    acct = get_or_404(store.accounts, account_id, "Account")
    enr = store.enrollments[acct["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if acct["status"] == "CLOSED":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Account is CLOSED")

    if idempotency_key is not None:
        payload_hash = _item_payload_hash(body, account_id, idempotency_key)
        prior = store.item_idem.get((account_id, idempotency_key))
        if prior is not None:
            prior_hash, prior_item_id = prior
            if prior_hash == payload_hash:
                return success_object(item_out(store.items[prior_item_id]), 201)
            raise_err(ERR_IDEMPOTENCY_CONFLICT, "idempotency_key reused with a different payload")

    if presented_at is None:
        presented_at = clock.now()
    item = ingest_presented_item(acct, enr, {
        "check_number": check_number,
        "amount_cents": amount_cents,
        "payee_name_raw": payee_name_raw,
        "channel": channel,
        "presented_at": presented_at,
        "idempotency_key": idempotency_key,
    })
    if idempotency_key is not None:
        store.item_idem[(account_id, idempotency_key)] = (payload_hash, item["id"])
    return success_object(item_out(item), 201)


@bp.route("/treasury/presented-items/<iid>", methods=["GET"])
def get_item(iid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.items, iid, "PresentedItem")
    check_ownership(user, item_enrollment_id(rec))
    return success_object(item_out(rec), 200)


@bp.route("/treasury/presented-items", methods=["GET"])
def list_items():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    records = scope_list(store.items.values(), user, item_enrollment_id)
    for param in ("account_id", "exception_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [i for i in records if str(i.get(param)) == v]
    return list_response(records, item_out)


@bp.route("/treasury/presented-items/<iid>/reverse", methods=["POST"])
def reverse_item(iid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body = body_json()
    req_str(body, "reason", non_empty=False)
    rec = get_or_404(store.items, iid, "PresentedItem")
    enr = store.enrollments[item_enrollment_id(rec)]
    guard_enrollment_mutable(enr)
    if rec["status"] != "PAID":
        raise_err(ERR_ITEM_NOT_REVERSIBLE, "Only a PAID item can be reversed")
    rec["status"] = "REVERSED"
    bump(rec)
    apply_reversal(store.accounts[rec["account_id"]], rec["amount_cents"])
    return success_object(item_out(rec), 200)
