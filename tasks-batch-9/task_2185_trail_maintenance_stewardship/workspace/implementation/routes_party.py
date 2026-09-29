"""Work parties (two independent state axes) and the volunteer roster."""

import math
from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, actor, require, role
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("party", __name__)

SCHEDULE_STATUSES = ("PLANNED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "SUSPENDED", "CANCELLED")
READINESS_STATUSES = ("PENDING", "BRIEFED", "CLEARED", "BLOCKED")
SHIFT_STATUSES = ("REGISTERED", "CHECKED_IN", "CHECKED_OUT", "HOURS_DISPUTED",
                  "HOURS_VERIFIED", "HOURS_CERTIFIED", "WITHDRAWN", "NO_SHOW")
CREW_ROLES = ("CREW_MEMBER", "SAWYER", "FIRST_AIDER", "CREW_LEADER")


# ---------------------------------------------------------------------------
# shared gate helpers
# ---------------------------------------------------------------------------
def _check_segment_closed(segment):
    if segment["posture"] in ("SEASONAL_CLOSED", "INCIDENT_CLOSED"):
        fail("ERR_SEGMENT_CLOSED", "The trail segment is closed.")


def _check_work_type_restriction(segment, party):
    if not domain.posture_allows_work_type(segment["posture"], party["work_type"]):
        fail("ERR_WET_WEATHER_RESTRICTED",
             "The segment posture does not permit this work type.")


def _check_certifications(party, manager):
    required = set(party.get("required_certifications") or [])
    rows = domain.shifts_of_party(party)
    for shift in rows:
        if shift["status"] not in ("REGISTERED", "CHECKED_IN"):
            continue
        volunteer = store.volunteers.get(shift["volunteer_id"])
        certs = set((volunteer or {}).get("certifications") or [])
        if not required.issubset(certs):
            fail("ERR_CERTIFICATION_MISSING",
                 "A registrant is missing a required certification.")
    if party["work_type"] == "CHAINSAW" and manager is not None and manager["requires_certified_sawyer"]:
        has_sawyer = False
        for shift in rows:
            if shift["status"] == "WITHDRAWN":
                continue
            volunteer = store.volunteers.get(shift["volunteer_id"])
            certs = set((volunteer or {}).get("certifications") or [])
            if certs & set(calc.SAWYER_CERTS):
                has_sawyer = True
                break
        if not has_sawyer:
            fail("ERR_CERTIFICATION_MISSING", "The party retains no certified sawyer.")


def _check_first_aid(party):
    domain.refresh_party(party)
    required = max(1, int(math.ceil(party["registered_count"] / float(calc.FIRST_AID_RATIO))))
    if party["first_aid_capable_count"] < required:
        fail("ERR_FIRST_AID_COVERAGE_INSUFFICIENT", "First-aid cover is insufficient.")


def _check_briefing_on_record(party):
    if party["readiness_status"] == "PENDING":
        fail("ERR_BRIEFING_INCOMPLETE", "The party has no briefing on record.")


# ---------------------------------------------------------------------------
# WorkParty CRUD
# ---------------------------------------------------------------------------
@bp.post("/work-parties")
@require("CrewLeader")
def create_party():
    data = v.body()
    work_plan_id = v.req_id(data, "work_plan_id")
    trail_segment_id = v.req_id(data, "trail_segment_id")
    start_at = v.req_datetime(data, "start_at")
    end_at = v.req_datetime(data, "end_at")
    work_type = v.req_enum(data, "work_type", calc.WORK_TYPES)
    max_participants = v.req_int(data, "max_participants", minimum=1)
    work_permit_id = v.opt_id(data, "work_permit_id")
    travel_allowance_minutes = v.opt_int(data, "travel_allowance_minutes", 0, minimum=0)
    required_certifications = v.opt_enum_array(
        data, "required_certifications", calc.CERTIFICATIONS, [])

    if end_at <= start_at:
        fail("ERR_INVALID_REQUEST", "end_at must be strictly after start_at.")
    if start_at.date() != end_at.date():
        fail("ERR_INVALID_REQUEST", "start_at and end_at must fall on the same UTC calendar day.")

    plan = domain.get_plan(work_plan_id)
    segment = domain.get_segment(trail_segment_id)
    if work_permit_id is not None:
        domain.get_permit(work_permit_id)

    agreement = domain.plan_agreement(plan)
    if agreement is not None and agreement["trail_segment_id"] != trail_segment_id:
        fail("ERR_INVALID_REQUEST",
             "trail_segment_id must equal the segment named on the plan's adoption.")
    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_ADOPTION_NOT_ACTIVE", "The governing adoption is not ACTIVE.")

    party = new_entity({
        "work_plan_id": work_plan_id,
        "trail_segment_id": trail_segment_id,
        "work_permit_id": work_permit_id,
        "start_at": store.iso(start_at),
        "end_at": store.iso(end_at),
        "work_type": work_type,
        "max_participants": max_participants,
        "travel_allowance_minutes": travel_allowance_minutes,
        "required_certifications": list(required_certifications or []),
        "schedule_status": "PLANNED",
        "readiness_status": "PENDING",
        "briefing_delivered_at": None,
        "briefing_leader_user_id": None,
        "tool_checklist_complete": False,
        "first_aid_kit_count": 0,
        "registered_count": 0,
        "checked_in_count": 0,
        "first_aid_capable_count": 0,
        "linked_report_count": 0,
        "roster_capacity": max_participants,
        "block_reason": None,
    })
    store.parties[party["id"]] = party
    domain.refresh_party(party)
    return created(domain.s_party(party))


@bp.get("/work-parties/<entity_id>")
@require(*ALL_ROLES)
def read_party(entity_id):
    return ok(domain.s_party(domain.get_party(entity_id)))


@bp.get("/work-parties")
@require(*ALL_ROLES)
def list_parties():
    work_plan_id = request.args.get("work_plan_id")
    trail_segment_id = request.args.get("trail_segment_id")
    work_permit_id = request.args.get("work_permit_id")
    schedule_status = request.args.get("schedule_status")
    readiness_status = request.args.get("readiness_status")
    if schedule_status is not None and schedule_status not in SCHEDULE_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'schedule_status' is not a declared member.")
    if readiness_status is not None and readiness_status not in READINESS_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'readiness_status' is not a declared member.")
    rows = store.ordered(list(store.parties.values()))
    if work_plan_id is not None:
        rows = [r for r in rows if r["work_plan_id"] == work_plan_id]
    if trail_segment_id is not None:
        rows = [r for r in rows if r["trail_segment_id"] == trail_segment_id]
    if work_permit_id is not None:
        rows = [r for r in rows if r.get("work_permit_id") == work_permit_id]
    if schedule_status is not None:
        rows = [r for r in rows if r["schedule_status"] == schedule_status]
    if readiness_status is not None:
        rows = [r for r in rows if r["readiness_status"] == readiness_status]
    return paginate(rows, domain.s_party)


# ---------------------------------------------------------------------------
# readiness axis
# ---------------------------------------------------------------------------
@bp.post("/work-parties/<entity_id>/briefing")
@require("CrewLeader")
def brief_party(entity_id):
    party = domain.get_party(entity_id)
    data = v.body()
    tool_checklist_complete = v.req_bool(data, "tool_checklist_complete")
    first_aid_kit_count = v.req_int(data, "first_aid_kit_count", minimum=0)

    if party["schedule_status"] not in ("PLANNED", "CONFIRMED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "The party's schedule status does not accept a briefing.")
    if party["readiness_status"] not in ("PENDING", "BLOCKED"):
        fail("ERR_INVALID_STATE", "A briefing is already on record.")
    if party["readiness_status"] == "BLOCKED" and domain.blocking_cause(party) is not None:
        fail("ERR_INVALID_STATE", "A blocking cause still holds.")

    if not tool_checklist_complete or first_aid_kit_count < 1:
        fail("ERR_BRIEFING_INCOMPLETE", "The briefing is incomplete.")

    party["tool_checklist_complete"] = tool_checklist_complete
    party["first_aid_kit_count"] = first_aid_kit_count
    party["readiness_status"] = "BRIEFED"
    party["block_reason"] = None
    party["briefing_delivered_at"] = store.now_iso()
    party["briefing_leader_user_id"] = actor()
    touch(party)
    domain.try_clear(party)
    return ok(domain.s_party(party))


# ---------------------------------------------------------------------------
# schedule axis
# ---------------------------------------------------------------------------
@bp.post("/work-parties/<entity_id>/confirm")
@require("CrewLeader")
def confirm_party(entity_id):
    party = domain.get_party(entity_id)
    if party["schedule_status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "Only a PLANNED party may be confirmed.")

    segment = domain.get_segment(party["trail_segment_id"])
    manager = domain.segment_manager(segment)
    agreement = domain.party_agreement(party)
    permit = domain.party_permit(party)

    _check_segment_closed(segment)
    _check_work_type_restriction(segment, party)
    _check_certifications(party, manager)
    _check_first_aid(party)
    _check_briefing_on_record(party)

    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_ADOPTION_NOT_ACTIVE", "The governing adoption is not ACTIVE.")

    if manager is not None and manager["permit_required"]:
        if (permit is None or permit["status"] != "ISSUED"
                or party["work_type"] not in (permit.get("allowed_work_types") or [])):
            fail("ERR_PERMIT_NOT_ISSUED", "No issued permit covers this work party.")

    if permit is not None and permit["status"] == "ISSUED":
        if not domain.party_dates_inside_permit(party, permit):
            fail("ERR_PERMIT_WINDOW_MISMATCH",
                 "The party's dates fall outside the permit window.")

    start = store.parse_dt(party["start_at"])
    end = store.parse_dt(party["end_at"])
    buffer = timedelta(minutes=calc.SEGMENT_BUFFER_MINUTES)
    for other in domain.parties_of_segment(segment):
        if other["id"] == party["id"]:
            continue
        if other["schedule_status"] not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        other_start = store.parse_dt(other["start_at"])
        other_end = store.parse_dt(other["end_at"])
        if start < other_end + buffer and other_start < end + buffer:
            fail("ERR_SEGMENT_PARTY_OVERLAP",
                 "Another work party conflicts on this segment.")

    if permit is not None and permit.get("max_party_size") is not None:
        if int(party["max_participants"]) > int(permit["max_party_size"]):
            fail("ERR_PARTY_SIZE_EXCEEDS_PERMIT",
                 "The declared party size exceeds the permit ceiling.")

    party["schedule_status"] = "CONFIRMED"
    touch(party)
    return ok(domain.s_party(party))


@bp.post("/work-parties/<entity_id>/start")
@require("CrewLeader")
def start_party(entity_id):
    party = domain.get_party(entity_id)
    if party["schedule_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Only a CONFIRMED party may be started.")
    if store.now() < store.parse_dt(party["start_at"]):
        fail("ERR_INVALID_STATE", "The logical clock has not reached start_at.")

    segment = domain.get_segment(party["trail_segment_id"])
    _check_segment_closed(segment)
    _check_work_type_restriction(segment, party)
    _check_first_aid(party)
    _check_briefing_on_record(party)

    party["schedule_status"] = "IN_PROGRESS"
    touch(party)
    return ok(domain.s_party(party))


@bp.post("/work-parties/<entity_id>/complete")
@require("CrewLeader")
def complete_party(entity_id):
    party = domain.get_party(entity_id)
    if party["schedule_status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Only an IN_PROGRESS party may be completed.")
    if store.now() < store.parse_dt(party["start_at"]):
        fail("ERR_INVALID_STATE", "The logical clock has not reached start_at.")

    party["schedule_status"] = "COMPLETED"
    touch(party)

    end_at = store.parse_dt(party["end_at"])
    cutoff = min(store.now(), end_at)
    for shift in domain.shifts_of_party(party):
        if shift["status"] == "CHECKED_IN":
            _apply_checkout(shift, party, cutoff)
        elif shift["status"] == "REGISTERED":
            shift["status"] = "NO_SHOW"
            touch(shift)
            volunteer = store.volunteers.get(shift["volunteer_id"])
            if volunteer is not None:
                volunteer["active_registration_count"] = max(
                    0, int(volunteer["active_registration_count"]) - 1)
                touch(volunteer)

    permit = domain.party_permit(party)
    if permit is not None:
        domain.refresh_permit(permit)
        touch(permit)
        domain.consume_permit_if_done(permit)
    return ok(domain.s_party(party))


@bp.post("/work-parties/<entity_id>/cancel")
@require("CrewLeader", "StewardshipCoordinator")
def cancel_party(entity_id):
    party = domain.get_party(entity_id)
    data = v.body()
    v.req_str(data, "reason")

    acting = role()
    if acting == "CrewLeader":
        allowed = ("PLANNED", "CONFIRMED")
    else:
        allowed = ("SUSPENDED",)
    if party["schedule_status"] not in allowed:
        fail("ERR_INVALID_STATE", "The party may not be cancelled from this state.")

    party["schedule_status"] = "CANCELLED"
    touch(party)
    domain.withdraw_registered_shifts(party)
    for report in store.ordered(list(store.reports.values())):
        if report.get("linked_work_party_id") != party["id"]:
            continue
        if report["status"] == "SCHEDULED":
            report["status"] = "TRIAGED"
        report["linked_work_party_id"] = None
        touch(report)
    return ok(domain.s_party(party))


def _apply_checkout(shift, party, checked_out_at):
    checked_in_at = store.parse_dt(shift["checked_in_at"])
    worked, billable, hours = calc.credited_hours(
        checked_in_at, checked_out_at, party["travel_allowance_minutes"])
    shift["status"] = "CHECKED_OUT"
    shift["checked_out_at"] = store.iso(checked_out_at)
    shift["worked_minutes"] = worked
    shift["billable_minutes"] = billable
    shift["credited_hours"] = hours
    volunteer = store.volunteers.get(shift["volunteer_id"])
    shift["skill_class_snapshot"] = (volunteer or {}).get("skill_class")
    touch(shift)
    if volunteer is not None:
        domain.move_hours(volunteer, lifetime_credited_hours=hours, pending_hours=hours)
    return hours


# ---------------------------------------------------------------------------
# VolunteerShift
# ---------------------------------------------------------------------------
@bp.post("/work-parties/<entity_id>/shifts")
@require("Volunteer", "CrewLeader")
def register_shift(entity_id):
    party = domain.get_party(entity_id)
    data = v.body()
    volunteer_id = v.req_id(data, "volunteer_id")
    expected_version = v.req_int(data, "expected_work_party_version")
    role_on_crew = v.opt_enum(data, "role_on_crew", CREW_ROLES, "CREW_MEMBER")

    volunteer = domain.get_volunteer(volunteer_id)

    if party["schedule_status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_INVALID_STATE", "The work party no longer accepts registrations.")

    domain.refresh_party(party)
    if expected_version != int(party["version"]):
        fail("ERR_STALE_WORK_PARTY_VERSION", "The work party version is stale.")

    if not domain.waiver_current(volunteer):
        fail("ERR_WAIVER_NOT_SIGNED", "The volunteer's waiver is not current.")

    required = set(party.get("required_certifications") or [])
    if not required.issubset(set(volunteer.get("certifications") or [])):
        fail("ERR_CERTIFICATION_MISSING", "The volunteer lacks a required certification.")

    new_start = store.parse_dt(party["start_at"])
    new_end = store.parse_dt(party["end_at"])

    # Volunteer interval rule: closed intervals, zero buffer, other parties only.
    for shift in domain.shifts_of_volunteer(volunteer_id):
        if shift["status"] not in ("REGISTERED", "CHECKED_IN", "CHECKED_OUT"):
            continue
        if shift["work_party_id"] == party["id"]:
            continue
        other = store.parties.get(shift["work_party_id"])
        if other is None:
            continue
        other_start = store.parse_dt(other["start_at"])
        other_end = store.parse_dt(other["end_at"])
        if new_start < other_end and other_start < new_end:
            fail("ERR_VOLUNTEER_DOUBLE_BOOKED", "The volunteer is already booked in this window.")

    # Daily ceiling across other parties starting on the same UTC calendar day.
    total_hours = (new_end - new_start).total_seconds() / 3600.0
    for shift in domain.shifts_of_volunteer(volunteer_id):
        if shift["status"] not in ("REGISTERED", "CHECKED_IN", "CHECKED_OUT"):
            continue
        if shift["work_party_id"] == party["id"]:
            continue
        other = store.parties.get(shift["work_party_id"])
        if other is None:
            continue
        other_start = store.parse_dt(other["start_at"])
        if other_start.date() != new_start.date():
            continue
        other_end = store.parse_dt(other["end_at"])
        total_hours += (other_end - other_start).total_seconds() / 3600.0
    if total_hours > calc.MAX_DAILY_SHIFT_HOURS + 1e-9:
        fail("ERR_VOLUNTEER_DAILY_HOURS_EXCEEDED",
             "The volunteer's daily hour ceiling would be exceeded.")

    if int(party["registered_count"]) >= int(party["roster_capacity"]):
        fail("ERR_ROSTER_FULL", "The roster is full.")

    for shift in domain.shifts_of_party(party):
        if (shift["volunteer_id"] == volunteer_id
                and shift["status"] not in ("WITHDRAWN", "NO_SHOW")):
            fail("ERR_DUPLICATE_REGISTRATION", "The volunteer is already on this roster.")

    shift = new_entity({
        "work_party_id": party["id"],
        "volunteer_id": volunteer_id,
        "role_on_crew": role_on_crew,
        "status": "REGISTERED",
        "checked_in_at": None,
        "checked_out_at": None,
        "worked_minutes": 0,
        "billable_minutes": 0,
        "credited_hours": 0,
        "adjusted_hours": None,
        "skill_class_snapshot": None,
        "hours_verified_by_user_id": None,
        "hours_certified_by_user_id": None,
        "dispute_reason": None,
    })
    store.shifts[shift["id"]] = shift

    domain.refresh_party(party)
    touch(party)
    volunteer["active_registration_count"] = int(volunteer["active_registration_count"]) + 1
    touch(volunteer)
    return created(domain.s_shift(shift))


@bp.get("/shifts/<entity_id>")
@require(*ALL_ROLES)
def read_shift(entity_id):
    return ok(domain.s_shift(domain.get_shift(entity_id)))


@bp.get("/shifts")
@require(*ALL_ROLES)
def list_shifts():
    work_party_id = request.args.get("work_party_id")
    volunteer_id = request.args.get("volunteer_id")
    status = request.args.get("status")
    if status is not None and status not in SHIFT_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a declared member.")
    rows = store.ordered(list(store.shifts.values()))
    if work_party_id is not None:
        rows = [r for r in rows if r["work_party_id"] == work_party_id]
    if volunteer_id is not None:
        rows = [r for r in rows if r["volunteer_id"] == volunteer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_shift)


@bp.post("/shifts/<entity_id>/check-in")
@require("Volunteer", "CrewLeader")
def check_in_shift(entity_id):
    shift = domain.get_shift(entity_id)
    if role() == "Volunteer" and actor() != shift["volunteer_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A volunteer may only check in their own shift.")

    party = domain.get_party(shift["work_party_id"])
    if shift["status"] != "REGISTERED":
        fail("ERR_INVALID_STATE", "Only a REGISTERED shift may be checked in.")
    if party["schedule_status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "The work party is not IN_PROGRESS.")

    shift["status"] = "CHECKED_IN"
    shift["checked_in_at"] = store.now_iso()
    touch(shift)
    domain.refresh_party(party)
    touch(party)
    return ok(domain.s_shift(shift))


@bp.post("/shifts/<entity_id>/check-out")
@require("CrewLeader")
def check_out_shift(entity_id):
    shift = domain.get_shift(entity_id)
    party = domain.get_party(shift["work_party_id"])
    if shift["status"] != "CHECKED_IN":
        fail("ERR_INVALID_STATE", "Only a CHECKED_IN shift may be checked out.")
    if party["schedule_status"] not in ("IN_PROGRESS", "COMPLETED"):
        fail("ERR_INVALID_STATE", "The work party is not IN_PROGRESS or COMPLETED.")
    if store.now() <= store.parse_dt(shift["checked_in_at"]):
        fail("ERR_INVALID_STATE", "The logical clock must be later than checked_in_at.")

    _apply_checkout(shift, party, store.now())
    domain.refresh_party(party)
    touch(party)
    return ok(domain.s_shift(shift))


@bp.post("/shifts/<entity_id>/withdraw")
@require("Volunteer", "CrewLeader")
def withdraw_shift(entity_id):
    shift = domain.get_shift(entity_id)
    if role() == "Volunteer" and actor() != shift["volunteer_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A volunteer may only withdraw their own shift.")

    data = v.body()
    v.opt_str(data, "reason")

    party = domain.get_party(shift["work_party_id"])
    if shift["status"] != "REGISTERED":
        fail("ERR_INVALID_STATE", "Only a REGISTERED shift may be withdrawn.")
    if party["schedule_status"] == "COMPLETED":
        fail("ERR_INVALID_STATE", "The work party has already completed.")

    shift["status"] = "WITHDRAWN"
    touch(shift)
    domain.refresh_party(party)
    touch(party)
    volunteer = store.volunteers.get(shift["volunteer_id"])
    if volunteer is not None:
        volunteer["active_registration_count"] = max(
            0, int(volunteer["active_registration_count"]) - 1)
        touch(volunteer)
    return ok(domain.s_shift(shift))


@bp.post("/shifts/<entity_id>/hours-review")
@require("StewardshipCoordinator")
def review_hours(entity_id):
    shift = domain.get_shift(entity_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("VERIFY", "DISPUTE", "RESET"))
    adjusted_hours = None
    if decision == "DISPUTE":
        adjusted_hours = v.req_num(data, "adjusted_hours", minimum=0)
        if not v.is_multiple_of_quarter(float(adjusted_hours)):
            fail("ERR_INVALID_REQUEST", "adjusted_hours must be a multiple of 0.25.")
        v.req_str(data, "dispute_reason")

    party = domain.get_party(shift["work_party_id"])
    plan = domain.party_plan(party)
    volunteer = store.volunteers.get(shift["volunteer_id"])

    if decision == "VERIFY":
        if shift["status"] not in ("CHECKED_OUT", "HOURS_DISPUTED"):
            fail("ERR_INVALID_STATE", "Only a CHECKED_OUT or HOURS_DISPUTED shift may be verified.")
        if party["schedule_status"] != "COMPLETED":
            fail("ERR_INVALID_STATE", "The work party has not COMPLETED.")
        hours = shift["credited_hours"]
        shift["status"] = "HOURS_VERIFIED"
        shift["hours_verified_by_user_id"] = actor()
        touch(shift)
        if volunteer is not None:
            domain.move_hours(volunteer, pending_hours=-hours, verified_hours=hours)
        if plan is not None:
            plan["verified_volunteer_hours"] = calc.add_hours(
                plan["verified_volunteer_hours"], hours)
            touch(plan)
    elif decision == "DISPUTE":
        if shift["status"] != "CHECKED_OUT":
            fail("ERR_INVALID_STATE", "Only a CHECKED_OUT shift may be disputed.")
        delta = calc.add_hours(adjusted_hours, -shift["credited_hours"])
        shift["adjusted_hours"] = float(adjusted_hours)
        shift["dispute_reason"] = data.get("dispute_reason")
        shift["credited_hours"] = float(adjusted_hours)
        shift["status"] = "HOURS_DISPUTED"
        touch(shift)
        if volunteer is not None:
            domain.move_hours(volunteer, lifetime_credited_hours=delta, pending_hours=delta)
    else:
        if shift["status"] != "HOURS_DISPUTED":
            fail("ERR_INVALID_STATE", "Only a HOURS_DISPUTED shift may be reset.")
        checked_in_at = store.parse_dt(shift["checked_in_at"])
        checked_out_at = store.parse_dt(shift["checked_out_at"])
        worked, billable, hours = calc.credited_hours(
            checked_in_at, checked_out_at, party["travel_allowance_minutes"])
        delta = calc.add_hours(hours, -shift["credited_hours"])
        shift["worked_minutes"] = worked
        shift["billable_minutes"] = billable
        shift["credited_hours"] = hours
        shift["adjusted_hours"] = None
        shift["dispute_reason"] = None
        shift["status"] = "CHECKED_OUT"
        touch(shift)
        if volunteer is not None:
            domain.move_hours(volunteer, lifetime_credited_hours=delta, pending_hours=delta)
    return ok(domain.s_shift(shift))


@bp.post("/shifts/<entity_id>/certify")
@require("GrantsAdministrator")
def certify_shift(entity_id):
    shift = domain.get_shift(entity_id)
    if actor() == shift.get("hours_verified_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The certifier may not be the verifier of these hours.")

    if shift["status"] != "HOURS_VERIFIED":
        fail("ERR_INVALID_STATE", "Only a HOURS_VERIFIED shift may be certified.")

    party = domain.get_party(shift["work_party_id"])
    plan = domain.party_plan(party)
    volunteer = store.volunteers.get(shift["volunteer_id"])

    work_date = store.parse_dt(party["start_at"]).date()
    if not domain.waiver_current(volunteer, work_date):
        fail("ERR_WAIVER_NOT_SIGNED", "The volunteer's waiver did not cover the work date.")

    hours = shift["credited_hours"]
    shift["status"] = "HOURS_CERTIFIED"
    shift["hours_certified_by_user_id"] = actor()
    touch(shift)
    if volunteer is not None:
        domain.move_hours(volunteer, verified_hours=-hours, certified_hours=hours)
    if plan is not None:
        plan["verified_volunteer_hours"] = calc.add_hours(plan["verified_volunteer_hours"], -hours)
        plan["certified_volunteer_hours"] = calc.add_hours(plan["certified_volunteer_hours"], hours)
        touch(plan)
    return ok(domain.s_shift(shift))
