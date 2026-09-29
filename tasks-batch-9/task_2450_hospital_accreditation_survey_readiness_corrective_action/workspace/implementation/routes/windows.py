"""Survey window prediction, command center and survey findings
(PRD 3.6, 3.7)."""

from flask import Blueprint, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_standard,
    get_unit,
    get_window,
    opt_bool,
    opt_str,
    page,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("windows", __name__)

ACTIONS = (
    "ACTIVATE_COMMAND_CENTER",
    "DEMOBILIZE_COMMAND_CENTER",
    "OPEN_SURVEY",
    "CLOSE_SURVEY",
)


@bp.post("/accreditation/survey-windows")
def create_window():
    require_roles("AccreditationDirector")
    b = body()
    cycle_label = req_str(b, "cycle_label")
    prior_survey_end_date = req_dt(b, "prior_survey_end_date")

    # Rung 11
    for existing in db.windows.values():
        if existing["cycle_label"] == cycle_label:
            raise ApiError("ERR_DUPLICATE_RESOURCE", message="cycle_label already registered.")

    predicted_open = calc.add_months(prior_survey_end_date, calc.MIN_INTERVAL_MONTHS)
    predicted_close = calc.add_months(prior_survey_end_date, calc.MAX_INTERVAL_MONTHS)
    cc_from = calc.add_days(predicted_open, -calc.COMMAND_CENTER_LEAD_DAYS)

    # Rung 29 — closed interval, touching endpoints intersect, capacity one.
    for existing in rows(db.windows):
        if existing["window_state"] == "CLOSED":
            continue
        if (
            predicted_open <= existing["predicted_close_date"]
            and predicted_close >= existing["predicted_open_date"]
        ):
            raise ApiError("ERR_SURVEY_WINDOW_OVERLAP")

    window = base_entity("SurveyWindow")
    window.update(
        {
            "cycle_label": cycle_label,
            "prior_survey_end_date": prior_survey_end_date,
            "predicted_open_date": predicted_open,
            "predicted_close_date": predicted_close,
            "command_center_activation_allowed_from": cc_from,
            "window_state": "PROJECTED",
            "command_center_state": "STANDBY",
            "survey_opened_at": None,
            "survey_closed_at": None,
            "condition_level_finding_count": 0,
            "follow_up_required": False,
            "follow_up_due_at": None,
        }
    )
    db.windows[window["id"]] = window
    return object_response(serialize.survey_window(window), 201)


@bp.get("/accreditation/survey-windows/<window_id>")
def read_window(window_id):
    require_roles(*ALL_ROLES)
    window = get_window(window_id)
    return object_response(serialize.survey_window(window))


