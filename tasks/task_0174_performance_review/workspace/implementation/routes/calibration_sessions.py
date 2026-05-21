"""CalibrationSession endpoints (PRD §3.5)."""

from flask import Blueprint

import config
from db import store
from errors import raise_err
from middleware import require_role
from response import ok
from services.audit import log_event
from services.calculations import bell_curve_compliance, bell_curve_distribution
from services.cascades import commit_calibration_session
from services.serializers import calibration_session_view

from . import _helpers as H

bp = Blueprint("calibration_sessions", __name__)


def _facilitator_conflicts(cycle_id: str, department: str, facilitator_id: str) -> bool:
    """Returns True if facilitator_id == manager_employee_id of any ReviewCase
    whose subject is in the given department, within the given cycle."""
    for rc in store.review_cases.values():
        if rc["cycle_id"] != cycle_id:
            continue
        subject = store.employees.get(rc["subject_employee_id"])
        if not subject:
            continue
        if subject.get("department") != department:
            continue
        if rc.get("manager_employee_id") == facilitator_id:
            return True
    return False


@bp.route("/cycles/<cycle_id>/calibration-sessions", methods=["POST"])
@require_role("HRBP")
def create_session(cycle_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        body = H.get_body()
        department = H.require_str(
            H.require_field(body, "department"), "department", 1, 200,
        )
        facilitator_id = H.require_str(
            H.require_field(body, "facilitator_employee_id"),
            "facilitator_employee_id",
        )
        facilitator = store.employees.get(facilitator_id)
        if not facilitator:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      f"facilitator_employee_id '{facilitator_id}' not found.")

        # Uniqueness per (cycle_id, department)
        for s in store.calibration_sessions.values():
            if s["cycle_id"] == cycle_id and s["department"] == department:
                raise_err("ERR_INVALID_STATE",
                          "A CalibrationSession already exists for this (cycle, department).")

        if _facilitator_conflicts(cycle_id, department, facilitator_id):
            raise_err("ERR_FACILITATOR_CONFLICT",
                      "Facilitator is the manager of a case in this department.")

        cs = H.new_entity({
            "cycle_id": cycle_id,
            "department": department,
            "facilitator_employee_id": facilitator_id,
            "status": "SCHEDULED",
            "proposed_ratings": [],
            "bell_curve_distribution": {b: 0 for b in config.RATING_BUCKETS},
            "committed_at": None,
        })
        store.calibration_sessions[cs["id"]] = cs
        log_event("CalibrationSession", cs["id"], "calibration_session.create", payload=body)
        return ok(calibration_session_view(cs), status=201)


