"""Capital calls: create, issue (pro-rata synthesis), cancel (PRD 3.4)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_capital_call
from services.calculations import capital_call_prorata
from services.domain import stamp_new, touch, sorted_items, call_contributions
from validate import get_body, req_int, req_datetime, pagination, apply_filters

bp = Blueprint("capital_calls", __name__)
RS = {"strict_slashes": False}

ELIGIBLE_SUB_STATES = ("SUITABILITY_APPROVED", "AWAITING_FUNDING", "FUNDED")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_capital_call(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    body = get_body()
    c = {
        "offering_id": offeringId,
        "call_index": None,
        "total_call_cents": req_int(body, "total_call_cents", minimum=0),
        "due_date": req_datetime(body, "due_date"),
        "escrow_released_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(c)
    db["capital_calls"][c["id"]] = c
    return success_object(ser_capital_call(c), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_capital_calls(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    limit, offset = pagination()
    items = [c for c in db["capital_calls"].values() if c["offering_id"] == offeringId]
    items = apply_filters(sorted_items(items), {"status": "status"})
    page = items[offset:offset + limit]
    return success_list([ser_capital_call(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_capital_call(caller, syndicationId, offeringId, capitalCallId):
    return success_object(
        ser_capital_call(resolve.capital_call(syndicationId, offeringId, capitalCallId)))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/issue",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def issue_capital_call(caller, syndicationId, offeringId, capitalCallId):
    syn = resolve.syndication(syndicationId)
    off = resolve.offering(syndicationId, offeringId)
    call = resolve.capital_call(syndicationId, offeringId, capitalCallId)
    if call["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot issue a capital call in status {call['status']}")
    if syn["status"] != "ACTIVE":
        raise_error("ERR_SYNDICATION_NOT_ACTIVE",
                    "syndication must be ACTIVE to issue a capital call")
    if off["status"] not in ("OPEN", "CLOSED_TO_NEW_SUBSCRIPTIONS"):
        raise_error("ERR_OFFERING_NOT_ACCEPTING_CALLS",
                    "offering must be OPEN or CLOSED_TO_NEW_SUBSCRIPTIONS to issue a call")
    issued = [c for c in db["capital_calls"].values()
              if c["offering_id"] == offeringId and c.get("call_index") is not None]
    call["call_index"] = len(issued) + 1
    eligible = sorted(
        (s for s in db["subscriptions"].values()
         if s["offering_id"] == offeringId and s["status"] in ELIGIBLE_SUB_STATES),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    amounts = capital_call_prorata(call["total_call_cents"], [
        {"subscription_id": s["id"], "committed_cents": s["committed_cents"],
         "seq": s["_seq"]}
        for s in eligible
    ])
    for s in eligible:
        contrib = {
            "capital_call_id": call["id"],
            "subscription_id": s["id"],
            "amount_due_cents": amounts.get(s["id"], 0),
            "amount_received_cents": 0,
            "received_at": None,
            "status": "PENDING",
        }
        stamp_new(contrib)
        db["contributions"][contrib["id"]] = contrib
    call["status"] = "ISSUED"
    touch(call)
    return success_object(ser_capital_call(call))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/capital-calls/<capitalCallId>/cancel",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def cancel_capital_call(caller, syndicationId, offeringId, capitalCallId):
    call = resolve.capital_call(syndicationId, offeringId, capitalCallId)
    if call["status"] not in ("DRAFT", "ISSUED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot cancel a capital call in status {call['status']}")
    if call["escrow_released_cents"] != 0:
        raise_error("ERR_ESCROW_ALREADY_RELEASED",
                    "cannot cancel after escrow has been released")
    for contrib in call_contributions(call["id"]):
        if contrib["status"] in ("PENDING", "ESCROW_RECEIVED"):
            contrib["status"] = "DEFAULTED"
            touch(contrib)
    call["status"] = "CANCELLED"
    touch(call)
    return success_object(ser_capital_call(call))
