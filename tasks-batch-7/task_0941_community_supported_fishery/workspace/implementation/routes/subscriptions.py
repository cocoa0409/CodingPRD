"""Subscriptions and the two payment bases (PRD 3.2)."""
from flask import Blueprint, request

import authz
import calc
import cascades
import constants as C
import guards
import lookup
import store
import validate as V
from errors import ApiError
from routes.common import created, filter_eq, listing, ok, ok_raw, always

bp = Blueprint("subscriptions", __name__)

ACTIVE_LIFECYCLES = ("PENDING", "WAITLISTED", "ACTIVE", "PAUSED", "PAST_DUE")


@bp.post("/subscriptions")
def create_subscription():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "member_id", "share_plan_id", "season_id", "fulfillment_mode",
              "payment_basis", "join_week_index")                        # rung 4
    mode = V.enum_field(body["fulfillment_mode"], C.FULFILLMENT_MODES,
                        "fulfillment_mode")
    basis = V.enum_field(body["payment_basis"], C.PAYMENT_BASES, "payment_basis")  # rung 5
    V.id_field(body["member_id"], "member_id")
    V.id_field(body["share_plan_id"], "share_plan_id")
    V.id_field(body["season_id"], "season_id")
    join_week = V.int_field(body["join_week_index"], "join_week_index", minimum=1)  # rung 6
    season_peek = lookup.maybe("Season", body["season_id"])
    if season_peek is not None and join_week > season_peek["total_weeks"]:
        raise ApiError("ERR_VALIDATION",
                       "Field 'join_week_index' must be at most the season's total_weeks.")
    waitlisted = body.get("waitlist_requested")
    waitlisted = False if waitlisted is None else \
        V.bool_field(waitlisted, "waitlist_requested")
    hub_id = body.get("pickup_hub_id")
    zone_id = body.get("delivery_zone_id")
    renewed_id = body.get("renewed_from_subscription_id")

    season = lookup.season(body["season_id"])                            # rung 7
    plan = lookup.share_plan(body["share_plan_id"])                      # rung 8
    hub = lookup.pickup_hub(hub_id) if hub_id is not None else None      # rung 8
    zone = lookup.delivery_zone(zone_id) if zone_id is not None else None  # rung 8
    member = lookup.member(body["member_id"])                            # rung 9
    renewed = lookup.subscription(renewed_id) if renewed_id is not None else None  # rung 10

    # rung 23 -- the referential agreements of PRD 2.8
    if mode == "HUB_PICKUP":
        guards.reference(hub is not None and zone is None,
                         "A HUB_PICKUP subscription supplies pickup_hub_id and no delivery_zone_id.")
    else:
        guards.reference(zone is not None and hub is None,
                         "A HOME_DELIVERY subscription supplies delivery_zone_id and no pickup_hub_id.")
        guards.reference(zone["is_serviceable"] is True,
                         "The named delivery zone is not serviceable.")
    guards.reference(plan["season_id"] == season["id"],
                     "The plan must belong to the subscription's season.")

    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.member_not_restricted(member)                                 # rung 26
    guards.unique("Subscription",
                  lambda s: s["member_id"] == member["id"]
                  and s["season_id"] == season["id"]
                  and s["lifecycle_status"] in ACTIVE_LIFECYCLES)        # rung 53

    weeks = calc.delivery_week_set(join_week, season["total_weeks"],
                                   plan["delivery_frequency"])
    promised = len(weeks)
    # Adjudication of friction 2: promised_delivery_count and commitment_cents
    # are written at CREATION, not at activation.  PRD 3.2 says "Creation is
    # also where the season commitment is priced", and the installment
    # commitment is defined as the unit price times "the number of deliveries
    # promised from the join week onward" -- so promised_delivery_count must
    # already exist at creation for commitment_cents to be computable at all.
    # Activation then "records promised_delivery_count as the number of rows it
    # created", which re-states the same number; both sentences stay true.
    ppd, commitment = calc.subscription_commitment_total(
        plan["price_per_delivery_cents"], basis, promised,
        plan["scheduled_delivery_count"])

    paid = 0
    if renewed is not None:
        paid = renewed["rollover_credit_cents"]

    rec = store.create("Subscription", {
        "member_id": member["id"], "share_plan_id": plan["id"],
        "season_id": season["id"],
        "pickup_hub_id": hub["id"] if hub is not None else None,
        "delivery_zone_id": zone["id"] if zone is not None else None,
        "renewed_from_subscription_id": renewed["id"] if renewed is not None else None,
        "fulfillment_mode": mode, "payment_basis": basis,
        "join_week_index": join_week,
        "lifecycle_status": "WAITLISTED" if waitlisted else "PENDING",
        "billing_status": "UNBILLED", "commitment_cents": commitment,
        "price_per_delivery_cents": ppd, "promised_delivery_count": promised,
        "delivered_count": 0, "credited_count": 0, "skip_credited_count": 0,
        "undelivered_count": 0, "member_fault_count": 0, "skip_count": 0,
        "skip_credit_balance_cents": 0, "paid_cents": paid,
        "rollover_credit_cents": 0, "expired_credit_cents": 0,
        "true_up_status": "NOT_DUE", "true_up_amount_cents": 0,
    })
    return created(rec)


