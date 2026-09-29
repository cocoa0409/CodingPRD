"""Rostering the shift, the ordinance ceilings, waivers and settlement.

PRD 3.3 (roster creation, clock-in, waivers) and PRD 3.7 (shift settlement).
"""

from decimal import Decimal

from flask import Blueprint, request

import derive
from auth import (
    COMPLIANCE_OFFICER,
    HOUSEKEEPING_DIRECTOR,
    ROOM_ATTENDANT,
    SUPERVISOR,
    authenticate,
)
from envelope import created, filtered, ok, paginate
from errors import ApiError
from numeric import jsonnum, to_frac
from serialize import roster_out
from store import STORE, base_record, touch
from validate import read_body, vdatetime, vdec, venum, vint, vstr

bp = Blueprint("roster", __name__)

MAX_WORKED_MINUTES_PER_SHIFT = 720


def _require_owner(actor, roster):
    """Ladder rung 7: a RoomAttendant may only act on their own roster."""
    if actor.role == ROOM_ATTENDANT and roster["attendant_id"] != actor.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNMENT_OWNER",
            "Roster %s does not belong to the acting attendant." % roster["id"],
        )


@bp.post("/housekeeping/shift-rosters")
def create_roster():
    authenticate((HOUSEKEEPING_DIRECTOR, SUPERVISOR))
    body = read_body()
    forecast_day_id = vstr(body, "forecast_day_id", 1, None)
    attendant_id = vstr(body, "attendant_id", 1, None)
    planned_start_at = vdatetime(body, "planned_start_at", required=False, default=None)

    day = derive.get_forecast_day(STORE, forecast_day_id)
    attendant = derive.get_attendant(STORE, attendant_id)

    # Rung 8: scope coherence fires before either state gate.
    if attendant["property_id"] != day["property_id"]:
        raise ApiError(
            "ERR_PROPERTY_SCOPE_MISMATCH",
            "Attendant %s belongs to another property than the forecast day."
            % attendant["id"],
        )

    if day["status"] == "CLOSED":
        raise ApiError("ERR_FORECAST_ALREADY_CLOSED", "Forecast day is already closed.")
    if day["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED", "Forecast day is not PUBLISHED.")
    if attendant["status"] != "ACTIVE":
        raise ApiError("ERR_ATTENDANT_NOT_ACTIVE", "Attendant is not ACTIVE.")

    for existing in derive.rosters_of_forecast_day(STORE, day["id"]):
        if existing["attendant_id"] == attendant["id"]:
            raise ApiError(
                "ERR_ROSTER_DUPLICATE",
                "A roster already exists for this attendant on this forecast day.",
            )

    prop = STORE.properties[day["property_id"]]
    row = base_record(STORE)
    row.update({
        "forecast_day_id": day["id"],
        "attendant_id": attendant["id"],
        "planned_start_at": planned_start_at,
        "status": "PLANNED",
        "compliance_state": "COMPLIANT",
        "waiver_state": "NONE",
        "waiver_requested_credits": None,
        "waiver_requested_by_user_id": None,
        "waiver_decided_by_user_id": None,
        "assigned_credits": Decimal("0.00"),
        "assigned_square_feet": 0,
        "effective_credit_cap": derive.effective_credit_cap(prop, attendant),
        "effective_sqft_cap": derive.effective_sqft_cap(prop),
        "worked_minutes": None,
        "break_minutes": 0,
        "paid_minutes": None,
        "overtime_minutes": None,
        "rooms_completed_gross": 0,
        "rooms_credited_net": 0,
        "minutes_per_room_gross": None,
        "minutes_per_room_net": None,
        "target_minutes_per_room": None,
        "productivity_flag": "PENDING",
        "required_inspection_samples": 0,
        "inspections_completed": 0,
        "base_wage_cents": None,
        "ordinance_premium_cents": None,
        "total_labor_cost_cents": None,
    })
    STORE.rosters[row["id"]] = row
    return created(roster_out(STORE, row))


@bp.get("/housekeeping/shift-rosters/<rid>")
def read_roster(rid):
    authenticate(None)
    row = derive.get_roster(STORE, rid)
    return ok(roster_out(STORE, row))


