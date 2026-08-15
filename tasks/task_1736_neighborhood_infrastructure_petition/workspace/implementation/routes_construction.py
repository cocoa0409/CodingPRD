"""ConstructionPhase and ChangeOrder endpoints (§3.6)."""
from datetime import datetime, timezone

from flask import Blueprint

import errors
import services
import shape
from envelope import ok_object
from helpers import get_or_404, list_response, sort_created
from security import STAFF_ROLES, authenticate, require_role
from serializers import ser_change_order, ser_phase
from store import STORE, new_id, now, touch

bp = Blueprint("construction", __name__)


def _phase_or_404(pid):
    return get_or_404("phases", pid, errors.PHASE_NOT_FOUND, "Construction phase not found")


def _co_or_404(cid):
    return get_or_404("change_orders", cid, errors.CHANGE_ORDER_NOT_FOUND,
                      "Change order not found")


@bp.route("/construction-phases", methods=["POST"])
def create_phase():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    name = shape.req_str(body, "name")
    crew_name = shape.req_str(body, "crew_name")
    start_d = shape.req_date(body, "start_date")
    end_d = shape.req_date(body, "end_date")
    if end_d < start_d:
        errors.raise_err(errors.INVALID_REQUEST, "end_date must be >= start_date")
    cost = shape.req_int(body, "estimated_cost_cents")
    if cost <= 0:
        errors.raise_err(errors.INVALID_REQUEST, "estimated_cost_cents must be > 0")
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    if d["status"] not in ("APPROVED", "CONSTRUCTION"):
        errors.raise_err(errors.DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION,
                         "District must be APPROVED or under CONSTRUCTION")
    if not services.check_season(d, start_d, end_d):
        errors.raise_err(errors.SEASON_WINDOW_VIOLATION,
                         "Phase dates fall outside the district construction season")
    if not services.check_crew_buffer(d, crew_name, start_d, end_d):
        errors.raise_err(errors.PHASE_SCHEDULE_CONFLICT,
                         "Same-crew phases require a >= 5 calendar-day gap")
    if not services.check_capacity(d, start_d, end_d):
        errors.raise_err(errors.CONSTRUCTION_CAPACITY_EXCEEDED,
                         "At most 2 phases may run concurrently")
    ts = now()
    p = {
        "id": new_id(),
        "district_id": district_id,
        "name": name,
        "crew_name": crew_name,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "estimated_cost_cents": cost,
        "status": "PLANNED",
        "started_at": None,
        "completed_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("phases", p)
    return ok_object(ser_phase(p), 201)


@bp.route("/construction-phases/<pid>", methods=["GET"])
def get_phase(pid):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    return ok_object(ser_phase(_phase_or_404(pid)))


@bp.route("/construction-phases/<pid>/start", methods=["POST"])
def start_phase(pid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    p = _phase_or_404(pid)
    if p["status"] != "PLANNED":
        errors.raise_err(errors.PHASE_NOT_PLANNED, "Phase must be PLANNED to start")
    d = STORE.districts[p["district_id"]]
    if d["status"] not in ("APPROVED", "CONSTRUCTION"):
        errors.raise_err(errors.DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION,
                         "District must be APPROVED or under CONSTRUCTION")
    start_dt = datetime.strptime(p["start_date"], "%Y-%m-%d").replace(
        tzinfo=timezone.utc)
    if now() < start_dt:
        errors.raise_err(errors.PHASE_START_NOT_REACHED,
                         "The phase start date has not been reached")
    p["status"] = "IN_PROGRESS"
    p["started_at"] = now()
    touch(p)
    if d["status"] == "APPROVED":
        d["status"] = "CONSTRUCTION"
        touch(d)
    return ok_object(ser_phase(p))


@bp.route("/construction-phases/<pid>/complete", methods=["POST"])
def complete_phase(pid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    p = _phase_or_404(pid)
    if p["status"] != "IN_PROGRESS":
        errors.raise_err(errors.PHASE_NOT_IN_PROGRESS,
                         "Phase must be IN_PROGRESS to complete")
    p["status"] = "COMPLETED"
    p["completed_at"] = now()
    touch(p)
    return ok_object(ser_phase(p))


@bp.route("/construction-phases/<pid>/cancel", methods=["POST"])
def cancel_phase(pid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    p = _phase_or_404(pid)
    if p["status"] != "PLANNED":
        errors.raise_err(errors.PHASE_NOT_PLANNED, "Phase must be PLANNED to cancel")
    p["status"] = "CANCELLED"
    touch(p)
    return ok_object(ser_phase(p))


@bp.route("/construction-phases/<pid>/change-orders", methods=["GET"])
def phase_change_orders(pid):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    _phase_or_404(pid)
    records = [c for c in STORE.change_orders.values() if c["phase_id"] == pid]
    return list_response(sort_created(records), ser_change_order, paginated=False)


# --- change orders ---

@bp.route("/change-orders", methods=["POST"])
def create_change_order():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    phase_id = shape.opt_str(body, "phase_id", None)
    description = shape.req_str(body, "description")
    amount = shape.req_int(body, "amount_cents")
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    phase = None
    if phase_id is not None:
        phase = _phase_or_404(phase_id)
    if d["status"] != "CONSTRUCTION":
        errors.raise_err(errors.DISTRICT_NOT_IN_CONSTRUCTION,
                         "Change orders may only be proposed during CONSTRUCTION")
    if phase is not None and phase["district_id"] != district_id:
        errors.raise_err(errors.PHASE_NOT_IN_DISTRICT,
                         "Linked phase does not belong to the change order's district")
    if amount <= 0:
        errors.raise_err(errors.INVALID_AMOUNT, "amount_cents must be > 0")
    ts = now()
    c = {
        "id": new_id(),
        "district_id": district_id,
        "phase_id": phase_id,
        "description": description,
        "amount_cents": amount,
        "status": "PROPOSED",
        "proposed_by_user_id": ctx.user_id,
        "decided_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("change_orders", c)
    return ok_object(ser_change_order(c), 201)


@bp.route("/change-orders/<cid>", methods=["GET"])
def get_change_order(cid):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    return ok_object(ser_change_order(_co_or_404(cid)))


@bp.route("/change-orders/<cid>/approve", methods=["POST"])
def approve_change_order(cid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    c = _co_or_404(cid)
    if ctx.user_id == c["proposed_by_user_id"]:
        errors.raise_err(errors.SEGREGATION_OF_DUTIES,
                         "The proposing engineer may not approve their own change order")
    if c["status"] != "PROPOSED":
        errors.raise_err(errors.CHANGE_ORDER_NOT_PROPOSED,
                         "Change order must be PROPOSED to approve")
    d = STORE.districts[c["district_id"]]
    if d["status"] != "CONSTRUCTION":
        errors.raise_err(errors.DISTRICT_NOT_IN_CONSTRUCTION,
                         "District must be in CONSTRUCTION")
    c["status"] = "APPROVED"
    c["decided_by_user_id"] = ctx.user_id
    touch(c)
    touch(d)  # approved_change_total / overrun_flag recomputed (derived at read)
    return ok_object(ser_change_order(c))


@bp.route("/change-orders/<cid>/reject", methods=["POST"])
def reject_change_order(cid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    c = _co_or_404(cid)
    if c["status"] != "PROPOSED":
        errors.raise_err(errors.CHANGE_ORDER_NOT_PROPOSED,
                         "Change order must be PROPOSED to reject")
    d = STORE.districts[c["district_id"]]
    if d["status"] != "CONSTRUCTION":
        errors.raise_err(errors.DISTRICT_NOT_IN_CONSTRUCTION,
                         "District must be in CONSTRUCTION")
    c["status"] = "REJECTED"
    c["decided_by_user_id"] = ctx.user_id
    touch(c)
    return ok_object(ser_change_order(c))
