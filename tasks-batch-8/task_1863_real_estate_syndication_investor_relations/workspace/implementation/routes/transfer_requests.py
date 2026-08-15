"""Transfer requests: sponsor gate, agent gate, settlement with carryover (PRD 3.9)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, AGENT, INVESTOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_transfer_request
from services import domain
from services.calculations import transfer_carryover
from services.domain import stamp_new, touch, sorted_items, ONBOARDED_STATES
from util import CLOCK, fmt_dt
from validate import (
    get_body, req_int, req_str, req_version, pagination, apply_filters,
)

bp = Blueprint("transfer_requests", __name__)
RS = {"strict_slashes": False}


def _visible_subscription_or_404(caller, sub):
    if caller.role == INVESTOR and sub["investor_id"] != caller.user_id:
        raise_error("ERR_SUBSCRIPTION_NOT_FOUND", f"subscription not found: {sub['id']}")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def create_transfer(caller, syndicationId, offeringId, subscriptionId):
    off = resolve.offering(syndicationId, offeringId)
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    body = get_body()
    to_investor_id = req_str(body, "to_investor_id")
    transfer_cents = req_int(body, "transfer_cents")
    if db["investors"].get(to_investor_id) is None:
        raise_error("ERR_INVESTOR_NOT_FOUND", f"investor not found: {to_investor_id}")
    if caller.user_id != sub["investor_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only initiate transfers from its own subscription")
    # OCC guard (PRD 2.7): the initiator's observed subscription version.
    req_version(body, "expected_subscription_version", sub["version"],
                "ERR_STALE_SUBSCRIPTION_VERSION")
    if off["status"] != "OPEN":
        raise_error("ERR_OFFERING_NOT_OPEN",
                    "offering must be OPEN for a new transfer request")
    t = {
        "from_subscription_id": subscriptionId,
        "to_investor_id": to_investor_id,
        "transfer_cents": transfer_cents,
        "status": "PENDING_SPONSOR_REVIEW",
        "settled_at": None,
    }
    stamp_new(t)
    db["transfer_requests"][t["id"]] = t
    # Creation marks the subscription as under-transfer: version bump.
    touch(sub)
    return success_object(ser_transfer_request(t), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_transfers(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    _visible_subscription_or_404(caller, sub)
    limit, offset = pagination()
    items = [t for t in db["transfer_requests"].values()
             if t["from_subscription_id"] == subscriptionId]
    items = apply_filters(sorted_items(items), {"status": "status"})
    page = items[offset:offset + limit]
    return success_list([ser_transfer_request(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_transfer(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    _visible_subscription_or_404(caller, sub)
    t = db["transfer_requests"].get(transferRequestId)
    if t is None or t["from_subscription_id"] != subscriptionId:
        raise_error("ERR_TRANSFER_REQUEST_NOT_FOUND",
                    f"transfer request not found: {transferRequestId}")
    return success_object(ser_transfer_request(t))


def _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off = resolve.offering(syndicationId, offeringId)
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    tr = resolve.transfer_request(syndicationId, offeringId, subscriptionId, transferRequestId)
    return off, sub, tr


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/sponsor-approve",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def sponsor_approve(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "PENDING_SPONSOR_REVIEW":
        raise_error("ERR_INVALID_STATE",
                    f"cannot sponsor-approve a transfer in status {tr['status']}")
    if sub["status"] != "FUNDED":
        raise_error("ERR_SUBSCRIPTION_NOT_FUNDED",
                    "source subscription must be FUNDED")
    if tr["transfer_cents"] <= 0 or tr["transfer_cents"] > sub["funded_cents"]:
        raise_error("ERR_TRANSFER_EXCEEDS_FUNDED",
                    "transfer_cents must be > 0 and <= the funded balance")
    tr["status"] = "PENDING_TRANSFER_AGENT"
    touch(tr)
    return success_object(ser_transfer_request(tr))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/sponsor-reject",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def sponsor_reject(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "PENDING_SPONSOR_REVIEW":
        raise_error("ERR_INVALID_STATE",
                    f"cannot sponsor-reject a transfer in status {tr['status']}")
    tr["status"] = "REJECTED"
    touch(tr)
    return success_object(ser_transfer_request(tr))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/agent-approve",
          methods=["POST"], **RS)
@endpoint(AGENT)
def agent_approve(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "PENDING_TRANSFER_AGENT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot agent-approve a transfer in status {tr['status']}")
    # Buyer must hold a separate ACCREDITATION_VERIFIED-or-later subscription here.
    buyer_onboarded = any(
        s["offering_id"] == offeringId and s["id"] != sub["id"]
        and s["investor_id"] == tr["to_investor_id"] and s["status"] in ONBOARDED_STATES
        for s in db["subscriptions"].values()
    )
    if not buyer_onboarded:
        raise_error("ERR_BUYER_NOT_ONBOARDED",
                    "buyer has no ACCREDITATION_VERIFIED-or-later subscription on this offering")
    if tr["to_investor_id"] == sub["investor_id"]:
        raise_error("ERR_SELF_TRANSFER", "buyer cannot equal the seller")
    tr["status"] = "APPROVED"
    touch(tr)
    return success_object(ser_transfer_request(tr))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/agent-reject",
          methods=["POST"], **RS)
@endpoint(AGENT)
def agent_reject(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "PENDING_TRANSFER_AGENT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot agent-reject a transfer in status {tr['status']}")
    tr["status"] = "REJECTED"
    touch(tr)
    return success_object(ser_transfer_request(tr))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/settle",
          methods=["POST"], **RS)
@endpoint(AGENT)
def settle_transfer(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot settle a transfer in status {tr['status']}")
    # The buyer's FUNDED subscription on this offering (earliest created).
    targets = sorted(
        (s for s in db["subscriptions"].values()
         if s["offering_id"] == offeringId and s["id"] != sub["id"]
         and s["investor_id"] == tr["to_investor_id"] and s["status"] == "FUNDED"),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    to_sub = targets[0] if targets else None
    if to_sub is None:
        raise_error("ERR_BUYER_NOT_ONBOARDED",
                    "buyer has no FUNDED subscription on this offering")
    t = tr["transfer_cents"]
    pre_funded = sub["funded_cents"]
    accrued_now = domain.current_accrued_pref(sub, off)
    carry_pref, carry_unret = transfer_carryover(
        pre_funded, t, accrued_now, sub["unreturned_capital_cents"])
    sub["funded_cents"] -= t
    sub["unreturned_capital_cents"] -= carry_unret
    sub["_pref_ledger"] = sub.get("_pref_ledger", 0) + carry_pref
    to_sub["funded_cents"] += t
    to_sub["unreturned_capital_cents"] += carry_unret
    to_sub["_pref_ledger"] = to_sub.get("_pref_ledger", 0) - carry_pref
    touch(to_sub)
    if sub["funded_cents"] == 0:
        domain.freeze_accrual(sub, off)
        sub["status"] = "WITHDRAWN"
    touch(sub)
    tr["status"] = "SETTLED"
    tr["settled_at"] = fmt_dt(CLOCK.now())
    touch(tr)
    return success_object(ser_transfer_request(tr))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/transfer-requests/<transferRequestId>/cancel",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def cancel_transfer(caller, syndicationId, offeringId, subscriptionId, transferRequestId):
    off, sub, tr = _load(caller, syndicationId, offeringId, subscriptionId, transferRequestId)
    if tr["status"] != "PENDING_SPONSOR_REVIEW":
        raise_error("ERR_INVALID_STATE",
                    f"cannot cancel a transfer in status {tr['status']}")
    if caller.user_id != sub["investor_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only cancel its own transfer request")
    tr["status"] = "CANCELLED"
    touch(tr)
    return success_object(ser_transfer_request(tr))