@bp.get("/housekeeping/shift-rosters")
def list_rosters():
    authenticate(None)
    rows = filtered(
        list(STORE.rosters.values()),
        request.args,
        {
            "forecast_day_id": ("forecast_day_id", None),
            "attendant_id": ("attendant_id", None),
            "status": ("status", None),
            "compliance_state": ("compliance_state", None),
        },
    )
    return paginate(rows, request.args, lambda r: roster_out(STORE, r))


@bp.post("/housekeeping/shift-rosters/<rid>/clock-in")
def clock_in(rid):
    actor = authenticate((SUPERVISOR, ROOM_ATTENDANT))
    roster = derive.get_roster(STORE, rid)
    _require_owner(actor, roster)

    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] != "PLANNED":
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not in PLANNED.")

    day = derive.forecast_day_of_roster(STORE, roster)
    attendant = derive.attendant_of_roster(STORE, roster)
    if day["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED", "Forecast day is not PUBLISHED.")
    if attendant["status"] != "ACTIVE":
        raise ApiError("ERR_ATTENDANT_NOT_ACTIVE", "Attendant is not ACTIVE.")
    if roster["compliance_state"] == "BREACH_BLOCKED":
        raise ApiError(
            "ERR_ROSTER_WORKLOAD_BREACH",
            "Roster is BREACH_BLOCKED and accepts no further work.",
        )

    # Clocking in advances only the lifecycle dimension.
    roster["status"] = "CLOCKED_IN"
    touch(STORE, roster)
    return ok(roster_out(STORE, roster))


@bp.post("/housekeeping/shift-rosters/<rid>/close")
def close_roster(rid):
    authenticate((HOUSEKEEPING_DIRECTOR, SUPERVISOR))
    body = read_body()
    # Rung 4 rejects negatives outright; rung 36 owns the plausibility ceiling.
    worked_minutes = vint(body, "worked_minutes", 0, None)
    break_minutes = vint(body, "break_minutes", 0, None, required=False, default=0)

    roster = derive.get_roster(STORE, rid)
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] != "CLOCKED_IN":
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not CLOCKED_IN.")

    assignments = derive.assignments_of_roster(STORE, roster["id"])
    for a in assignments:
        if a["status"] == "IN_PROGRESS":
            raise ApiError(
                "ERR_ASSIGNMENT_IN_PROGRESS",
                "Assignment %s is still IN_PROGRESS." % a["id"],
            )

    prop = derive.property_of_roster(STORE, roster)
    attendant = derive.attendant_of_roster(STORE, roster)
    performed = derive.performed_assignments(STORE, roster["id"])
    required_samples = derive.required_samples_for(
        len(performed), derive.sampling_rate(prop, attendant)
    )
    completed_inspections = derive.roster_inspections_completed(STORE, roster["id"])
    if completed_inspections < required_samples:
        raise ApiError(
            "ERR_INSPECTION_SAMPLE_INCOMPLETE",
            "%d of %d required inspections recorded."
            % (completed_inspections, required_samples),
        )

    if worked_minutes > MAX_WORKED_MINUTES_PER_SHIFT:
        raise ApiError(
            "ERR_WORKED_MINUTES_IMPLAUSIBLE",
            "worked_minutes must lie between 0 and 720 inclusive.",
        )
    if break_minutes > worked_minutes:
        raise ApiError(
            "ERR_BREAK_EXCEEDS_WORKED",
            "break_minutes must not exceed worked_minutes.",
        )

    # Hop one: rooms planned but never started are pushed off the day.
    for a in assignments:
        if a["status"] == "ASSIGNED":
            a["status"] = "DEFERRED"
            touch(STORE, a)

    # Hop two: the deferred rows have left the counted set.  The roster's own version
    # is bumped exactly once, by the close itself, at the end.
    credits_changed = derive.recompute_roster(STORE, roster, bump=False)
    # Hop three: the parent day's conserved total follows the roster's credits.
    if credits_changed:
        day = STORE.forecast_days.get(roster["forecast_day_id"])
        if day is not None:
            derive.recompute_forecast_allocated(STORE, day, bump=True)

    paid_minutes, overtime_minutes, productive_minutes = derive.settle_minutes(
        prop, worked_minutes, break_minutes
    )
    gross = derive.minutes_per_room(productive_minutes, roster["rooms_completed_gross"])
    net = derive.minutes_per_room(productive_minutes, roster["rooms_credited_net"])
    target = derive.target_minutes_per_room(
        prop, roster["assigned_credits"], roster["rooms_credited_net"]
    )

    roster["worked_minutes"] = worked_minutes
    roster["break_minutes"] = break_minutes
    roster["paid_minutes"] = paid_minutes
    roster["overtime_minutes"] = overtime_minutes
    roster["minutes_per_room_gross"] = gross
    roster["minutes_per_room_net"] = net
    roster["target_minutes_per_room"] = target
    roster["productivity_flag"] = derive.resolve_productivity_flag(
        STORE, roster, net, target
    )

    base, premium, total = derive.labor_cost(
        paid_minutes,
        attendant["hourly_rate_cents"],
        overtime_minutes,
        roster["compliance_state"],
    )
    roster["base_wage_cents"] = base
    roster["ordinance_premium_cents"] = premium
    roster["total_labor_cost_cents"] = total

    roster["status"] = "CLOSED"
    touch(STORE, roster)
    return ok(roster_out(STORE, roster))


