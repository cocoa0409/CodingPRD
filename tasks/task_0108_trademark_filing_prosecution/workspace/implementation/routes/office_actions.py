"""OfficeAction + OfficeActionResponse routes and the examination loop
(PRD §3.3).
"""

from flask import Blueprint

from db import db, parse_iso, iso_from_datetime
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models, calc
from services.body import (
    get_json_body,
    require_nonempty_string,
    require_enum,
    optional_bool,
)
from services.pagination import parse_pagination, slice_sorted
from services.ownership import check_application_owner
from services.dateutil import add_days, days_late

bp = Blueprint("office_actions", __name__)

GROUNDS = {
    "LIKELIHOOD_OF_CONFUSION",
    "MERELY_DESCRIPTIVE",
    "SPECIMEN_DEFECT",
    "IDENTIFICATION_INDEFINITE",
}


# ----- Issue office action (UNDER_EXAMINATION -> OFFICE_ACTION_ISSUED) -------

@bp.post("/office-actions")
@require_roles("Examiner")
def issue_office_action(_user_id, _role):
    body = get_json_body()
    application_id = require_nonempty_string(body, "application_id")
    ground = require_enum(body, "ground", GROUNDS)
    is_final = optional_bool(body, "is_final", False)

    app = models.get_or_404(db.applications, application_id, "TrademarkApplication")
    if app["status"] != "UNDER_EXAMINATION":
        raise_api("ERR_INVALID_STATE", "Application is not UNDER_EXAMINATION")

    now = db.current_utc_dt()
    issued_iso = db.current_utc_iso()
    response_deadline = add_days(now, calc.RESPONSE_PERIOD_DAYS)
    round_number = app["office_action_round"] + 1

    oa = models.make_record({
        "application_id": application_id,
        "round_number": round_number,
        "is_final": is_final,
        "ground": ground,
        "issued_at": issued_iso,
        "response_deadline": iso_from_datetime(response_deadline),
        "status": "OUTSTANDING",
    })
    db.office_actions[oa["id"]] = oa

    app["office_action_round"] = round_number
    app["status"] = "OFFICE_ACTION_ISSUED"
    models.create_docket_deadline(
        "OFFICE_ACTION", oa["id"], iso_from_datetime(response_deadline),
        application_id=application_id,
    )
    models.touch(app)
    return success(models.ser_office_action(oa), 201)


@bp.get("/office-actions/<rid>")
@require_roles("Attorney", "Applicant", "Examiner")
def get_office_action(rid, _user_id, _role):
    oa = models.get_or_404(db.office_actions, rid, "OfficeAction")
    return success(models.ser_office_action(oa), 200)


# ----- Expire (system sweep: OFFICE_ACTION_ISSUED -> ABANDONED) -------------

@bp.post("/office-actions/<rid>/expire")
@require_roles("Examiner")
def expire_office_action(rid, _user_id, _role):
    oa = models.get_or_404(db.office_actions, rid, "OfficeAction")
    if oa["status"] != "OUTSTANDING":
        raise_api("ERR_INVALID_STATE", "Office action is not OUTSTANDING")

    grace = calc.FINAL_GRACE_DAYS if oa["is_final"] else calc.NONFINAL_GRACE_DAYS
    cutoff = add_days(parse_iso(oa["response_deadline"]), grace)
    now = db.current_utc_dt()
    if now < cutoff:
        raise_api("ERR_INVALID_STATE", "Grace tail has not fully elapsed")

    app = db.applications[oa["application_id"]]
    oa["status"] = "EXPIRED"
    models.touch(oa)
    models.set_docket_status("OFFICE_ACTION", oa["id"], "MISSED", only_pending=True)
    app["status"] = "ABANDONED"
    models.touch(app)
    return success(models.ser_office_action(oa), 200)


# ----- List responses of an office action -----------------------------------

@bp.get("/office-actions/<rid>/responses")
@require_roles("Attorney", "Applicant", "Examiner")
def list_office_action_responses(rid, _user_id, _role):
    models.get_or_404(db.office_actions, rid, "OfficeAction")
    limit, offset = parse_pagination()
    items = [
        r for r in db.office_action_responses.values()
        if r["office_action_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_office_action_response(r) for r in page], limit, offset, total
    )


# ----- Submit response (OFFICE_ACTION_ISSUED -> UNDER_EXAMINATION) -----------

resp_bp = Blueprint("office_action_responses", __name__)


@resp_bp.post("/office-action-responses")
@require_roles("Attorney", "Applicant")
def submit_office_action_response(_user_id, _role):
    body = get_json_body()
    office_action_id = require_nonempty_string(body, "office_action_id")
    argument_text = require_nonempty_string(body, "argument_text")
    amends = optional_bool(body, "amends_identification", False)

    oa = models.get_or_404(db.office_actions, office_action_id, "OfficeAction")
    app = db.applications[oa["application_id"]]

    # Ownership (priority 4).
    check_application_owner(app, _role, _user_id)

    # Already-closed guard (PRD §3.8): "a duplicate trigger on a resource already
    # advanced past the step in question — such as responding to an office action
    # no longer OUTSTANDING ... yields ERR_ACTION_ALREADY_CLOSED." The office
    # action is the operative resource for this transition, so its non-OUTSTANDING
    # status is classified as the already-closed case, taking precedence over the
    # generic application-state check (which would otherwise see UNDER_EXAMINATION
    # after a first response and wrongly report ERR_INVALID_STATE).
    if oa["status"] != "OUTSTANDING":
        raise_api("ERR_ACTION_ALREADY_CLOSED", "Office action is no longer outstanding")

    # State (priority 5): application must be in OFFICE_ACTION_ISSUED.
    if app["status"] != "OFFICE_ACTION_ISSUED":
        raise_api("ERR_INVALID_STATE", "Application is not in OFFICE_ACTION_ISSUED")

    # Business-temporal (priority 14): timeliness depends on finality.
    now = db.current_utc_dt()
    deadline = parse_iso(oa["response_deadline"])
    if oa["is_final"]:
        if now > deadline:
            raise_api("ERR_RESPONSE_DEADLINE_PASSED", "Final action response is late")
    else:
        grace_end = add_days(deadline, calc.NONFINAL_GRACE_DAYS)
        if now > grace_end:
            raise_api(
                "ERR_RESPONSE_DEADLINE_PASSED",
                "Non-final action grace tail has elapsed",
            )

    submitted_iso = db.current_utc_iso()
    late = days_late(now, deadline)

    rec = models.make_record({
        "office_action_id": office_action_id,
        "argument_text": argument_text,
        "amends_identification": amends,
        "submitted_at": submitted_iso,
        "days_late": late,
    })
    db.office_action_responses[rec["id"]] = rec

    oa["status"] = "RESPONDED"
    models.touch(oa)
    models.set_docket_status("OFFICE_ACTION", oa["id"], "MET", only_pending=True)
    app["status"] = "UNDER_EXAMINATION"
    models.touch(app)
    return success(models.ser_office_action_response(rec), 201)
