"""Enrollment lifecycle transitions and safety-hold lifting (PRD §3.4, §3.5).

POST /enrollments/{id}/transition drives enrollment_status through CONSENT,
RANDOMIZE, ACTIVATE, COMPLETE, WITHDRAW. POST /enrollments/{id}/lift-hold moves
safety_status HOLD -> CLEAR. Cross-entity gates (trial posture, capacity, OCC)
and cascades (arm/trial counters, visit cancellation, posture recompute) live
here.
"""
from flask import Blueprint

import db
import domain
from errors import err
from middleware import require
from response import object_response
from serialize import serialize
from validate import get_json, require_fields, check_action, check_int

bp = Blueprint("lifecycle", __name__)

TRANSITION_ACTIONS = {"CONSENT", "RANDOMIZE", "ACTIVATE", "COMPLETE", "WITHDRAW"}


@bp.route("/enrollments/<enrollment_id>/transition", methods=["POST"])
@require("CoordinatorStaff")
def transition(enrollment_id, caller_id=None, caller_role=None):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        err("ERR_NOT_FOUND", "Enrollment not found")
    t = db.trials[e["trial_id"]]

    body = get_json()
    require_fields(body, "action")
    # Action discriminator (priority 6).
    action = check_action(body, "action", TRANSITION_ACTIONS)

    # Per-action required fields (priority 7).
    if action == "CONSENT" and not body.get("consent_document_id"):
        err("ERR_MISSING_ACTION_FIELD", "CONSENT requires consent_document_id")
    if action == "RANDOMIZE" and body.get("expected_trial_version") is None:
        err("ERR_MISSING_ACTION_FIELD", "RANDOMIZE requires expected_trial_version")

    if action == "CONSENT":
        return _consent(e, t, body)
    if action == "RANDOMIZE":
        return _randomize(e, t, body)
    if action == "ACTIVATE":
        return _activate(e, t)
    if action == "COMPLETE":
        return _complete(e, t)
    return _withdraw(e, t)


def _consent(e, t, body):
    # State (priority 8): must be SCREENED.
    if e["enrollment_status"] != "SCREENED":
        err("ERR_INVALID_STATE", "Enrollment is not in SCREENED state")
    # Trial must be OPEN (priority 11).
    if t["posture"] != "OPEN":
        err("ERR_TRIAL_NOT_OPEN", "Trial is not OPEN")

    consent_document_id = body["consent_document_id"]
    doc = db.consent_documents.get(consent_document_id)
    active = domain.active_consent(t["id"])
    # Consent integrity (priority 13): ACTIVE, belongs to trial, version matches
    # the trial's current ACTIVE consent version_number.
    if (doc is None
            or doc["trial_id"] != t["id"]
            or doc["status"] != "ACTIVE"
            or active is None
            or doc["version_number"] != active["version_number"]):
        err("ERR_CONSENT_VERSION_MISMATCH", "Consent document is not the current ACTIVE version")

    e["signed_consent_document_id"] = doc["id"]
    e["signed_consent_version"] = doc["version_number"]
    e["enrollment_status"] = "CONSENTED"
    domain.touch(e)
    return object_response(serialize("Enrollment", e), 200)


def _randomize(e, t, body):
    expected = check_int(body, "expected_trial_version")

    # State (priority 8): must be CONSENTED.
    if e["enrollment_status"] != "CONSENTED":
        err("ERR_INVALID_STATE", "Enrollment is not in CONSENTED state")
    # Trial must be OPEN (priority 11).
    if t["posture"] != "OPEN":
        err("ERR_TRIAL_NOT_OPEN", "Trial is not OPEN")
    # Hold gate (priority 12).
    if e["safety_status"] == "HOLD":
        err("ERR_ENROLLMENT_ON_HOLD", "Enrollment is on a safety hold")
    # Capacity (priority 21).
    if t["enrolled_count"] >= t["target_enrollment"]:
        err("ERR_TRIAL_AT_CAPACITY", "Trial has reached target enrollment")
    # OCC (priority 22).
    if expected != t["version"]:
        err("ERR_STALE_TRIAL_VERSION", "expected_trial_version does not match the trial version")

    arm = domain.select_arm(t)
    if arm is None:
        err("ERR_TRIAL_NOT_CONFIGURED", "Trial has no randomization arms")

    e["arm_id"] = arm["id"]
    e["enrollment_status"] = "RANDOMIZED"
    domain.touch(e)

    # Cascades: arm.assigned_count and Trial.enrolled_count (recomputed from
    # the now-updated enrollment set), each a mutation.
    domain.recompute_arm_assigned_count(arm)
    domain.touch(arm)
    domain.recompute_enrolled_count(t)
    domain.recompute_trial_posture(t)
    domain.touch(t)

    return object_response(serialize("Enrollment", e), 200)


