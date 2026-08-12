"""RentScheduleLine and EscalationStep endpoints."""

from flask import Blueprint

from db import db, new_resource, touch
from errors import err
from response import success_object
from services import calc
from services.validate import (
    body, req_int, req_enum, req_date, opt_string, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("schedules", __name__)

STEP_KINDS = {"FIXED_PCT", "CPI_LOOKUP", "STEPPED_AMOUNT"}


@bp.post("/lease-admin/leases/<lease_id>/rent-schedule-lines")
def create_line(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    base_rent_cents = req_int(data, "base_rent_cents", min_v=0)
    escalation_step_id = opt_string(data, "escalation_step_id")
    # Temporal well-formedness (pipeline step 5).
    if calc.d(period_start) >= calc.d(period_end):
        err("ERR_INVALID_DATE_RANGE", "period_start must precede period_end")
    # Referential integrity (pipeline step 8).
    step = None
    if escalation_step_id is not None:
        step = db["escalation_steps"].get(escalation_step_id)
        if step is None or step["lease_id"] != lease_id:
            err("ERR_REFERENTIAL_INTEGRITY",
                "escalation_step_id must reference an EscalationStep on the same lease")
    # Schedule-overlap guard (pipeline step 9): half-open overlap.
    ns, ne = calc.d(period_start), calc.d(period_end)
    for other in db["rent_schedule_lines"].values():
        if other["lease_id"] != lease_id:
            continue
        if ns < calc.d(other["period_end"]) and ne > calc.d(other["period_start"]):
            err("ERR_SCHEDULE_OVERLAP",
                "New line overlaps an existing schedule line on the same lease")
    lid, common = new_resource()
    line = {
        **common,
        "lease_id": lease_id,
        "period_start": period_start,
        "period_end": period_end,
        "base_rent_cents": base_rent_cents,
        "escalation_step_id": escalation_step_id,
        "effective_rent_cents": 0,
    }
    line["effective_rent_cents"] = calc.escalated_rent_for_period(line, step)
    db["rent_schedule_lines"][lid] = line
    calc.recompute_cached_annual_rent(lease)
    touch(lease)
    return success_object(line, status=201)


@bp.get("/lease-admin/leases/<lease_id>/rent-schedule-lines")
def list_lines(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [l for l in db["rent_schedule_lines"].values()
         if l["lease_id"] == lease_id])


@bp.get("/lease-admin/rent-schedule-lines/<line_id>")
def get_line(line_id):
    return success_object(
        get_child_or_404("rent_schedule_lines", line_id, "RentScheduleLine"))


@bp.get("/lease-admin/rent-schedule-lines")
def list_lines_filtered():
    return list_response(db["rent_schedule_lines"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("escalation_step_id"),
         lambda r, v: r["escalation_step_id"] == v),
    ])


@bp.post("/lease-admin/leases/<lease_id>/escalation-steps")
def create_step(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    step_index = req_int(data, "step_index", min_v=1)
    kind = req_enum(data, "kind", STEP_KINDS)
    # Exactly one magnitude per kind (pipeline step 4).
    if kind in ("FIXED_PCT", "CPI_LOOKUP"):
        pct_bps = req_int(data, "pct_bps", min_v=0, max_v=100000)
        if data.get("amount_cents") is not None:
            err("ERR_INVALID_REQUEST",
                "amount_cents is only allowed for kind=STEPPED_AMOUNT")
        amount_cents = None
    else:
        amount_cents = req_int(data, "amount_cents", min_v=0)
        if data.get("pct_bps") is not None:
            err("ERR_INVALID_REQUEST",
                "pct_bps is only allowed for kind=FIXED_PCT or CPI_LOOKUP")
        pct_bps = None
    effective_on = req_date(data, "effective_on")
    # step_index unique within lease.
    for s in db["escalation_steps"].values():
        if s["lease_id"] == lease_id and s["step_index"] == step_index:
            err("ERR_INVALID_REQUEST",
                "step_index must be unique within the lease")
    sid, common = new_resource()
    step = {
        **common,
        "lease_id": lease_id,
        "step_index": step_index,
        "kind": kind,
        "pct_bps": pct_bps,
        "amount_cents": amount_cents,
        "effective_on": effective_on,
    }
    db["escalation_steps"][sid] = step
    # Recompute any schedule lines already referencing this step.
    changed = False
    for line in db["rent_schedule_lines"].values():
        if line["lease_id"] == lease_id and \
           line["escalation_step_id"] == sid:
            line["effective_rent_cents"] = calc.escalated_rent_for_period(
                line, step)
            touch(line)
            changed = True
    if changed:
        calc.recompute_cached_annual_rent(lease)
        touch(lease)
    return success_object(step, status=201)


@bp.get("/lease-admin/leases/<lease_id>/escalation-steps")
def list_steps(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [s for s in db["escalation_steps"].values()
         if s["lease_id"] == lease_id])


@bp.get("/lease-admin/escalation-steps/<step_id>")
def get_step(step_id):
    return success_object(
        get_child_or_404("escalation_steps", step_id, "EscalationStep"))


@bp.get("/lease-admin/escalation-steps")
def list_steps_filtered():
    return list_response(db["escalation_steps"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
    ])
