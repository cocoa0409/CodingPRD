"""Landing lots, the weekly catch allocation, splits, sub-lots, the cold
chain and quality disposition (PRD 3.4, 3.6)."""
from flask import Blueprint, g, request

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
from money import round_half_up
from routes.common import created, filter_eq, listing, ok, always

bp = Blueprint("lots", __name__)


@bp.get("/landing-lots/<lid>")
def read_lot(lid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR, C.ROLE_HUB, C.ROLE_QUALITY)
    lot = lookup.landing_lot(lid)                                        # rung 14
    trip = lookup.trip_of_lot(lot)
    authz.own_vessel(trip["vessel_id"])                                  # rung 22
    return ok(lot)


@bp.get("/landing-lots")
def list_lots():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR, C.ROLE_HUB, C.ROLE_QUALITY)
    pred = filter_eq(request.args, "trip_id", lambda r: r["trip_id"], always)
    return listing("LandingLot", request.args, pred)


# --------------------------------------------------------------------------
# POST /csf/landing-lots/{id}/allocations
# --------------------------------------------------------------------------
@bp.post("/landing-lots/<lid>/allocations")
def run_allocation(lid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "week_index", "expected_landing_lot_version")        # rung 4
    week_index = V.int_field(body["week_index"], "week_index", minimum=1)  # rung 6
    expected = V.int_field(body["expected_landing_lot_version"],
                           "expected_landing_lot_version", minimum=0)
    lot_peek = lookup.maybe("LandingLot", lid)
    if lot_peek is not None:
        season_peek = lookup.season_of_lot(lot_peek)
        if season_peek is not None and week_index > season_peek["total_weeks"]:
            raise ApiError("ERR_VALIDATION",
                           "Field 'week_index' must be at most the season's total_weeks.")

    lot = lookup.landing_lot(lid)                                        # rung 14
    trip = lookup.trip_of_lot(lot)
    season = lookup.maybe("Season", trip["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25

    guards.state_in(lot["status"], ("RECORDED", "ALLOCATED"))            # rung 28
    guards.state_in(lot["quality_status"], ("CLEAR",),
                    "The lot's quality_status must be CLEAR to allocate.")
    guards.state_in(trip["status"], ("LANDED",),
                    "The lot's trip must be LANDED to allocate.")
    guards.state_in(trip["sustainability_band"], ("GREEN", "YELLOW", "ORANGE"),
                    "A RED sustainability band cannot be allocated.")
    existing_sub_lots = cascades.sub_lots_of(lot)
    if lot["status"] == "ALLOCATED":
        guards.state_require(not existing_sub_lots,
                             "An allocation cannot be re-run once the lot has been split.")
    guards.expected_version(expected, lot)                               # rung 31

    # A re-run first discards the prior allocation completely.
    if lot["status"] == "ALLOCATED":
        for d in cascades.deliveries_of_lot(lot):
            d["fulfillment_status"] = "SCHEDULED"
            d["fill_status"] = "PENDING"
            d["allocated_pounds"] = calc.ZERO_LB
            d["box_pounds"] = calc.lb(d["substituted_pounds"])
            d["landing_lot_id"] = None
            store.touch(d)

    tier = C.SPECIES_TIER_MAP[lot["species"]]
    eligible = []
    for d in store.ordered("ShareDelivery"):
        if d["season_id"] != trip["season_id"]:
            continue
        if d["week_index"] != week_index:
            continue
        if d["fulfillment_status"] != "SCHEDULED":
            continue
        sub = lookup.subscription_of_delivery(d)
        if sub is None or sub["lifecycle_status"] != "ACTIVE":
            continue
        plan = lookup.plan_of_subscription(sub)
        if plan is None or plan["species_tier"] != tier:
            continue
        eligible.append((d, plan))

    # Fixed order: weight_units DESC, then created_at ASC (store.ordered already
    # returns creation order, and Python's sort is stable).
    eligible.sort(key=lambda pair: -pair[1]["weight_units"])
    shares = [{"key": d["id"], "weight_units": plan["weight_units"],
               "target": plan["target_pounds_per_delivery"],
               "floor": plan["min_floor_pounds"]}
              for d, plan in eligible]

    variant, allocated = calc.catch_allocation(lot["landed_pounds_net"], shares)
    total = calc.ZERO_LB
    for d, plan in eligible:
        pounds = allocated[d["id"]]
        d["landing_lot_id"] = lot["id"]
        d["allocated_pounds"] = pounds
        d["box_pounds"] = calc.lb(pounds + d["substituted_pounds"])
        d["fulfillment_status"] = "ALLOCATED"
        d["fill_status"] = "FULL_FILL" if pounds >= plan["target_pounds_per_delivery"] \
            else "UNDER_FILLED"
        store.touch(d)
        total = calc.lb(total + pounds)

    secondary, donated = calc.surplus_routing(lot["landed_pounds_net"], total)
    lot["allocation_variant"] = variant
    lot["allocated_pounds_total"] = total
    lot["surplus_secondary_pounds"] = secondary
    lot["surplus_donated_pounds"] = donated
    lot["allocation_week_index"] = week_index
    lot["status"] = "ALLOCATED"
    store.touch(lot)
    return ok(lot)


# --------------------------------------------------------------------------
# POST /csf/landing-lots/{id}/splits
# --------------------------------------------------------------------------
@bp.post("/landing-lots/<lid>/splits")
def split_lot(lid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "destinations")                                      # rung 4
    raw = body["destinations"]
    if not isinstance(raw, list) or len(raw) == 0:
        raise ApiError("ERR_VALIDATION", "Field 'destinations' must be a non-empty array.")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", "Each destination must be an object.")
        for name in ("destination_type", "destination_id", "pounds"):
            if name not in entry or entry[name] is None:
                raise ApiError("ERR_VALIDATION",
                               "Field 'destinations[].%s' is required." % name)
        dtype = V.enum_field(entry["destination_type"], C.DESTINATION_TYPES,
                             "destination_type")                        # rung 5
        parsed.append({"destination_type": dtype,
                       "destination_id": entry["destination_id"],
                       "pounds": entry["pounds"]})
    for entry in parsed:
        V.id_field(entry["destination_id"], "destination_id")            # rung 6
        entry["pounds"] = V.pounds_field(entry["pounds"], "pounds")

    lot = lookup.landing_lot(lid)                                        # rung 14
    trip = lookup.trip_of_lot(lot)
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(lot["status"], ("ALLOCATED",))                       # rung 28
    guards.state_in(lot["quality_status"], ("CLEAR",),
                    "The lot's quality_status must be CLEAR to split.")

    # rung 48 -- calculations.sublot_split_conservation, no tolerance at all
    requested_total = calc.ZERO_LB
    for entry in parsed:
        requested_total = calc.lb(requested_total + entry["pounds"])
    if requested_total != lot["allocated_pounds_total"]:
        raise ApiError("ERR_MASS_CONSERVATION_VIOLATION")

    lot_deliveries = cascades.deliveries_of_lot(lot)
    routed = {}
    for entry in parsed:
        expected = calc.ZERO_LB
        members = []
        for d in lot_deliveries:
            sub = lookup.subscription_of_delivery(d)
            if sub is None:
                continue
            if entry["destination_type"] == "HUB":
                match = sub.get("pickup_hub_id") == entry["destination_id"]
            else:
                match = sub.get("delivery_zone_id") == entry["destination_id"]
            if match:
                expected = calc.lb(expected + d["allocated_pounds"])
                members.append(d)
        if expected != entry["pounds"]:
            raise ApiError("ERR_MASS_CONSERVATION_VIOLATION")
        routed[id(entry)] = members

    for entry in parsed:
        sub_lot = store.create("SubLot", {
            "landing_lot_id": lot["id"],
            "pickup_hub_id": entry["destination_id"]
            if entry["destination_type"] == "HUB" else None,
            "delivery_zone_id": entry["destination_id"]
            if entry["destination_type"] == "ROUTE" else None,
            "destination_type": entry["destination_type"],
            "pounds": entry["pounds"], "status": "IN_TRANSIT",
        })
        for d in routed[id(entry)]:
            d["sub_lot_id"] = sub_lot["id"]
            store.touch(d)

    lot["split_pounds_total"] = requested_total
    lot["status"] = "SPLIT"
    store.touch(lot)
    return ok(lot)


# --------------------------------------------------------------------------
# POST /csf/landing-lots/{id}/disposition
# --------------------------------------------------------------------------
@bp.post("/landing-lots/<lid>/disposition")
def disposition(lid):
    authz.require_roles(C.ROLE_QUALITY)
    body = V.body_of(request)
    V.require(body, "disposition")                                       # rung 4
    choice = V.enum_field(body["disposition"], C.DISPOSITIONS, "disposition")  # rung 5
    lot = lookup.landing_lot(lid)                                        # rung 14
    trip = lookup.trip_of_lot(lot)
    season = lookup.maybe("Season", trip["season_id"])
    guards.season_not_closed(season)                                     # rung 24
    guards.state_in(lot["quality_status"], ("HOLD",))                    # rung 28

    # rung 43 -- the cold-chain budget gate
    if choice == "RELEASE":
        if lot["cold_chain_cumulative_minutes"] > C.COLD_CHAIN_RELEASE_LIMIT_MIN or \
                lot["peak_temp_c"] > C.QUALITY_RELEASE_TEMP_C:
            raise ApiError("ERR_COLD_CHAIN_BUDGET_EXCEEDED")
    elif choice == "DISCOUNT":
        if lot["cold_chain_cumulative_minutes"] > C.COLD_CHAIN_DISCOUNT_LIMIT_MIN:
            raise ApiError("ERR_COLD_CHAIN_BUDGET_EXCEEDED")
    # DISCARD has no budget test at all.

    # rung 44 -- segregation of duties, breaching legs only
    for event in store.ordered("ColdChainEvent",
                               lambda e: e["landing_lot_id"] == lot["id"]
                               and e["breach_type"] != "NONE"):
        if event["recorded_by_user_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if choice == "RELEASE":
        lot["quality_status"] = "RELEASED"
        store.touch(lot)
        for statement in store.ordered("SettlementStatement",
                                       lambda s: s["landing_lot_id"] == lot["id"]
                                       and s["status"] == "HELD"):
            statement["status"] = "PROVISIONAL"
            store.touch(statement)
    elif choice == "DISCOUNT":
        lot["quality_status"] = "DISCOUNTED"
        store.touch(lot)
        for delivery in cascades.deliveries_of_lot(lot):
            if delivery["billing_status"] not in ("CHARGED", "PARTIALLY_CREDITED"):
                continue
            delta = round_half_up(
                calc.Decimal(delivery["invoice_total_cents"]) *
                C.QUALITY_DISCOUNT_CREDIT_PCT)
            cascades.add_credit(delivery, delta)
            # Adjudication of friction 9: a credit that brings credit_cents to
            # or past charged_cents still lands on PARTIALLY_CREDITED.  The
            # DISCOUNT side effect is stated unconditionally ("every ShareDelivery
            # ... receives a credit of ... and moves billing_status to
            # PARTIALLY_CREDITED"), the strict-inequality clause describes the
            # ordinary case, and no alternative branch is named anywhere; CREDITED
            # belongs to the recall walk and REFUNDED to the discard cascade, so
            # borrowing either here would forge a cascade that did not happen.
            delivery["billing_status"] = "PARTIALLY_CREDITED"
            store.touch(delivery)
    else:
        lot["quality_status"] = "DISCARDED"
        store.touch(lot)
        cascades.discard_cascade(lot, season)
    return ok(lot)


# --------------------------------------------------------------------------
# Sub-lots
# --------------------------------------------------------------------------
@bp.get("/sub-lots/<sid>")
def read_sub_lot(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB, C.ROLE_QUALITY)
    return ok(lookup.sub_lot(sid))                                       # rung 15


@bp.get("/sub-lots")
def list_sub_lots():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB, C.ROLE_QUALITY)
    a = request.args
    pred = filter_eq(a, "landing_lot_id", lambda r: r["landing_lot_id"], always)
    pred = filter_eq(a, "pickup_hub_id", lambda r: r["pickup_hub_id"], pred)
    pred = filter_eq(a, "delivery_zone_id", lambda r: r["delivery_zone_id"], pred)
    return listing("SubLot", a, pred)


@bp.post("/sub-lots/<sid>/arrive")
def arrive(sid):
    authz.require_roles(C.ROLE_HUB)
    sub_lot = lookup.sub_lot(sid)                                        # rung 15
    lot = lookup.maybe("LandingLot", sub_lot["landing_lot_id"])
    trip = lookup.trip_of_lot(lot)
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(sub_lot["status"], ("IN_TRANSIT",))                  # rung 28
    guards.state_require(lot["quality_status"] != "DISCARDED",
                         "Arrival is refused while the parent lot is DISCARDED.")
    sub_lot["status"] = "ARRIVED"
    store.touch(sub_lot)
    cascades.maybe_dispatch_lot(lot)
    return ok(sub_lot)


# --------------------------------------------------------------------------
# Cold-chain events
# --------------------------------------------------------------------------
@bp.post("/cold-chain-events")
def create_cold_chain_event():
    authz.require_roles(C.ROLE_HUB, C.ROLE_QUALITY)
    body = V.body_of(request)
    V.require(body, "landing_lot_id", "custody_leg", "minutes_above_threshold",
              "peak_temp_c")                                             # rung 4
    leg = V.enum_field(body["custody_leg"], C.CUSTODY_LEGS, "custody_leg")  # rung 5
    V.id_field(body["landing_lot_id"], "landing_lot_id")
    minutes = V.int_field(body["minutes_above_threshold"],
                          "minutes_above_threshold", minimum=0)         # rung 6
    peak = V.decimal_field(body["peak_temp_c"], "peak_temp_c", max_decimals=1)
    sub_lot_id = body.get("sub_lot_id")

    lot = lookup.landing_lot(body["landing_lot_id"])                     # rung 14
    sub_lot = lookup.sub_lot(sub_lot_id) if sub_lot_id is not None else None  # rung 15
    trip = lookup.trip_of_lot(lot)
    season = lookup.maybe("Season", trip["season_id"])
    guards.season_not_closed(season)                                     # rung 24

    prior = store.ordered("ColdChainEvent",
                          lambda e: e["landing_lot_id"] == lot["id"])
    cumulative = sum(e["minutes_above_threshold"] for e in prior) + minutes
    max_single = max([e["minutes_above_threshold"] for e in prior] + [minutes])
    peak_all = max([e["peak_temp_c"] for e in prior] + [peak])
    breach = calc.breach_type(minutes, cumulative)

    rec = store.create("ColdChainEvent", {
        "landing_lot_id": lot["id"],
        "sub_lot_id": sub_lot["id"] if sub_lot is not None else None,
        "custody_leg": leg, "minutes_above_threshold": minutes,
        "peak_temp_c": peak, "recorded_at": clock.now(),
        "recorded_by_user_id": g.user_id, "breach_type": breach,
    })

    lot["cold_chain_cumulative_minutes"] = cumulative
    lot["cold_chain_max_single_minutes"] = max_single
    lot["peak_temp_c"] = peak_all
    store.touch(lot)

    # Adjudication of friction 10: a breach only moves the quality axis when the
    # lot is CLEAR.  PRD 2.10 makes RELEASED, DISCOUNTED and DISCARDED terminal
    # on that axis and the only declared entry to HOLD is CLEAR -> HOLD, so a
    # breach logged against an already-dispositioned (or already-held) lot leaves
    # the quality axis, and therefore the settlement axis it drives, untouched.
    # The roll-ups and this leg's own breach_type are still written, because
    # "once written they are never excluded from any later evaluation".
    if breach != "NONE" and lot["quality_status"] == "CLEAR":
        lot["quality_status"] = "HOLD"
        for statement in store.ordered("SettlementStatement",
                                       lambda s: s["landing_lot_id"] == lot["id"]
                                       and s["status"] == "PROVISIONAL"):
            statement["status"] = "HELD"
            store.touch(statement)
    return created(rec)


@bp.get("/cold-chain-events/<eid>")
def read_cold_chain_event(eid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB, C.ROLE_QUALITY)
    rec = store.get("ColdChainEvent", eid)
    if rec is None:
        raise ApiError("ERR_LANDING_LOT_NOT_FOUND")
    return ok(rec)


@bp.get("/cold-chain-events")
def list_cold_chain_events():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB, C.ROLE_QUALITY)
    a = request.args
    pred = filter_eq(a, "landing_lot_id", lambda r: r["landing_lot_id"], always)
    pred = filter_eq(a, "sub_lot_id", lambda r: r["sub_lot_id"], pred)
    return listing("ColdChainEvent", a, pred)
