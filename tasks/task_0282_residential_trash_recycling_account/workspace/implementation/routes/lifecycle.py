"""Account service lifecycle: activate-start, suspend, resume, stop, transfer-out
(PRD §3.3, §3.4, SCAFFOLD §1.2 ServiceAccount service machine)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from response import ok
from routes.helpers import gate
from routes.accounts import _address_in_use
from services import validate as V
from services.common import new_record, touch
from services.lookup import get_or_404, ref_or_404
from services.serialize import account_out
from services.schedule import (
    generate_schedule_rows,
    cancel_future_planned,
    cancel_all_planned,
)

bp = Blueprint("lifecycle", __name__)


def _has_complete_carts(account_id):
    has_trash = any(
        c["account_id"] == account_id and c["status"] == "ACTIVE" and c["cart_type"] == "TRASH"
        for c in db.cart_assignments.values()
    )
    has_recyc = any(
        c["account_id"] == account_id and c["status"] == "ACTIVE" and c["cart_type"] == "RECYCLING"
        for c in db.cart_assignments.values()
    )
    return has_trash and has_recyc


@bp.route("/accounts/<aid>/activate-start", methods=["POST"])
def activate_start(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    # priority 7: state legality
    if a["status"] != "PENDING_START":
        raise err("ERR_INVALID_STATE", "Account is not in PENDING_START.")
    # priority 8: carts incomplete (precedes plan-archived per validation order)
    if not _has_complete_carts(a["id"]):
        raise err("ERR_CARTS_INCOMPLETE", "Account needs an ACTIVE TRASH and RECYCLING cart.")
    # priority 9: plan must not be archived
    plan = db.service_plans.get(a["plan_id"])
    if plan is None or plan["archived"]:
        raise err("ERR_PLAN_ARCHIVED", "Account's plan is archived.")

    a["status"] = "ACTIVE"
    from util import format_date
    a["service_start_date"] = format_date(clock.today_date())
    zone = db.collection_zones[a["zone_id"]]
    generate_schedule_rows(a, zone)
    touch(a)
    return ok(account_out(a))


@bp.route("/accounts/<aid>/suspend", methods=["POST"])
def suspend(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE.")
    a["status"] = "SUSPENDED"
    cancel_future_planned(a)
    touch(a)
    return ok(account_out(a))


@bp.route("/accounts/<aid>/resume", methods=["POST"])
def resume(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    if a["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Account is not SUSPENDED.")
    a["status"] = "ACTIVE"
    zone = db.collection_zones[a["zone_id"]]
    generate_schedule_rows(a, zone)
    touch(a)
    return ok(account_out(a))


def _expire_issued_credits(account_id):
    for c in db.missed_pickup_credits.values():
        if c["account_id"] == account_id and c["status"] == "ISSUED":
            c["status"] = "EXPIRED"
            touch(c)


def _remove_active_carts(account_id):
    from routes.carts import recompute_is_extra
    for c in db.cart_assignments.values():
        if c["account_id"] == account_id and c["status"] == "ACTIVE":
            c["status"] = "REMOVED"
            touch(c)
    recompute_is_extra(account_id)


@bp.route("/accounts/<aid>/stop", methods=["POST"])
def stop(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE or SUSPENDED.")
    a["status"] = "STOPPED"
    cancel_all_planned(a)
    _remove_active_carts(a["id"])
    _expire_issued_credits(a["id"])  # credit forfeited on stop
    touch(a)
    return ok(account_out(a))


@bp.route("/accounts/<aid>/transfer-out", methods=["POST"])
def transfer_out(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    body = V.get_body(request)

    # priority 4: body FK existence before well-formedness (PRD §2.6). Resolve
    # only present-and-string FK fields here.
    if isinstance(body.get("new_zone_id"), str):
        ref_or_404(db.collection_zones, body["new_zone_id"])
    if isinstance(body.get("new_plan_id"), str):
        ref_or_404(db.service_plans, body["new_plan_id"])

    # priority 5: body well-formedness (required fields present)
    expected_version = V.require_int(body, "expected_account_version")
    new_address = V.require_str(body, "new_service_address", non_empty=True)
    new_zone_id = V.require_str(body, "new_zone_id")
    new_plan_id = body.get("new_plan_id")
    if new_plan_id is not None and not isinstance(new_plan_id, str):
        raise err("ERR_INVALID_REQUEST", "new_plan_id must be a string.")

    # priority 6: OCC
    if expected_version != a["version"]:
        raise err("ERR_STALE_VERSION", "expected_account_version does not match.")
    # priority 7: state legality (transfer reachable only from ACTIVE)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE.")

    # destination plan = supplied new_plan_id or inherited source plan
    dest_plan_id = new_plan_id if new_plan_id is not None else a["plan_id"]
    dest_plan = db.service_plans.get(dest_plan_id)
    # priority 9: destination plan must not be archived
    if dest_plan is None or dest_plan["archived"]:
        raise err("ERR_PLAN_ARCHIVED", "Destination plan is archived.")
    # priority 10: new address uniqueness
    if _address_in_use(new_address):
        raise err("ERR_ADDRESS_IN_USE", "New service address is already in use.")

    # Mint destination account in PENDING_START.
    dest = new_record({
        "plan_id": dest_plan_id,
        "zone_id": new_zone_id,
        "service_address": new_address,
        "holder_name": a["holder_name"],
        "status": "PENDING_START",
        "billing_status": "CURRENT",
        "autopay_enabled": a["autopay_enabled"],
        "stored_payment_token": a["stored_payment_token"],
        "service_start_date": None,
        "transferred_from_account_id": a["id"],
    })
    db.service_accounts[dest["id"]] = dest

    # Migrate ISSUED credits (re-point account_id; credit survives the move).
    for c in db.missed_pickup_credits.values():
        if c["account_id"] == a["id"] and c["status"] == "ISSUED":
            c["account_id"] = dest["id"]
            touch(c)

    # Source: cancel PLANNED schedules, remove ACTIVE carts.
    cancel_all_planned(a)
    _remove_active_carts(a["id"])

    a["status"] = "TRANSFERRED_OUT"
    touch(a)

    # Endpoint returns the new (destination) account with 201.
    return ok(account_out(dest), 201)
