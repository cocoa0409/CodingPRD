"""Award-allocation governance — PRD §3.7."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from services import lanes as lane_svc, optimize

bp = Blueprint("allocations", __name__)


@bp.get("/freight-procurement/award-allocations/<allocation_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def get_allocation(allocation_id):
    return responses.ok(helpers.get_allocation(allocation_id))


@bp.get("/freight-procurement/award-allocations")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_allocations():
    rows = store.sorted_rows(store.allocations.values())
    rows = helpers.filter_rows(rows, {
        "bid_event_id": "bid_event_id",
        "optimization_run_id": "optimization_run_id",
        "lane_id": "lane_id",
        "carrier_id": "carrier_id",
        "lane_bid_id": "lane_bid_id",
        "routing_position": "routing_position",
        "status": "status",
    })
    return responses.listing(rows)


@bp.post("/freight-procurement/award-allocations/<allocation_id>/approve")
@auth.roles_required("CategoryManager")
def approve(allocation_id):
    allocation = helpers.get_allocation(allocation_id)
    v.body()
    event = helpers.event_of(allocation)

    if allocation["status"] != "PROPOSED":
        raise ApiError("ERR_ALLOCATION_NOT_PROPOSED")
    if event is None or event["status"] != "AWARDING":
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")

    carrier = store.carriers.get(allocation["carrier_id"])
    helpers.check_fitness(carrier, standing=helpers.STANDING_APPROVAL)

    # Link 1 — the approval itself.
    allocation["status"] = "APPROVED"
    allocation["approved_by_user_id"] = auth.actor()
    allocation["approved_at"] = store.now_iso()
    store.touch(allocation)

    # Link 2 — the lane's reserved volume.
    lane = store.lanes.get(allocation["lane_id"])
    if lane is not None:
        lane["unallocated_volume_loads"] -= allocation["allocated_volume_loads"]
        lane_svc.recompute_awarded_coverage(lane)
        store.touch(lane)

    # Link 3 — the event's coverage and diversity.
    lane_svc.recompute_coverage(event)
    store.touch(event)
    return responses.ok(allocation)


@bp.post("/freight-procurement/award-allocations/<allocation_id>/reject")
@auth.roles_required("CategoryManager")
def reject(allocation_id):
    allocation = helpers.get_allocation(allocation_id)
    payload = v.body()
    reason = v.string_field(payload, "rejection_reason", min_len=1)
    event = helpers.event_of(allocation)

    if allocation["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError("ERR_ALLOCATION_NOT_PROPOSED")
    if event is None or event["status"] != "AWARDING":
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")

    was_approved = allocation["status"] == "APPROVED"
    position = allocation["routing_position"]
    lane = store.lanes.get(allocation["lane_id"])

    # Link 1 — the rejection.
    allocation["status"] = "REJECTED"
    allocation["rejection_reason"] = reason
    store.touch(allocation)

    # Link 2 — the bid it referenced is no longer routed on the lane.
    bid = store.lane_bids.get(allocation["lane_bid_id"])
    if bid is not None and bid["status"] == "SHORTLISTED":
        bid["status"] = "NOT_AWARDED"
        store.touch(bid)

    # Link 3 — only an approved allocation held a debit.
    if was_approved and lane is not None:
        lane["unallocated_volume_loads"] += allocation["allocated_volume_loads"]
        lane_svc.recompute_awarded_coverage(lane)
        store.touch(lane)

    # Link 4 — a rejected PRIMARY promotes the lane's backups; rejecting a backup
    # promotes nothing because no gap opens above it.
    if position == "PRIMARY" and lane is not None:
        promoted = False
        for from_position, to_position in (("BACKUP_1", "PRIMARY"),
                                           ("BACKUP_2", "BACKUP_1")):
            for other in store.sorted_rows(store.allocations.values()):
                if (other["lane_id"] != lane["id"]
                        or other["optimization_run_id"]
                        != allocation["optimization_run_id"]):
                    continue
                if other["routing_position"] != from_position:
                    continue
                if other["status"] not in ("PROPOSED", "APPROVED"):
                    continue
                other["routing_position"] = to_position
                other["promoted_from_position"] = from_position
                store.touch(other)
                promoted = True
                break
        if promoted:
            optimize.rederive_lane_volumes(event, lane,
                                           allocation["optimization_run_id"])
            lane_svc.recompute_awarded_coverage(lane)
            store.touch(lane)

    lane_svc.recompute_coverage(event)
    store.touch(event)
    return responses.ok(allocation)
