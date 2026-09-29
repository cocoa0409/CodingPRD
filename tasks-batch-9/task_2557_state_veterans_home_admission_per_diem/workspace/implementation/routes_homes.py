"""Veterans homes, federal recognition, care units and survey results."""
import re

from flask import Blueprint

import calc
import services
from calc import CARE_LEVELS, applicant_out, home_out, unit_out, waitlist_out
from common import (
    f_date,
    f_enum,
    f_int,
    f_str,
    fail,
    guard,
    json_body,
    object_response,
    pagination,
    paginate,
    q_str,
)
from store import clock_date, new_record, parse_date, store, touch_once

bp = Blueprint("homes", __name__)

READ_ALL = (
    "StateProgramAdmin",
    "AdmissionsCoordinator",
    "ClinicalAssessor",
    "BusinessOfficeManager",
    "FederalPerDiemAuditor",
    "SurveyAgency",
)
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
RECOGNITION_STATUSES = ("RECOGNIZED", "PROVISIONAL", "SUSPENDED")
CERTIFICATION_STATUSES = ("CERTIFIED", "CONDITIONAL", "DECERTIFIED")
SCOPES = ("ISOLATED", "PATTERN", "WIDESPREAD")
SEVERITIES = ("MINIMAL", "MINIMAL_HARM", "ACTUAL_HARM", "IMMEDIATE_JEOPARDY")


def find_home(home_id):
    home = store.homes.get(home_id)
    if home is None:
        fail("ERR_HOME_NOT_FOUND", "No veterans home with id %s." % home_id)
    return home


def find_unit(unit_id):
    unit = store.care_units.get(unit_id)
    if unit is None:
        fail("ERR_CARE_UNIT_NOT_FOUND", "No care unit with id %s." % unit_id)
    return unit


# ------------------------------------------------------------------ reads ----
@bp.get("/veterans-homes/<home_id>")
def get_home(home_id):
    guard(*READ_ALL)
    return object_response(home_out(find_home(home_id)))


@bp.get("/veterans-homes")
def list_homes():
    guard(
        "StateProgramAdmin",
        "AdmissionsCoordinator",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "SurveyAgency",
    )
    limit, offset = pagination()
    state_code = q_str("state_code")
    recognition_status = q_str("recognition_status")
    rows = list(store.homes.values())
    if state_code is not None:
        rows = [h for h in rows if h["state_code"] == state_code]
    if recognition_status is not None:
        rows = [h for h in rows if h["recognition_status"] == recognition_status]
    rows = sorted(rows, key=lambda h: (h["name"], h["_seq"]))
    rows = sorted(rows, key=lambda h: h["created_at"], reverse=True)
    return paginate(rows, limit, offset, home_out)


@bp.get("/veterans-homes/<home_id>/care-units")
def list_home_units(home_id):
    guard(*READ_ALL)
    limit, offset = pagination()
    home = find_home(home_id)
    care_level = q_str("care_level")
    certification_status = q_str("certification_status")
    rows = calc.home_units(home["id"])
    if care_level is not None:
        rows = [u for u in rows if u["care_level"] == care_level]
    if certification_status is not None:
        rows = [u for u in rows if u["certification_status"] == certification_status]
    rows = sorted(rows, key=lambda u: (u["care_level"], u["unit_name"], u["created_at"], u["_seq"]))
    return paginate(rows, limit, offset, unit_out)


