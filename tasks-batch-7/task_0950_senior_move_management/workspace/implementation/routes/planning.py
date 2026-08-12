"""Sort plans (the freeze point) and move-day plans (the six-hop cascade)."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import parse_dt, shift_hours, D

bp = Blueprint("planning", __name__)

PLAN_READ = ["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]
MDP_READ = ["MOVE_MANAGER", "CREW_LEAD", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]


# ---------------------------------------------------------------------------
# sort plans
# ---------------------------------------------------------------------------

@bp.route("/sort-plans", methods=["POST"])
def create_sort_plan():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"),
                                    ("expected_engagement_version", "int")],
                          optional=[("notes", "string")])
    engagement = gates.resolve_body_fks(req.body)["engagement_id"]
    gates.gate3(engagement)
    gates.gate11_version(req.body["expected_engagement_version"], engagement,
                         "ERR_STALE_ENGAGEMENT_VERSION")

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "approved_by_party_id": None,
        "status": "DRAFT",
        "notes": req.body.get("notes"),
        "rejected_reason": None,
        "reopen_count": 0,
        "undecided_count_at_submit": 0,
        "frozen_at_utc": None,
    })
    store.insert("sort_plans", record)
    store.touch(engagement)
    return one("sort_plans", record, 201)


@bp.route("/sort-plans", methods=["GET"])
def list_sort_plans():
    req = gates.preflight(PLAN_READ, is_list=True)
    rows = filtered(store.all_of("sort_plans"), req.args,
                    ["engagement_id", "approved_by_party_id", "status"])
    return listing("sort_plans", req, rows)


@bp.route("/sort-plans/<pid>", methods=["GET"])
def read_sort_plan(pid):
    req = gates.preflight(PLAN_READ)
    record = gates.path_record("sort_plans", pid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("sort_plans", record)


@bp.route("/sort-plans/<pid>/submit", methods=["POST"])
def submit_sort_plan(pid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("sort_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["DRAFT"], ["FROZEN"])

    items = derive.items_of(engagement["id"])
    undecided = [i for i in items if i["disposition"] == "UNDECIDED"]
    if undecided:
        raise ApiError("ERR_UNDECIDED_ITEMS_REMAIN")
    if not items:
        raise ApiError("ERR_NO_INVENTORY")
    for item in items:
        if derive.item_hold_state(item) == "HELD":
            raise ApiError("ERR_ITEM_UNDER_FAMILY_HOLD")

    record["status"] = "SUBMITTED"
    record["undecided_count_at_submit"] = len(undecided)
    store.touch(record)
    return one("sort_plans", record)


@bp.route("/sort-plans/<pid>/approve", methods=["POST"])
def approve_sort_plan(pid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("approved_by_party_id", "string")])
    record = gates.path_record("sort_plans", pid)
    gates.resolve_body_fks(req.body)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["approved_by_party_id"]])

    non_keep = [i["appraised_value_cents"] for i in derive.items_of(engagement["id"])
                if i["disposition"] != "KEEP"]
    subject = max(non_keep) if non_keep else 0
    gates.gate4_authority(req, "DISPOSITION", subject_value=subject)

    gates.gate10_state(record["status"], ["SUBMITTED"], ["FROZEN"])
    if record["undecided_count_at_submit"] != 0:
        raise ApiError("ERR_UNDECIDED_ITEMS_REMAIN")

    record["status"] = "APPROVED"
    record["approved_by_party_id"] = req.body["approved_by_party_id"]
    store.touch(record)
    services.sort_plan_approval_cascade(record, engagement, req.role)
    return one("sort_plans", record)


@bp.route("/sort-plans/<pid>/reject", methods=["POST"])
def reject_sort_plan(pid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("reason", "nes")])
    record = gates.path_record("sort_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_authority(req, "DISPOSITION")
    gates.gate10_state(record["status"], ["SUBMITTED"], ["FROZEN"])
    record["status"] = "REJECTED"
    record["rejected_reason"] = req.body["reason"]
    store.touch(record)
    return one("sort_plans", record)


@bp.route("/sort-plans/<pid>/reopen", methods=["POST"])
def reopen_sort_plan(pid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("sort_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    # rung 37 sits in gate 6 and therefore precedes the gate-10 state rung
    if record["status"] == "FROZEN":
        raise ApiError("ERR_SORT_PLAN_FROZEN")
    gates.gate10_state(record["status"], ["REJECTED", "APPROVED"], ["FROZEN"])
    was_approved = record["status"] == "APPROVED"
    if was_approved:
        plan = derive.move_day_plan_of(engagement["id"])
        gates.require_state(plan is None
                            or plan["status"] not in ("FROZEN", "IN_PROGRESS", "COMPLETED"))
    if record["reopen_count"] >= K.MAX_SORT_PLAN_REOPENS:
        raise ApiError("ERR_SORT_PLAN_REOPEN_LIMIT")

    record["reopen_count"] = record["reopen_count"] + 1
    record["status"] = "DRAFT"
    record["rejected_reason"] = None
    store.touch(record)
    if was_approved:
        for item in derive.items_of(engagement["id"]):
            if item["disposition_locked"]:
                item["disposition_locked"] = False
                store.touch(item)
        services.cascade_reopen_milestone(engagement["id"], "SORT_PLAN")
    return one("sort_plans", record)


# ---------------------------------------------------------------------------
# move-day plans
# ---------------------------------------------------------------------------

@bp.route("/move-day-plans", methods=["POST"])
def create_move_day_plan():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"),
                                    ("scheduled_start_utc", "datetime"),
                                    ("truck_capacity_cft", "number"),
                                    ("truck_count", "int")])
    engagement = gates.resolve_body_fks(req.body)["engagement_id"]
    gates.gate3(engagement)
    gates.gate5_phase(engagement, ["PACK", "MOVE_DAY"])

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "status": "DRAFT",
        "scheduled_start_utc": req.body["scheduled_start_utc"],
        "freeze_at_utc": shift_hours(req.body["scheduled_start_utc"], -K.MOVE_FREEZE_HOURS),
        "truck_capacity_cft": req.body["truck_capacity_cft"],
        "truck_count": req.body["truck_count"],
        "planned_trip_count": 0,
        "actual_trip_count": None,
        "actual_loaded_volume_cft": None,
        "reschedule_count": 0,
        "started_at_utc": None,
        "completed_at_utc": None,
    })
    store.insert("move_day_plans", record)
    return one("move_day_plans", record, 201)


@bp.route("/move-day-plans", methods=["GET"])
def list_move_day_plans():
    req = gates.preflight(MDP_READ, is_list=True)
    rows = filtered(store.all_of("move_day_plans"), req.args, ["engagement_id", "status"])
    return listing("move_day_plans", req, rows)


@bp.route("/move-day-plans/<pid>", methods=["GET"])
def read_move_day_plan(pid):
    req = gates.preflight(MDP_READ)
    record = gates.path_record("move_day_plans", pid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("move_day_plans", record)


def recompute_planned_trips(plan, engagement):
    plan["planned_trip_count"] = calc.truck_trip_count(
        derive.keep_volume_cft(engagement["id"]),
        plan["truck_capacity_cft"], plan["truck_count"])


@bp.route("/move-day-plans/<pid>/confirm", methods=["POST"])
def confirm_move_day_plan(pid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["CREWED"], ["COMPLETED"])
    sort_plan = derive.sort_plan_of(engagement["id"])
    gates.require_state(sort_plan is not None and sort_plan["status"] == "APPROVED")
    record["status"] = "CONFIRMED"
    recompute_planned_trips(record, engagement)
    store.touch(record)
    return one("move_day_plans", record)


@bp.route("/move-day-plans/<pid>/recrew", methods=["POST"])
def recrew_move_day_plan(pid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate6_roster_frozen(record)
    gates.gate10_state(record["status"], ["CONFIRMED"], ["COMPLETED"])
    for assignment in derive.assignments_of_plan(record["id"]):
        if assignment["status"] == "CONFIRMED":
            assignment["status"] = "ASSIGNED"
            store.touch(assignment)
    record["status"] = "DRAFT"
    store.touch(record)
    return one("move_day_plans", record)


@bp.route("/move-day-plans/<pid>/freeze", methods=["POST"])
def freeze_move_day_plan(pid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    if not gates.freeze_window_entered(record):
        raise ApiError("ERR_FREEZE_WINDOW_NOT_ENTERED")
    gates.gate10_state(record["status"], ["CONFIRMED"], ["COMPLETED"])

    record["status"] = "FROZEN"
    store.touch(record)
    sort_plan = derive.sort_plan_of(engagement["id"])
    if sort_plan is not None and sort_plan["status"] == "APPROVED":
        sort_plan["status"] = "FROZEN"
        sort_plan["frozen_at_utc"] = store.now_iso()
        store.touch(sort_plan)
    services.cascade_complete_milestone(engagement["id"], "PACK")
    return one("move_day_plans", record)


@bp.route("/move-day-plans/<pid>/start", methods=["POST"])
def start_move_day_plan(pid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["FROZEN"], ["COMPLETED"])
    gates.require_state(parse_dt(store.now_iso()) >= parse_dt(record["scheduled_start_utc"]))
    if derive.crew_confirmed_count(record) < derive.crew_min_required(record):
        raise ApiError("ERR_CREW_MINIMUM_NOT_MET")
    if derive.crew_lead_non_terminal_count(record) < K.CREW_LEAD_REQUIRED_COUNT:
        raise ApiError("ERR_CREW_LEAD_REQUIRED")

    record["status"] = "IN_PROGRESS"
    record["started_at_utc"] = store.now_iso()
    store.touch(record)
    return one("move_day_plans", record)


@bp.route("/move-day-plans/<pid>/complete", methods=["POST"])
def complete_move_day_plan(pid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"],
                          required=[("actual_loaded_volume_cft", "number")])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["IN_PROGRESS"], ["COMPLETED"])
    for assignment in derive.assignments_of_plan(record["id"]):
        gates.require_state(assignment["status"] in
                            ("COMPLETED", "NO_SHOW", "REPLACED", "CHECKED_IN"))

    record["status"] = "COMPLETED"
    record["completed_at_utc"] = store.now_iso()
    record["actual_loaded_volume_cft"] = req.body["actual_loaded_volume_cft"]
    store.touch(record)
    services.move_day_completion_cascade(record, engagement)
    record["actual_trip_count"] = calc.truck_trip_count(
        req.body["actual_loaded_volume_cft"], record["truck_capacity_cft"],
        record["truck_count"])
    return one("move_day_plans", record)


@bp.route("/move-day-plans/<pid>/reschedule", methods=["POST"])
def reschedule_move_day_plan(pid):
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("new_start_utc", "datetime"), ("reason", "nes")])
    record = gates.path_record("move_day_plans", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["CONFIRMED", "FROZEN"], ["COMPLETED"])
    if record["reschedule_count"] >= K.MAX_MOVE_DAY_RESCHEDULES:
        raise ApiError("ERR_RESCHEDULE_LIMIT")
    if parse_dt(req.body["new_start_utc"]) <= parse_dt(store.now_iso()):
        raise ApiError("ERR_RESCHEDULE_LIMIT")

    old_date = parse_dt(record["scheduled_start_utc"]).date().isoformat()
    new_date = parse_dt(req.body["new_start_utc"]).date().isoformat()
    record["reschedule_count"] = record["reschedule_count"] + 1
    record["scheduled_start_utc"] = req.body["new_start_utc"]
    record["freeze_at_utc"] = shift_hours(req.body["new_start_utc"], -K.MOVE_FREEZE_HOURS)
    for assignment in store.where("vendor_assignments", engagement_id=engagement["id"]):
        if assignment["status"] in ("ACCEPTED", "SCHEDULED", "COI_BLOCKED") and \
                assignment["service_date"] == old_date:
            assignment["service_date"] = new_date
            store.touch(assignment)
    # RESCHEDULED is never observable: the plan returns to DRAFT in this request
    record["status"] = "RESCHEDULED"
    for assignment in derive.assignments_of_plan(record["id"]):
        if assignment["status"] == "CONFIRMED":
            assignment["status"] = "ASSIGNED"
            store.touch(assignment)
    record["status"] = "DRAFT"
    store.touch(record)
    return one("move_day_plans", record)
