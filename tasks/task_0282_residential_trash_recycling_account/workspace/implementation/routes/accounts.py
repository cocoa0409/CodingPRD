"""Service account create/list/read, payment-method, autopay (PRD §3.2, §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services.common import new_record, touch, sort_by_created
from services.lookup import get_or_404, ref_or_404
from services.serialize import account_out

bp = Blueprint("accounts", __name__)

ACTIVE_ADDRESS_STATES = {"PENDING_START", "ACTIVE", "SUSPENDED"}


def _address_in_use(address, exclude_id=None):
    for a in db.service_accounts.values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["service_address"] == address and a["status"] in ACTIVE_ADDRESS_STATES:
            return True
    return False


@bp.route("/accounts", methods=["POST"])
def create_account():
    gate({"Dispatcher"})
    body = V.get_body(request)

    # priority 4: body FK existence checked before well-formedness (PRD §2.6).
    # Only FK fields that are present-and-string can be resolved here; absent or
    # mistyped FKs surface as ERR_INVALID_REQUEST in the well-formedness pass.
    plan = None
    if isinstance(body.get("plan_id"), str):
        plan = ref_or_404(db.service_plans, body["plan_id"])
    if isinstance(body.get("zone_id"), str):
        ref_or_404(db.collection_zones, body["zone_id"])

    # priority 5: well-formedness
    plan_id = V.require_str(body, "plan_id")
    zone_id = V.require_str(body, "zone_id")
    service_address = V.require_str(body, "service_address", non_empty=True)
    holder_name = V.require_str(body, "holder_name")

    if plan is None:
        plan = ref_or_404(db.service_plans, plan_id)

    # priority 9: plan archived
    if plan["archived"]:
        raise err("ERR_PLAN_ARCHIVED", "Cannot assign an archived plan.")
    # priority 10: address uniqueness
    if _address_in_use(service_address):
        raise err("ERR_ADDRESS_IN_USE", "Service address is already in use.")

    rec = new_record({
        "plan_id": plan_id,
        "zone_id": zone_id,
        "service_address": service_address,
        "holder_name": holder_name,
        "status": "PENDING_START",
        "billing_status": "CURRENT",
        "autopay_enabled": False,
        "stored_payment_token": None,
        "service_start_date": None,
        "transferred_from_account_id": None,
    })
    db.service_accounts[rec["id"]] = rec
    return ok(account_out(rec), 201)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    gate({"Dispatcher"})
    limit, offset = V.parse_pagination(request.args)
    plan_id = request.args.get("plan_id")
    zone_id = request.args.get("zone_id")
    xfer = request.args.get("transferred_from_account_id")

    items = list(db.service_accounts.values())
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if zone_id is not None:
        items = [a for a in items if a["zone_id"] == zone_id]
    if xfer is not None:
        items = [a for a in items if a["transferred_from_account_id"] == xfer]

    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([account_out(a) for a in page], limit, offset, total)


@bp.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    # balances recomputed on read; read does not bump version (PRD §3.2)
    return ok(account_out(a))


@bp.route("/accounts/<aid>/payment-method", methods=["POST"])
def set_payment_method(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    body = V.get_body(request)
    token = V.require_str(body, "stored_payment_token")
    a["stored_payment_token"] = token
    touch(a)
    return ok(account_out(a))


@bp.route("/accounts/<aid>/autopay", methods=["POST"])
def set_autopay(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    body = V.get_body(request)
    enabled = V.require_bool(body, "autopay_enabled")
    # priority 14: autopay cannot be enabled without a stored payment method
    if enabled and a["stored_payment_token"] is None:
        raise err("ERR_NO_PAYMENT_METHOD", "Autopay requires a stored payment method.")
    a["autopay_enabled"] = enabled
    touch(a)
    return ok(account_out(a))
