"""Capital call contributions: escrow receipts and releases (PRD 3.4)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, INVESTOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_contribution
from services.domain import (
    touch, sorted_items, call_contributions, unfreeze_accrual,
)
from util import CLOCK, fmt_dt, parse_dt
from validate import get_body, req_int, pagination, apply_filters

bp = Blueprint("contributions", __name__)
RS = {"strict_slashes": False}


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/contributions",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_contributions(caller, syndicationId, offeringId, capitalCallId):
    resolve.capital_call(syndicationId, offeringId, capitalCallId)
    limit, offset = pagination()
    items = [c for c in db["contributions"].values() if c["capital_call_id"] == capitalCallId]
    items = apply_filters(sorted_items(items),
                          {"status": "status", "subscription_id": "subscription_id"})
    page = items[offset:offset + limit]
    return success_list([ser_contribution(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/contributions/<contributionId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_contribution(caller, syndicationId, offeringId, capitalCallId, contributionId):
    return success_object(ser_contribution(
        resolve.contribution(syndicationId, offeringId, capitalCallId, contributionId)))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/contributions/<contributionId>/receive-escrow",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def receive_escrow(caller, syndicationId, offeringId, capitalCallId, contributionId):
    contrib = resolve.contribution(syndicationId, offeringId, capitalCallId, contributionId)
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=1)
    # DEFAULTED is admitted here so a late wire reaches the domain guards:
    # PRD 3.4 rejects "a receipt arriving after the call's due_date" with
    # ERR_ESCROW_PAST_DUE, and PRD 2.9's example has an investor who "wires
    # too much money after the due date" hear about the overpayment first —
    # both presuppose the wire is answered by the domain guards, not the
    # state guard. A DEFAULTED contribution can never actually receive funds:
    # default requires the due date to have passed, so every wire on it is
    # late and is rejected by the timeliness guard (or the overpayment guard
    # first). RELEASED stays rejected by the state guard.
    if contrib["status"] not in ("PENDING", "ESCROW_RECEIVED", "DEFAULTED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot receive escrow for a contribution in status {contrib['status']}")
    sub = db["subscriptions"].get(contrib["subscription_id"])
    if sub is None or caller.user_id != sub["investor_id"]:
        raise_error("ERR_NOT_YOUR_CONTRIBUTION",
                    "an investor may only fund its own contribution")
    # Overpayment is evaluated before the past-due guard (PRD 2.9).
    if contrib["amount_received_cents"] + amount > contrib["amount_due_cents"]:
        raise_error("ERR_ESCROW_OVERPAYMENT",
                    "receipt would exceed the contribution's amount_due_cents")
    call = db["capital_calls"][contrib["capital_call_id"]]
    if CLOCK.now() > parse_dt(call["due_date"]):
        raise_error("ERR_ESCROW_PAST_DUE", "the capital call's due date has passed")
    contrib["amount_received_cents"] += amount
    contrib["received_at"] = fmt_dt(CLOCK.now())
    if contrib["status"] == "PENDING":
        contrib["status"] = "ESCROW_RECEIVED"
    touch(contrib)
    # Bubble: ISSUED -> PARTIALLY_FUNDED when this receipt lands while at least
    # one sibling is still PENDING or received-but-not-yet-released.
    if call["status"] == "ISSUED":
        others = [x for x in call_contributions(call["id"]) if x["id"] != contrib["id"]]
        if any(x["status"] in ("PENDING", "ESCROW_RECEIVED") for x in others):
            call["status"] = "PARTIALLY_FUNDED"
            touch(call)
    return success_object(ser_contribution(contrib))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/contributions/<contributionId>/release-escrow",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def release_escrow(caller, syndicationId, offeringId, capitalCallId, contributionId):
    off = resolve.offering(syndicationId, offeringId)
    contrib = resolve.contribution(syndicationId, offeringId, capitalCallId, contributionId)
    if contrib["status"] != "ESCROW_RECEIVED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot release a contribution in status {contrib['status']}")
    call = db["capital_calls"][contrib["capital_call_id"]]
    if call["status"] not in ("ISSUED", "PARTIALLY_FUNDED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot release escrow on a call in status {call['status']}")
    if contrib["amount_received_cents"] != contrib["amount_due_cents"]:
        raise_error("ERR_ESCROW_INCOMPLETE",
                    "escrow release requires amount_received_cents == amount_due_cents")
    released = contrib["amount_received_cents"]
    contrib["status"] = "RELEASED"
    touch(contrib)
    call["escrow_released_cents"] += released
    sub = db["subscriptions"].get(contrib["subscription_id"])
    if sub is not None:
        sub["funded_cents"] += released
        sub["unreturned_capital_cents"] += released
        if sub["status"] == "AWAITING_FUNDING":
            sub["status"] = "FUNDED"
            sub["funded_at"] = fmt_dt(CLOCK.now())
            unfreeze_accrual(sub)
        touch(sub)
    # Bubble: every contribution RELEASED -> the call is FULLY_FUNDED.
    if all(x["status"] == "RELEASED" for x in call_contributions(call["id"])):
        call["status"] = "FULLY_FUNDED"
    touch(call)
    return success_object(ser_contribution(contrib))