@bp.post("/accreditation/survey-windows/<window_id>/transition")
def transition_window(window_id):
    require_roles("AccreditationDirector")
    b = body()
    action = req_enum(b, "action", ACTIONS)
    opt_str(b, "note")

    window = get_window(window_id)
    window_state = window["window_state"]
    cc_state = window["command_center_state"]

    # Rung 13 — declared transitions. OPEN_SURVEY's window-state eligibility is
    # owned by rung 17, so it is not evaluated here.
    if action == "ACTIVATE_COMMAND_CENTER" and cc_state not in ("STANDBY", "DEMOBILIZED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "DEMOBILIZE_COMMAND_CENTER" and (
        cc_state != "ACTIVATED" or window_state == "ACTIVE_SURVEY"
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "CLOSE_SURVEY" and window_state != "ACTIVE_SURVEY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 17
    if action == "OPEN_SURVEY" and window_state not in ("ELIGIBLE", "CLOSED"):
        raise ApiError("ERR_SURVEY_WINDOW_NOT_ELIGIBLE")

    # Rung 18
    if action == "OPEN_SURVEY" and cc_state != "ACTIVATED":
        raise ApiError("ERR_COMMAND_CENTER_NOT_ACTIVATED")

    # Rung 24
    if action == "OPEN_SURVEY" and cascade.immediate_threat_active():
        raise ApiError("ERR_IMMEDIATE_THREAT_ACTIVE")

    # Rung 31
    if action == "ACTIVATE_COMMAND_CENTER":
        if db.clock < window["command_center_activation_allowed_from"]:
            raise ApiError("ERR_COMMAND_CENTER_WINDOW_NOT_OPEN")

    # Rung 32 — the follow-up entry point only.
    if action == "OPEN_SURVEY" and window_state == "CLOSED":
        if not window["follow_up_required"]:
            raise ApiError("ERR_FOLLOW_UP_NOT_REQUIRED")
        if window["follow_up_due_at"] is None or db.clock > window["follow_up_due_at"]:
            raise ApiError("ERR_FOLLOW_UP_WINDOW_EXPIRED")

    if action == "ACTIVATE_COMMAND_CENTER":
        window["command_center_state"] = "ACTIVATED"
        touch(window)
    elif action == "DEMOBILIZE_COMMAND_CENTER":
        window["command_center_state"] = "DEMOBILIZED"
        touch(window)
    elif action == "OPEN_SURVEY":
        window["window_state"] = "ACTIVE_SURVEY"
        window["survey_opened_at"] = db.clock
        touch(window)
        cascade.lock_units_for_survey()
    else:
        _close_survey(window)

    return object_response(serialize.survey_window(window))


def _close_survey(window):
    closed_at = db.clock
    window["window_state"] = "CLOSED"
    window["survey_closed_at"] = closed_at
    touch(window)

    for finding in rows(db.findings):
        if finding["survey_window_id"] != window["id"]:
            continue
        if finding["state"] != "DRAFT":
            continue
        due = calc.esc_due_initial(closed_at, finding["response_deadline_days"])
        finding["state"] = "RESPONSE_PENDING"
        finding["initial_response_due_at"] = due
        finding["response_due_at"] = due
        touch(finding)

    if window["condition_level_finding_count"] >= 1:
        window["follow_up_required"] = True
        window["follow_up_due_at"] = calc.add_days(closed_at, calc.FOLLOW_UP_LEAD_DAYS)
    else:
        window["follow_up_required"] = False
        window["follow_up_due_at"] = None
        if window["command_center_state"] == "ACTIVATED":
            window["command_center_state"] = "DEMOBILIZED"
    touch(window)

    cascade.release_units_after_survey()

    for finding in rows(db.findings):
        if finding["survey_window_id"] != window["id"]:
            continue
        if finding["state"] != "FOLLOW_UP_PENDING":
            continue
        finding["state"] = "ACCEPTED"
        finding["accepted_at"] = closed_at
        touch(finding)


@bp.post("/accreditation/survey-windows/<window_id>/findings")
def record_finding(window_id):
    require_roles("ExternalSurveyor")
    b = body()
    standard_id = req_str(b, "standard_id")
    unit_id = req_str(b, "unit_id")
    observed = req_int(b, "observed_noncompliance_count")
    sampled = req_int(b, "sampled_count")
    harm = opt_bool(b, "patient_harm_observed", default=False)

    # Rung 5
    window = get_window(window_id)
    # Rung 6 — unit before standard.
    unit = get_unit(unit_id)
    standard = get_standard(standard_id)

    # Rung 10
    if sampled < 1 or observed < 1 or observed > sampled:
        raise ApiError("ERR_SAMPLE_COUNT_INVALID")

    # Rung 19
    if window["window_state"] != "ACTIVE_SURVEY":
        raise ApiError("ERR_SURVEY_NOT_ACTIVE")

    classification = calc.finding_risk_classification(
        observed, sampled, standard["risk_tier"], harm
    )

    finding = base_entity("SurveyFinding")
    finding.update(
        {
            "survey_window_id": window["id"],
            "standard_id": standard["id"],
            "unit_id": unit["id"],
            "observed_noncompliance_count": observed,
            "sampled_count": sampled,
            "patient_harm_observed": harm,
            "noncompliance_rate": classification["noncompliance_rate"],
            "classification": classification["classification"],
            "risk_level": classification["risk_level"],
            "condition_level": classification["condition_level"],
            "response_deadline_days": classification["response_deadline_days"],
            "initial_response_due_at": None,
            "response_due_at": None,
            "state": "DRAFT",
            "clarification_round_count": 0,
            "submission_count": 0,
            "accepted_at": None,
        }
    )
    db.findings[finding["id"]] = finding

    if finding["condition_level"]:
        window["condition_level_finding_count"] += 1
        touch(window)

    return object_response(serialize.finding(finding), 201)


@bp.get("/accreditation/survey-findings")
def list_findings():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    result = rows(db.findings)
    window_id = request.args.get("survey_window_id")
    standard_id = request.args.get("standard_id")
    unit_id = request.args.get("unit_id")
    state = request.args.get("state")
    if window_id:
        result = [f for f in result if f["survey_window_id"] == window_id]
    if standard_id:
        result = [f for f in result if f["standard_id"] == standard_id]
    if unit_id:
        result = [f for f in result if f["unit_id"] == unit_id]
    if state:
        result = [f for f in result if f["state"] == state]
    items, total = page(result, limit, offset)
    return array_response([serialize.finding(f) for f in items], limit, offset, total)
