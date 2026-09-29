"""Casefinding sources, entries, reportability decisions and entry reopen."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import (add_days, all_of, clock_date, days_between, fmt_date, mark,
                parse_date)
from errors import ApiError, invalid
from middleware import ANY_ROLE, actor, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("casefinding", __name__)


# --------------------------------------------------------------- sources

@bp.post(PREFIX + "/casefinding-sources")
@endpoint(["RegistryManager"])
def create_source():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    source_type = validate.f_enum(body, "source_type", spec.SOURCE_TYPES)
    expected = validate.f_int(body, "expected_monthly_volume", minimum=0)

    need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    source = db.new_entity("source", {
        "program_id": program_id,
        "source_type": source_type,
        "expected_monthly_volume": expected,
        "entries_this_month": 0,
        "casefinding_completeness_pct": 100.0 if expected == 0 else 0.0,
        "last_reconciled_through": None,
    })
    return ok(source, 201)


@bp.get(PREFIX + "/casefinding-sources")
@endpoint(ANY_ROLE)
def list_sources():
    program_id = validate.q_str("program_id")
    source_type = validate.q_enum("source_type", spec.SOURCE_TYPES)
    items = all_of("source")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if source_type is not None:
        items = [s for s in items if s["source_type"] == source_type]
    return page(items)


@bp.get(PREFIX + "/casefinding-sources/<source_id>")
@endpoint(ANY_ROLE)
def read_source(source_id):
    source = need("source", source_id, "ERR_SOURCE_NOT_FOUND")
    return ok(source)


# --------------------------------------------------------------- entries

@bp.post(PREFIX + "/casefinding-sources/<source_id>/entries")
@endpoint(["RegistryManager", "RegistryAbstractor"])
def create_entry(source_id):
    body = validate.body()
    patient_mrn = validate.f_str(body, "patient_mrn")
    accession_date = validate.f_date(body, "accession_date")
    primary_site_code = validate.f_str(body, "primary_site_code")
    histology_code = validate.f_str(body, "histology_code")
    behavior_code = validate.f_enum(body, "behavior_code", spec.BEHAVIOR_CODES)
    diagnosis_date = validate.f_date(body, "diagnosis_date")
    first_contact_date = validate.f_date(body, "first_contact_date")
    diagnosed_at = validate.f_bool(body, "diagnosed_at_facility")
    treated_at = validate.f_bool(body, "first_treatment_at_facility")
    ambiguous = validate.f_bool(body, "ambiguous_terminology_flag",
                                required=False, default=False)
    validate.f_int(body, "referral_lag_days", required=False)

    if diagnosis_date > clock_date():
        raise invalid("diagnosis_date may not be later than the clock date.")
    if first_contact_date < diagnosis_date:
        raise invalid("first_contact_date may not precede diagnosis_date.")

    source = need("source", source_id, "ERR_SOURCE_NOT_FOUND")

    for existing in services.entries_of_source(source_id):
        if (existing["patient_mrn"] == patient_mrn
                and existing["primary_site_code"] == primary_site_code
                and existing["diagnosis_date"] == fmt_date(diagnosis_date)):
            raise ApiError("ERR_DUPLICATE_CASEFINDING_ENTRY")

    program = db.get("program", source["program_id"])
    lag = days_between(diagnosis_date, first_contact_date)
    class_code = calcs.class_of_case(diagnosed_at, treated_at, lag)
    analytic = calcs.analytic_flag(class_code)
    suggestion, reason = calcs.reportability_suggestion(
        diagnosis_date, program["reference_year"], behavior_code,
        primary_site_code, histology_code)

    entry = db.new_entity("entry", {
        "source_id": source_id,
        "program_id": source["program_id"],
        "patient_mrn": patient_mrn,
        "accession_date": fmt_date(accession_date),
        "primary_site_code": primary_site_code,
        "histology_code": histology_code,
        "behavior_code": behavior_code,
        "diagnosis_date": fmt_date(diagnosis_date),
        "first_contact_date": fmt_date(first_contact_date),
        "diagnosed_at_facility": diagnosed_at,
        "first_treatment_at_facility": treated_at,
        "ambiguous_terminology_flag": ambiguous,
        "referral_lag_days": lag,
        "class_of_case_code": class_code,
        "analytic_flag": analytic,
        "suggested_reportability": suggestion,
        "suggested_reason_code": reason,
        "reportability_state": "PENDING_REVIEW",
        "decision_reason_code": None,
        "override_reason_code": None,
        "decided_by_user_id": None,
        "created_case_id": None,
        "reopen_count": 0,
    })
    services.refresh_source_completeness(source)
    return ok(entry, 201)


@bp.get(PREFIX + "/casefinding-entries")
@endpoint(ANY_ROLE)
def list_entries():
    source_id = validate.q_str("source_id")
    program_id = validate.q_str("program_id")
    created_case_id = validate.q_str("created_case_id")
    reportability_state = validate.q_enum("reportability_state",
                                         spec.REPORTABILITY_STATES)
    class_of_case_code = validate.q_enum("class_of_case_code",
                                        spec.CLASS_OF_CASE_CODES)
    items = all_of("entry")
    if source_id is not None:
        items = [e for e in items if e["source_id"] == source_id]
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if created_case_id is not None:
        items = [e for e in items if e["created_case_id"] == created_case_id]
    if reportability_state is not None:
        items = [e for e in items
                 if e["reportability_state"] == reportability_state]
    if class_of_case_code is not None:
        items = [e for e in items
                 if e["class_of_case_code"] == class_of_case_code]
    return page(items)


@bp.get(PREFIX + "/casefinding-entries/<entry_id>")
@endpoint(ANY_ROLE)
def read_entry(entry_id):
    entry = need("entry", entry_id, "ERR_ENTRY_NOT_FOUND")
    return ok(entry)


def _mint_case(entry, program):
    diagnosis_date = parse_date(entry["diagnosis_date"])
    first_contact_date = parse_date(entry["first_contact_date"])
    program_cases = services.cases_of_program(program["id"])
    same_year = [c for c in program_cases
                 if parse_date(c["diagnosis_date"]).year == diagnosis_date.year]
    accession_number = "%04d-%05d" % (diagnosis_date.year, len(same_year) + 1)
    sequence_number = 1 + len([c for c in program_cases
                               if c["patient_mrn"] == entry["patient_mrn"]
                               and c["case_state"] != "VOIDED"])
    due = add_days(first_contact_date, program["timeliness_standard_days"])

    case = db.new_entity("case", {
        "entry_id": entry["id"],
        "program_id": program["id"],
        "assigned_abstractor_id": None,
        "patient_mrn": entry["patient_mrn"],
        "accession_number": accession_number,
        "sequence_number": sequence_number,
        "class_of_case_code": entry["class_of_case_code"],
        "analytic_flag": entry["analytic_flag"],
        "diagnosis_date": entry["diagnosis_date"],
        "first_contact_date": entry["first_contact_date"],
        "abstract_due_date": fmt_date(due),
        "completed_on": None,
        "case_state": "IDENTIFIED",
        "submission_state": "NOT_SUBMITTED",
        "timeliness_status": "ON_TIME",
        "days_to_due": 0,
        "vital_status": "UNKNOWN",
        "last_contact_date": None,
        "follow_up_due_date": None,
        "follow_up_status": "NOT_REQUIRED",
        "_pre_cascade_completed_on": None,
    })
    services.refresh_case_timeliness(case)
    services.refresh_case_follow_up(case)
    return case


@bp.post(PREFIX + "/casefinding-entries/<entry_id>/reportability-decision")
@endpoint(["RegistryManager", "RegistryAbstractor"])
def reportability_decision(entry_id):
    body = validate.body()
    decision = validate.f_enum(body, "decision", spec.REPORTABILITY_DECISIONS)
    decision_reason_code = validate.f_str(body, "decision_reason_code")
    override_reason_code = validate.f_str(body, "override_reason_code",
                                          required=False)

    entry = need("entry", entry_id, "ERR_ENTRY_NOT_FOUND")
    program = db.get("program", entry["program_id"])

    if entry["reportability_state"] != "PENDING_REVIEW":
        raise ApiError("ERR_ENTRY_NOT_PENDING_REVIEW")
    if decision == "REPORTABLE" and program["accreditation_state"] == "WITHDRAWN":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if decision == "REPORTABLE":
        diagnosis_date = parse_date(entry["diagnosis_date"])
        if diagnosis_date.year < program["reference_year"]:
            raise ApiError("ERR_DIAGNOSIS_BEFORE_REFERENCE_YEAR")
    if decision != entry["suggested_reportability"]:
        if not override_reason_code:
            raise ApiError("ERR_REPORTABILITY_OVERRIDE_REASON_REQUIRED")

    mark(entry)
    entry["decision_reason_code"] = decision_reason_code
    if override_reason_code is not None:
        entry["override_reason_code"] = override_reason_code
    entry["decided_by_user_id"] = actor()

    if decision == "NON_REPORTABLE":
        entry["reportability_state"] = "NON_REPORTABLE"
        return ok(entry)

    entry["reportability_state"] = "REPORTABLE"
    case = _mint_case(entry, program)
    entry["created_case_id"] = case["id"]
    services.refresh_program_aggregates(program)
    return ok(entry)


@bp.post(PREFIX + "/casefinding-entries/<entry_id>/reopen")
@endpoint(["RegistryManager"])
def reopen_entry(entry_id):
    body = validate.body()
    validate.f_str(body, "reopen_reason")

    entry = need("entry", entry_id, "ERR_ENTRY_NOT_FOUND")

    if entry["reportability_state"] not in ("REPORTABLE", "NON_REPORTABLE"):
        raise ApiError("ERR_ENTRY_NOT_REOPENABLE")
    if entry["reopen_count"] >= spec.ENTRY_REOPEN_MAX:
        raise ApiError("ERR_ENTRY_NOT_REOPENABLE")
    case = db.get("case", entry.get("created_case_id"))
    if case is not None and case["case_state"] not in ("IDENTIFIED", "ASSIGNED"):
        raise ApiError("ERR_ENTRY_NOT_REOPENABLE")

    was_reportable = entry["reportability_state"] == "REPORTABLE"
    mark(entry)
    entry["reportability_state"] = "PENDING_REVIEW"
    entry["reopen_count"] = entry["reopen_count"] + 1
    entry["decision_reason_code"] = None
    entry["override_reason_code"] = None

    if not was_reportable:
        return ok(entry)

    entry["decided_by_user_id"] = None
    entry["created_case_id"] = None
    if case is not None:
        mark(case)
        assigned_id = case.get("assigned_abstractor_id")
        case["case_state"] = "VOIDED"
        if assigned_id is not None:
            case["assigned_abstractor_id"] = None
            abstractor = db.get("abstractor", assigned_id)
            if abstractor is not None:
                mark(abstractor)
                abstractor["assigned_open_case_count"] = max(
                    0, abstractor["assigned_open_case_count"] - 1)
        services.refresh_case_timeliness(case)
    program = db.get("program", entry["program_id"])
    if program is not None:
        services.refresh_program_aggregates(program)
    return ok(entry)
