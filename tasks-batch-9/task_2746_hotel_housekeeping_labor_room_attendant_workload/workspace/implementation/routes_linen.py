"""Linen par levels, laundry turnaround and shortage escalation -- PRD 3.8."""

from flask import Blueprint, request

import derive
from auth import HOUSEKEEPING_DIRECTOR, LAUNDRY_LEAD, SUPERVISOR, authenticate
from envelope import created, filtered, ok, paginate
from errors import ApiError
from serialize import laundry_cycle_out, linen_item_out
from store import STORE, base_record, touch
from validate import read_body, vdatetime, venum, vint, vstr

bp = Blueprint("linen", __name__)


# ---------------------------------------------------------------------------
# Linen inventory lines
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/linen-items")
def create_linen_item():
    authenticate((HOUSEKEEPING_DIRECTOR, LAUNDRY_LEAD))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    linen_type = venum(body, "linen_type", derive.LINEN_TYPES)
    total_owned_sets = vint(body, "total_owned_sets", 0, 100000)
    initial_soiled_sets = vint(
        body, "initial_soiled_sets", 0, 100000, required=False, default=0
    )
    if initial_soiled_sets > total_owned_sets:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "initial_soiled_sets must not exceed total_owned_sets.",
        )

    prop = derive.get_property(STORE, property_id)

    for existing in derive.linen_items_of_property(STORE, prop["id"]):
        if existing["linen_type"] == linen_type:
            raise ApiError(
                "ERR_LINEN_TYPE_DUPLICATE",
                "A %s line already exists for this property." % linen_type,
            )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "linen_type": linen_type,
        "total_owned_sets": total_owned_sets,
        "on_hand_clean": total_owned_sets - initial_soiled_sets,
        "in_laundry": 0,
        "soiled_queue": initial_soiled_sets,
        "par_required_sets": 0,
        "coverage_ratio": None,
        "shortage_status": "OK",
    })
    STORE.linen_items[row["id"]] = row
    # The derived figures are computed at creation, but the line is minted at
    # version 1 rather than bumped by its own creation.
    derive.recompute_linen(STORE, row, bump=False)
    return created(linen_item_out(STORE, row))


@bp.get("/housekeeping/linen-items/<lid>")
def read_linen_item(lid):
    authenticate(None)
    row = derive.get_linen_item(STORE, lid)
    return ok(linen_item_out(STORE, row))


@bp.get("/housekeeping/linen-items")
def list_linen_items():
    authenticate(None)
    rows = filtered(
        list(STORE.linen_items.values()),
        request.args,
        {
            "property_id": ("property_id", None),
            "linen_type": ("linen_type", None),
            "shortage_status": ("shortage_status", None),
        },
    )
    return paginate(rows, request.args, lambda r: linen_item_out(STORE, r))


@bp.post("/housekeeping/linen-items/<lid>/soil")
def soil_linen(lid):
    authenticate((SUPERVISOR, LAUNDRY_LEAD))
    body = read_body()
    sets = vint(body, "sets", 0, 100000)

    item = derive.get_linen_item(STORE, lid)
    if item["on_hand_clean"] - sets < 0:
        # PRD 2.11 reserves ERR_LINEN_STOCK_INSUFFICIENT for the completion debit and
        # the laundry dispatch, so an over-large manual soiling is a request error.
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "sets exceeds the %d sets on the clean shelf." % item["on_hand_clean"],
        )

    item["on_hand_clean"] = item["on_hand_clean"] - sets
    item["soiled_queue"] = item["soiled_queue"] + sets
    derive.recompute_linen(STORE, item, bump=True)
    return ok(linen_item_out(STORE, item))


# ---------------------------------------------------------------------------
# Laundry cycles
# ---------------------------------------------------------------------------

def _overlapping_batch_sets(store, property_id, start, end):
    """The plant capacity rule is collective: every QUEUED or LATE_ESCALATED cycle of
    the property whose [dispatched_at, expected_return_at) window overlaps the new
    one contributes its batch_sets."""
    total = 0
    item_ids = set(i["id"] for i in derive.linen_items_of_property(store, property_id))
    for cycle in store.laundry_cycles.values():
        if cycle["linen_item_id"] not in item_ids:
            continue
        if cycle["status"] not in ("QUEUED", "LATE_ESCALATED"):
            continue
        if cycle["dispatched_at"] < end and start < cycle["expected_return_at"]:
            total += int(cycle["batch_sets"])
    return total


