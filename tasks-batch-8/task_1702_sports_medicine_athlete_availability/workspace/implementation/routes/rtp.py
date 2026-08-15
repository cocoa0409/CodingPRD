"""RTP protocols, stage advances, regressions, clearance authorizations."""
from datetime import timedelta

from flask import Blueprint, request

from db import (STORE, new_id, now_stamp, touch, clock_date, clock_dt,
                logical_now_iso, fmt_ts, parse_iso_dt)
from errors import (bad_request, not_found, conflict, ApiError,
                    ERR_STALE_VERSION, ERR_CASE_NOT_IN_REHAB,
                    ERR_RTP_ALREADY_EXISTS, ERR_NO_ACTIVE_TREATMENT_PLAN,
                    ERR_PROTOCOL_NOT_ADVANCEABLE, ERR_PROTOCOL_NOT_REGRESSABLE,
                    ERR_CANNOT_REGRESS_BELOW_ZERO,
                    ERR_PROTOCOL_NOT_AWAITING_CLEARANCE,
                    ERR_CLEARANCE_NOT_PENDING, ERR_CLEARANCE_ALREADY_PENDING,
                    ERR_SOD_SELF_CLEARANCE, ERR_SOD_EVALUATOR_CLEARANCE,
                    ERR_STALE_EVALUATION, ERR_NO_FRESH_STATUS_ENTRY)
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import (rtp_protocol_json, rtp_stage_advance_json,
                                clearance_json, sorted_items)
from services.common import find_all, find_one, latest_current_entry
from services.derived import recompute_athlete
from services.rtp import evaluate_readiness
from util import body, present, require_int, optional_str

bp = Blueprint("rtp", __name__)

PROTOCOL_READERS = ("MedicalStaff", "TeamPhysician", "TeamAdmin")
CLEARANCE_TTL_HOURS = 72
CLEARANCE_EVAL_MAX_AGE_HOURS = 72
DECISIONS = ("GRANTED", "RETURNED_FOR_REVIEW")


def _get_protocol(pid):
    p = STORE["rtp_protocols"].get(pid)
    if p is None:
        raise not_found("RTPProtocol not found")
    return p


def _get_clearance(cid):
    c = STORE["clearances"].get(cid)
    if c is None:
        raise not_found("ClearanceAuthorization not found")
    return c


