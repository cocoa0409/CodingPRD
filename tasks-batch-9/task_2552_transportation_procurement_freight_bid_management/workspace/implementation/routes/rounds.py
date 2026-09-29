"""Round reads, lane-bid submission and round closure — PRD §3.4 and §3.5."""
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from numeric import D, q4
from services import bidding

bp = Blueprint("rounds", __name__)


@bp.get("/freight-procurement/bid-rounds/<round_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def get_round(round_id):
    return responses.ok(helpers.get_round(round_id))


@bp.post("/freight-procurement/bid-rounds/<round_id>/lane-bids")
@auth.roles_required("CarrierRep")
def submit_bid(round_id):
    round_row = helpers.get_round(round_id)
    payload = v.body()
    lane_id = v.id_field(payload, "lane_id")
    carrier_id = v.id_field(payload, "carrier_id")
    rate = v.dec_field(payload, "rate_per_mile", exclusive_min=True)
    fuel_included = v.bool_field(payload, "fuel_surcharge_included")
    committed = v.int_field(payload, "committed_volume_loads", minimum=1)
    transit_days = v.int_field(payload, "transit_days_offered", minimum=1)

    lane = helpers.get_lane(lane_id)
    carrier = helpers.get_carrier(carrier_id)
    auth.own_carrier_or_raise(carrier_id)

    event = helpers.event_of(round_row)
    if round_row["status"] != "OPEN":
        raise ApiError("ERR_ROUND_NOT_OPEN")
    # closes_at is the submission deadline: a bid arriving at or after it is late.
    if store.now() >= store.parse_dt(round_row["closes_at"]):
        raise ApiError("ERR_ROUND_NOT_OPEN")

    helpers.check_fitness(carrier)

    pairing = [i for i in store.invitations.values()
               if i["bid_event_id"] == round_row["bid_event_id"]
               and i["carrier_id"] == carrier["id"]]
    if not pairing:
        raise ApiError("ERR_CARRIER_NOT_INVITED")
    if not any(i["status"] == "ACCEPTED" for i in pairing):
        raise ApiError("ERR_INVITATION_NOT_ACCEPTED")

    for other in store.lane_bids.values():
        if (other["bid_round_id"] == round_row["id"] and other["lane_id"] == lane["id"]
                and other["carrier_id"] == carrier["id"]
                and other["status"] != "WITHDRAWN"):
            raise ApiError("ERR_DUPLICATE_LANE_BID")

    if lane["bid_event_id"] != round_row["bid_event_id"]:
        raise ApiError("ERR_LANE_NOT_IN_EVENT_SCOPE")
    if transit_days > lane["service_days_required"]:
        raise ApiError("ERR_TRANSIT_DAYS_EXCEEDED")

    if rate < D(event["rate_floor_per_mile"]):
        raise ApiError("ERR_RATE_BELOW_FLOOR")
    _check_round_target(round_row, event, lane, carrier, rate)

    bid = store.new_row(
        bid_round_id=round_row["id"],
        lane_id=lane["id"],
        carrier_id=carrier["id"],
        rate_per_mile=rate,
        fuel_surcharge_included=fuel_included,
        committed_volume_loads=committed,
        transit_days_offered=transit_days,
        status="SUBMITTED",
        is_incumbent=(lane["incumbent_carrier_id"] == carrier["id"]),
        evaluated_basis=event["cost_basis"],
        awardable_volume_loads=0,
        linehaul_per_load_usd=Decimal("0.00"),
        accessorial_per_load_usd=Decimal("0.00"),
        cost_per_load_usd=Decimal("0.00"),
        evaluated_total_cost_usd=Decimal("0.00"),
        cost_rank_score=Decimal("0.00"),
        rank_in_lane=0,
        withdrawn_at=None,
    )
    bidding.evaluate_bid(bid, lane, event, carrier)
    store.lane_bids[bid["id"]] = bid

    bidding.rerank_lane(round_row["id"], lane["id"])
    bidding.recompute_round_counters(round_row)
    store.touch(round_row)
    return responses.created(bid)


def _check_round_target(round_row, event, lane, carrier, rate):
    """From round 2 onward a returning bidder must meet the round's reduction target
    against its own previous rate; a first-time bidder cannot violate it."""
    target = D(round_row["target_reduction_pct"])
    if round_row["round_no"] < 2 or target <= Decimal("0.00"):
        return
    previous = None
    for other_round in store.rounds.values():
        if (other_round["bid_event_id"] == round_row["bid_event_id"]
                and other_round["round_no"] == round_row["round_no"] - 1):
            previous = other_round
    if previous is None:
        return
    earlier = [b for b in store.sorted_rows(store.lane_bids.values())
               if b["bid_round_id"] == previous["id"] and b["lane_id"] == lane["id"]
               and b["carrier_id"] == carrier["id"] and b["status"] != "WITHDRAWN"]
    if not earlier:
        return
    previous_rate = D(earlier[-1]["rate_per_mile"])
    ceiling = q4(previous_rate * (Decimal("1") - target / Decimal("100.00")))
    if rate > ceiling:
        raise ApiError("ERR_RATE_ABOVE_ROUND_TARGET")


@bp.post("/freight-procurement/bid-rounds/<round_id>/close")
@auth.roles_required("ProcurementAnalyst")
def close_round(round_id):
    round_row = helpers.get_round(round_id)
    v.body()
    event = helpers.event_of(round_row)

    if round_row["status"] != "OPEN" or event is None or event["status"] != "ROUND_OPEN":
        raise ApiError("ERR_ROUND_NOT_OPEN")

    round_row["status"] = "CLOSED"
    round_row["closed_at"] = store.now_iso()
    bidding.recompute_round_counters(round_row)
    store.touch(round_row)

    # Closing re-evaluates every submitted bid so the optimiser reads final, post-
    # withdrawal reality.
    affected = set()
    for bid in store.sorted_rows(store.lane_bids.values()):
        if bid["bid_round_id"] != round_row["id"] or bid["status"] != "SUBMITTED":
            continue
        lane = store.lanes.get(bid["lane_id"])
        carrier = store.carriers.get(bid["carrier_id"])
        if lane is None or carrier is None:
            continue
        bidding.evaluate_bid(bid, lane, event, carrier)
        store.touch(bid)
        affected.add(bid["lane_id"])
    for lane_id in sorted(affected):
        bidding.rerank_lane(round_row["id"], lane_id)

    event["status"] = "ROUND_CLOSED"
    store.touch(event)
    return responses.ok(round_row)
