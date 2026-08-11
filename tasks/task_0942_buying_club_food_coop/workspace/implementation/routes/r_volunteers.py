"""Volunteer shifts (5 endpoints) and the four-hop verification cascade."""

from decimal import Decimal

from flask import Blueprint

from core import serialize
from core.constants import (COMMISSION_VOLUNTEER_MIN_HOURS, ROLES, SHIFT_STATUSES,
                            VOLUNTEER_CREDIT_CENTS_PER_HOUR)
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_filter, free_filter,
                         gate_coordinator, gate_cycle_closed, gate_posted_ledger,
                         pagination, path_row, req_id, req_number,
                         rung_drop_coordinator)
from core.money import round_half_up
from core.store import DB, ordered, touch
from services import commission, credits, reconciliation

bp = Blueprint("volunteers", __name__)
R5 = list(ROLES)

LOGGABLE_DROP_RUN_STATES = ("OPEN", "QUALIFIED", "SUBMITTED", "RECEIVED", "SETTLED")


@bp.post("/volunteer-shifts")
@endpoint(["ClubAdmin", "DropCoordinator"])
def log_shift(ctx):
    drop_run = body_fk(ctx, "drop_run_id")                 # rung 5
    member = body_fk(ctx, "member_id")
    req_id(ctx, "drop_run_id")                             # rung 7
    req_id(ctx, "member_id")
    hours = req_number(ctx, "hours", minimum_exclusive=0)
    gate_cycle_closed(drop_run)                            # rung 9
    gate_coordinator(ctx)                                  # rung 11
    if drop_run["status"] not in LOGGABLE_DROP_RUN_STATES:  # rung 18
        raise ApiError("ERR_INVALID_DROP_RUN_STATE")
    rung_drop_coordinator(ctx, drop_run)                   # rung 27
    row = DB.insert("VolunteerShift", {
        "drop_run_id": drop_run["id"], "member_id": member["id"],
        "credit_grant_id": None, "hours": hours, "status": "LOGGED",
        "verified_by_user_id": None,
    })
    return created(serialize.volunteer_shift(row))


@bp.get("/volunteer-shifts")
@endpoint(R5)
def list_shifts(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", SHIFT_STATUSES)
    drop_run_id = free_filter(ctx, "drop_run_id")
    member_id = free_filter(ctx, "member_id")
    credit_grant_id = free_filter(ctx, "credit_grant_id")
    rows = []
    for row in DB.all("VolunteerShift"):
        if drop_run_id is not None and row["drop_run_id"] != drop_run_id:
            continue
        if member_id is not None and row["member_id"] != member_id:
            continue
        if credit_grant_id is not None and row["credit_grant_id"] != credit_grant_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/volunteer-shifts/<volunteer_shift_id>")
@endpoint(R5)
def read_shift(ctx, volunteer_shift_id):
    return ok(serialize.volunteer_shift(path_row("volunteer_shift_id", volunteer_shift_id)))


def _recompute_volunteer_hours(drop_run):
    total = Decimal("0")
    for shift in ordered([s for s in DB.volunteer_shifts.values()
                          if s["drop_run_id"] == drop_run["id"]]):
        if shift["status"] == "VERIFIED":
            total += Decimal(str(shift["hours"]))
    drop_run["verified_volunteer_hours"] = float(total)
    drop_run["volunteer_obligation_met"] = total >= Decimal(COMMISSION_VOLUNTEER_MIN_HOURS)
    touch(drop_run)


@bp.post("/volunteer-shifts/<volunteer_shift_id>/verify")
@endpoint(["ClubAdmin", "DropCoordinator"])
def verify_shift(ctx, volunteer_shift_id):
    shift = path_row("volunteer_shift_id", volunteer_shift_id)   # rung 4
    drop_run = DB.get("DropRun", shift["drop_run_id"])
    gate_cycle_closed(shift)                               # rung 9
    gate_coordinator(ctx)                                  # rung 11
    gate_posted_ledger(drop_run)                           # rung 12
    if shift["status"] != "LOGGED":                        # rung 23
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    rung_drop_coordinator(ctx, drop_run)                   # rung 27

    met_before = drop_run["volunteer_obligation_met"]
    # HOP 1
    shift["status"] = "VERIFIED"
    shift["verified_by_user_id"] = ctx.user_id
    # HOP 2
    _recompute_volunteer_hours(drop_run)
    amount = round_half_up(Decimal(str(shift["hours"]))
                           * Decimal(VOLUNTEER_CREDIT_CENTS_PER_HOUR))
    grant = credits.mint(shift["member_id"], amount, credits.default_expiry_iso(),
                         "VOLUNTEER")
    shift["credit_grant_id"] = grant["id"]
    touch(shift)
    # HOPS 3 and 4
    if not met_before and drop_run["volunteer_obligation_met"]:
        commission.adjust_for_volunteer(drop_run)
        reconciliation.recompute_downstream(drop_run)
    return ok(serialize.volunteer_shift(shift))


@bp.post("/volunteer-shifts/<volunteer_shift_id>/reject")
@endpoint(["ClubAdmin", "DropCoordinator"])
def reject_shift(ctx, volunteer_shift_id):
    shift = path_row("volunteer_shift_id", volunteer_shift_id)   # rung 4
    drop_run = DB.get("DropRun", shift["drop_run_id"])
    gate_cycle_closed(shift)                               # rung 9
    gate_coordinator(ctx)                                  # rung 11
    if shift["status"] != "LOGGED":                        # rung 23
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    rung_drop_coordinator(ctx, drop_run)                   # rung 27
    shift["status"] = "REJECTED"
    shift["verified_by_user_id"] = ctx.user_id
    touch(shift)
    return ok(serialize.volunteer_shift(shift))
