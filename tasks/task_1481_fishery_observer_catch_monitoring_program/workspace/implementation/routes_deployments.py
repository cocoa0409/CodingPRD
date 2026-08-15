"""Deployments, safety inspections, and haul samples (PRD 3.4-3.6)."""

from flask import Blueprint

import logic
import store
from core import (
    ALL_ROLES, ApiError, body, dec, err_forbidden, err_invalid, err_state,
    get_or_404, is_int, list_response, ok, parse_dt, req_decimal2, req_dt,
    req_int, req_str, require_roles, round4,
)

bp = Blueprint("deployments", __name__, url_prefix="/observer-program")

CHECKLIST_FIELDS = (
    "life_raft_certified", "epirb_registered", "immersion_suits_adequate",
    "fire_suppression_ok", "comms_equipment_ok",
)


def _owning_observer(a, deployment):
    if deployment["observer_id"] != a["id"]:
        raise err_forbidden("The acting observer is not the deployment's observer")


# ---------------------------------------------------------------------------
# Deployment create / reschedule / cancel / lifecycle
# ---------------------------------------------------------------------------


@bp.post("/deployments")
def create_deployment():
    require_roles("ProgramCoordinator")
    b = body()
    # Body FK existence, left-to-right (priority 3).
    notice_id = b.get("selection_notice_id")
    if isinstance(notice_id, str):
        get_or_404("selection_notices", notice_id, "SelectionNotice")
    observer_id = b.get("observer_id")
    if isinstance(observer_id, str):
        get_or_404("observers", observer_id, "Observer")
    # Schema (priority 4).
    notice_id = req_str(b, "selection_notice_id")
    observer_id = req_str(b, "observer_id")
    dep_s = req_dt(b, "scheduled_departure_date")
    ret_s = req_dt(b, "scheduled_return_date")
    expected = b.get("expected_selection_notice_version")
    if expected is None or not is_int(expected):
        raise err_invalid("Field 'expected_selection_notice_version' is required and must be an integer")
    notice = store.db["selection_notices"][notice_id]
    observer = store.db["observers"][observer_id]
    # OCC (priority 5).
    if expected != notice["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_selection_notice_version does not match the notice's current version")
    # State (priority 6).
    if notice["status"] != "ACCEPTED":
        raise ApiError("ERR_NOTICE_NOT_ACCEPTED", 409,
                       "Deployments may only be scheduled against an ACCEPTED notice")
    # Temporal (priority 8).
    dep_dt = parse_dt(dep_s)
    ret_dt = parse_dt(ret_s)
    if ret_dt <= dep_dt:
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "scheduled_return_date must fall after scheduled_departure_date")
    planned = logic.days_between(ret_dt, dep_dt) + 1
    if planned > logic.MAX_DEPLOYMENT_SEA_DAYS:
        raise ApiError("ERR_DEPLOYMENT_TOO_LONG", 422,
                       "planned_sea_days exceeds 45")
    logic.check_observer_overlap(observer_id, dep_dt, ret_dt)
    logic.check_vessel_turnaround(notice["vessel_id"], dep_dt)
    # Referential (priority 9).
    vessel = store.db["vessels"].get(notice["vessel_id"])
    if vessel is None or vessel["status"] != "ACTIVE":
        raise ApiError("ERR_VESSEL_NOT_ACTIVE", 409, "The notice's vessel is not ACTIVE")
    if vessel["monitoring_mode"] != "HUMAN_OBSERVER":
        raise ApiError("ERR_VESSEL_NOT_HUMAN_MODE", 409,
                       "The vessel is in ELECTRONIC_MONITORING mode")
    if observer["status"] != "ACTIVE":
        raise ApiError("ERR_OBSERVER_NOT_AVAILABLE", 409,
                       "The observer is not ACTIVE")
    operator = store.db["operators"].get(vessel["operator_id"])
    if operator is not None and operator["payment_standing"] != "GOOD":
        raise ApiError("ERR_OPERATOR_DELINQUENT", 409,
                       "The vessel's operator is DELINQUENT")
    # Caps (priority 10).
    logic.check_observer_caps(observer, planned)
    # Fiscal / allocation (priority 11).
    if planned > notice["remaining_sea_days"]:
        raise ApiError("ERR_SEA_DAY_ALLOCATION_EXCEEDED", 422,
                       "planned_sea_days exceed the notice's remaining_sea_days")

    deployment = store.new_entity({
        "selection_notice_id": notice["id"],
        "coverage_plan_id": notice["coverage_plan_id"],
        "vessel_id": notice["vessel_id"],
        "observer_id": observer_id,
        "assigned_debriefer_id": None,
        "scheduled_departure_date": dep_s,
        "scheduled_return_date": ret_s,
        "planned_sea_days": planned,
        "actual_return_date": None,
        "actual_sea_days": None,
        "latest_safety_result": None,
        "early_termination_reason": None,
        "submitted_at": None,
        "status": "SCHEDULED",
    })
    store.db["deployments"][deployment["id"]] = deployment
    logic.ledger_reserve(notice, planned)
    return ok(deployment, status=201)