@bp.get("/subscriptions/<sid>")
def read_subscription(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    sub = lookup.subscription(sid)
    authz.own_member(sub["member_id"])                                   # rung 22
    return ok(sub)


@bp.get("/subscriptions")
def list_subscriptions():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    a = request.args
    pred = filter_eq(a, "member_id", lambda r: r["member_id"], always)
    pred = filter_eq(a, "share_plan_id", lambda r: r["share_plan_id"], pred)
    pred = filter_eq(a, "season_id", lambda r: r["season_id"], pred)
    pred = filter_eq(a, "pickup_hub_id", lambda r: r["pickup_hub_id"], pred)
    pred = filter_eq(a, "delivery_zone_id", lambda r: r["delivery_zone_id"], pred)
    pred = filter_eq(a, "renewed_from_subscription_id",
                     lambda r: r["renewed_from_subscription_id"], pred)
    pred = filter_eq(a, "lifecycle_status", lambda r: r["lifecycle_status"], pred)
    return listing("Subscription", a, pred)


@bp.post("/subscriptions/<sid>/activate")
def activate(sid):
    authz.require_roles(C.ROLE_ADMIN)
    sub = lookup.subscription(sid)                                       # rung 10
    season = lookup.maybe("Season", sub["season_id"])
    member = lookup.member_of_subscription(sub)
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.member_not_restricted(member)                                 # rung 26
    guards.state_in(sub["lifecycle_status"], ("PENDING",))               # rung 28
    guards.paid_in_full(sub)                                             # rung 30

    plan = lookup.plan_of_subscription(sub)
    weeks = calc.delivery_week_set(sub["join_week_index"], season["total_weeks"],
                                   plan["delivery_frequency"])
    for week in weeks:
        store.create("ShareDelivery", {
            "subscription_id": sub["id"], "season_id": season["id"],
            "landing_lot_id": None, "sub_lot_id": None, "pickup_window_id": None,
            "week_index": week,
            "scheduled_at": calc.scheduled_at_for_week(season["start_date"], week),
            "allocated_pounds": calc.ZERO_LB, "substituted_pounds": calc.ZERO_LB,
            "box_pounds": calc.ZERO_LB, "pack_size": "NONE", "gel_pack_count": 0,
            "subtotal_cents": 0, "surcharge_cents": 0, "delivery_fee_cents": 0,
            "invoice_total_cents": 0, "charged_cents": 0, "credit_cents": 0,
            "fill_status": "PENDING", "fulfillment_status": "SCHEDULED",
            "billing_status": "PENDING",
        })
    sub["promised_delivery_count"] = len(weeks)
    sub["lifecycle_status"] = "ACTIVE"
    sub["billing_status"] = "PREPAID_SETTLED" \
        if sub["payment_basis"] == "PREPAID_FULL_SEASON" else "CURRENT"
    store.touch(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/pause")
def pause(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    sub = lookup.subscription(sid)
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", sub["season_id"]))   # rung 24
    guards.state_in(sub["lifecycle_status"], ("ACTIVE",))                # rung 28
    # PRD 3.2: pausing "makes every one of its SCHEDULED deliveries ...
    # ineligible for catch allocation"; allocation eligibility already reads
    # lifecycle_status == ACTIVE, so the pause itself is the whole side effect.
    sub["lifecycle_status"] = "PAUSED"
    store.touch(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/resume")
def resume(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    sub = lookup.subscription(sid)
    authz.own_member(sub["member_id"])                                   # rung 22
    season = lookup.maybe("Season", sub["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.member_not_restricted(lookup.member_of_subscription(sub))     # rung 26
    guards.state_in(sub["lifecycle_status"], ("PAUSED",))                # rung 28
    sub["lifecycle_status"] = "ACTIVE"
    store.touch(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/cancel")
def cancel(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    sub = lookup.subscription(sid)
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", sub["season_id"]))   # rung 24
    guards.state_in(sub["lifecycle_status"], ("ACTIVE", "PAUSED", "PAST_DUE"))  # rung 28
    for delivery in cascades.deliveries_of_subscription(sub):
        if delivery["fulfillment_status"] != "SCHEDULED":
            continue
        delivery["fulfillment_status"] = "VOIDED"
        delivery["fill_status"] = "VOID"
        store.touch(delivery)
    sub["lifecycle_status"] = "CANCELLED"
    sub["billing_status"] = "SETTLED"
    store.touch(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/payments")
def payments(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    body = V.body_of(request)
    V.require(body, "amount_cents")                                      # rung 4
    amount = V.cents_field(body["amount_cents"], "amount_cents")         # rung 6
    sub = lookup.subscription(sid)                                       # rung 10
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", sub["season_id"]))   # rung 24
    guards.state_in(sub["lifecycle_status"], ("PENDING", "ACTIVE", "PAST_DUE"))  # rung 28

    sub["paid_cents"] = sub["paid_cents"] + amount
    if sub["lifecycle_status"] == "PAST_DUE" and \
            sub["paid_cents"] >= cascades.cumulative_charged(sub):
        sub["lifecycle_status"] = "ACTIVE"
        if sub["billing_status"] == "DUNNING":
            sub["billing_status"] = "CURRENT"
    store.touch(sub)
    return ok(sub)


@bp.get("/subscriptions/<sid>/ledger")
def ledger(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    sub = lookup.subscription(sid)
    authz.own_member(sub["member_id"])                                   # rung 22
    return ok_raw({
        "promised_delivery_count": sub["promised_delivery_count"],
        "delivered_count": sub["delivered_count"],
        "credited_count": sub["credited_count"],
        "member_fault_count": sub["member_fault_count"],
        "skip_credited_count": sub["skip_credited_count"],
        "undelivered_count": sub["undelivered_count"],
        "skip_credit_balance_cents": sub["skip_credit_balance_cents"],
        "expired_credit_cents": sub["expired_credit_cents"],
        "commitment_cents": sub["commitment_cents"],
        "paid_cents": sub["paid_cents"],
        "rollover_credit_cents": sub["rollover_credit_cents"],
        "true_up_amount_cents": sub["true_up_amount_cents"],
    })
