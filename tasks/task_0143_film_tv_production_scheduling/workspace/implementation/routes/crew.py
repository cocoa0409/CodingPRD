"""Crew members and assignments (parallel attendance x payment state, costing)."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, require_enum, require_int,
                     optional_enum, optional_bool, optional_int, parse_pagination,
                     paginate, parse_iso_datetime, hours_between)
from response import success_object, success_array
from services.serialize import public
from services.recompute import (touch, recompute_committed_cost, committed_cost,
                                projected_committed_with, budget_line_for,
                                recompute_variance)
from services import calc

bp = Blueprint("crew", __name__)

UNION_CODES = {"SAG_AFTRA", "IATSE", "DGA", "NONE"}


def _fringe_for(production_id, union_code):
    for f in db.union_fringes.values():
        if f["production_id"] == production_id and f["union_code"] == union_code:
            return f
    return None


# --- CrewMember -------------------------------------------------------------
@bp.route("/crew-members", methods=["POST"])
def create_crew_member():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    full_name = require_string(body, "full_name")
    role_title = require_string(body, "role_title")
    daily_rate = require_int(body, "daily_rate_cents", minimum=0)
    is_sag = optional_bool(body, "is_sag_aftra", False)
    union_code = optional_enum(body, "union_code", UNION_CODES, "NONE")
    with db.lock:
        ts = now_iso()
        cm = {
            "id": new_id(),
            "production_id": production_id,
            "full_name": full_name,
            "role_title": role_title,
            "is_sag_aftra": is_sag,
            "daily_rate_cents": daily_rate,
            "union_code": union_code,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.crew_members[cm["id"]] = cm
        return success_object(public(cm), status=201)


@bp.route("/crew-members/<cid>", methods=["GET"])
def get_crew_member(cid):
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PayrollCoordinator", "UnionRep"})
    cm = db.crew_members.get(cid)
    if not cm:
        raise err("ERR_NOT_FOUND", "Crew member not found.")
    return success_object(public(cm))


@bp.route("/crew-members", methods=["GET"])
def list_crew_members():
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PayrollCoordinator", "UnionRep"})
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    items = list(db.crew_members.values())
    if production_id is not None:
        items = [c for c in items if c["production_id"] == production_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(c) for c in page], limit, offset, total)


# --- Assignment -------------------------------------------------------------
@bp.route("/assignments", methods=["POST"])
def create_assignment():
    role = authenticate()
    authorize(role, {"FirstAD"})
    body = get_json_body()
    # existence (priority 3): FK body fields left-to-right in order consumed.
    shooting_day_id = require_string(body, "shooting_day_id")
    crew_member_id = require_string(body, "crew_member_id")
    day = db.shooting_days.get(shooting_day_id)
    if not day:
        raise err("ERR_NOT_FOUND", "Shooting day not found.")
    cm = db.crew_members.get(crew_member_id)
    if not cm:
        raise err("ERR_NOT_FOUND", "Crew member not found.")
    # request validity (priority 4): call_time + OCC field
    call_time_str = require_string(body, "call_time")
    call_time = parse_iso_datetime(call_time_str, "call_time")
    if "expected_shooting_day_version" not in body or body["expected_shooting_day_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_shooting_day_version.")
    expected = require_int(body, "expected_shooting_day_version")
    with db.lock:
        # OCC (priority 6) before business rules (priority 7+)
        if expected != day["version"]:
            raise err("ERR_STALE_VERSION", "Shooting day version is stale.")
        # business referential (priority 7): same production
        if day["production_id"] != cm["production_id"]:
            raise err("ERR_CROSS_PRODUCTION_REFERENCE",
                      "Crew member and shooting day belong to different productions.")
        # double-booked (priority 9): one booking per person per day
        for a in db.assignments.values():
            if a["shooting_day_id"] == shooting_day_id and a["crew_member_id"] == crew_member_id:
                raise err("ERR_DOUBLE_BOOKED", "Crew member already booked on this day.")
        # estimated_assignment_cost
        fringe = _fringe_for(cm["production_id"], cm["union_code"])
        est = calc.estimated_assignment_cost(cm["daily_rate_cents"], cm["union_code"], fringe)
        ts = now_iso()
        a = {
            "id": new_id(),
            "shooting_day_id": shooting_day_id,
            "crew_member_id": crew_member_id,
            "call_time": call_time_str,
            "wrap_time": None,
            "meal_breaks_taken": 0,
            "hours_worked": 0,
            "attendance_status": "SCHEDULED",
            "payment_status": "UNPAID",
            "estimated_cost_cents": est,
            "meal_penalty_cents": 0,
            "turnaround_penalty_cents": 0,
            "fringe_cents": 0,
            "paid_cost_cents": 0,
            "prior_assignment_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.assignments[a["id"]] = a
        # recompute production committed cost; bump shooting day version
        prod = db.productions.get(day["production_id"])
        if prod:
            recompute_committed_cost(prod)
        touch(day)
        return success_object(public(a), status=201)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PayrollCoordinator", "UnionRep"})
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", "Assignment not found.")
    return success_object(public(a))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PayrollCoordinator", "UnionRep"})
    limit, offset = parse_pagination()
    shooting_day_id = request.args.get("shooting_day_id")
    crew_member_id = request.args.get("crew_member_id")
    items = list(db.assignments.values())
    if shooting_day_id is not None:
        items = [a for a in items if a["shooting_day_id"] == shooting_day_id]
    if crew_member_id is not None:
        items = [a for a in items if a["crew_member_id"] == crew_member_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(a) for a in page], limit, offset, total)


@bp.route("/assignments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        a = db.assignments.get(aid)
        if not a:
            raise err("ERR_NOT_FOUND", "Assignment not found.")
        if a["attendance_status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Assignment must be SCHEDULED to check in.")
        day = db.shooting_days.get(a["shooting_day_id"])
        if not day or day["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "Parent day must be IN_PROGRESS to check in.")
        a["attendance_status"] = "CHECKED_IN"
        touch(a)
        return success_object(public(a))


@bp.route("/assignments/<aid>/check-out", methods=["POST"])
def check_out(aid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", "Assignment not found.")
    body = get_json_body()
    # request validity (priority 4): wrap_time present + typed; meal_breaks_taken optional
    wrap_time_str = require_string(body, "wrap_time")
    wrap_time = parse_iso_datetime(wrap_time_str, "wrap_time")
    meal_breaks = optional_int(body, "meal_breaks_taken", default=0, minimum=0)
    with db.lock:
        # state (priority 5)
        if a["attendance_status"] != "CHECKED_IN":
            raise err("ERR_INVALID_STATE", "Assignment must be CHECKED_IN to check out.")
        call_time = parse_iso_datetime(a["call_time"], "call_time")
        # ERR_INVALID_TIME_RANGE (priority 12): wrap strictly after call
        if not (wrap_time > call_time):
            raise err("ERR_INVALID_TIME_RANGE", "wrap_time must be strictly after call_time.")
        cm = db.crew_members[a["crew_member_id"]]
        # ERR_CREW_TIME_CONFLICT (priority 11): closed-interval overlap with other
        # wrapped assignments of the same crew member (touching endpoints conflict).
        for other in db.assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["crew_member_id"] != cm["id"]:
                continue
            if other["attendance_status"] != "WRAPPED" or not other["wrap_time"]:
                continue
            o_call = parse_iso_datetime(other["call_time"], "call_time")
            o_wrap = parse_iso_datetime(other["wrap_time"], "wrap_time")
            # closed-interval overlap: a.start <= o.end AND o.start <= a.end
            if call_time <= o_wrap and o_call <= wrap_time:
                raise err("ERR_CREW_TIME_CONFLICT",
                          "Crew member time occupation conflicts with a wrapped assignment.")
        # stamp wrap_time, hours_worked
        hours_worked = hours_between(call_time, wrap_time)
        a["wrap_time"] = wrap_time_str
        a["hours_worked"] = hours_worked
        a["meal_breaks_taken"] = meal_breaks
        # resolve prior_assignment_id: same crew member's most recent WRAPPED
        # by wrap_time DESC, created_at DESC tie-break.
        prior = None
        for other in db.assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["crew_member_id"] != cm["id"]:
                continue
            if other["attendance_status"] != "WRAPPED" or not other["wrap_time"]:
                continue
            if prior is None:
                prior = other
            else:
                o_wrap = parse_iso_datetime(other["wrap_time"], "wrap_time")
                p_wrap = parse_iso_datetime(prior["wrap_time"], "wrap_time")
                if (o_wrap, other["created_at"], other["_seq"]) > \
                   (p_wrap, prior["created_at"], prior["_seq"]):
                    prior = other
        a["prior_assignment_id"] = prior["id"] if prior else None
        # meal penalty
        a["meal_penalty_cents"] = calc.meal_penalty(
            hours_worked, meal_breaks, cm["is_sag_aftra"])
        # turnaround penalty
        if prior is not None:
            prior_wrap = parse_iso_datetime(prior["wrap_time"], "wrap_time")
            rest_hours = hours_between(prior_wrap, call_time)
            a["turnaround_penalty_cents"] = calc.turnaround_penalty(
                rest_hours, True, cm["is_sag_aftra"], cm["daily_rate_cents"])
        else:
            a["turnaround_penalty_cents"] = calc.turnaround_penalty(
                0, False, cm["is_sag_aftra"], cm["daily_rate_cents"])
        # union fringe
        fringe = _fringe_for(cm["production_id"], cm["union_code"])
        a["fringe_cents"] = calc.union_fringe_accrual(
            cm["daily_rate_cents"], cm["union_code"], fringe)
        a["attendance_status"] = "WRAPPED"
        touch(a)
        return success_object(public(a))


@bp.route("/assignments/<aid>/no-show", methods=["POST"])
def no_show(aid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        a = db.assignments.get(aid)
        if not a:
            raise err("ERR_NOT_FOUND", "Assignment not found.")
        if a["attendance_status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Assignment must be SCHEDULED to mark no-show.")
        a["attendance_status"] = "NO_SHOW"
        a["payment_status"] = "VOID"
        touch(a)
        # estimated cost no longer counts toward committed; recompute.
        day = db.shooting_days.get(a["shooting_day_id"])
        if day:
            prod = db.productions.get(day["production_id"])
            if prod:
                recompute_committed_cost(prod)
        return success_object(public(a))


@bp.route("/assignments/<aid>/approve-pay", methods=["POST"])
def approve_pay(aid):
    role = authenticate()
    authorize(role, {"PayrollCoordinator"})
    with db.lock:
        a = db.assignments.get(aid)
        if not a:
            raise err("ERR_NOT_FOUND", "Assignment not found.")
        # state (priority 5): payment UNPAID and attendance WRAPPED
        if a["payment_status"] != "UNPAID" or a["attendance_status"] != "WRAPPED":
            raise err("ERR_INVALID_STATE",
                      "Assignment must be WRAPPED and UNPAID to approve pay.")
        cm = db.crew_members[a["crew_member_id"]]
        paid = calc.actual_assignment_cost(
            cm["daily_rate_cents"], a["hours_worked"], a["meal_penalty_cents"],
            a["turnaround_penalty_cents"], a["fringe_cents"])
        day = db.shooting_days[a["shooting_day_id"]]
        prod = db.productions[day["production_id"]]
        # budget gate (priority 15): projected committed_cost with this assignment
        # APPROVED at `paid` must not strictly exceed total_budget_cents.
        projected = projected_committed_with(
            prod, a, new_estimated=paid, treat_as_payment="APPROVED")
        if projected > prod["total_budget_cents"]:
            raise err("ERR_BUDGET_WOULD_EXCEED",
                      "Approving pay would exceed the production budget.")
        a["paid_cost_cents"] = paid
        a["payment_status"] = "APPROVED"
        touch(a)
        recompute_committed_cost(prod)
        return success_object(public(a))


@bp.route("/assignments/<aid>/mark-paid", methods=["POST"])
def mark_paid(aid):
    role = authenticate()
    authorize(role, {"PayrollCoordinator"})
    with db.lock:
        a = db.assignments.get(aid)
        if not a:
            raise err("ERR_NOT_FOUND", "Assignment not found.")
        if a["payment_status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Assignment must be APPROVED to mark paid.")
        day = db.shooting_days[a["shooting_day_id"]]
        prod = db.productions[day["production_id"]]
        a["payment_status"] = "PAID"
        touch(a)
        # The production is mutated once by this single action: actual_cost_cents
        # rises and committed_cost_cents is recomputed (PAID now contributes
        # paid_cost_cents). One action -> one version bump on the production.
        prod["actual_cost_cents"] += a["paid_cost_cents"]
        prod["committed_cost_cents"] = committed_cost(prod)
        touch(prod)
        # BELOW_THE_LINE_LABOR.actual_cents += (paid - fringe); FRINGES += fringe
        labor_portion = a["paid_cost_cents"] - a["fringe_cents"]
        btl = budget_line_for(prod["id"], "BELOW_THE_LINE_LABOR")
        if btl is not None:
            btl["actual_cents"] += labor_portion
            recompute_variance(btl)
            touch(btl)
        fr = budget_line_for(prod["id"], "FRINGES")
        if fr is not None:
            fr["actual_cents"] += a["fringe_cents"]
            recompute_variance(fr)
            touch(fr)
        return success_object(public(a))
