"""CashOut endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.calculations import compute_cashout_fee, cashout_minimum_for
from services.claims import (
    reserve_available_claims,
    settle_claims_paid,
    revert_claims_available,
)
from services.ledger import emit_ledger
from services.referrals import maybe_qualify_referrals_for
from services.serialize import cashout_out
from services.wallet import net_cashoutable
from state import store
from validation import get_json_body, require_int, require_enum

bp = Blueprint("cashouts", __name__)


@bp.route("/cashouts", methods=["POST"])
def create_cashout():
    user_id, role = get_identity()
    require_roles(role, ["Member"])
    body = get_json_body()

    member_id = body.get("member_id")
    if member_id is None:
        raise err("ERR_VALIDATION", "Missing required field: member_id")
    # Body-FK resolution (priority 4).
    if not isinstance(member_id, str) or member_id not in store.members:
        raise err("ERR_REFERENCE_NOT_FOUND", "member_id does not resolve.")

    # Ownership (authz): a Member may only cash out their own wallet.
    if not member_owns(user_id, member_id):
        raise err("ERR_FORBIDDEN", "A member may only cash out their own wallet.")

    # Shape (priority 5).
    method = require_enum(body, "method", {"PAYPAL", "CHECK", "GIFT_CARD"})
    requested_amount_cents = require_int(body, "requested_amount_cents", minimum=1)
    expected_member_version = require_int(body, "expected_member_version")

    member = store.members[member_id]

    # OCC (priority 7).
    if expected_member_version != member["version"]:
        raise err("ERR_STALE_VERSION", "expected_member_version is stale.")

    # Member suspended (priority 11).
    if member["account_status"] == "SUSPENDED":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended.")

    # Threshold (priority 14): below per-method minimum.
    minimum = cashout_minimum_for(method)
    if requested_amount_cents < minimum:
        raise err("ERR_BELOW_CASHOUT_MINIMUM", "Below the per-method minimum.")

    # Threshold (priority 15): exceeds net_cashoutable_cents.
    if requested_amount_cents > net_cashoutable(store, member_id):
        raise err("ERR_INSUFFICIENT_BALANCE", "Exceeds net cashoutable balance.")

    fee_cents, net_payout_cents = compute_cashout_fee(method, requested_amount_cents)

    c = base_common_fields(store, full=True)
    c.update({
        "member_id": member_id,
        "method": method,
        "requested_amount_cents": requested_amount_cents,
        "fee_cents": fee_cents,
        "net_payout_cents": net_payout_cents,
        "status": "REQUESTED",
        "expected_member_version": expected_member_version,
    })

    # Reserve AVAILABLE claims (oldest created_at first) up to requested amount.
    reserved = reserve_available_claims(store, member_id, c["id"], requested_amount_cents)
    if reserved is None:
        raise err("ERR_CASHOUT_NOT_RESERVABLE",
                  "No available claims sum to the requested amount.")

    store.cashouts[c["id"]] = c
    # Member.version increments by 1 on cash-out creation (OCC anchor).
    touch(store, member)

    return object_response(store.clock, cashout_out(store, c), status=201)


@bp.route("/cashouts/<cid>", methods=["GET"])
def get_cashout(cid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    c = store.cashouts.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Cash-out not found.")
    if role == "Member" and not member_owns(user_id, c["member_id"]):
        raise err("ERR_FORBIDDEN", "A member may only read their own cash-outs.")
    return object_response(store.clock, cashout_out(store, c))


@bp.route("/cashouts", methods=["GET"])
def list_cashouts():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    items = list(store.cashouts.values())
    if role == "Member":
        items = [c for c in items if c["member_id"] == user_id]
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    method = request.args.get("method")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if method is not None:
        items = [c for c in items if c["method"] == method]
    return list_response(items, cashout_out)


@bp.route("/cashouts/<cid>/process", methods=["POST"])
def process_cashout(cid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    c = store.cashouts.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Cash-out not found.")
    if c["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Cash-out is not in REQUESTED state.")
    member = store.members[c["member_id"]]
    if member["account_status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended.")
    if member["verification_status"] != "VERIFIED":
        raise err("ERR_MEMBER_NOT_VERIFIED", "Member is not verified.")
    c["status"] = "PROCESSING"
    touch(store, c)
    return object_response(store.clock, cashout_out(store, c))


@bp.route("/cashouts/<cid>/settle", methods=["POST"])
def settle_cashout(cid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    c = store.cashouts.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Cash-out not found.")
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"PAID", "FAILED"})
    if c["status"] != "PROCESSING":
        raise err("ERR_INVALID_STATE", "Cash-out is not in PROCESSING state.")

    member = store.members[c["member_id"]]
    if outcome == "PAID":
        c["status"] = "PAID"
        touch(store, c)
        emit_ledger(store, c["member_id"], "CASHOUT_DEBIT",
                    -c["requested_amount_cents"], cashout_id=c["id"])
        settle_claims_paid(store, c)
        # A now-PAID claim may push the member's cumulative qualifying total over a
        # referral threshold.
        maybe_qualify_referrals_for(store, c["member_id"])
    else:  # FAILED
        c["status"] = "FAILED"
        touch(store, c)
        revert_claims_available(store, c)
    return object_response(store.clock, cashout_out(store, c))


@bp.route("/cashouts/<cid>/retry", methods=["POST"])
def retry_cashout(cid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    c = store.cashouts.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Cash-out not found.")
    if c["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Cash-out is not in FAILED state.")
    member = store.members[c["member_id"]]
    if net_cashoutable(store, c["member_id"]) < c["requested_amount_cents"]:
        raise err("ERR_INSUFFICIENT_BALANCE", "Insufficient balance to retry.")
    reserved = reserve_available_claims(store, c["member_id"], c["id"],
                                        c["requested_amount_cents"])
    if reserved is None:
        raise err("ERR_CASHOUT_NOT_RESERVABLE",
                  "No available claims sum to the requested amount.")
    c["status"] = "REQUESTED"
    touch(store, c)
    return object_response(store.clock, cashout_out(store, c))
