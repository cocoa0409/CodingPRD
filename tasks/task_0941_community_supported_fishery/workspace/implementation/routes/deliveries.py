"""Share deliveries: packing, the two fulfillment pipelines and substitution
(PRD 3.5, 3.7)."""
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

bp = Blueprint("deliveries", __name__)


@bp.get("/share-deliveries/<did>")
def read_delivery(did):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    return ok(delivery)


@bp.get("/share-deliveries")
def list_deliveries():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    a = request.args
    pred = filter_eq(a, "subscription_id", lambda r: r["subscription_id"], always)
    pred = filter_eq(a, "season_id", lambda r: r["season_id"], pred)
    pred = filter_eq(a, "landing_lot_id", lambda r: r["landing_lot_id"], pred)
    pred = filter_eq(a, "sub_lot_id", lambda r: r["sub_lot_id"], pred)
    pred = filter_eq(a, "pickup_window_id", lambda r: r["pickup_window_id"], pred)
    pred = filter_eq(a, "week_index", lambda r: r["week_index"], pred)
    pred = filter_eq(a, "fulfillment_status", lambda r: r["fulfillment_status"], pred)
    return listing("ShareDelivery", a, pred)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/pack
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/pack")
def pack(did):
    authz.require_roles(C.ROLE_HUB)
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    season = lookup.maybe("Season", delivery["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.state_in(delivery["fulfillment_status"], ("ALLOCATED",))      # rung 28
    guards.state_require(delivery.get("sub_lot_id") is not None,
                         "A box that has not been assigned to a consignment cannot be packed.")
    guards.state_in(delivery["fill_status"],
                    ("FULL_FILL", "UNDER_FILLED", "SUBSTITUTED"),
                    "The box's fill_status does not admit packing.")
    # PRD 3.7 states this rejection for packing in its own words: "Packing is
    # refused with ERR_PAYMENT_REQUIRED when the owning subscription is in
    # PAST_DUE."  The rung-30 summary in PRD 2.5 enumerates activation, staging
    # and dispatch; the specific workflow sentence governs over the summary.
    guards.not_past_due(sub)                                             # rung 30

    plan = lookup.plan_of_subscription(sub)
    mode = sub["fulfillment_mode"]
    zone = lookup.maybe("DeliveryZone", sub.get("delivery_zone_id"))

    box_pounds = calc.lb(delivery["allocated_pounds"] + delivery["substituted_pounds"])
    pack_size = calc.pack_size_selection(mode, box_pounds)
    transit = zone["transit_hours"] if zone is not None else calc.Decimal("0")
    gel_packs = calc.gel_pack_count(mode, season["ambient_band"], pack_size, transit)
    subtotal, surcharge, delivery_fee, invoice_total = calc.member_week_invoice(
        sub["price_per_delivery_cents"], mode, pack_size, gel_packs,
        zone["fee_tier"] if zone is not None else None)

    delivery["box_pounds"] = box_pounds
    delivery["pack_size"] = pack_size
    delivery["gel_pack_count"] = gel_packs
    delivery["subtotal_cents"] = subtotal
    delivery["surcharge_cents"] = surcharge
    delivery["delivery_fee_cents"] = delivery_fee
    delivery["invoice_total_cents"] = invoice_total
    delivery["charged_cents"] = invoice_total
    delivery["fulfillment_status"] = "PACKED"
    delivery["billing_status"] = "CHARGED"
    store.touch(delivery)
    cascades.arrears_check(sub)
    return ok(delivery)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/dispatch
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/dispatch")
def dispatch(did):
    authz.require_roles(C.ROLE_HUB)
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(delivery["fulfillment_status"], ("PACKED",))         # rung 28
    guards.state_require(sub["fulfillment_mode"] == "HOME_DELIVERY",
                         "Dispatch belongs to the home-delivery pipeline.")
    sub_lot = lookup.maybe("SubLot", delivery.get("sub_lot_id"))
    guards.state_require(sub_lot is not None and sub_lot["destination_type"] == "ROUTE",
                         "The carrying sub-lot must be a ROUTE consignment.")
    guards.state_require(delivery["gel_pack_count"] >= 1,
                         "A dispatched box must carry at least one gel pack.")
    guards.not_past_due(sub)                                             # rung 30
    delivery["fulfillment_status"] = "IN_TRANSIT"
    store.touch(delivery)
    return ok(delivery)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/deliver
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/deliver")
def deliver(did):
    authz.require_roles(C.ROLE_HUB)
    delivery = lookup.share_delivery(did)                                # rung 16
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(delivery["fulfillment_status"], ("IN_TRANSIT",))     # rung 28
    lot = lookup.maybe("LandingLot", delivery.get("landing_lot_id"))
    if lot is None or lot["quality_status"] not in ("CLEAR", "RELEASED", "DISCOUNTED"):
        raise ApiError("ERR_LOT_ON_QUALITY_HOLD")                        # rung 41
    if not any(e["custody_leg"] == "HUB_TO_DOOR"
               for e in store.all_of("ColdChainEvent")
               if e["landing_lot_id"] == lot["id"]):
        raise ApiError("ERR_COLD_CHAIN_EVIDENCE_MISSING")                # rung 42

    delivery["fulfillment_status"] = "DELIVERED"
    store.touch(delivery)
    # PRD 3.2 defines delivered_count as the deliveries that "reached DELIVERED
    # or PICKED_UP", and INV_PROMISED_COUNT_PARTITION needs both pipelines to
    # feed it, so a completed home delivery counts exactly as a collection does.
    sub = lookup.subscription_of_delivery(delivery)
    sub["delivered_count"] = sub["delivered_count"] + 1
    store.touch(sub)
    cascades.settle_custody(delivery)
    return ok(delivery)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/stage-at-hub
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/stage-at-hub")
def stage_at_hub(did):
    authz.require_roles(C.ROLE_HUB)
    body = V.body_of(request)
    V.require(body, "pickup_window_id")                                  # rung 4
    V.id_field(body["pickup_window_id"], "pickup_window_id")             # rung 6
    window = lookup.pickup_window(body["pickup_window_id"])              # rung 8
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    guards.reference(window["week_index"] == delivery["week_index"],     # rung 23
                     "The window's week_index must equal the delivery's.")
    guards.reference(window["pickup_hub_id"] == sub.get("pickup_hub_id"),
                     "The window's hub must equal the subscription's hub.")
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(delivery["fulfillment_status"], ("PACKED",))         # rung 28
    guards.state_require(sub["fulfillment_mode"] == "HUB_PICKUP",
                         "Staging belongs to the hub-pickup pipeline.")
    sub_lot = lookup.maybe("SubLot", delivery.get("sub_lot_id"))
    guards.state_require(sub_lot is not None and sub_lot["destination_type"] == "HUB",
                         "The carrying sub-lot must be a HUB consignment.")
    guards.not_past_due(sub)                                             # rung 30
    guards.window_status(window, ("SCHEDULED", "OPEN"))                  # rung 45
    guards.window_has_slot(window)                                       # rung 47

    delivery["pickup_window_id"] = window["id"]
    delivery["fulfillment_status"] = "AT_HUB"
    store.touch(delivery)
    window["slots_reserved"] = window["slots_reserved"] + 1
    cascades.recompute_slots(window)
    store.touch(window)
    return ok(delivery)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/pickup
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/pickup")
def pickup(did):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(delivery["fulfillment_status"], ("AT_HUB",))         # rung 28
    guards.subscription_active(sub)                                      # rung 29
    lot = lookup.maybe("LandingLot", delivery.get("landing_lot_id"))
    if lot is None or lot["quality_status"] not in ("CLEAR", "RELEASED", "DISCOUNTED"):
        raise ApiError("ERR_LOT_ON_QUALITY_HOLD")                        # rung 41
    if not any(e["custody_leg"] == "HUB_HOLD"
               for e in store.all_of("ColdChainEvent")
               if e["landing_lot_id"] == lot["id"]):
        raise ApiError("ERR_COLD_CHAIN_EVIDENCE_MISSING")                # rung 42
    window = lookup.maybe("PickupWindow", delivery.get("pickup_window_id"))
    guards.window_status(window, ("OPEN", "GRACE"))                      # rung 45
    now = clock.now()
    deadline = window["closes_at"] + timedelta(minutes=window["grace_minutes"])
    if now > deadline:
        raise ApiError("ERR_WINDOW_GRACE_EXPIRED")                       # rung 46

    delivery["fulfillment_status"] = "PICKED_UP"
    store.touch(delivery)
    window["slots_reserved"] = max(0, window["slots_reserved"] - 1)
    window["slots_occupied"] = window["slots_occupied"] + 1
    cascades.recompute_slots(window)
    if window["status"] == "OPEN" and now > window["closes_at"]:
        window["status"] = "GRACE"
    store.touch(window)
    sub["delivered_count"] = sub["delivered_count"] + 1
    store.touch(sub)
    cascades.settle_custody(delivery)
    return ok(delivery)


# --------------------------------------------------------------------------
# POST /csf/share-deliveries/{id}/substitutions
# --------------------------------------------------------------------------
@bp.post("/share-deliveries/<did>/substitutions")
def propose_substitution(did):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "substitute_landing_lot_id", "substitute_pounds")    # rung 4
    V.id_field(body["substitute_landing_lot_id"], "substitute_landing_lot_id")
    substitute_pounds = V.pounds_field(body["substitute_pounds"],
                                       "substitute_pounds")             # rung 6

    sub_lot_source = lookup.landing_lot(body["substitute_landing_lot_id"])  # rung 14
    delivery = lookup.share_delivery(did)                                # rung 16
    sub = lookup.subscription_of_delivery(delivery)
    member = lookup.member_of_subscription(sub)
    plan = lookup.plan_of_subscription(sub)
    source_trip = lookup.trip_of_lot(sub_lot_source)
    guards.reference(source_trip["season_id"] == delivery["season_id"],  # rung 23
                     "The substitute lot must belong to the delivery's season.")
    season = lookup.maybe("Season", delivery["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.state_in(delivery["fill_status"], ("UNDER_FILLED",))          # rung 28
    guards.subscription_active(sub)                                      # rung 29

    species = sub_lot_source["species"]
    if species in member["allergy_exclusions"]:                          # rung 37
        raise ApiError("ERR_ALLERGY_EXCLUSION")
    if member["never_substitute"]:                                       # rung 38
        raise ApiError("ERR_NEVER_SUBSTITUTE")
    if species in member["dislikes"] and _alternative_exists(season, member, species):
        raise ApiError("ERR_DISLIKE_ALTERNATIVE_AVAILABLE")              # rung 39

    committed = calc.ZERO_LB
    for offer in store.all_of("SubstitutionEvent"):
        if offer["substitute_landing_lot_id"] == sub_lot_source["id"] and \
                offer["status"] in ("ACCEPTED", "CREDIT_ISSUED"):
            committed = calc.lb(committed + offer["substitute_pounds"])
    available = calc.lb(sub_lot_source["landed_pounds_net"]
                        - sub_lot_source["allocated_pounds_total"] - committed)
    if substitute_pounds > available:                                    # rung 40
        raise ApiError("ERR_NO_SUBSTITUTE_AVAILABLE")

    # PRD 3.5 caps the credit at "the delivery's own subtotal_cents", and the
    # ShareDelivery field description defines subtotal_cents as "the share charge
    # for this delivery before any fee, equals Subscription.price_per_delivery_cents".
    # A substitution is normally proposed between allocation and packing, when the
    # stored subtotal_cents is still 0, so reading the cap off the stored field
    # would force every BELOW_VALUE credit to 0 and strand the whole branch --
    # including PRD 3.5's own worked example of a 2325-cent credit.  The cap is
    # therefore the subscription's price_per_delivery_cents, which is what the
    # field is defined to equal.
    cap = sub["price_per_delivery_cents"]
    shortfall, owed, sub_value, variant, credit = calc.substitution_value_settlement(
        plan["target_pounds_per_delivery"], delivery["allocated_pounds"],
        plan["species_tier"], substitute_pounds,
        sub_lot_source["retail_value_cents_per_lb"], cap)

    rec = store.create("SubstitutionEvent", {
        "share_delivery_id": delivery["id"],
        "substitute_landing_lot_id": sub_lot_source["id"],
        "substitute_species": species, "substitute_pounds": substitute_pounds,
        "shortfall_pounds": shortfall, "owed_value_cents": owed,
        "substitute_value_cents": sub_value, "settlement_variant": variant,
        "member_credit_cents": credit, "status": "PROPOSED",
    })
    return created(rec)


def _alternative_exists(season, member, disliked_species):
    """PRD 3.5's disliked-species test."""
    blocked = set(member["allergy_exclusions"]) | set(member["dislikes"])
    for candidate in season["offered_species"]:
        if candidate == disliked_species or candidate in blocked:
            continue
        for lot in store.all_of("LandingLot"):
            if lot["species"] != candidate:
                continue
            if lot["status"] not in ("RECORDED", "ALLOCATED", "SPLIT"):
                continue
            if lot["quality_status"] != "CLEAR":
                continue
            trip = lookup.trip_of_lot(lot)
            if trip is not None and trip["season_id"] == season["id"]:
                return True
    return False


@bp.get("/substitution-events/<eid>")
def read_substitution(eid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    offer = lookup.substitution(eid)                                     # rung 17
    delivery = lookup.maybe("ShareDelivery", offer["share_delivery_id"])
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    return ok(offer)


@bp.get("/substitution-events")
def list_substitutions():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    a = request.args
    pred = filter_eq(a, "share_delivery_id", lambda r: r["share_delivery_id"], always)
    pred = filter_eq(a, "substitute_landing_lot_id",
                     lambda r: r["substitute_landing_lot_id"], pred)
    return listing("SubstitutionEvent", a, pred)


@bp.post("/substitution-events/<eid>/accept")
def accept_substitution(eid):
    authz.require_roles(C.ROLE_MEMBER)
    offer = lookup.substitution(eid)                                     # rung 17
    delivery = lookup.maybe("ShareDelivery", offer["share_delivery_id"])
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(offer["status"], ("PROPOSED",))                      # rung 28
    guards.state_in(delivery["fill_status"], ("UNDER_FILLED",),
                    "The box is no longer UNDER_FILLED.")

    delivery["substituted_pounds"] = calc.lb(
        delivery["substituted_pounds"] + offer["substitute_pounds"])
    delivery["box_pounds"] = calc.lb(
        delivery["allocated_pounds"] + delivery["substituted_pounds"])
    delivery["fill_status"] = "SUBSTITUTED"
    store.touch(delivery)

    if offer["settlement_variant"] == "EQUAL_OR_GREATER":
        offer["status"] = "ACCEPTED"
    else:
        offer["status"] = "CREDIT_ISSUED"
        cascades.add_credit(delivery, offer["member_credit_cents"])
        if delivery["billing_status"] in ("CHARGED", "PARTIALLY_CREDITED") and \
                offer["member_credit_cents"] > 0:
            # Adjudication of friction 9 (second site): the money axis lands on
            # PARTIALLY_CREDITED whatever the accumulated credit reaches, since
            # no alternative branch is declared for a credit that meets or
            # exceeds charged_cents.
            delivery["billing_status"] = "PARTIALLY_CREDITED"
    store.touch(offer)
    return ok(offer)


@bp.post("/substitution-events/<eid>/reject")
def reject_substitution(eid):
    authz.require_roles(C.ROLE_MEMBER)
    offer = lookup.substitution(eid)                                     # rung 17
    delivery = lookup.maybe("ShareDelivery", offer["share_delivery_id"])
    sub = lookup.subscription_of_delivery(delivery)
    authz.own_member(sub["member_id"])                                   # rung 22
    guards.season_not_closed(lookup.maybe("Season", delivery["season_id"]))  # rung 24
    guards.state_in(offer["status"], ("PROPOSED",))                      # rung 28
    offer["status"] = "REJECTED"
    store.touch(offer)
    return ok(offer)
