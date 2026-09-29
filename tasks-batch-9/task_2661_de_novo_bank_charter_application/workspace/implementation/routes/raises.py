"""Capital raise, subscription and escrow writes."""
from flask import Blueprint

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate
from routes.helpers import must_get

bp = Blueprint("raises", __name__)

FUNDING_EVENTS = ("FUND", "REFUND")
SCREENING_OUTCOMES = ("SCREENING", "CLEARED", "REJECTED")
SCREENING_SOURCES = {
    "SCREENING": ("UNSCREENED",),
    "CLEARED": ("UNSCREENED", "SCREENING"),
    "REJECTED": ("UNSCREENED", "SCREENING", "CLEARED"),
}


@bp.post("/de-novo/capital-raises")
def create_raise():
    authenticate(("CharterCounsel",))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    target_gross = v.req_int(data, "target_gross_cents", 1, None)
    minimum_gross = v.req_int(data, "minimum_gross_cents", 1, None)
    price = v.req_int(data, "offering_price_cents_per_share", 1, None)
    max_shares = v.req_int(data, "max_shares", 1, None)
    expense_claim = v.req_int(data, "organizational_expense_claim_cents", 0, None)
    group = must_get("groups", group_id)
    if group["stage"] in ("OPEN", "ABANDONED"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    if calc.raise_in(group["id"], ("STRUCTURING", "OPEN", "ESCROW_LOCKED")) is not None:
        raise err("ERR_ACTIVE_CAPITAL_RAISE_EXISTS")
    if minimum_gross > target_gross:
        raise err("ERR_MINIMUM_EXCEEDS_TARGET")
    if max_shares * price < target_gross:
        raise err("ERR_OFFERING_CAPACITY_BELOW_TARGET")
    raise_row = db.insert("raises", {
        "group_id": group["id"],
        "status": "STRUCTURING",
        "target_gross_cents": target_gross,
        "minimum_gross_cents": minimum_gross,
        "offering_price_cents_per_share": price,
        "max_shares": max_shares,
        "organizational_expense_claim_cents": expense_claim,
        "subscribed_shares": 0,
        "pledged_gross_cents": 0,
        "funded_gross_cents": 0,
        "cleared_escrow_cents": 0,
        "projected_reimbursement_cents": 0,
        "projected_net_release_cents": 0,
        "released_net_cents": 0,
        "refunded_gross_cents": 0,
    })
    calc.recompute_raise(raise_row)
    db.touch(group)
    db.commit()
    return response.object_response(serialize.capital_raise(raise_row), 201)


@bp.post("/de-novo/capital-raises/<raise_id>/open")
def open_raise(raise_id):
    authenticate(("CharterCounsel",))
    v.body()
    raise_row = must_get("raises", raise_id)
    if raise_row["status"] != "STRUCTURING":
        raise err("ERR_RAISE_NOT_OPENABLE")
    group = db.get("groups", raise_row["group_id"])
    if group is None or group["stage"] not in (
            "ORGANIZING", "FILING_READY", "UNDER_REVIEW", "CONDITIONALLY_APPROVED"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    raise_row["status"] = "OPEN"
    db.touch(raise_row)
    db.commit()
    return response.object_response(serialize.capital_raise(raise_row))


@bp.post("/de-novo/capital-raises/<raise_id>/lock-escrow")
def lock_escrow(raise_id):
    authenticate(("EscrowAgent",))
    v.body()
    raise_row = must_get("raises", raise_id)
    if raise_row["status"] != "OPEN":
        raise err("ERR_RAISE_NOT_LOCKABLE")
    if calc.cleared_subscription_count(raise_row) < 1:
        raise err("ERR_NO_CLEARED_SUBSCRIPTIONS")
    if raise_row["cleared_escrow_cents"] < raise_row["minimum_gross_cents"]:
        raise err("ERR_ESCROW_BELOW_MINIMUM")
    calc.recompute_raise(raise_row)
    raise_row["status"] = "ESCROW_LOCKED"
    db.touch(raise_row)
    db.commit()
    return response.object_response(serialize.capital_raise(raise_row))


@bp.post("/de-novo/capital-raises/<raise_id>/release-escrow")
def release_escrow(raise_id):
    authenticate(("EscrowAgent",))
    v.body()
    raise_row = must_get("raises", raise_id)
    if raise_row["status"] != "ESCROW_LOCKED":
        raise err("ERR_ESCROW_NOT_LOCKED")
    group = db.get("groups", raise_row["group_id"])
    if group is None or group["stage"] != "PRE_OPENING":
        raise err("ERR_GROUP_NOT_IN_PRE_OPENING")
    filings = calc.filings_of(group["id"])
    cleared = [f for f in filings if f["pre_opening_clearance"]]
    if len(cleared) != 2:
        raise err("ERR_PRE_OPENING_CONDITIONS_OPEN")
    calc.recompute_raise(raise_row)
    chartering = calc.filing_by_authority(group["id"], "CHARTERING_AUTHORITY")
    pinned_plan = None
    if chartering is not None:
        pinned_plan = db.get("plans", chartering["pinned_business_plan_id"])
    required = pinned_plan["opening_tier1_capital_cents"] if pinned_plan is not None else 0
    if raise_row["projected_net_release_cents"] < required:
        raise err("ERR_NET_RELEASE_BELOW_PLAN_CAPITAL")
    raise_row["released_net_cents"] = raise_row["projected_net_release_cents"]
    raise_row["status"] = "RELEASED"
    db.touch(raise_row)
    db.commit()
    return response.object_response(serialize.capital_raise(raise_row))


@bp.post("/de-novo/subscriptions")
def create_subscription():
    authenticate(("EscrowAgent",))
    data = v.body()
    raise_id = v.req_id(data, "capital_raise_id")
    subscriber_name = v.req_str(data, "subscriber_name", 1, 120)
    shares = v.req_int(data, "shares", 1, None)
    organizer_id = v.opt_id(data, "organizer_id")
    raise_row = must_get("raises", raise_id)
    organizer = None
    if organizer_id is not None:
        organizer = must_get("organizers", organizer_id)
    if raise_row["status"] != "OPEN":
        raise err("ERR_RAISE_NOT_OPEN")
    if organizer is not None and organizer["group_id"] != raise_row["group_id"]:
        raise err("ERR_SUBSCRIBER_ORGANIZER_MISMATCH")
    if raise_row["subscribed_shares"] + shares > raise_row["max_shares"]:
        raise err("ERR_OFFERING_OVERSUBSCRIBED")
    subscription = db.insert("subscriptions", {
        "capital_raise_id": raise_row["id"],
        "organizer_id": organizer_id,
        "subscriber_name": subscriber_name,
        "shares": shares,
        # amount_cents is frozen from the raise's price at creation (PRD 106).
        "amount_cents": shares * raise_row["offering_price_cents_per_share"],
        "funding_state": "PLEDGED",
        "clearance_state": "UNSCREENED",
        "counts_toward_escrow": False,
    })
    calc.recompute_raise(raise_row)
    db.touch(raise_row)
    db.commit()
    return response.object_response(serialize.subscription(subscription), 201)


@bp.post("/de-novo/subscriptions/<subscription_id>/funding")
def subscription_funding(subscription_id):
    authenticate(("EscrowAgent",))
    data = v.body()
    funding_event = v.req_enum(data, "funding_event", FUNDING_EVENTS)
    subscription = must_get("subscriptions", subscription_id)
    raise_row = db.get("raises", subscription["capital_raise_id"])
    if funding_event == "FUND":
        if subscription["funding_state"] != "PLEDGED":
            raise err("ERR_FUNDING_TRANSITION_NOT_ALLOWED")
        if raise_row is None or raise_row["status"] != "OPEN":
            raise err("ERR_RAISE_NOT_OPEN")
        subscription["funding_state"] = "FUNDED"
    else:
        if subscription["funding_state"] != "FUNDED":
            raise err("ERR_FUNDING_TRANSITION_NOT_ALLOWED")
        if raise_row is not None and raise_row["status"] == "RELEASED":
            raise err("ERR_ESCROW_ALREADY_RELEASED")
        if raise_row is None or raise_row["status"] not in ("OPEN", "ESCROW_LOCKED"):
            raise err("ERR_RAISE_NOT_OPEN")
        subscription["funding_state"] = "REFUNDED"
    db.touch(subscription)
    if raise_row is not None:
        calc.recompute_raise(raise_row)
        db.touch(raise_row)
        cascade.raise_shortfall_cascade(raise_row)
    db.commit()
    return response.object_response(serialize.subscription(subscription))


@bp.post("/de-novo/subscriptions/<subscription_id>/screening-result")
def subscription_screening(subscription_id):
    authenticate(("EscrowAgent",))
    data = v.body()
    outcome = v.req_enum(data, "outcome", SCREENING_OUTCOMES)
    subscription = must_get("subscriptions", subscription_id)
    raise_row = db.get("raises", subscription["capital_raise_id"])
    if subscription["clearance_state"] not in SCREENING_SOURCES[outcome]:
        raise err("ERR_SCREENING_TRANSITION_NOT_ALLOWED")
    if outcome == "REJECTED" and raise_row is not None and raise_row["status"] == "RELEASED":
        raise err("ERR_ESCROW_ALREADY_RELEASED")
    subscription["clearance_state"] = outcome
    if outcome == "REJECTED" and subscription["funding_state"] == "FUNDED":
        # PRD 228: a rejected investor's money goes back in the same operation.
        subscription["funding_state"] = "REFUNDED"
    db.touch(subscription)
    if raise_row is not None:
        calc.recompute_raise(raise_row)
        db.touch(raise_row)
        cascade.raise_shortfall_cascade(raise_row)
    db.commit()
    return response.object_response(serialize.subscription(subscription))