@bp.post("/housekeeping/laundry-cycles")
def create_laundry_cycle():
    authenticate((LAUNDRY_LEAD,))
    body = read_body()
    linen_item_id = vstr(body, "linen_item_id", 1, None)
    batch_sets = vint(body, "batch_sets", 1, 100000)
    dispatched_at = vdatetime(body, "dispatched_at", required=True, nullable=False)
    expected_return_at = vdatetime(body, "expected_return_at", required=True, nullable=False)
    expected_linen_item_version = vint(body, "expected_linen_item_version", 0, None)

    item = derive.get_linen_item(STORE, linen_item_id)

    # Rung 9: optimistic concurrency on the linen line.
    if expected_linen_item_version != item["version"]:
        raise ApiError(
            "ERR_STALE_LINEN_VERSION",
            "expected_linen_item_version %d does not match the current version %d."
            % (expected_linen_item_version, item["version"]),
        )

    if expected_return_at <= dispatched_at:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "expected_return_at must be strictly after dispatched_at.",
        )

    prop = STORE.properties[item["property_id"]]
    in_flight = _overlapping_batch_sets(
        STORE, item["property_id"], dispatched_at, expected_return_at
    )
    if in_flight + batch_sets > prop["laundry_capacity_sets"]:
        raise ApiError(
            "ERR_LAUNDRY_CAPACITY_EXCEEDED",
            "Overlapping batches would reach %d sets against a plant capacity of %d."
            % (in_flight + batch_sets, prop["laundry_capacity_sets"]),
        )

    if item["soiled_queue"] - batch_sets < 0:
        raise ApiError(
            "ERR_LINEN_STOCK_INSUFFICIENT",
            "The soiled queue holds %d sets and the dispatch asks for %d."
            % (item["soiled_queue"], batch_sets),
        )

    row = base_record(STORE)
    row.update({
        "linen_item_id": item["id"],
        "batch_sets": batch_sets,
        "dispatched_at": dispatched_at,
        "expected_return_at": expected_return_at,
        "returned_at": None,
        "returned_sets": None,
        "status": "QUEUED",
        "turnaround_minutes": None,
        "sla_breach": False,
        "linen_item_version_after": None,
    })
    STORE.laundry_cycles[row["id"]] = row

    item["soiled_queue"] = item["soiled_queue"] - batch_sets
    item["in_laundry"] = item["in_laundry"] + batch_sets
    derive.recompute_linen(STORE, item, bump=True)
    row["linen_item_version_after"] = item["version"]
    return created(laundry_cycle_out(STORE, row))


@bp.get("/housekeeping/laundry-cycles/<cid>")
def read_laundry_cycle(cid):
    authenticate(None)
    row = derive.get_laundry_cycle(STORE, cid)
    return ok(laundry_cycle_out(STORE, row))


@bp.get("/housekeeping/laundry-cycles")
def list_laundry_cycles():
    authenticate(None)
    rows = filtered(
        list(STORE.laundry_cycles.values()),
        request.args,
        {"linen_item_id": ("linen_item_id", None), "status": ("status", None)},
    )
    return paginate(rows, request.args, lambda r: laundry_cycle_out(STORE, r))


