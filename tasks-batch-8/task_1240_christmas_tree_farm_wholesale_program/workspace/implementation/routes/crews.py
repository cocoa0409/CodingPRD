"""Crew and HarvestTicket endpoints (PRD 3.5)."""
from flask import Blueprint, request

from authz import require_role
from db import store
from errors import (crew_double_booked, crew_not_active, cut_exceeds_allocation,
                    forbidden, invalid_state, malformed,
                    outside_harvest_window, posture_forbids,
                    ticket_block_mismatch, ticket_not_voidable,
                    block_not_harvestable)
from helpers import (body, get_or_404, has_field, is_int, is_num, new_record,
                     paginate, req_field, req_int, req_num, req_str, touch)
from respond import success
from serialize import crew_out, ticket_out
from services import (block_of_lot, buckets_of_lot, check_lot_depleted,
                      compute_ticket_pay, season_of_block)
from timeutil import parse_date

bp = Blueprint("crews", __name__)


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------

@bp.post("/api/crews")
def create_crew():
    require_role("FarmManager")
    data = body()
    season_id = req_field(data, "season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season_id does not exist")
    season_id = req_str(data, "season_id")
    crew_code = req_str(data, "crew_code")
    size = req_int(data, "size", minimum=1)
    if any(c["season_id"] == season_id and c["crew_code"] == crew_code
           for c in store.crews.values()):
        raise malformed("crew_code must be unique within the season")
    # Posture (priority 7): crew hiring is permitted in any non-CLOSED posture.
    if store.seasons[season_id]["posture"] == "CLOSED":
        raise posture_forbids("The season is CLOSED")
    rec = new_record({
        "season_id": season_id,
        "crew_code": crew_code,
        "size": size,
        "status": "ACTIVE",
    })
    store.crews[rec["id"]] = rec
    return success(crew_out(rec), status=201)


@bp.get("/api/crews/<cid>")
def get_crew(cid):
    user_id, role = require_role("Owner", "FarmManager", "CrewLead")
    crew = get_or_404(store.crews, cid)
    if role == "CrewLead" and crew["id"] != user_id:
        raise forbidden("A crew lead may read only its own crew")
    return success(crew_out(crew))


@bp.get("/api/crews")
def list_crews():
    user_id, role = require_role("Owner", "FarmManager", "CrewLead")
    items = sorted(store.crews.values(), key=lambda c: c["_seq"])
    if role == "CrewLead":
        items = [c for c in items if c["id"] == user_id]
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [c for c in items if c["season_id"] == season_id]
    page, meta = paginate(items)
    return success([crew_out(c) for c in page], response_type="array",
                   pagination=meta)


@bp.post("/api/crews/<cid>/lay-off")
def lay_off_crew(cid):
    require_role("FarmManager")
    crew = get_or_404(store.crews, cid)
    if crew["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE crew can be laid off")
    crew["status"] = "LAID_OFF"
    touch(crew)
    return success(crew_out(crew))


# ---------------------------------------------------------------------------
# Harvest tickets
# ---------------------------------------------------------------------------

def _parse_lines(data):
    """Validate the lines array shape (priority 5). Returns the raw list."""
    raw = req_field(data, "lines")
    if not isinstance(raw, list) or not raw:
        raise malformed("Field lines must be a non-empty array")
    for line in raw:
        if not isinstance(line, dict):
            raise malformed("Each line must be an object")
        if not has_field(line, "allocation_id") or not isinstance(line["allocation_id"], str):
            raise malformed("Each line must carry an allocation_id string")
        if not has_field(line, "cut_count") or not is_int(line["cut_count"]) or line["cut_count"] < 1:
            raise malformed("Each line cut_count must be an integer >= 1")
    return raw


