"""FeedingTrialProtocol endpoints."""

from decimal import Decimal
from flask import Blueprint

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_int, optional_field, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import stamp_new, touch, serialize, serialize_list, round_half_up

bp = Blueprint("feeding_trials", __name__)

TRIAL_TERMINAL = {"PASSED", "FAILED", "ABORTED"}


@bp.route("/formulas/<id>/feeding-trial-protocols", methods=["POST"])
def create_protocol(id):
    require_roles("TrialCoordinator")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    if formula["adequacy_basis"] != "FEEDING_TRIAL":
        raise errors.profile_basis_mismatch(
            "FeedingTrialProtocol allowed only for FEEDING_TRIAL-basis formulas")
    body = get_json_body()
    protocol_code = require_string(body, "protocol_code")
    animal_count = require_int(body, "animal_count")
    duration_days = require_int(body, "duration_days")

    if formula["life_stage"] == "ADULT_MAINTENANCE":
        if animal_count < 8:
            raise errors.invalid_request("animal_count must be >= 8 for adult maintenance protocols")
        if duration_days < 26:
            raise errors.invalid_request("duration_days must be >= 26 for adult maintenance protocols")

    for p in store.feeding_trial_protocols.values():
        if p["protocol_code"] == protocol_code:
            raise errors.duplicate_key("protocol_code already exists")

    protocol = {
        "formula_id": id,
        "protocol_code": protocol_code,
        "animal_count": animal_count,
        "duration_days": duration_days,
        "status": "PLANNED",
        "enrolled_count": 0,
        "completed_count": 0,
        "completion_ratio": 0,
    }
    stamp_new(protocol)
    store.feeding_trial_protocols[protocol["id"]] = protocol
    return success_object(serialize(protocol), 201)


def _get_protocol(id):
    p = store.feeding_trial_protocols.get(id)
    if p is None:
        raise errors.not_found("FeedingTrialProtocol not found")
    return p


def _check_not_terminal(p):
    if p["status"] in TRIAL_TERMINAL:
        raise errors.already_terminal("Protocol is in a terminal state")


@bp.route("/feeding-trial-protocols/<id>", methods=["GET"])
def get_protocol(id):
    require_roles("PlatformAdmin", "TrialCoordinator", "QAApprover", "QualityAnalyst")
    protocol = _get_protocol(id)
    return success_object(serialize(protocol), 200)


@bp.route("/formulas/<id>/feeding-trial-protocols", methods=["GET"])
def list_protocols(id):
    require_roles("PlatformAdmin", "TrialCoordinator", "QAApprover", "QualityAnalyst")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    items = [p for p in store.feeding_trial_protocols.values() if p["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/feeding-trial-protocols/<id>/open-enrollment", methods=["POST"])
def open_enrollment(id):
    require_roles("TrialCoordinator")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "PLANNED":
        raise errors.invalid_state("Only PLANNED protocols can open enrollment")
    formula = store.formulas.get(protocol["formula_id"])
    if formula is None or formula["adequacy_basis"] != "FEEDING_TRIAL":
        raise errors.profile_basis_mismatch("Formula must be FEEDING_TRIAL basis")
    if formula["status"] not in ("DRAFT", "NUTRIENT_REVIEW"):
        raise errors.invalid_state("Formula must be in DRAFT or NUTRIENT_REVIEW")
    protocol["status"] = "ENROLLING"
    touch(protocol, status_changed=True)
    return success_object(serialize(protocol), 200)


@bp.route("/feeding-trial-protocols/<id>/enroll", methods=["POST"])
def enroll(id):
    require_roles("TrialCoordinator")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "ENROLLING":
        raise errors.invalid_state("Enrollment events only accepted while ENROLLING")
    body = get_json_body()
    enrolled_delta = require_int(body, "enrolled_delta")
    protocol["enrolled_count"] = int(protocol["enrolled_count"]) + enrolled_delta
    touch(protocol)
    return success_object(serialize(protocol), 200)


@bp.route("/feeding-trial-protocols/<id>/start-trial", methods=["POST"])
def start_trial(id):
    require_roles("TrialCoordinator")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "ENROLLING":
        raise errors.invalid_state("Only ENROLLING protocols can start")
    if int(protocol["enrolled_count"]) < int(protocol["animal_count"]):
        raise errors.trial_not_fully_enrolled()
    protocol["status"] = "RUNNING"
    touch(protocol, status_changed=True)
    return success_object(serialize(protocol), 200)


@bp.route("/feeding-trial-protocols/<id>/complete-observation", methods=["POST"])
def complete_observation(id):
    require_roles("TrialCoordinator")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "RUNNING":
        raise errors.invalid_state("Only RUNNING protocols can complete observation")
    body = get_json_body()
    completed_count = require_int(body, "completed_count")
    protocol["completed_count"] = completed_count
    animal_count = int(protocol["animal_count"])
    if animal_count > 0:
        ratio = round_half_up(Decimal(completed_count) / Decimal(animal_count), 4)
    else:
        ratio = Decimal("0.0000")
    protocol["completion_ratio"] = ratio
    protocol["status"] = "ANALYSIS"
    touch(protocol, status_changed=True)
    return success_object(serialize(protocol), 200)


@bp.route("/feeding-trial-protocols/<id>/record-verdict", methods=["POST"])
def record_verdict(id):
    require_roles("QAApprover")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "ANALYSIS":
        raise errors.invalid_state("Only ANALYSIS protocols can receive a verdict")
    body = get_json_body()
    requested = optional_field(body, "requested_verdict")
    ratio = protocol.get("completion_ratio") or Decimal("0")
    ratio = Decimal(str(ratio))
    if requested == "PASSED" and ratio < Decimal("0.75"):
        raise errors.trial_completion_low()
    if ratio >= Decimal("0.75"):
        protocol["status"] = "PASSED"
    else:
        protocol["status"] = "FAILED"
    touch(protocol, status_changed=True)
    return success_object(serialize(protocol), 200)


@bp.route("/feeding-trial-protocols/<id>/abort", methods=["POST"])
def abort_protocol(id):
    require_roles("QAApprover")
    protocol = _get_protocol(id)
    _check_not_terminal(protocol)
    if protocol["status"] != "RUNNING":
        raise errors.invalid_state("Only RUNNING protocols can be aborted")
    protocol["status"] = "ABORTED"
    touch(protocol, status_changed=True)
    return success_object(serialize(protocol), 200)
