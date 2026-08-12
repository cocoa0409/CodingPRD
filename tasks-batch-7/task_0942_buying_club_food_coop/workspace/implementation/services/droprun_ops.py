"""Drop run creation, the merge cascade and the roll-forward cascade."""

from datetime import timedelta

from core import clock
from core.constants import ROUTE_TURNAROUND_HOURS
from core.errors import ApiError
from core.store import DB, ordered, touch
from services import recompute


def route_run_for(cycle, route_id, mint=True):
    """The cycle's RouteRun for a route, minted on first use subject to the
    48-hour route turnaround rule (rung 37)."""
    for run in recompute.route_runs_of_cycle(cycle):
        if run["route_id"] == route_id:
            return run
    if not mint:
        return None
    _assert_no_window_conflict(cycle, route_id)
    return DB.insert("RouteRun", {
        "cycle_id": cycle["id"], "route_id": route_id, "status": "PLANNED",
        "aggregated_subtotal_cents": 0, "supplier_invoice_cents": 0,
        "freight_cents": 0, "invoice_recorded_by_user_id": None,
        "cold_pallet_count": 0, "dry_pallet_count": 0, "reefer_slots_used": 0,
        "reefer_surcharge_cents": 0, "received_subtotal_cents": 0,
    })


def _assert_no_window_conflict(cycle, route_id):
    buffer = timedelta(hours=ROUTE_TURNAROUND_HOURS)
    new_opens = clock.parse(cycle["opens_at"])
    new_cutoff = clock.parse(cycle["cutoff_at"])
    for run in DB.all("RouteRun"):
        if run["route_id"] != route_id or run["cycle_id"] == cycle["id"]:
            continue
        other = DB.get("Cycle", run["cycle_id"])
        if other is None:
            continue
        other_opens = clock.parse(other["opens_at"])
        other_cutoff = clock.parse(other["cutoff_at"])
        if new_opens < other_cutoff + buffer and other_opens < new_cutoff + buffer:
            raise ApiError("ERR_ROUTE_WINDOW_CONFLICT")


def create_drop_run(cycle, drop_point):
    route_run = route_run_for(cycle, drop_point["route_id"])
    return DB.insert("DropRun", {
        "cycle_id": cycle["id"],
        "drop_point_id": drop_point["id"],
        "route_run_id": route_run["id"],
        "coordinator_member_id": drop_point["coordinator_member_id"],
        "merged_into_drop_run_id": None,
        "status": "OPEN",
        "subtotal_cents": 0,
        "discounted_subtotal_cents": 0,
        "received_subtotal_cents": 0,
        "verified_volunteer_hours": 0,
        "volunteer_obligation_met": False,
        "freight_alloc_cents": 0,
        "reefer_alloc_cents": 0,
        "rollforward_count": 0,
    })


def merge(source, target):
    """The depth-4 merge cascade."""
    # HOP 1 — the source empties into the target.
    source["status"] = "MERGED"
    source["merged_into_drop_run_id"] = target["id"]
    source["subtotal_cents"] = 0
    source["discounted_subtotal_cents"] = 0
    touch(source)
    # HOP 2 — every member order that pointed at the source is repointed.
    for order in recompute.orders_of_drop_run(source):
        order["drop_run_id"] = target["id"]
        touch(order)
    # HOP 3 — the target's subtotals are recomputed.
    subtotal, discounted = recompute.live_drop_subtotal(target)
    target["subtotal_cents"] = subtotal
    target["discounted_subtotal_cents"] = discounted
    touch(target)              # the merge always bumps both runs' versions
    # HOP 4 — the route run's aggregate is recomputed.
    route_run = DB.get("RouteRun", target["route_run_id"])
    if route_run is not None:
        recompute.recompute_route_aggregate(route_run)
    return source


def roll_forward(source, target_cycle):
    """The cross-cycle depth-5 cascade."""
    drop_point = DB.get("DropPoint", source["drop_point_id"])

    # HOP 1 — the source rolls.
    source["rollforward_count"] += 1
    source["status"] = "ROLLED_FORWARD"
    touch(source)

    # HOP 2 — a new OPEN drop run on the target cycle, inheriting the count.
    route_run = route_run_for(target_cycle, drop_point["route_id"])
    new_run = DB.insert("DropRun", {
        "cycle_id": target_cycle["id"],
        "drop_point_id": drop_point["id"],
        "route_run_id": route_run["id"],
        "coordinator_member_id": drop_point["coordinator_member_id"],
        "merged_into_drop_run_id": None,
        "status": "OPEN",
        "subtotal_cents": 0,
        "discounted_subtotal_cents": 0,
        "received_subtotal_cents": 0,
        "verified_volunteer_hours": 0,
        "volunteer_obligation_met": False,
        "freight_alloc_cents": 0,
        "reefer_alloc_cents": 0,
        "rollforward_count": source["rollforward_count"],
    })

    # HOPS 3-5 — orders, lines, then the source lines are consumed.
    for order in recompute.orders_of_drop_run(source):
        opted_in = [l for l in recompute.lines_of_order(order) if l["rollover_opt_in"]]
        if not opted_in:
            continue
        new_order = DB.insert("MemberOrder", new_order_fields(order["member_id"],
                                                              new_run["id"]))
        for line in ordered(opted_in):
            qty = line["short_units"] if line["status"] == "SHORT_FILLED" else line["qty_units"]
            DB.insert("OrderLine", {
                "member_order_id": new_order["id"],
                "item_id": line["item_id"],
                "qty_units": qty,
                "rollover_opt_in": line["rollover_opt_in"],
                "substitution_pref": line["substitution_pref"],
                "rolled_from_order_line_id": line["id"],
                "status": "REQUESTED",
                "bound_case_price_cents": 0,
                "unit_price_cents": 0,
                "is_split_unit": False,
                "split_fee_per_unit_cents": 0,
                "confirmed_units": 0,
                "allocated_units": 0,
                "short_units": 0,
                "allocation_remainder_rank": 0,
                "line_gross_cents": 0,
            })
            line["status"] = "ROLLED_FORWARD"
            touch(line)

    recompute.recompute_live_drop_subtotal(new_run)
    return source


def new_order_fields(member_id, drop_run_id):
    return {
        "member_id": member_id,
        "drop_run_id": drop_run_id,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "gross_cents": 0,
        "split_fee_cents": 0,
        "tier_discount_cents": 0,
        "freight_alloc_cents": 0,
        "reefer_alloc_cents": 0,
        "pre_credit_total_cents": 0,
        "credit_applied_cents": 0,
        "actual_total_cents": 0,
        "estimated_total_cents": 0,
        "authorized_amount_cents": 0,
        "captured_cents": 0,
        "refunded_cents": 0,
    }
