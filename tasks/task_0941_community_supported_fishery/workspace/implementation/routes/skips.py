"""Skips, share transfers and recalls (PRD 3.8, 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import authz
import calc
import cascades
import clock
import constants as C
import guards
import lookup
import store
import validate as V
from errors import ApiError
from routes.common import created, filter_eq, listing, ok, always

bp = Blueprint("skips", __name__)


# --------------------------------------------------------------------------
# Skip requests
# --------------------------------------------------------------------------
@bp.post("/skip-requests")
def create_skip():
    authz.require_roles(C.ROLE_MEMBER)
    body = V.body_of(request)
    V.require(body, "share_delivery_id")                                 # rung 4
    V.id_field(body["share_delivery_id"], "share_delivery_id")           # rung 6
    delivery = lookup.share_delivery(body["share_delivery_id"])          # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    season = lookup.maybe("Season", delivery["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.state_in(delivery["fulfillment_status"], ("SCHEDULED",))      # rung 28
    guards.subscription_active(sub)                                      # rung 29
    guards.skip_cap(sub)                                                 # rung 49

    cutoff = delivery["scheduled_at"] - timedelta(
        hours=season["landing_commit_lead_hours"])
    now = clock.now()
    if now <= cutoff:
        variant, credit, status = "CREDIT", sub["price_per_delivery_cents"], "CREDITED"
        sub["skip_credit_balance_cents"] = sub["skip_credit_balance_cents"] + credit
        sub["skip_credited_count"] = sub["skip_credited_count"] + 1
        delivery["billing_status"] = "CREDITED"
    else:
        variant, credit, status = "FORFEIT", 0, "FORFEITED"
        sub["member_fault_count"] = sub["member_fault_count"] + 1
        delivery["billing_status"] = "FORFEITED"
    sub["skip_count"] = sub["skip_count"] + 1
    store.touch(sub)
    delivery["fulfillment_status"] = "SKIPPED"
    store.touch(delivery)

    rec = store.create("SkipRequest", {
        "subscription_id": sub["id"], "share_delivery_id": delivery["id"],
        "week_index": delivery["week_index"], "requested_at": now,
        "cutoff_at": cutoff, "settlement_variant": variant,
        "credit_cents": credit, "status": status,
    })
    return created(rec)


@bp.get("/skip-requests/<sid>")
def read_skip(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    skip = lookup.skip_request(sid)                                      # rung 18
    sub = lookup.maybe("Subscription", skip["subscription_id"])
    authz.own_member(sub["member_id"])                                   # rung 22
    return ok(skip)


@bp.get("/skip-requests")
def list_skips():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    a = request.args
    pred = filter_eq(a, "subscription_id", lambda r: r["subscription_id"], always)
    pred = filter_eq(a, "share_delivery_id", lambda r: r["share_delivery_id"], pred)
    return listing("SkipRequest", a, pred)


@bp.post("/skip-requests/<sid>/revoke")
def revoke_skip(sid):
    authz.require_roles(C.ROLE_MEMBER)
    skip = lookup.skip_request(sid)                                      # rung 18
    sub = lookup.maybe("Subscription", skip["subscription_id"])
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", sub["season_id"]))   # rung 24
    guards.state_in(skip["status"], ("CREDITED",))                       # rung 28
    if clock.now() > skip["cutoff_at"]:                                  # rung 50
        raise ApiError("ERR_SKIP_WINDOW_CLOSED")

    sub["skip_credit_balance_cents"] = \
        sub["skip_credit_balance_cents"] - skip["credit_cents"]
    sub["skip_count"] = sub["skip_count"] - 1
    sub["skip_credited_count"] = sub["skip_credited_count"] - 1
    store.touch(sub)
    delivery = lookup.maybe("ShareDelivery", skip["share_delivery_id"])
    if delivery is not None:
        delivery["fulfillment_status"] = "SCHEDULED"
        delivery["billing_status"] = "PENDING"
        store.touch(delivery)
    skip["status"] = "REVOKED"
    store.touch(skip)
    return ok(skip)


# --------------------------------------------------------------------------
# Share transfers
# --------------------------------------------------------------------------
def _remaining_deliveries(from_sub, effective_week_index):
    return [d for d in cascades.deliveries_of_subscription(from_sub)
            if d["week_index"] >= effective_week_index
            and d["fulfillment_status"] == "SCHEDULED"]


@bp.post("/share-transfers")
def create_transfer():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    body = V.body_of(request)
    V.require(body, "from_subscription_id", "to_subscription_id", "season_id",
              "effective_week_index", "expected_subscription_version")   # rung 4
    V.id_field(body["from_subscription_id"], "from_subscription_id")
    V.id_field(body["to_subscription_id"], "to_subscription_id")
    V.id_field(body["season_id"], "season_id")
    week = V.int_field(body["effective_week_index"], "effective_week_index",
                       minimum=1)                                        # rung 6
    expected = V.int_field(body["expected_subscription_version"],
                           "expected_subscription_version", minimum=0)
    season_peek = lookup.maybe("Season", body["season_id"])
    if season_peek is not None and week > season_peek["total_weeks"]:
        raise ApiError("ERR_VALIDATION",
                       "Field 'effective_week_index' must be at most the season's total_weeks.")

    season = lookup.season(body["season_id"])                            # rung 7
    from_sub = lookup.subscription(body["from_subscription_id"])         # rung 10
    to_sub = lookup.subscription(body["to_subscription_id"])             # rung 10
    authz.own_member(from_sub["member_id"])                              # rung 22
    guards.reference(from_sub["season_id"] == season["id"]               # rung 23
                     and to_sub["season_id"] == season["id"],
                     "Both subscriptions of a transfer must belong to the named season.")
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.subscription_active(from_sub)                                 # rung 29
    guards.expected_version(expected, from_sub)                          # rung 31

    remaining = len(_remaining_deliveries(from_sub, week))
    guards.transfer_eligible(from_sub, to_sub, remaining)                # rung 51

    variant, fee, refund, charge = calc.transfer_settlement(
        remaining, from_sub["price_per_delivery_cents"], from_sub["payment_basis"])
    rec = store.create("ShareTransfer", {
        "from_subscription_id": from_sub["id"], "to_subscription_id": to_sub["id"],
        "season_id": season["id"], "remaining_delivery_count": remaining,
        "effective_week_index": week, "transfer_fee_cents": fee,
        "transferor_refund_cents": refund, "transferee_charge_cents": charge,
        "settlement_variant": variant, "status": "REQUESTED",
    })
    store.touch(from_sub)
    return created(rec)


@bp.get("/share-transfers/<tid>")
def read_transfer(tid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    transfer = lookup.share_transfer(tid)                                # rung 20
    from_sub = lookup.maybe("Subscription", transfer["from_subscription_id"])
    to_sub = lookup.maybe("Subscription", transfer["to_subscription_id"])
    authz.own_member_any([s["member_id"] for s in (from_sub, to_sub) if s])  # rung 22
    return ok(transfer)


@bp.get("/share-transfers")
def list_transfers():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    a = request.args
    pred = filter_eq(a, "from_subscription_id",
                     lambda r: r["from_subscription_id"], always)
    pred = filter_eq(a, "to_subscription_id", lambda r: r["to_subscription_id"], pred)
    pred = filter_eq(a, "season_id", lambda r: r["season_id"], pred)
    return listing("ShareTransfer", a, pred)


@bp.post("/share-transfers/<tid>/accept")
def accept_transfer(tid):
    authz.require_roles(C.ROLE_MEMBER)
    transfer = lookup.share_transfer(tid)                                # rung 20
    from_sub = lookup.maybe("Subscription", transfer["from_subscription_id"])
    to_sub = lookup.maybe("Subscription", transfer["to_subscription_id"])
    authz.own_member(to_sub["member_id"])                                # rung 22
    season = lookup.maybe("Season", transfer["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.state_in(transfer["status"], ("REQUESTED",))                  # rung 28
    moving = _remaining_deliveries(from_sub, transfer["effective_week_index"])
    guards.transfer_eligible(from_sub, to_sub, len(moving))              # rung 51

    # Adjudication of friction 3: the transferee's boxes are the RE-PARENTED
    # rows, not a second set created from scratch.  PRD 3.8 says in one sentence
    # that the transferor's SCHEDULED deliveries at or after effective_week_index
    # are "re-parented to the receiving subscription, and the receiving
    # subscription gets one share delivery for each delivery week from
    # effective_week_index onward" -- the second clause restates the first.
    # Creating rows as well would give the transferee two boxes for every week
    # and break INV_PROMISED_COUNT_PARTITION on the spot.
    #
    # Adjudication of friction 4: because nothing is newly created, no biweekly
    # parity is re-anchored.  The moved rows keep the week set the transferor's
    # own join_week_index produced; the transferee's join_week_index no longer
    # describes anything it will receive.  This follows directly from friction 3
    # and is the only reading under which remaining_delivery_count -- which the
    # transfer was priced on -- equals the boxes the transferee actually gets.
    for delivery in moving:
        delivery["subscription_id"] = to_sub["id"]
        store.touch(delivery)

    from_sub["lifecycle_status"] = "TRANSFERRED"
    if from_sub["payment_basis"] == "PREPAID_FULL_SEASON":
        from_sub["billing_status"] = "REFUND_PENDING"
        # the refund is disbursed inside the same request
        from_sub["billing_status"] = "SETTLED"
    else:
        from_sub["billing_status"] = "SETTLED"
    store.touch(from_sub)

    to_sub["lifecycle_status"] = "ACTIVE"
    to_sub["commitment_cents"] = transfer["transferee_charge_cents"]
    to_sub["billing_status"] = "CURRENT"
    to_sub["promised_delivery_count"] = len(moving)
    store.touch(to_sub)

    transfer["status"] = "ACCEPTED"
    store.touch(transfer)
    return ok(transfer)


@bp.post("/share-transfers/<tid>/decline")
def decline_transfer(tid):
    authz.require_roles(C.ROLE_MEMBER)
    transfer = lookup.share_transfer(tid)                                # rung 20
    to_sub = lookup.maybe("Subscription", transfer["to_subscription_id"])
    authz.own_member(to_sub["member_id"])                                # rung 22
    guards.season_not_closed(lookup.maybe("Season", transfer["season_id"]))  # rung 24
    guards.state_in(transfer["status"], ("REQUESTED",))                  # rung 28
    transfer["status"] = "DECLINED"
    store.touch(transfer)
    return ok(transfer)


# --------------------------------------------------------------------------
# Recall notices
# --------------------------------------------------------------------------
@bp.post("/recall-notices")
def create_recall():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "landing_lot_id", "reason")                          # rung 4
    reason = V.enum_field(body["reason"], C.RECALL_REASONS, "reason")    # rung 5
    V.id_field(body["landing_lot_id"], "landing_lot_id")                 # rung 6
    lot = lookup.landing_lot(body["landing_lot_id"])                     # rung 14
    trip = lookup.trip_of_lot(lot)
    season = lookup.maybe("Season", trip["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.state_in(lot["status"], ("SPLIT", "DISPATCHED", "CLOSED"))    # rung 28

    rec = store.create("RecallNotice", {
        "landing_lot_id": lot["id"], "season_id": trip["season_id"],
        "reason": reason, "impacted_sub_lot_count": 0,
        "impacted_delivery_count": 0, "impacted_member_count": 0,
        "total_credit_cents": 0, "status": "SCOPED",
    })
    cascades.recall_walk(lot, rec)
    return created(rec)


@bp.get("/recall-notices/<rid>")
def read_recall(rid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_QUALITY)
    return ok(lookup.recall(rid))                                        # rung 21


@bp.get("/recall-notices")
def list_recalls():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_QUALITY)
    a = request.args
    pred = filter_eq(a, "landing_lot_id", lambda r: r["landing_lot_id"], always)
    pred = filter_eq(a, "season_id", lambda r: r["season_id"], pred)
    return listing("RecallNotice", a, pred)


@bp.post("/recall-notices/<rid>/remediate")
def remediate_recall(rid):
    authz.require_roles(C.ROLE_ADMIN)
    notice = lookup.recall(rid)                                          # rung 21
    guards.season_not_closed(lookup.maybe("Season", notice["season_id"]))  # rung 24
    guards.state_in(notice["status"], ("SCOPED",))                       # rung 28
    lot = lookup.maybe("LandingLot", notice["landing_lot_id"])
    guards.state_require(
        not any(s["status"] == "IN_TRANSIT" for s in cascades.sub_lots_of(lot)),
        "Remediation requires no sub-lot of the recalled lot to remain IN_TRANSIT.")
    notice["status"] = "REMEDIATED"
    notice["status"] = "CLOSED"
    store.touch(notice)
    return ok(notice)
