"""Crew members, crew assignments and time entries."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import parse_dt

bp = Blueprint("crew", __name__)

CREW_READ = ["MOVE_MANAGER", "CREW_LEAD", "BILLING_ADMIN"]
ASSIGNMENT_TERMINAL = ["COMPLETED", "REPLACED"]


# ---------------------------------------------------------------------------
# crew members - platform reference data, no engagement context
# ---------------------------------------------------------------------------

@bp.route("/crew-members", methods=["POST"])
def create_crew_member():
    req = gates.preflight(["PLATFORM_ADMIN"],
                          required=[("full_name", "string"), ("crew_role", "string")],
                          optional=[("hourly_rate_cents", "int")])
    rate = req.body.get("hourly_rate_cents")
    record = store.base_record()
    record.update({
        "full_name": req.body["full_name"],
        "crew_role": req.body["crew_role"],
        "hourly_rate_cents": K.ROLE_RATE_CENTS[req.body["crew_role"]] if rate is None else rate,
    })
    store.insert("crew_members", record)
    return one("crew_members", record, 201)


@bp.route("/crew-members/<cid>", methods=["GET"])
def read_crew_member(cid):
    req = gates.preflight(["PLATFORM_ADMIN", "MOVE_MANAGER", "CREW_LEAD"])
    record = gates.path_record("crew_members", cid)
    gates.gate4_ownership(req, crew_member_id=record["id"])
    return one("crew_members", record)


# ---------------------------------------------------------------------------
# crew assignments
# ---------------------------------------------------------------------------

@bp.route("/crew-assignments", methods=["POST"])
def create_crew_assignment():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("move_day_plan_id", "string"),
                                    ("crew_member_id", "string"),
                                    ("expected_move_day_plan_version", "int")],
                          optional=[("replaces_assignment_id", "string")])
    fks = gates.resolve_body_fks(req.body)
    plan = fks["move_day_plan_id"]
    member = store.get("crew_members", req.body["crew_member_id"])
    if member is None:
        raise ApiError("ERR_CREW_RECORD_NOT_FOUND")
    engagement = store.get("engagements", plan["engagement_id"])
    gates.gate3(engagement)
    gates.gate6_roster_frozen(plan)

    replaced = fks.get("replaces_assignment_id")
    if replaced is not None:
        gates.require_state(replaced["status"] == "NO_SHOW")

    gates.gate11_version(req.body["expected_move_day_plan_version"], plan,
                         "ERR_STALE_MOVE_DAY_PLAN_VERSION")

    record = store.base_record()
    record.update({
        "move_day_plan_id": plan["id"],
        "crew_member_id": member["id"],
        "replaces_assignment_id": replaced["id"] if replaced is not None else None,
        "status": "ASSIGNED",
        "checked_in_at_utc": None,
        "checked_out_at_utc": None,
        "no_show_note": None,
    })
    store.insert("crew_assignments", record)
    if replaced is not None:
        replaced["status"] = "REPLACED"
        store.touch(replaced)
    store.touch(plan)
    return one("crew_assignments", record, 201)


@bp.route("/crew-assignments", methods=["GET"])
def list_crew_assignments():
    req = gates.preflight(CREW_READ, is_list=True)
    rows = filtered(store.all_of("crew_assignments"), req.args,
                    ["move_day_plan_id", "crew_member_id", "replaces_assignment_id", "status"])
    return listing("crew_assignments", req, rows)


@bp.route("/crew-assignments/<aid>", methods=["GET"])
def read_crew_assignment(aid):
    req = gates.preflight(CREW_READ)
    record = gates.path_record("crew_assignments", aid)
    gates.gate4_ownership(req, engagement=derive.assignment_engagement(record))
    return one("crew_assignments", record)


def _assignment_context(aid):
    record = gates.path_record("crew_assignments", aid)
    plan = store.get("move_day_plans", record["move_day_plan_id"])
    engagement = store.get("engagements", plan["engagement_id"])
    return record, plan, engagement


@bp.route("/crew-assignments/<aid>/confirm", methods=["POST"])
def confirm_crew_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"])
    record, plan, engagement = _assignment_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate6_roster_frozen(plan)
    gates.gate10_state(record["status"], ["ASSIGNED"], ASSIGNMENT_TERMINAL)
    gates.require_state(plan["status"] in ("DRAFT", "CREWED"))

    record["status"] = "CONFIRMED"
    store.touch(record)
    if plan["status"] == "DRAFT" \
            and derive.crew_confirmed_count(plan) >= derive.crew_min_required(plan) \
            and derive.crew_lead_confirmed_count(plan) >= K.CREW_LEAD_REQUIRED_COUNT:
        plan["status"] = "CREWED"
        plan["planned_trip_count"] = calc.truck_trip_count(
            derive.keep_volume_cft(engagement["id"]),
            plan["truck_capacity_cft"], plan["truck_count"])
        store.touch(plan)
    return one("crew_assignments", record)


@bp.route("/crew-assignments/<aid>/check-in", methods=["POST"])
def check_in_crew_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"], required=[("at_utc", "datetime")])
    record, plan, engagement = _assignment_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["CONFIRMED"], ASSIGNMENT_TERMINAL)
    gates.require_state(plan["status"] == "IN_PROGRESS")
    gates.require_state(plan["started_at_utc"] is not None
                        and parse_dt(req.body["at_utc"]) >= parse_dt(plan["started_at_utc"]))

    record["status"] = "CHECKED_IN"
    record["checked_in_at_utc"] = req.body["at_utc"]
    store.touch(record)
    return one("crew_assignments", record)


@bp.route("/crew-assignments/<aid>/check-out", methods=["POST"])
def check_out_crew_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"], required=[("at_utc", "datetime")])
    record, plan, engagement = _assignment_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["CHECKED_IN"], ASSIGNMENT_TERMINAL)
    if parse_dt(req.body["at_utc"]) <= parse_dt(record["checked_in_at_utc"]):
        raise ApiError("ERR_INVALID_TIME_RANGE")

    record["status"] = "COMPLETED"
    record["checked_out_at_utc"] = req.body["at_utc"]
    services.create_time_entry(record, "LABOR", record["checked_in_at_utc"],
                               req.body["at_utc"])
    store.touch(record)
    return one("crew_assignments", record)


@bp.route("/crew-assignments/<aid>/no-show", methods=["POST"])
def no_show_crew_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"], required=[("note", "string")])
    record, plan, engagement = _assignment_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["ASSIGNED", "CONFIRMED"], ASSIGNMENT_TERMINAL)
    record["status"] = "NO_SHOW"
    record["no_show_note"] = req.body["note"]
    store.touch(record)
    return one("crew_assignments", record)


# ---------------------------------------------------------------------------
# time entries
# ---------------------------------------------------------------------------

@bp.route("/time-entries", methods=["POST"])
def create_time_entry():
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"],
                          required=[("crew_assignment_id", "string"),
                                    ("entry_kind", "string"),
                                    ("started_at_utc", "datetime"),
                                    ("ended_at_utc", "datetime")])
    fks = gates.resolve_body_fks(req.body)
    assignment = fks["crew_assignment_id"]
    engagement = derive.assignment_engagement(assignment)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.require_state(assignment["status"] in ("CHECKED_IN", "COMPLETED"))
    if parse_dt(req.body["ended_at_utc"]) <= parse_dt(req.body["started_at_utc"]):
        raise ApiError("ERR_INVALID_TIME_RANGE")

    record = services.create_time_entry(assignment, req.body["entry_kind"],
                                        req.body["started_at_utc"],
                                        req.body["ended_at_utc"])
    return one("time_entries", record, 201)


@bp.route("/time-entries", methods=["GET"])
def list_time_entries():
    req = gates.preflight(CREW_READ, is_list=True)
    rows = filtered(store.all_of("time_entries"), req.args,
                    ["crew_assignment_id", "entry_kind"])
    return listing("time_entries", req, rows)


@bp.route("/time-entries/<tid>", methods=["GET"])
def read_time_entry(tid):
    req = gates.preflight(CREW_READ)
    record = gates.path_record("time_entries", tid)
    assignment = store.get("crew_assignments", record["crew_assignment_id"])
    gates.gate4_ownership(req, engagement=derive.assignment_engagement(assignment))
    return one("time_entries", record)


@bp.route("/time-entries/<tid>/void", methods=["POST"])
def void_time_entry(tid):
    req = gates.preflight(["MOVE_MANAGER", "BILLING_ADMIN"], required=[("reason", "nes")])
    record = gates.path_record("time_entries", tid)
    assignment = store.get("crew_assignments", record["crew_assignment_id"])
    engagement = derive.assignment_engagement(assignment)
    gates.gate3(engagement)
    gates.require_state(not record["voided"])
    record["voided"] = True
    record["void_reason"] = req.body["reason"]
    store.touch(record)
    return one("time_entries", record)