def _check_protocol_occ(j, protocol):
    if not present(j, "expected_protocol_version"):
        raise bad_request("Missing required field: expected_protocol_version")
    ev = j["expected_protocol_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise bad_request("Invalid expected_protocol_version")
    if ev != protocol["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_protocol_version does not match current version")


# ---------------- RTP protocols ----------------

@bp.route("/rtp-protocols", methods=["POST"])
def create_rtp_protocol():
    require_roles("MedicalStaff")
    j = body()
    # existence (3)
    case = None
    if present(j, "injury_case_id"):
        case = STORE["injury_cases"].get(j["injury_case_id"])
        if case is None:
            raise not_found("InjuryCase not found: injury_case_id")
    if case is None:
        raise bad_request("Missing required field: injury_case_id")
    # state (4)
    if case["status"] != "REHAB":
        raise conflict(ERR_CASE_NOT_IN_REHAB,
                       "RTP creation requires case REHAB")
    # aggregate (9)
    active_plan = find_one("treatment_plans",
                           lambda p: p["injury_case_id"] == case["id"]
                           and p["status"] == "ACTIVE")
    if active_plan is None:
        raise conflict(ERR_NO_ACTIVE_TREATMENT_PLAN,
                       "RTP creation requires an ACTIVE treatment plan")
    # field constraints (10)
    total_stages = require_int(j, "total_stages", 3, 7)
    # uniqueness (17)
    existing = find_one("rtp_protocols",
                        lambda p: p["injury_case_id"] == case["id"])
    if existing is not None:
        raise conflict(ERR_RTP_ALREADY_EXISTS,
                       "An RTPProtocol already exists for this InjuryCase")
    today = clock_date()
    ts = now_stamp()
    protocol = {
        "id": new_id(), "injury_case_id": case["id"],
        "athlete_id": case["athlete_id"], "total_stages": total_stages,
        "current_stage_index": 0,
        "current_stage_entered_on": today.isoformat(),
        "_current_stage_entered_on": today,
        "regression_count": 0, "status": "NOT_STARTED",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["rtp_protocols"][protocol["id"]] = protocol
    # case REHAB -> RTP
    case["status"] = "RTP"
    touch(case)
    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(rtp_protocol_json(protocol), 201)


@bp.route("/rtp-protocols", methods=["GET"])
def list_rtp_protocols():
    require_roles(*PROTOCOL_READERS)
    items = sorted_items(STORE["rtp_protocols"])
    injury_case_id = request.args.get("injury_case_id")
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    if injury_case_id is not None:
        items = [p for p in items if p["injury_case_id"] == injury_case_id]
    if athlete_id is not None:
        items = [p for p in items if p["athlete_id"] == athlete_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list([rtp_protocol_json(p) for p in items])


@bp.route("/rtp-protocols/<protocolId>", methods=["GET"])
def get_rtp_protocol(protocolId):
    require_roles(*PROTOCOL_READERS)
    return ok_obj(rtp_protocol_json(_get_protocol(protocolId)))


# ---------------- Stage advances ----------------

@bp.route("/rtp-protocols/<protocolId>/advances", methods=["POST"])
def create_advance(protocolId):
    uid, _ = require_roles("MedicalStaff")
    protocol = _get_protocol(protocolId)
    j = body()
    _check_protocol_occ(j, protocol)
    if protocol["status"] not in ("NOT_STARTED", "IN_PROGRESS", "REGRESSED"):
        raise conflict(ERR_PROTOCOL_NOT_ADVANCEABLE,
                       "Protocol is not in an advanceable state")
    case = STORE["injury_cases"][protocol["injury_case_id"]]
    was_regressed = protocol["status"] == "REGRESSED"
    snapshot = evaluate_readiness(protocol, case)  # raises on failure

    today = clock_date()
    from_idx = protocol["current_stage_index"]
    to_idx = from_idx + 1
    protocol["current_stage_index"] = to_idx
    protocol["current_stage_entered_on"] = today.isoformat()
    protocol["_current_stage_entered_on"] = today
    if to_idx == protocol["total_stages"] - 1:
        protocol["status"] = "AWAITING_CLEARANCE"
    else:
        protocol["status"] = "IN_PROGRESS"
    touch(protocol)

    adv = {
        "id": new_id(), "rtp_protocol_id": protocol["id"],
        "from_stage_index": from_idx, "to_stage_index": to_idx,
        "kind": "ADVANCE", "advanced_by_user_id": uid,
        "readiness_snapshot": snapshot, "created_at": now_stamp(),
    }
    STORE["rtp_stage_advances"][adv["id"]] = adv

    # regression-cycle: advance out of REGRESSED returns case REHAB -> RTP
    if was_regressed and case["status"] == "REHAB":
        case["status"] = "RTP"
        touch(case)
        athlete = STORE["athletes"][case["athlete_id"]]
        recompute_athlete(athlete, bump=True)
    return ok_obj(rtp_stage_advance_json(adv), 201)


@bp.route("/rtp-protocols/<protocolId>/advances", methods=["GET"])
def list_protocol_advances(protocolId):
    require_roles(*PROTOCOL_READERS)
    _get_protocol(protocolId)
    items = [a for a in sorted_items(STORE["rtp_stage_advances"])
             if a["rtp_protocol_id"] == protocolId]
    return ok_list([rtp_stage_advance_json(a) for a in items])


@bp.route("/rtp-stage-advances", methods=["GET"])
def list_stage_advances():
    require_roles(*PROTOCOL_READERS)
    items = sorted_items(STORE["rtp_stage_advances"])
    rtp_protocol_id = request.args.get("rtp_protocol_id")
    kind = request.args.get("kind")
    if rtp_protocol_id is not None:
        items = [a for a in items if a["rtp_protocol_id"] == rtp_protocol_id]
    if kind is not None:
        items = [a for a in items if a["kind"] == kind]
    return ok_list([rtp_stage_advance_json(a) for a in items])


@bp.route("/rtp-stage-advances/<advanceId>", methods=["GET"])
def get_stage_advance(advanceId):
    require_roles(*PROTOCOL_READERS)
    a = STORE["rtp_stage_advances"].get(advanceId)
    if a is None:
        raise not_found("RTPStageAdvance not found")
    return ok_obj(rtp_stage_advance_json(a))


# ---------------- Regression ----------------

@bp.route("/rtp-protocols/<protocolId>/regress", methods=["POST"])
def regress_protocol(protocolId):
    uid, _ = require_roles("MedicalStaff")
    protocol = _get_protocol(protocolId)
    if protocol["status"] not in ("IN_PROGRESS", "AWAITING_CLEARANCE"):
        raise conflict(ERR_PROTOCOL_NOT_REGRESSABLE,
                       "regress requires protocol IN_PROGRESS or AWAITING_CLEARANCE")
    if protocol["current_stage_index"] <= 0:
        raise conflict(ERR_CANNOT_REGRESS_BELOW_ZERO,
                       "Cannot regress below stage zero")
    j = body()
    if not present(j, "reason") or not isinstance(j["reason"], str):
        raise bad_request("Missing required field: reason")

    today = clock_date()
    from_idx = protocol["current_stage_index"]
    protocol["current_stage_index"] = from_idx - 1
    protocol["current_stage_entered_on"] = today.isoformat()
    protocol["_current_stage_entered_on"] = today
    protocol["regression_count"] += 1
    protocol["status"] = "REGRESSED"
    touch(protocol)

    adv = {
        "id": new_id(), "rtp_protocol_id": protocol["id"],
        "from_stage_index": from_idx, "to_stage_index": from_idx - 1,
        "kind": "REGRESSION", "advanced_by_user_id": uid,
        "readiness_snapshot": None, "created_at": now_stamp(),
    }
    STORE["rtp_stage_advances"][adv["id"]] = adv

    # cascade: parent case RTP -> REHAB
    case = STORE["injury_cases"][protocol["injury_case_id"]]
    if case["status"] == "RTP":
        case["status"] = "REHAB"
        touch(case)
    # cascade: any PENDING clearance on this protocol -> EXPIRED
    for c in find_all("clearances",
                      lambda c: c["rtp_protocol_id"] == protocol["id"]
                      and c["status"] == "PENDING"):
        c["status"] = "EXPIRED"
        touch(c)
    athlete = STORE["athletes"][protocol["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(rtp_protocol_json(protocol))


# ---------------- Clearances ----------------

@bp.route("/rtp-protocols/<protocolId>/clearances", methods=["POST"])
def request_clearance(protocolId):
    uid, _ = require_roles("MedicalStaff")
    protocol = _get_protocol(protocolId)
    j = body()
    _check_protocol_occ(j, protocol)
    # state (4)
    if protocol["status"] != "AWAITING_CLEARANCE":
        raise conflict(ERR_PROTOCOL_NOT_AWAITING_CLEARANCE,
                       "Clearance request requires protocol AWAITING_CLEARANCE")
    returned = find_all("clearances",
                        lambda c: c["rtp_protocol_id"] == protocol["id"]
                        and c["status"] == "RETURNED_FOR_REVIEW")
    pending = find_one("clearances",
                       lambda c: c["rtp_protocol_id"] == protocol["id"]
                       and c["status"] == "PENDING")
    # re-request freshness (8)
    if returned and pending is None:
        today = clock_date()
        fresh = any(e["injury_case_id"] == protocol["injury_case_id"]
                    and e["is_current"] and e["_entry_date"] == today
                    for e in STORE["daily_status_entries"].values())
        if not fresh:
            raise conflict(ERR_NO_FRESH_STATUS_ENTRY,
                           "Re-request lacks a status entry dated today")
    # uniqueness (17)
    if pending is not None:
        raise conflict(ERR_CLEARANCE_ALREADY_PENDING,
                       "A PENDING clearance already exists on the protocol")
    request_notes = optional_str(j, "request_notes")

    ts = now_stamp()
    clearance = {
        "id": new_id(), "rtp_protocol_id": protocol["id"],
        "injury_case_id": protocol["injury_case_id"],
        "athlete_id": protocol["athlete_id"],
        "requested_by_user_id": uid, "decided_by_user_id": None,
        "decision": None, "status": "PENDING",
        "requested_at": logical_now_iso(), "decided_at": None,
        "expires_at": None, "request_notes": request_notes,
        "decision_notes": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["clearances"][clearance["id"]] = clearance
    # re-request path: prior RETURNED_FOR_REVIEW rows -> EXPIRED
    for old in returned:
        old["status"] = "EXPIRED"
        touch(old)
    # request creation mutates the protocol (version +1)
    touch(protocol)
    return ok_obj(clearance_json(clearance), 201)


@bp.route("/clearances", methods=["GET"])
def list_clearances():
    require_roles(*PROTOCOL_READERS)
    items = sorted_items(STORE["clearances"])
    rtp_protocol_id = request.args.get("rtp_protocol_id")
    injury_case_id = request.args.get("injury_case_id")
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    if rtp_protocol_id is not None:
        items = [c for c in items if c["rtp_protocol_id"] == rtp_protocol_id]
    if injury_case_id is not None:
        items = [c for c in items if c["injury_case_id"] == injury_case_id]
    if athlete_id is not None:
        items = [c for c in items if c["athlete_id"] == athlete_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return ok_list([clearance_json(c) for c in items])


@bp.route("/clearances/<clearanceId>", methods=["GET"])
def get_clearance(clearanceId):
    require_roles(*PROTOCOL_READERS)
    return ok_obj(clearance_json(_get_clearance(clearanceId)))


@bp.route("/clearances/<clearanceId>/decide", methods=["POST"])
def decide_clearance(clearanceId):
    uid, _ = require_roles("TeamPhysician")
    clearance = _get_clearance(clearanceId)
    j = body()
    decision = j.get("decision")
    decision_valid = decision in DECISIONS

    # state (4)
    if clearance["status"] != "PENDING":
        raise conflict(ERR_CLEARANCE_NOT_PENDING,
                       "decide requires clearance PENDING")
    protocol = STORE["rtp_protocols"][clearance["rtp_protocol_id"]]
    if decision == "GRANTED" and protocol["status"] != "AWAITING_CLEARANCE":
        raise conflict(ERR_PROTOCOL_NOT_AWAITING_CLEARANCE,
                       "GRANTED requires protocol AWAITING_CLEARANCE")
    # segregation of duties (5)
    if uid == clearance["requested_by_user_id"]:
        raise ApiError(ERR_SOD_SELF_CLEARANCE, 403,
                       "Clearance decider is the same user as the requester")
    case = STORE["injury_cases"][clearance["injury_case_id"]]
    latest = latest_current_entry(case["id"])
    if latest is not None and uid == latest["recorded_by_user_id"]:
        raise ApiError(ERR_SOD_EVALUATOR_CLEARANCE, 403,
                       "Clearance decider recorded the latest status entry")
    # evaluation freshness (6) — GRANTED only
    if decision == "GRANTED":
        stale = True
        if latest is not None:
            created = parse_iso_dt(latest["created_at"])
            if created is not None and (clock_dt() - created) <= timedelta(hours=CLEARANCE_EVAL_MAX_AGE_HOURS):
                stale = False
        if stale:
            raise conflict(ERR_STALE_EVALUATION,
                           "Latest status entry is older than the evaluation window")
    # field constraints (10)
    if not decision_valid:
        raise bad_request("decision must be one of GRANTED | RETURNED_FOR_REVIEW")
    decision_notes = optional_str(j, "decision_notes")

    now_iso = logical_now_iso()
    clearance["decision"] = decision
    clearance["decided_by_user_id"] = uid
    clearance["decided_at"] = now_iso
    clearance["decision_notes"] = decision_notes

    if decision == "GRANTED":
        clearance["status"] = "GRANTED"
        clearance["expires_at"] = fmt_ts(clock_dt() + timedelta(hours=CLEARANCE_TTL_HOURS))
        touch(clearance)
        # protocol AWAITING_CLEARANCE -> CLEARED; case RTP -> CLEARED
        protocol["status"] = "CLEARED"
        touch(protocol)
        case["status"] = "CLEARED"
        case["cleared_on"] = clock_date().isoformat()
        touch(case)
        athlete = STORE["athletes"][case["athlete_id"]]
        recompute_athlete(athlete, bump=True)
    else:
        clearance["status"] = "RETURNED_FOR_REVIEW"
        touch(clearance)
    return ok_obj(clearance_json(clearance))
