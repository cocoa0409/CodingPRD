"""Milestones, unpack sessions and the punch list."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered

bp = Blueprint("timeline", __name__)

MILESTONE_READ = ["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY",
                  "BILLING_ADMIN"]
SESSION_ROLES = ["MOVE_MANAGER", "CREW_LEAD", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]
PUNCH_ROLES = ["MOVE_MANAGER", "CREW_LEAD", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]
SETTLE_PHASES = ["SETTLE_IN", "CLOSE_OUT"]


# ---------------------------------------------------------------------------
# milestones
# ---------------------------------------------------------------------------

@bp.route("/milestones", methods=["GET"])
def list_milestones():
    req = gates.preflight(MILESTONE_READ, is_list=True)
    rows = filtered(store.all_of("milestones"), req.args,
                    ["engagement_id", "completed_by_party_id", "milestone_key", "status",
                     "overdue_status"])
    rows = sorted(rows, key=lambda m: (m["sequence_index"], m["_seq"]))
    return listing("milestones", req, rows)


@bp.route("/milestones/<mid>", methods=["GET"])
def read_milestone(mid):
    req = gates.preflight(MILESTONE_READ)
    record = gates.path_record("milestones", mid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("milestones", record)


@bp.route("/milestones/<mid>/complete", methods=["POST"])
def complete_milestone(mid):
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("completed_by_party_id", "string")])
    record = gates.path_record("milestones", mid)
    gates.resolve_body_fks(req.body)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_party_membership(engagement, [req.body["completed_by_party_id"]])

    if record["sequence_index"] > 1:
        predecessor = None
        for row in derive.milestones_of(engagement["id"]):
            if row["sequence_index"] == record["sequence_index"] - 1:
                predecessor = row
        if predecessor is None or predecessor["status"] != "COMPLETE":
            raise ApiError("ERR_PREDECESSOR_MILESTONE_INCOMPLETE")

    gates.gate10_state(record["status"], ["IN_PROGRESS", "REOPENED"])
    if record["milestone_key"] == "MOVE_DAY":
        plan = derive.move_day_plan_of(engagement["id"])
        gates.require_state(plan is not None and plan["status"] == "COMPLETED")
    if record["milestone_key"] == "CLOSE_OUT":
        gates.require_state(not derive.billing_hold(engagement))
        for punch in store.where("punch_list_items", engagement_id=engagement["id"]):
            gates.require_state(punch["status"] not in ("OPEN", "REOPENED"))

    services.complete_milestone(record, req.body["completed_by_party_id"])
    return one("milestones", record)


@bp.route("/milestones/<mid>/reopen", methods=["POST"])
def reopen_milestone(mid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("milestones", mid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)

    for row in derive.milestones_of(engagement["id"]):
        if row["sequence_index"] > record["sequence_index"] and row["status"] == "COMPLETE":
            raise ApiError("ERR_SUCCESSOR_MILESTONE_COMPLETE")

    gates.gate10_state(record["status"], ["COMPLETE"])
    if record["reopen_count"] >= K.MAX_MILESTONE_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT")

    services.reopen_milestone(record)
    return one("milestones", record)


# ---------------------------------------------------------------------------
# unpack sessions
# ---------------------------------------------------------------------------

@bp.route("/unpack-sessions", methods=["POST"])
def create_session():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"),
                                    ("scheduled_start_utc", "datetime"),
                                    ("priority", "string")])
    engagement = gates.resolve_body_fks(req.body)["engagement_id"]
    gates.gate3(engagement)
    gates.gate5_phase(engagement, SETTLE_PHASES)

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "priority": req.body["priority"],
        "status": "SCHEDULED",
        "scheduled_start_utc": req.body["scheduled_start_utc"],
        "reopen_count": 0,
        "started_at_utc": None,
    })
    store.insert("unpack_sessions", record)
    return one("unpack_sessions", record, 201)


@bp.route("/unpack-sessions", methods=["GET"])
def list_sessions():
    req = gates.preflight(SESSION_ROLES, is_list=True)
    rows = filtered(store.all_of("unpack_sessions"), req.args,
                    ["engagement_id", "status", "priority"])
    return listing("unpack_sessions", req, rows)


@bp.route("/unpack-sessions/<sid>", methods=["GET"])
def read_session(sid):
    req = gates.preflight(SESSION_ROLES)
    record = gates.path_record("unpack_sessions", sid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("unpack_sessions", record)


@bp.route("/unpack-sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"])
    record = gates.path_record("unpack_sessions", sid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["SCHEDULED", "REOPENED"])
    plan = derive.move_day_plan_of(engagement["id"])
    gates.require_state(plan is not None and plan["status"] == "COMPLETED")

    if record["priority"] == "STANDARD":
        for other in store.where("unpack_sessions", engagement_id=engagement["id"]):
            if other["priority"] != "ESSENTIALS" or other["_seq"] >= record["_seq"]:
                continue
            if other["status"] != "COMPLETED":
                raise ApiError("ERR_ESSENTIALS_SESSION_PENDING")

    record["status"] = "IN_PROGRESS"
    record["started_at_utc"] = store.now_iso()
    store.touch(record)
    return one("unpack_sessions", record)


@bp.route("/unpack-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"])
    record = gates.path_record("unpack_sessions", sid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["IN_PROGRESS"])
    record["status"] = "COMPLETED"
    store.touch(record)
    return one("unpack_sessions", record)


# ---------------------------------------------------------------------------
# punch list
# ---------------------------------------------------------------------------

@bp.route("/punch-list-items", methods=["POST"])
def create_punch():
    req = gates.preflight(PUNCH_ROLES,
                          required=[("engagement_id", "string"), ("description", "string"),
                                    ("severity", "string")],
                          optional=[("unpack_session_id", "string")])
    fks = gates.resolve_body_fks(req.body)
    engagement = fks["engagement_id"]
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate5_phase(engagement, SETTLE_PHASES)

    session = fks.get("unpack_session_id")
    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "unpack_session_id": session["id"] if session is not None else None,
        "severity": req.body["severity"],
        "status": "OPEN",
        "description": req.body["description"],
        "resolution_note": None,
        "reopen_count": 0,
    })
    store.insert("punch_list_items", record)
    return one("punch_list_items", record, 201)


@bp.route("/punch-list-items", methods=["GET"])
def list_punch():
    req = gates.preflight(PUNCH_ROLES, is_list=True)
    rows = filtered(store.all_of("punch_list_items"), req.args,
                    ["engagement_id", "unpack_session_id", "status", "severity"])
    return listing("punch_list_items", req, rows)


@bp.route("/punch-list-items/<pid>", methods=["GET"])
def read_punch(pid):
    req = gates.preflight(PUNCH_ROLES)
    record = gates.path_record("punch_list_items", pid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("punch_list_items", record)


@bp.route("/punch-list-items/<pid>/resolve", methods=["POST"])
def resolve_punch(pid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"],
                          required=[("resolution_note", "nes")])
    record = gates.path_record("punch_list_items", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["OPEN", "REOPENED"])
    record["status"] = "RESOLVED"
    record["resolution_note"] = req.body["resolution_note"]
    store.touch(record)
    return one("punch_list_items", record)


@bp.route("/punch-list-items/<pid>/reopen", methods=["POST"])
def reopen_punch(pid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"],
                          required=[("reason", "nes")])
    record = gates.path_record("punch_list_items", pid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["RESOLVED"])
    if record["reopen_count"] >= K.MAX_PUNCH_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT")

    record["reopen_count"] = record["reopen_count"] + 1
    record["status"] = "REOPENED"
    store.touch(record)
    # cascade hop 1 - the named session, guarded by its own reopen cap
    if record["unpack_session_id"] is not None:
        session = store.get("unpack_sessions", record["unpack_session_id"])
        if session is not None and session["status"] == "COMPLETED" \
                and session["reopen_count"] < K.MAX_UNPACK_REOPENS:
            session["status"] = "REOPENED"
            session["reopen_count"] = session["reopen_count"] + 1
            store.touch(session)
    # cascade hop 2 - a COMPLETE CLOSE_OUT milestone
    services.cascade_reopen_milestone(engagement["id"], "CLOSE_OUT")
    return one("punch_list_items", record)
