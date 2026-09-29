"""Inspection cycles: creation, activation, the ops-run advance, close, reads."""

from flask import Blueprint

import calc
import domain
from auth import auth
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import get_int, lookup, page, pagination, body

bp = Blueprint("cycles", __name__, url_prefix="/fire-district")


def _cycle(cycle_id):
    return lookup("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")


@bp.post("/inspection-cycles")
def create_cycle():
    auth("ProgramAdmin")
    b = body()
    season_year = get_int(b, "season_year", minimum=2020, maximum=2100)
    notice_lead_days = get_int(b, "notice_lead_days", required=False, minimum=0, default=10)
    invoice_due_days = get_int(b, "invoice_due_days", required=False, minimum=1, default=45)
    # rung 8 — season_year is a natural key across the cycle collection.
    for existing in db.cycles.values():
        if existing["season_year"] == season_year:
            fail("ERR_APN_ALREADY_REGISTERED", "Season year %s is already claimed." % season_year)
    cycle = insert(db.cycles, {
        "season_year": season_year,
        "notice_lead_days": notice_lead_days,
        "invoice_due_days": invoice_due_days,
        "status": "PLANNING",
        "epoch": 0,
        "activated_at_utc": None,
        "closed_at_utc": None,
    })
    return created(jsonable(cycle))


@bp.post("/inspection-cycles/<cycle_id>/activate")
def activate_cycle(cycle_id):
    auth("ProgramAdmin")
    cycle = _cycle(cycle_id)
    if cycle["status"] != "PLANNING":
        fail("ERR_INVALID_STATE", "Only a PLANNING cycle can be activated.")
    for other in db.cycles.values():
        if other["id"] != cycle["id"] and other["status"] == "ACTIVE":
            fail("ERR_CYCLE_ALREADY_ACTIVE", "Another cycle is already ACTIVE.")
    cycle["status"] = "ACTIVE"
    cycle["activated_at_utc"] = db.clock
    touch(cycle)
    return ok(jsonable(cycle))


@bp.post("/inspection-cycles/<cycle_id>/advance")
def advance_cycle(cycle_id):
    auth("ProgramAdmin")
    cycle = _cycle(cycle_id)
    domain.require_active_cycle(cycle)

    # Step 1 — notices whose deadline has strictly passed lapse to OVERDUE.
    affected = []
    for notice in sort_created(list(db.notices.values())):
        if notice["status"] in ("ISSUED", "EXTENDED") and notice["deadline_utc"] < db.clock:
            notice["status"] = "OVERDUE"
            touch(notice)
            parcel = db.parcels.get(notice["parcel_id"])
            if parcel is not None and parcel not in affected:
                affected.append(parcel)

    # Step 2 — a consequence of step 1; the write is idempotent but still bumps.
    for parcel in affected:
        parcel["compliance_status"] = "NON_COMPLIANT"
        domain.recount_open_violations(parcel)
        touch(parcel)

    # Step 3 — invoices past due attach as liens.
    for order in sort_created(list(db.orders.values())):
        if order["status"] == "INVOICED" and order["invoice_due_utc"] < db.clock:
            order["status"] = "LIEN_FILED"
            order["lien_amount_cents"] = (
                order["total_recoverable_cents"] - order["paid_cents"]
            )
            touch(order)

    # Step 4 — waitlist promotion, program by program, in created_at order.
    for program in sort_created(list(db.programs.values())):
        if program["cycle_id"] != cycle["id"]:
            continue
        promoted = False
        for enrollment in domain.program_enrollments(program["id"]):
            if enrollment["status"] != "WAITLISTED":
                continue
            if program["reserved_slots"] >= program["capacity_slots"]:
                continue
            award = enrollment["award_cents"]
            if program["program_type"] == "COST_SHARE_GRANT":
                if award is None or program["budget_remaining_cents"] < award:
                    continue
                enrollment["reserved_amount_cents"] = award
            enrollment["status"] = "APPROVED"
            enrollment["waitlist_position"] = None
            domain.recount_program_reservations(program)
            touch(enrollment)
            touch(program, force=True)
            promoted = True
        if promoted:
            domain.renumber_waitlist(program)

    # Step 5 — the whole non-exempt inventory is re-ranked from scratch.
    domain.recompute_priority_ranks()

    # Step 6 — every community rate is recomputed under the community scope.
    communities = sort_created(list(db.communities.values()))
    for community in communities:
        domain.recompute_community(community, allow_lapse=False)

    # Step 7 — a consequence of step 6.
    for community in communities:
        rate = community["compliance_rate_pct"]
        if (
            community["status"] == "CERTIFIED"
            and rate is not None
            and rate < calc.COMMUNITY_LAPSE_FLOOR_PCT
        ):
            community["status"] = "LAPSED"
            community["lapse_count"] += 1
            touch(community)

    # Step 8 — the checkpoint counter.
    cycle["epoch"] += 1
    touch(cycle)
    return ok(jsonable(cycle))


@bp.post("/inspection-cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    auth("ProgramAdmin")
    cycle = _cycle(cycle_id)
    domain.require_active_cycle(cycle)
    for inspection in db.inspections.values():
        if (
            inspection["cycle_id"] == cycle["id"]
            and inspection["status"] in domain.LIVE_INSPECTION_STATUSES
        ):
            fail("ERR_INVALID_STATE", "Field work is still open on this cycle.")
    cycle["status"] = "CLOSED"
    cycle["closed_at_utc"] = db.clock
    touch(cycle)
    return ok(jsonable(cycle))


@bp.get("/inspection-cycles/<cycle_id>")
def read_cycle(cycle_id):
    auth("ProgramAdmin", "FireMarshal")
    return ok(jsonable(_cycle(cycle_id)))


@bp.get("/inspection-cycles/<cycle_id>/metrics")
def cycle_metrics(cycle_id):
    auth("ProgramAdmin", "FireMarshal")
    cycle = _cycle(cycle_id)
    return ok(jsonable(domain.district_metrics(cycle)))


@bp.get("/inspection-cycles/<cycle_id>/priority-queue")
def priority_queue(cycle_id):
    auth("ProgramAdmin", "FireMarshal")
    _cycle(cycle_id)
    limit, offset = pagination()
    candidates = [p for p in db.parcels.values() if not p["exemption_flag"]]
    ordered = sorted(
        candidates,
        key=lambda p: (
            p["inspection_priority_rank"] is None,
            p["inspection_priority_rank"] or 0,
            p["created_at"],
            p["_seq"],
        ),
    )
    window = page(ordered, limit, offset)
    return ok_list([jsonable(p) for p in window], limit, offset, len(ordered))