@bp.get("/deployments")
def list_deployments():
    require_roles(*ALL_ROLES)
    return list_response("deployments", {
        "selection_notice_id": "selection_notice_id",
        "coverage_plan_id": "coverage_plan_id",
        "vessel_id": "vessel_id",
        "observer_id": "observer_id",
        "assigned_debriefer_id": "assigned_debriefer_id",
        "status": "status",
    })


@bp.get("/deployments/<did>")
def get_deployment(did):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("deployments", did, "Deployment"))


@bp.post("/deployments/<did>/reschedule")
def reschedule_deployment(did):
    require_roles("ProgramCoordinator")
    d = get_or_404("deployments", did, "Deployment")
    b = body()
    dep_s = req_dt(b, "scheduled_departure_date")
    ret_s = req_dt(b, "scheduled_return_date")
    if d["status"] not in ("SCHEDULED", "SAFETY_HOLD"):
        raise err_state("Only SCHEDULED or SAFETY_HOLD deployments can be rescheduled")
    dep_dt = parse_dt(dep_s)
    ret_dt = parse_dt(ret_s)
    if ret_dt <= dep_dt:
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "scheduled_return_date must fall after scheduled_departure_date")
    new_planned = logic.days_between(ret_dt, dep_dt) + 1
    if new_planned > logic.MAX_DEPLOYMENT_SEA_DAYS:
        raise ApiError("ERR_DEPLOYMENT_TOO_LONG", 422,
                       "planned_sea_days exceeds 45")
    logic.check_observer_overlap(d["observer_id"], dep_dt, ret_dt, exclude_id=d["id"])
    logic.check_vessel_turnaround(d["vessel_id"], dep_dt, exclude_id=d["id"])
    observer = store.db["observers"].get(d["observer_id"])
    if observer is not None:
        logic.check_observer_caps(observer, new_planned, exclude_id=d["id"])
    notice = store.db["selection_notices"].get(d["selection_notice_id"])
    delta = new_planned - d["planned_sea_days"]
    if notice is not None and notice["remaining_sea_days"] - delta < 0:
        raise ApiError("ERR_SEA_DAY_ALLOCATION_EXCEEDED", 422,
                       "The rescheduled length exceeds the notice's remaining_sea_days")

    d["scheduled_departure_date"] = dep_s
    d["scheduled_return_date"] = ret_s
    d["planned_sea_days"] = new_planned
    if d["status"] == "SAFETY_HOLD":
        d["status"] = "SCHEDULED"
        d["latest_safety_result"] = None
    if notice is not None:
        logic.ledger_reconcile_reschedule(notice, delta)
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/cancel")
def cancel_deployment(did):
    require_roles("ProgramCoordinator")
    d = get_or_404("deployments", did, "Deployment")
    if d["status"] not in logic.CANCELLABLE_DEPLOYMENT_STATUSES:
        raise err_state("Only pre-boarding deployments can be cancelled")
    notice = store.db["selection_notices"].get(d["selection_notice_id"])
    if notice is not None:
        logic.ledger_release(notice, d["planned_sea_days"])
    d["status"] = "CANCELLED"
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/board")
def board_deployment(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    _owning_observer(a, d)
    if d["status"] in ("SCHEDULED", "SAFETY_HOLD"):
        raise ApiError("ERR_SAFETY_CHECK_REQUIRED", 409,
                       "Boarding requires a current passing safety inspection")
    if d["status"] != "READY_TO_DEPLOY":
        raise err_state("Only a READY_TO_DEPLOY deployment can be boarded")
    d["status"] = "AT_SEA"
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/return")
def return_deployment(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    _owning_observer(a, d)
    b = body()
    actual_s = req_dt(b, "actual_return_date")
    if d["status"] != "AT_SEA":
        raise err_state("Only an AT_SEA deployment can record a return")
    actual_dt = parse_dt(actual_s)
    dep_dt = parse_dt(d["scheduled_departure_date"])
    ret_dt = parse_dt(d["scheduled_return_date"])
    if actual_dt < dep_dt or actual_dt > ret_dt:
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "actual_return_date must fall within the scheduled window")
    actual = logic.days_between(actual_dt, dep_dt) + 1
    d["actual_return_date"] = actual_s
    d["actual_sea_days"] = actual
    d["status"] = "RETURNED"
    notice = store.db["selection_notices"].get(d["selection_notice_id"])
    if notice is not None:
        logic.ledger_consume(notice, d["planned_sea_days"], actual)
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/submit-data")
def submit_data(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    _owning_observer(a, d)
    if d["status"] in ("RETURNED", "EARLY_TERMINATED"):
        has_samples = any(
            s["deployment_id"] == d["id"] for s in store.db["haul_samples"].values()
        )
        if not has_samples:
            raise err_invalid("submit-data requires at least one haul sample")
    elif d["status"] == "DATA_REJECTED":
        pass
    else:
        raise err_state("Trip data cannot be submitted from status " + d["status"])
    d["submitted_at"] = store.fmt_clock(store.clock_now())
    d["status"] = "DEBRIEFING"
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/assign-debriefer")
def assign_debriefer(did):
    require_roles("ProgramCoordinator")
    d = get_or_404("deployments", did, "Deployment")
    b = body()
    debriefer_id = b.get("debriefer_id")
    if isinstance(debriefer_id, str):
        get_or_404("debriefers", debriefer_id, "Debriefer")
    debriefer_id = req_str(b, "debriefer_id")
    debriefer = store.db["debriefers"][debriefer_id]
    observer = store.db["observers"].get(d["observer_id"])
    if observer is not None and debriefer["person_ref"] == observer["person_ref"]:
        raise ApiError("ERR_DEBRIEFER_CONFLICT_OF_INTEREST", 403,
                       "The debriefer must not be the same natural person as the observer")
    if d["status"] in ("CLOSED", "CANCELLED"):
        raise err_state("Cannot assign a debriefer to a terminal deployment")
    d["assigned_debriefer_id"] = debriefer_id
    store.touch(d)
    return ok(d)


def _debriefer_gate(a, d):
    """Ownership (priority 2) then DEBRIEFING state then assignment (6)."""
    if d["assigned_debriefer_id"] is not None and d["assigned_debriefer_id"] != a["id"]:
        raise err_forbidden("The acting debriefer is not the assigned debriefer")
    if d["status"] != "DEBRIEFING":
        raise err_state("The deployment is not in DEBRIEFING")
    if d["assigned_debriefer_id"] is None:
        raise ApiError("ERR_DEBRIEFER_NOT_ASSIGNED", 409,
                       "No debriefer has been assigned to the deployment")


@bp.post("/deployments/<did>/validate-data")
def validate_data(did):
    a = require_roles("Debriefer")
    d = get_or_404("deployments", did, "Deployment")
    _debriefer_gate(a, d)
    samples = [s for s in store.db["haul_samples"].values() if s["deployment_id"] == d["id"]]
    if any(s["status"] in ("RECORDED", "FLAGGED") for s in samples):
        raise ApiError("ERR_SAMPLES_NOT_RESOLVED", 409,
                       "Every haul sample must be VERIFIED or DISCARDED")
    verified = [s for s in samples if s["status"] == "VERIFIED"]
    if len(verified) < 1:
        raise ApiError("ERR_SAMPLE_COVERAGE_INSUFFICIENT", 422,
                       "At least one haul sample must be VERIFIED")
    num = sum(dec(s["sampled_weight_kg"]) for s in verified)
    den = sum(dec(s["total_haul_weight_kg"]) for s in verified)
    coverage = round4(num / den) if den != 0 else dec(0)
    if coverage < logic.MIN_VERIFIED_COVERAGE:
        raise ApiError("ERR_SAMPLE_COVERAGE_INSUFFICIENT", 422,
                       "Verified coverage ratio is below 0.2000")
    d["status"] = "DATA_VALIDATED"
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/reject-data")
def reject_data(did):
    a = require_roles("Debriefer")
    d = get_or_404("deployments", did, "Deployment")
    _debriefer_gate(a, d)
    b = body()
    req_str(b, "rejection_reason")
    d["status"] = "DATA_REJECTED"
    store.touch(d)
    return ok(d)


@bp.post("/deployments/<did>/close")
def close_deployment(did):
    require_roles("ProgramCoordinator")
    d = get_or_404("deployments", did, "Deployment")
    if d["status"] != "DATA_VALIDATED":
        raise err_state("Only a DATA_VALIDATED deployment can be closed")
    actual = d["actual_sea_days"]
    observer = store.db["observers"].get(d["observer_id"])
    if observer is not None:
        observer["sea_days_used_ytd"] += actual
        store.touch(observer)
    vessel = store.db["vessels"].get(d["vessel_id"])
    if vessel is not None:
        vessel["sea_days_observed_ytd"] += actual
        vessel["last_observed_end_date"] = d["actual_return_date"]
        store.touch(vessel)
    plan = store.db["coverage_plans"].get(d["coverage_plan_id"])
    if plan is not None:
        plan["actual_observer_sea_days"] += actual
        store.touch(plan)
    notice = store.db["selection_notices"].get(d["selection_notice_id"])
    if notice is not None:
        logic.maybe_fulfill_notice(notice, d["id"])
    d["status"] = "CLOSED"
    store.touch(d)
    return ok(d)


# ---------------------------------------------------------------------------
# SafetyInspection
# ---------------------------------------------------------------------------


@bp.post("/deployments/<did>/safety-inspections")
def create_safety_inspection(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    _owning_observer(a, d)
    b = body()
    # Body FK existence (priority 3): supersedes_inspection_id.
    supersedes = b.get("supersedes_inspection_id")
    if isinstance(supersedes, str):
        get_or_404("safety_inspections", supersedes, "SafetyInspection")
    # Schema (priority 4): present-but-wrong-type is a schema error.
    for f in CHECKLIST_FIELDS:
        if f in b and b[f] is not None and not isinstance(b[f], bool):
            raise err_invalid("Field '%s' must be a boolean" % f)
    if "deficiency_notes" in b and b["deficiency_notes"] is not None \
            and not isinstance(b["deficiency_notes"], str):
        raise err_invalid("Field 'deficiency_notes' must be a string")
    if supersedes is not None and not isinstance(supersedes, str):
        raise err_invalid("Field 'supersedes_inspection_id' must be a string")
    # State (priority 6).
    if d["status"] not in ("SCHEDULED", "SAFETY_HOLD"):
        raise err_state("Safety inspections are only recorded pre-boarding")
    # Safety protocol (priority 7): completeness, notes-on-fail, supersession.
    values = {f: b.get(f) for f in CHECKLIST_FIELDS}
    if any(values[f] is None for f in CHECKLIST_FIELDS):
        raise ApiError("ERR_SAFETY_CHECKLIST_INCOMPLETE", 422,
                       "All five checklist booleans are required")
    result = "PASS" if all(values[f] for f in CHECKLIST_FIELDS) else "FAIL"
    notes = b.get("deficiency_notes")
    if result == "FAIL" and not notes:
        raise ApiError("ERR_SAFETY_CHECKLIST_INCOMPLETE", 422,
                       "deficiency_notes are required on a FAIL result")
    if d["status"] == "SAFETY_HOLD":
        fails = [
            i for i in store.db["safety_inspections"].values()
            if i["deployment_id"] == d["id"] and i["result"] == "FAIL"
        ]
        fails.sort(key=lambda i: (i["created_at"], i["_seq"]))
        latest_fail = fails[-1] if fails else None
        if supersedes is None or latest_fail is None or supersedes != latest_fail["id"]:
            raise ApiError("ERR_SAFETY_SUPERSESSION_REQUIRED", 422,
                           "Re-inspection must supersede the latest FAIL inspection")

    inspection = store.new_inspection({
        "deployment_id": d["id"],
        "vessel_id": d["vessel_id"],
        "observer_id": a["id"],
        "life_raft_certified": values["life_raft_certified"],
        "epirb_registered": values["epirb_registered"],
        "immersion_suits_adequate": values["immersion_suits_adequate"],
        "fire_suppression_ok": values["fire_suppression_ok"],
        "comms_equipment_ok": values["comms_equipment_ok"],
        "deficiency_notes": notes,
        "supersedes_inspection_id": supersedes,
        "result": result,
    })
    store.db["safety_inspections"][inspection["id"]] = inspection
    d["latest_safety_result"] = result
    d["status"] = "READY_TO_DEPLOY" if result == "PASS" else "SAFETY_HOLD"
    store.touch(d)
    return ok(inspection, status=201)


@bp.get("/safety-inspections")
def list_safety_inspections():
    require_roles(*ALL_ROLES)
    return list_response("safety_inspections", {
        "deployment_id": "deployment_id",
        "observer_id": "observer_id",
        "vessel_id": "vessel_id",
        "supersedes_inspection_id": "supersedes_inspection_id",
        "result": "result",
    })


@bp.get("/safety-inspections/<iid>")
def get_safety_inspection(iid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("safety_inspections", iid, "SafetyInspection"))


# ---------------------------------------------------------------------------
# HaulSample
# ---------------------------------------------------------------------------


@bp.post("/deployments/<did>/haul-samples")
def create_haul_sample(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    _owning_observer(a, d)
    b = body()
    haul_date = req_dt(b, "haul_date")
    haul_number = req_int(b, "haul_number")
    species_code = req_str(b, "species_code")
    sampled = req_decimal2(b, "sampled_weight_kg")
    total = req_decimal2(b, "total_haul_weight_kg")
    if haul_number < 1:
        raise err_invalid("haul_number must be >= 1")
    if sampled <= 0:
        raise err_invalid("sampled_weight_kg must be > 0")
    if total <= 0:
        raise err_invalid("total_haul_weight_kg must be > 0")
    if d["status"] != "AT_SEA":
        raise err_state("Haul samples can only be recorded while AT_SEA")
    haul_dt = parse_dt(haul_date)
    dep_dt = parse_dt(d["scheduled_departure_date"])
    ret_dt = parse_dt(d["scheduled_return_date"])
    if haul_dt < dep_dt or haul_dt > ret_dt:
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "haul_date must fall within the deployment window")
    ratio = round4(sampled / total)
    if ratio < logic.MIN_SAMPLE_RATIO or ratio > logic.MAX_SAMPLE_RATIO:
        raise ApiError("ERR_SAMPLE_RATIO_OUT_OF_RANGE", 422,
                       "sampling_ratio must lie within [0.2000, 1.0000]")
    if any(
        s["deployment_id"] == d["id"] and s["haul_number"] == haul_number
        for s in store.db["haul_samples"].values()
    ):
        raise ApiError("ERR_DUPLICATE_HAUL_NUMBER", 409,
                       "haul_number is already used within this deployment")
    sample = store.new_entity({
        "deployment_id": d["id"],
        "haul_date": haul_date,
        "haul_number": haul_number,
        "species_code": species_code,
        "sampled_weight_kg": sampled,
        "total_haul_weight_kg": total,
        "sampling_ratio": ratio,
        "flagged_reason": None,
        "verified_by_debriefer_id": None,
        "status": "RECORDED",
    })
    store.db["haul_samples"][sample["id"]] = sample
    return ok(sample, status=201)


@bp.get("/haul-samples")
def list_haul_samples():
    require_roles(*ALL_ROLES)
    return list_response("haul_samples", {
        "deployment_id": "deployment_id",
        "verified_by_debriefer_id": "verified_by_debriefer_id",
        "status": "status",
    })


@bp.get("/haul-samples/<sid>")
def get_haul_sample(sid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("haul_samples", sid, "HaulSample"))


def _sample_action(sid, action):
    a = require_roles("Debriefer")
    s = get_or_404("haul_samples", sid, "HaulSample")
    d = store.db["deployments"].get(s["deployment_id"])
    if d is None:
        raise err_state("The sample's deployment no longer exists")
    if d["assigned_debriefer_id"] != a["id"]:
        raise err_forbidden("The acting debriefer is not the assigned debriefer")
    b = body()
    reason = None
    if action in ("flag", "discard"):
        reason = req_str(b, "reason")
    if d["status"] != "DEBRIEFING":
        raise err_state("Samples can only be resolved during DEBRIEFING")
    allowed = {
        "verify": ("RECORDED", "FLAGGED"),
        "flag": ("RECORDED",),
        "discard": ("FLAGGED",),
    }[action]
    if s["status"] not in allowed:
        raise err_state("A %s sample cannot be %s" % (s["status"], action))
    if action == "verify":
        s["status"] = "VERIFIED"
    elif action == "flag":
        s["status"] = "FLAGGED"
        s["flagged_reason"] = reason
    else:
        s["status"] = "DISCARDED"
        s["flagged_reason"] = reason
    s["verified_by_debriefer_id"] = a["id"]
    store.touch(s)
    return ok(s)


@bp.post("/haul-samples/<sid>/verify")
def verify_sample(sid):
    return _sample_action(sid, "verify")


@bp.post("/haul-samples/<sid>/flag")
def flag_sample(sid):
    return _sample_action(sid, "flag")


@bp.post("/haul-samples/<sid>/discard")
def discard_sample(sid):
    return _sample_action(sid, "discard")