def _activate(e, t):
    # State (priority 8): must be RANDOMIZED.
    if e["enrollment_status"] != "RANDOMIZED":
        err("ERR_INVALID_STATE", "Enrollment is not in RANDOMIZED state")
    # Hold gate (priority 12).
    if e["safety_status"] == "HOLD":
        err("ERR_ENROLLMENT_ON_HOLD", "Enrollment is on a safety hold")

    e["enrollment_status"] = "ACTIVE"
    domain.touch(e)
    return object_response(serialize("Enrollment", e), 200)


def _complete(e, t):
    # State (priority 8): must be ACTIVE.
    if e["enrollment_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Enrollment is not in ACTIVE state")
    # Hold gate (priority 12).
    if e["safety_status"] == "HOLD":
        err("ERR_ENROLLMENT_ON_HOLD", "Enrollment is on a safety hold")
    # All visits resolved (no SCHEDULED visit remains).
    if any(v["status"] == "SCHEDULED" for v in domain.enrollment_visits(e["id"])):
        err("ERR_INVALID_STATE", "Enrollment has unresolved (SCHEDULED) visits")

    e["enrollment_status"] = "COMPLETED"
    domain.touch(e)
    return object_response(serialize("Enrollment", e), 200)


def _withdraw(e, t):
    # State (priority 8): permitted from any non-terminal state.
    prior_status = e["enrollment_status"]
    if prior_status not in ("SCREENED", "CONSENTED", "RANDOMIZED", "ACTIVE"):
        err("ERR_INVALID_STATE", "Enrollment is in a terminal state")

    e["enrollment_status"] = "WITHDRAWN"

    # Compensating cascade only for RANDOMIZED/ACTIVE (had consumed a slot).
    arm = None
    if prior_status in ("RANDOMIZED", "ACTIVE") and e["arm_id"]:
        arm = db.arms.get(e["arm_id"])

    domain.touch(e)

    if arm is not None:
        domain.recompute_arm_assigned_count(arm)
        domain.touch(arm)

    # Cancel every SCHEDULED visit of this enrollment.
    for v in domain.enrollment_visits(e["id"]):
        if v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            domain.touch(v)

    # Recompute trial counters/posture; one trial mutation.
    domain.recompute_enrolled_count(t)
    domain.recompute_active_safety_holds(t)
    domain.recompute_trial_posture(t)
    domain.touch(t)

    return object_response(serialize("Enrollment", e), 200)


@bp.route("/enrollments/<enrollment_id>/lift-hold", methods=["POST"])
@require("SafetyOfficer")
def lift_hold(enrollment_id, caller_id=None, caller_role=None):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        err("ERR_NOT_FOUND", "Enrollment not found")
    t = db.trials[e["trial_id"]]

    # State (priority 8): must be on HOLD.
    if e["safety_status"] != "HOLD":
        err("ERR_INVALID_STATE", "Enrollment is not on a safety hold")
    # Every AE must be adjudicated (none REPORTED / UNDER_REVIEW).
    for ae in domain.enrollment_adverse_events(e["id"]):
        if ae["report_status"] in ("REPORTED", "UNDER_REVIEW"):
            err("ERR_INVALID_STATE", "An adverse event is still open")

    e["safety_status"] = "CLEAR"
    domain.touch(e)

    domain.recompute_active_safety_holds(t)
    domain.recompute_trial_posture(t)
    domain.touch(t)

    return object_response(serialize("Enrollment", e), 200)