def _sweep_deep_cleans(store, property_id):
    """Hops three to five of the LATE_ESCALATED cascade: defer every still-ASSIGNED
    DEEP_CLEAN of the property whose forecast day is still PUBLISHED, then recompute
    the affected rosters and their forecast days."""
    victims = []
    for assignment in store.assignments.values():
        if assignment["service_type"] != "DEEP_CLEAN" or assignment["status"] != "ASSIGNED":
            continue
        roster = store.rosters.get(assignment["roster_id"])
        if roster is None:
            continue
        day = store.forecast_days.get(roster["forecast_day_id"])
        if day is None or day["property_id"] != property_id or day["status"] != "PUBLISHED":
            continue
        victims.append(assignment)

    victims.sort(key=lambda a: (a["created_at"], a["_seq"]))
    roster_ids = []
    for assignment in victims:
        assignment["status"] = "DEFERRED"
        touch(store, assignment)
        if assignment["roster_id"] not in roster_ids:
            roster_ids.append(assignment["roster_id"])

    day_ids = []
    for roster_id in roster_ids:
        roster = store.rosters[roster_id]
        changed = derive.recompute_roster(store, roster, bump=True)
        if changed and roster["forecast_day_id"] not in day_ids:
            day_ids.append(roster["forecast_day_id"])
    for day_id in day_ids:
        day = store.forecast_days.get(day_id)
        if day is not None:
            derive.recompute_forecast_allocated(store, day, bump=True)


@bp.post("/housekeeping/laundry-cycles/<cid>/return")
def return_laundry_cycle(cid):
    authenticate((LAUNDRY_LEAD,))
    body = read_body()
    returned_at = vdatetime(body, "returned_at", required=False, default=None)
    returned_sets = vint(body, "returned_sets", 0, 100000, required=False, default=None)

    cycle = derive.get_laundry_cycle(STORE, cid)
    if cycle["status"] != "QUEUED":
        raise ApiError("ERR_CYCLE_NOT_QUEUED", "Laundry cycle is not QUEUED.")

    if returned_sets is None:
        returned_sets = cycle["batch_sets"]
    if returned_sets > cycle["batch_sets"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "returned_sets must not exceed batch_sets."
        )
    if returned_at is None:
        returned_at = STORE.now()
    if returned_at < cycle["dispatched_at"]:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "returned_at must be at or after dispatched_at.",
        )

    item = derive.get_linen_item(STORE, cycle["linen_item_id"])
    prop = STORE.properties[item["property_id"]]

    # Hop one: the turnaround and the SLA verdict.
    turnaround, breach = derive.laundry_turnaround(
        cycle["dispatched_at"], returned_at, prop["laundry_sla_minutes"]
    )
    cycle["returned_at"] = returned_at
    cycle["returned_sets"] = returned_sets
    cycle["turnaround_minutes"] = turnaround
    cycle["sla_breach"] = breach
    cycle["status"] = "LATE_ESCALATED" if breach else "RETURNED"

    # Hop two: the sets come home, and any shortfall is written off against
    # total_owned_sets so the ledger identity of PRD 2.11 survives.
    shortfall = cycle["batch_sets"] - returned_sets
    item["in_laundry"] = item["in_laundry"] - cycle["batch_sets"]
    item["on_hand_clean"] = item["on_hand_clean"] + returned_sets
    if shortfall > 0:
        item["total_owned_sets"] = item["total_owned_sets"] - shortfall
    derive.recompute_linen(STORE, item, bump=True)

    cycle["linen_item_version_after"] = item["version"]
    touch(STORE, cycle)

    if breach:
        # Hops three to five: a late batch reaches all the way through to the day's
        # conserved credit total.
        _sweep_deep_cleans(STORE, item["property_id"])

    return ok(laundry_cycle_out(STORE, cycle))


@bp.post("/housekeeping/laundry-cycles/<cid>/void")
def void_laundry_cycle(cid):
    authenticate((LAUNDRY_LEAD,))
    cycle = derive.get_laundry_cycle(STORE, cid)
    if cycle["status"] != "QUEUED":
        raise ApiError("ERR_CYCLE_NOT_QUEUED", "Laundry cycle is not QUEUED.")

    item = derive.get_linen_item(STORE, cycle["linen_item_id"])
    # The exact compensation of the dispatch.
    item["in_laundry"] = item["in_laundry"] - cycle["batch_sets"]
    item["soiled_queue"] = item["soiled_queue"] + cycle["batch_sets"]
    derive.recompute_linen(STORE, item, bump=True)

    cycle["status"] = "VOIDED"
    cycle["linen_item_version_after"] = item["version"]
    touch(STORE, cycle)
    return ok(laundry_cycle_out(STORE, cycle))