@bp.get("/veterans-homes/<home_id>/applicants")
def list_home_applicants(home_id):
    guard(
        "StateProgramAdmin",
        "AdmissionsCoordinator",
        "ClinicalAssessor",
        "BusinessOfficeManager",
    )
    limit, offset = pagination()
    home = find_home(home_id)
    status = q_str("status")
    requested_care_level = q_str("requested_care_level")
    rows = [a for a in store.applicants.values() if a["veterans_home_id"] == home["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if requested_care_level is not None:
        rows = [a for a in rows if a["requested_care_level"] == requested_care_level]
    rows = sorted(
        rows,
        key=lambda a: (a["application_received_date"], a["created_at"], a["_seq"]),
    )
    return paginate(rows, limit, offset, applicant_out)


@bp.get("/care-units/<unit_id>")
def get_unit(unit_id):
    guard(*READ_ALL)
    return object_response(unit_out(find_unit(unit_id)))


@bp.get("/care-units/<unit_id>/waitlist-entries")
def list_unit_waitlist(unit_id):
    guard("StateProgramAdmin", "AdmissionsCoordinator", "ClinicalAssessor")
    limit, offset = pagination()
    unit = find_unit(unit_id)
    status = q_str("status")
    rows = services.unit_entries(unit["id"])
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    rows = sorted(rows, key=lambda w: (w["queue_position"], w["created_at"], w["_seq"]))
    return paginate(rows, limit, offset, waitlist_out)


# ----------------------------------------------------------------- writes ----
@bp.post("/veterans-homes")
def create_home():
    guard("StateProgramAdmin")
    body = json_body()
    name = f_str(body, "name", 1, 200)
    state_code = f_str(body, "state_code", 2, 2)
    if not STATE_CODE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "Field 'state_code' must be exactly two uppercase letters.")
    recognition_effective_date = f_date(body, "recognition_effective_date")
    recognition_status = f_enum(
        body, "recognition_status", RECOGNITION_STATUSES, required=False, default="RECOGNIZED"
    )
    pna = f_int(
        body,
        "personal_needs_allowance_monthly_cents",
        minimum=0,
        required=False,
        default=9000,
    )
    home = new_record()
    home.update(
        {
            "name": name,
            "state_code": state_code,
            "recognition_status": recognition_status,
            "recognition_effective_date": recognition_effective_date,
            "personal_needs_allowance_monthly_cents": pna,
            "last_survey_date": None,
        }
    )
    store.homes[home["id"]] = home
    return object_response(home_out(home), 201)


@bp.post("/veterans-homes/<home_id>/recognition")
def change_recognition(home_id):
    guard("StateProgramAdmin")
    body = json_body()
    action = f_enum(body, "action", ("GRANT", "SUSPEND", "RESTORE"))
    effective_date = f_date(body, "effective_date")
    f_str(body, "note", required=False)
    home = find_home(home_id)

    current = home["recognition_status"]
    decertified = calc.decertified_unit_count(home)
    if action == "GRANT":
        if current != "PROVISIONAL" or decertified != 0:
            fail("ERR_HOME_RECOGNITION_STATE_INVALID", "GRANT requires a PROVISIONAL home with no decertified units.")
        target = "RECOGNIZED"
    elif action == "SUSPEND":
        if current != "RECOGNIZED":
            fail("ERR_HOME_RECOGNITION_STATE_INVALID", "SUSPEND requires a RECOGNIZED home.")
        target = "SUSPENDED"
    else:
        if current != "SUSPENDED" or decertified != 0:
            fail("ERR_HOME_RECOGNITION_STATE_INVALID", "RESTORE requires a SUSPENDED home with no decertified units.")
        target = "RECOGNIZED"

    if parse_date(effective_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "effective_date may not lie in the future.")

    home["recognition_status"] = target
    home["recognition_effective_date"] = effective_date
    touch_once(home)
    if target == "SUSPENDED":
        services.void_draft_claims(home)
    return object_response(home_out(home))


@bp.post("/veterans-homes/<home_id>/care-units")
def create_unit(home_id):
    guard("StateProgramAdmin")
    body = json_body()
    unit_name = f_str(body, "unit_name", 1, 120)
    care_level = f_enum(body, "care_level", CARE_LEVELS)
    licensed_bed_count = f_int(body, "licensed_bed_count", minimum=1)
    out_of_service = f_int(body, "out_of_service_bed_count", minimum=0, required=False, default=0)
    if out_of_service > licensed_bed_count:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'out_of_service_bed_count' may not exceed licensed_bed_count.",
        )
    home = find_home(home_id)
    unit = new_record()
    unit.update(
        {
            "veterans_home_id": home["id"],
            "unit_name": unit_name,
            "care_level": care_level,
            "licensed_bed_count": licensed_bed_count,
            "out_of_service_bed_count": out_of_service,
            "certification_status": "CERTIFIED",
            "last_survey_compliance_score": 0,
            "last_survey_date": None,
        }
    )
    store.care_units[unit["id"]] = unit
    touch_once(home)
    return object_response(unit_out(unit), 201)


@bp.post("/care-units/<unit_id>/survey-result")
def record_survey(unit_id):
    guard("SurveyAgency")
    body = json_body()
    survey_date = f_date(body, "survey_date")
    if "deficiencies" not in body or body["deficiencies"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'deficiencies' is required.")
    raw = body["deficiencies"]
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field 'deficiencies' must be an array.")
    deficiencies = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each deficiency must be an object.")
        scope = f_enum(item, "scope", SCOPES)
        severity = f_enum(item, "severity", SEVERITIES)
        deficiencies.append({"scope": scope, "severity": severity})

    unit = find_unit(unit_id)
    if parse_date(survey_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "survey_date may not lie in the future.")

    previous = unit["certification_status"]
    score, outcome = calc.survey_outcome(deficiencies, previous)
    unit["last_survey_compliance_score"] = score
    unit["last_survey_date"] = survey_date
    unit["certification_status"] = outcome
    touch_once(unit)

    home = calc.home_of_unit(unit)
    if home is not None:
        home["last_survey_date"] = survey_date
        touch_once(home)

    if outcome == "DECERTIFIED" and previous != "DECERTIFIED":
        services.decertification_cascade(unit)
    elif previous == "DECERTIFIED" and outcome != "DECERTIFIED":
        services.reinstatement_cascade(unit)
    services.recompute_queue(unit["id"])
    return object_response(unit_out(unit))