@bp.route(
    "/cycles/<cycle_id>/calibration-sessions/<calibration_session_id>/proposals",
    methods=["PATCH"],
)
@require_role("HRBP")
def patch_proposals(cycle_id, calibration_session_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cs = H.get_calibration_session_or_404(cycle_id, calibration_session_id)
        body = H.get_body()
        proposals = body.get("proposed_ratings")
        if not isinstance(proposals, list):
            raise_err("ERR_VALIDATION", "proposed_ratings must be a list.")

        cleaned = []
        for i, entry in enumerate(proposals):
            if not isinstance(entry, dict):
                raise_err("ERR_VALIDATION", f"proposed_ratings[{i}] must be an object.")
            rc_id = entry.get("review_case_id")
            rating = entry.get("proposed_rating")
            if not isinstance(rc_id, str):
                raise_err("ERR_VALIDATION", f"proposed_ratings[{i}].review_case_id required.")
            if rating not in config.RATING_SET:
                raise_err("ERR_VALIDATION",
                          f"proposed_ratings[{i}].proposed_rating invalid.")
            cleaned.append({"review_case_id": rc_id, "proposed_rating": rating})

        cs["proposed_ratings"] = cleaned
        cs["bell_curve_distribution"] = bell_curve_distribution(cleaned)
        H.bump(cs)
        log_event("CalibrationSession", cs["id"], "calibration_session.proposals_patch", payload=body)
        return ok(calibration_session_view(cs))


@bp.route(
    "/cycles/<cycle_id>/calibration-sessions/<calibration_session_id>/start",
    methods=["POST"],
)
@require_role("HRBP")
def start_session(cycle_id, calibration_session_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cs = H.get_calibration_session_or_404(cycle_id, calibration_session_id)
        if cs["status"] != "SCHEDULED":
            raise_err("ERR_INVALID_STATE",
                      f"CalibrationSession is in {cs['status']}, not SCHEDULED.")
        if cycle["status"] != "IN_CALIBRATION":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not IN_CALIBRATION.")
        if _facilitator_conflicts(cycle_id, cs["department"], cs["facilitator_employee_id"]):
            raise_err("ERR_FACILITATOR_CONFLICT",
                      "Facilitator is the manager of a case in this department.")
        cs["status"] = "IN_SESSION"
        H.bump(cs)
        log_event("CalibrationSession", cs["id"], "calibration_session.start", payload={})
        return ok(calibration_session_view(cs))


@bp.route(
    "/cycles/<cycle_id>/calibration-sessions/<calibration_session_id>/commit",
    methods=["POST"],
)
@require_role("HRBP")
def commit_session(cycle_id, calibration_session_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cs = H.get_calibration_session_or_404(cycle_id, calibration_session_id)

        if cs["status"] != "IN_SESSION":
            raise_err("ERR_INVALID_STATE",
                      f"CalibrationSession is in {cs['status']}, not IN_SESSION.")
        if cycle["status"] != "IN_CALIBRATION":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not IN_CALIBRATION.")
        # Facilitator conflict check applies on commit too
        if _facilitator_conflicts(cycle_id, cs["department"], cs["facilitator_employee_id"]):
            raise_err("ERR_FACILITATOR_CONFLICT",
                      "Facilitator is the manager of a case in this department.")

        proposals = cs.get("proposed_ratings") or []
        # Coverage: every locked ReviewCase whose subject.department == session.department
        # appears exactly once in proposed_ratings.
        proposed_ids = [p["review_case_id"] for p in proposals]
        if len(set(proposed_ids)) != len(proposed_ids):
            raise_err("ERR_CALIBRATION_COVERAGE",
                      "A ReviewCase appears more than once in proposed_ratings.")

        target_cases = []
        for rc in store.review_cases.values():
            if rc["cycle_id"] != cycle_id or rc["status"] != "LOCKED":
                continue
            subject = store.employees.get(rc["subject_employee_id"])
            if not subject or subject.get("department") != cs["department"]:
                continue
            target_cases.append(rc["id"])

        if set(proposed_ids) != set(target_cases):
            raise_err("ERR_CALIBRATION_COVERAGE",
                      "Proposed ratings must cover exactly every locked case in this department.")

        # Bell-curve compliance
        check = bell_curve_compliance(proposals, cycle["bell_curve_target"])
        if not check["compliant"]:
            raise_err(
                "ERR_BELL_CURVE_VIOLATED",
                f"Bell curve deviates beyond 5pp on bucket(s): {check['offending']}.",
            )

        commit_calibration_session(cycle, cs)
        log_event("CalibrationSession", cs["id"], "calibration_session.commit", payload={})
        return ok(calibration_session_view(cs))


@bp.route(
    "/cycles/<cycle_id>/calibration-sessions/<calibration_session_id>/abandon",
    methods=["POST"],
)
@require_role("HRBP")
def abandon_session(cycle_id, calibration_session_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cs = H.get_calibration_session_or_404(cycle_id, calibration_session_id)
        if cs["status"] == "SCHEDULED":
            if cycle["status"] not in ("OPEN", "IN_CALIBRATION"):
                raise_err("ERR_INVALID_STATE",
                          f"Cycle is in {cycle['status']}; cannot abandon scheduled session.")
        elif cs["status"] == "IN_SESSION":
            # unconditional
            pass
        else:
            raise_err("ERR_INVALID_STATE",
                      f"CalibrationSession is in {cs['status']}; cannot abandon.")
        cs["status"] = "ABANDONED"
        H.bump(cs)
        log_event("CalibrationSession", cs["id"], "calibration_session.abandon", payload={})
        return ok(calibration_session_view(cs))