@bp.post("/api/harvest-tickets")
def create_ticket():
    user_id, role = require_role("CrewLead")
    data = body()
    # Ownership (priority 2): a crew lead posts only for its own crew.
    if has_field(data, "crew_id") and data["crew_id"] != user_id:
        raise forbidden("crew_id must equal the acting crew lead")
    # Existence of body FK references, left to right (priority 4):
    # crew_id, block_id, then each line's allocation_id in array order.
    crew_id = req_field(data, "crew_id")
    if isinstance(crew_id, str):
        get_or_404(store.crews, crew_id, "crew_id does not exist")
    block_id = req_field(data, "block_id")
    if isinstance(block_id, str):
        get_or_404(store.blocks, block_id, "block_id does not exist")
    if isinstance(data.get("lines"), list):
        for line in data["lines"]:
            if isinstance(line, dict) and isinstance(line.get("allocation_id"), str):
                get_or_404(store.allocations, line["allocation_id"],
                           "line allocation_id does not exist")
    # Well-formedness (priority 5).
    crew_id = req_str(data, "crew_id")
    block_id = req_str(data, "block_id")
    raw_date = req_field(data, "work_date")
    try:
        work_date = parse_date(raw_date)
    except ValueError:
        raise malformed("Field work_date must be an ISO date (YYYY-MM-DD)")
    hours_worked = req_num(data, "hours_worked")
    if hours_worked <= 0:
        raise malformed("Field hours_worked must be > 0")
    lines = _parse_lines(data)

    crew = store.crews[crew_id]
    block = store.blocks[block_id]
    season = season_of_block(block)
    # Posture (priority 7): ticket posting requires HARVEST.
    if season["posture"] != "HARVEST":
        raise posture_forbids("Harvest tickets require HARVEST posture")
    # Temporal (priority 9): work_date inside the harvest window, inclusive.
    if not (season["harvest_window_start"] <= work_date <= season["harvest_window_end"]):
        raise outside_harvest_window("work_date is outside the harvest window")
    # Referential (priority 11): the block must be HARVESTABLE.
    if block["rotation_state"] != "HARVESTABLE":
        raise block_not_harvestable("The block is not HARVESTABLE")
    # Referential (priority 14): the crew must be ACTIVE.
    if crew["status"] != "ACTIVE":
        raise crew_not_active("The crew is not ACTIVE")
    # Referential (priority 16): every line's allocation must belong to a
    # crop lot of the ticket's block.
    allocs = [store.allocations[line["allocation_id"]] for line in lines]
    for alloc in allocs:
        bucket = store.stand_buckets[alloc["bucket_id"]]
        lot = store.crop_lots[bucket["crop_lot_id"]]
        if lot["block_id"] != block_id:
            raise ticket_block_mismatch(
                "A line's allocation does not belong to this block")
    # Constraint (priority 24): at most one POSTED ticket per crew per date.
    if any(t["crew_id"] == crew_id and t["work_date"] == work_date
           and t["status"] == "POSTED" for t in store.tickets.values()):
        raise crew_double_booked("The crew already has a POSTED ticket on this date")
    # Constraint (priority 27): no line may exceed its allocation's uncut
    # remainder (accumulating across repeated allocations within the ticket).
    pending = {}
    for alloc, line in zip(allocs, lines):
        committed = pending.get(alloc["id"], alloc["cut_qty"])
        if alloc["status"] not in ("RESERVED", "CUT") or \
                line["cut_count"] > alloc["quantity"] - committed:
            raise cut_exceeds_allocation(
                "cut_count exceeds the allocation's uncut remainder")
        pending[alloc["id"]] = committed + line["cut_count"]

    # Apply the cut effects.
    touched_lots = set()
    for alloc, line in zip(allocs, lines):
        cut = line["cut_count"]
        bucket = store.stand_buckets[alloc["bucket_id"]]
        alloc["cut_qty"] += cut
        if alloc["cut_qty"] == alloc["quantity"]:
            alloc["status"] = "CUT"
        touch(alloc)
        bucket["standing_count"] -= cut
        bucket["reserved_count"] -= cut
        bucket["cut_cumulative"] += cut
        touch(bucket)
        touched_lots.add(bucket["crop_lot_id"])
    for lot_id in touched_lots:
        check_lot_depleted(store.crop_lots[lot_id])

    # Pay is computed at creation and frozen on the ticket.
    lines_with_class = [
        (store.stand_buckets[alloc["bucket_id"]]["height_class"], line["cut_count"])
        for alloc, line in zip(allocs, lines)
    ]
    piece, floor, gross, basis = compute_ticket_pay(
        lines_with_class, crew["size"], hours_worked)
    rec = new_record({
        "crew_id": crew_id,
        "block_id": block_id,
        "work_date": work_date,
        "hours_worked": hours_worked,
        "lines": [{"allocation_id": line["allocation_id"],
                   "cut_count": line["cut_count"]} for line in lines],
        "piece_total_cents": piece,
        "hourly_floor_cents": floor,
        "gross_pay_cents": gross,
        "pay_basis": basis,
        "status": "POSTED",
    })
    store.tickets[rec["id"]] = rec
    return success(ticket_out(rec), status=201)


