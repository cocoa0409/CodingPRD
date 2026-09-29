"""Cancer program registration, compliance summary and accreditation cycle."""

from decimal import Decimal

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import add_days, all_of, clock_date, fmt_date, mark, parse_date
from errors import ApiError, invalid
from middleware import ANY_ROLE, actor, endpoint
from response import object_response
from routes.common import PREFIX, need, ok, ok_data, page

bp = Blueprint("programs", __name__)


@bp.post(PREFIX + "/programs")
@endpoint(["PlatformAdmin"])
def create_program():
    body = validate.body()
    name = validate.f_str(body, "name")
    coc_program_id = validate.f_str(body, "coc_program_id")
    caseload = validate.f_int(body, "annual_analytic_caseload", minimum=0)
    reference_year = validate.f_int(body, "reference_year")
    standard_days = validate.f_int(
        body, "timeliness_standard_days", required=False,
        minimum=spec.MIN_TIMELINESS_STANDARD_DAYS,
        default=spec.DEFAULT_TIMELINESS_STANDARD_DAYS)

    for existing in all_of("program"):
        if existing["coc_program_id"] == coc_program_id:
            raise ApiError("ERR_DUPLICATE_COC_PROGRAM_ID")

    per_month = 2 if caseload >= spec.HIGH_VOLUME_CASELOAD else 1
    program = db.new_entity("program", {
        "name": name,
        "coc_program_id": coc_program_id,
        "annual_analytic_caseload": caseload,
        "reference_year": reference_year,
        "timeliness_standard_days": standard_days,
        "accreditation_state": "ACCREDITED",
        "survey_date": None,
        "survey_year": None,
        "next_survey_due_year": reference_year + spec.SURVEY_CYCLE_YEARS,
        "registry_posture": "OPEN",
        "identified_case_count": 0,
        "open_backlog_count": 0,
        "overdue_backlog_count": 0,
        "open_critical_deficiency_count": 0,
        "follow_up_rate_coc_pct": 100.0,
        "follow_up_rate_state_pct": 100.0,
        "lost_to_follow_up_pct": 0.0,
        "credited_sessions_12mo": 0,
        "required_sessions_12mo": per_month * 12,
        "conference_frequency_compliant": False,
        "coordinator_attendance_compliant": False,
        "_surveyor_of_record": None,
    })
    return ok(program, 201)


@bp.get(PREFIX + "/programs")
@endpoint(ANY_ROLE)
def list_programs():
    accreditation_state = validate.q_enum("accreditation_state",
                                          spec.ACCREDITATION_STATES)
    registry_posture = validate.q_enum("registry_posture",
                                       spec.REGISTRY_POSTURES)
    items = all_of("program")
    if accreditation_state is not None:
        items = [p for p in items
                 if p["accreditation_state"] == accreditation_state]
    if registry_posture is not None:
        items = [p for p in items if p["registry_posture"] == registry_posture]
    return page(items)


@bp.get(PREFIX + "/programs/<program_id>")
@endpoint(ANY_ROLE)
def read_program(program_id):
    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")
    return ok(program)


@bp.get(PREFIX + "/programs/<program_id>/compliance-summary")
@endpoint(["PlatformAdmin", "RegistryManager", "AccreditationCoordinator",
           "StateRegistryLiaison", "CoCSurveyor"])
def compliance_summary(program_id):
    variant = validate.q_enum("follow_up_variant", spec.FOLLOW_UP_VARIANTS)
    if variant is None:
        variant = "coc_five_year"
    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")
    services.refresh_program_follow_up(program)
    services.refresh_program_conference(program)
    services.refresh_program_aggregates(program)
    db.commit()
    payload = db.public(program)
    if variant == "state_central_all_years":
        payload["lost_to_follow_up_pct"] = float(calcs.rhu(
            Decimal(100) - Decimal(str(program["follow_up_rate_state_pct"])), 1))
    return object_response(payload, 200)


@bp.post(PREFIX + "/programs/<program_id>/survey-schedule")
@endpoint(["AccreditationCoordinator"])
def survey_schedule(program_id):
    body = validate.body()
    survey_date = validate.f_date(body, "survey_date")
    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    if program["accreditation_state"] not in ("ACCREDITED", "PROBATION"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if survey_date < add_days(clock_date(), spec.SURVEY_LEAD_DAYS):
        raise ApiError("ERR_SURVEY_DATE_TOO_SOON")

    mark(program)
    program["survey_date"] = fmt_date(survey_date)
    program["survey_year"] = survey_date.year
    program["accreditation_state"] = "SURVEY_SCHEDULED"
    services.refresh_program_aggregates(program)
    return ok(program)


@bp.post(PREFIX + "/programs/<program_id>/survey-complete")
@endpoint(["CoCSurveyor"])
def survey_complete(program_id):
    body = validate.body()
    validate.f_date(body, "completed_on")
    validate.f_str(body, "surveyor_note", required=False)
    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    if program["accreditation_state"] != "SURVEY_SCHEDULED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    mark(program)
    year = clock_date().year
    program["survey_year"] = year
    program["next_survey_due_year"] = year + spec.SURVEY_CYCLE_YEARS
    program["_surveyor_of_record"] = actor()
    open_major = services.open_deficiency_count(program["id"],
                                                ("MAJOR", "CRITICAL"))
    if open_major == 0:
        program["accreditation_state"] = "ACCREDITED"
    else:
        program["accreditation_state"] = "DEFICIENCY_RESPONSE"
    services.refresh_program_aggregates(program)
    return ok(program)


@bp.post(PREFIX + "/programs/<program_id>/accreditation-decision")
@endpoint(["CoCSurveyor"])
def accreditation_decision(program_id):
    body = validate.body()
    decision = validate.f_enum(body, "decision", spec.ACCREDITATION_DECISIONS)
    validate.f_str(body, "decision_note", required=False)
    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    if program["accreditation_state"] not in ("DEFICIENCY_RESPONSE", "PROBATION"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if program.get("_surveyor_of_record") is not None and \
            program["_surveyor_of_record"] == actor():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    if decision == "ACCREDIT":
        if services.open_deficiency_count(program["id"],
                                          ("MAJOR", "CRITICAL")) > 0:
            raise ApiError("ERR_OPEN_DEFICIENCIES_BLOCK_ACCREDITATION")
        coc_rate, _state_rate, _lost = services.compute_follow_up_rates(
            program["id"])
        if Decimal(str(coc_rate)) < Decimal(str(spec.FOLLOW_UP_ACCREDITATION_MIN_PCT)):
            raise ApiError("ERR_FOLLOW_UP_RATE_BELOW_THRESHOLD")

    mark(program)
    if decision == "ACCREDIT":
        program["accreditation_state"] = "ACCREDITED"
        if program.get("survey_year") is not None:
            program["next_survey_due_year"] = (program["survey_year"]
                                               + spec.SURVEY_CYCLE_YEARS)
        services.refresh_program_follow_up(program)
    elif decision == "PROBATION":
        program["accreditation_state"] = "PROBATION"
    else:
        program["accreditation_state"] = "WITHDRAWN"
    services.refresh_program_aggregates(program)
    return ok(program)