@bp.post("/housekeeping/shift-rosters/<rid>/waiver-request")
def waiver_request(rid):
    actor = authenticate((SUPERVISOR,))
    body = read_body()
    requested = vdec(body, "waiver_requested_credits", "0.00", None, 2)

    roster = derive.get_roster(STORE, rid)
    # PRD 3.3 states the waiver dimension first, then the lifecycle dimension.
    if roster["waiver_state"] != "NONE":
        raise ApiError(
            "ERR_WAIVER_ALREADY_DECIDED",
            "A waiver has already been filed on this roster.",
        )
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] not in ("PLANNED", "CLOCKED_IN"):
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not workable.")

    prop = derive.property_of_roster(STORE, roster)
    ceiling = to_frac(roster["effective_credit_cap"]) * to_frac(
        derive.waiver_headroom_factor(prop)
    )
    if to_frac(requested) > ceiling:
        raise ApiError(
            "ERR_WAIVER_EXCEEDS_ORDINANCE_MAX",
            "waiver_requested_credits exceeds the ordinance headroom.",
        )

    roster["waiver_requested_credits"] = requested
    roster["waiver_requested_by_user_id"] = actor.user_id
    roster["waiver_state"] = "REQUESTED"
    touch(STORE, roster)
    return ok(roster_out(STORE, roster))


@bp.post("/housekeeping/shift-rosters/<rid>/waiver-decision")
def waiver_decision(rid):
    actor = authenticate((COMPLIANCE_OFFICER,))
    body = read_body()
    decision = venum(body, "decision", ("GRANT", "DENY"))

    roster = derive.get_roster(STORE, rid)
    if roster["waiver_state"] == "NONE":
        raise ApiError("ERR_WAIVER_NOT_REQUESTED", "No waiver has been filed.")
    if roster["waiver_state"] in ("GRANTED", "DENIED"):
        raise ApiError("ERR_WAIVER_ALREADY_DECIDED", "The waiver is already decided.")

    # Segregation of duties: nobody decides the waiver they themselves filed.
    if actor.user_id == roster["waiver_requested_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who filed the waiver may not decide it.",
        )

    roster["waiver_state"] = "GRANTED" if decision == "GRANT" else "DENIED"
    roster["waiver_decided_by_user_id"] = actor.user_id
    # A DENY re-runs the same derivation while ignoring the waiver entirely.
    prop = derive.property_of_roster(STORE, roster)
    attendant = derive.attendant_of_roster(STORE, roster)
    roster["compliance_state"] = derive.resolve_compliance_state(
        roster,
        roster["assigned_credits"],
        roster["assigned_square_feet"],
        derive.effective_credit_cap(prop, attendant),
        derive.effective_sqft_cap(prop),
        ignore_waiver=(decision == "DENY"),
    )
    touch(STORE, roster)
    return ok(roster_out(STORE, roster))


@bp.get("/housekeeping/shift-rosters/<rid>/inspection-sample-plan")
def read_sample_plan(rid):
    authenticate(None)
    roster = derive.get_roster(STORE, rid)
    plan = derive.inspection_sample_plan(STORE, roster)
    plan["sample_rate"] = jsonnum(plan["sample_rate"])
    return ok(plan)