@bp.get("/api/harvest-tickets/<tid>")
def get_ticket(tid):
    user_id, role = require_role("Owner", "FarmManager", "CrewLead")
    ticket = get_or_404(store.tickets, tid)
    if role == "CrewLead" and ticket["crew_id"] != user_id:
        raise forbidden("A crew lead may read only its own crew's tickets")
    return success(ticket_out(ticket))


@bp.get("/api/harvest-tickets")
def list_tickets():
    user_id, role = require_role("Owner", "FarmManager", "CrewLead")
    items = sorted(store.tickets.values(), key=lambda t: t["_seq"])
    if role == "CrewLead":
        items = [t for t in items if t["crew_id"] == user_id]
    crew_id = request.args.get("crew_id")
    block_id = request.args.get("block_id")
    if crew_id is not None:
        items = [t for t in items if t["crew_id"] == crew_id]
    if block_id is not None:
        items = [t for t in items if t["block_id"] == block_id]
    page, meta = paginate(items)
    return success([ticket_out(t) for t in page], response_type="array",
                   pagination=meta)


@bp.post("/api/harvest-tickets/<tid>/void")
def void_ticket(tid):
    require_role("FarmManager")
    ticket = get_or_404(store.tickets, tid)
    # State (priority 6): only a POSTED ticket can be voided.
    if ticket["status"] != "POSTED":
        raise invalid_state("Only a POSTED ticket can be voided")
    block = store.blocks[ticket["block_id"]]
    season = season_of_block(block)
    # Referential (priority 18): void requires HARVEST posture and no line
    # allocation already loaded onto a truck.
    if season["posture"] != "HARVEST":
        raise ticket_not_voidable("Tickets can be voided only in HARVEST posture")
    allocs = [store.allocations[line["allocation_id"]] for line in ticket["lines"]]
    if any(a["status"] == "LOADED" or a["loaded_qty"] > 0 for a in allocs):
        raise ticket_not_voidable("A line's allocation has already been loaded")
    # Full compensating reversal of the cut effects.
    touched_lots = set()
    for alloc, line in zip(allocs, ticket["lines"]):
        cut = line["cut_count"]
        bucket = store.stand_buckets[alloc["bucket_id"]]
        alloc["cut_qty"] -= cut
        if alloc["status"] == "CUT" and alloc["cut_qty"] < alloc["quantity"]:
            alloc["status"] = "RESERVED"
        touch(alloc)
        bucket["standing_count"] += cut
        bucket["reserved_count"] += cut
        bucket["cut_cumulative"] -= cut
        touch(bucket)
        touched_lots.add(bucket["crop_lot_id"])
    ticket["status"] = "VOIDED"
    touch(ticket)
    return success(ticket_out(ticket))
