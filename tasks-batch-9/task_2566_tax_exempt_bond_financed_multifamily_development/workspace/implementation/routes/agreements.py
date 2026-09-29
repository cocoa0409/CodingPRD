"""Land-use restriction agreement drafting, recording and amendment (PRD 3.4)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, now_clock_iso, touch

bp = Blueprint("agreements", __name__)

MIN_COMPLIANCE_PERIOD_YEARS = 15
EXTENDED_USE_MARGIN_YEARS = 15


def _check_terms(compliance_period_years, extended_use_years):
    """Ladder rule 31 -- ERR_EXTENDED_USE_TOO_SHORT."""
    if compliance_period_years < MIN_COMPLIANCE_PERIOD_YEARS:
        fail("ERR_EXTENDED_USE_TOO_SHORT",
             "compliance_period_years must be at least %d." % MIN_COMPLIANCE_PERIOD_YEARS)
    if extended_use_years < compliance_period_years + EXTENDED_USE_MARGIN_YEARS:
        fail("ERR_EXTENDED_USE_TOO_SHORT",
             "extended_use_years must be at least compliance_period_years plus %d."
             % EXTENDED_USE_MARGIN_YEARS)


@bp.post("/regulatory-agreements")
def create_agreement():
    caller = guard("POST /regulatory-agreements")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    set_aside_election = v.req_enum(body, "set_aside_election", calc.SET_ASIDE_ELECTIONS)
    compliance_period_years = v.req_int(body, "compliance_period_years")
    extended_use_years = v.req_int(body, "extended_use_years")
    recording_county = v.req_str(body, "recording_county", allow_empty=False)

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)

    if set_aside_election != project.get("set_aside_election"):
        fail("ERR_SET_ASIDE_MISMATCH",
             "The agreement's election must equal the development's election.")
    _check_terms(compliance_period_years, extended_use_years)

    row = new_row(db.agreements, {
        "project_id": project_id,
        "set_aside_election": set_aside_election,
        "compliance_period_years": compliance_period_years,
        "extended_use_years": extended_use_years,
        "recording_county": recording_county,
        "status": "DRAFT",
        "instrument_number": None,
        "recording_date": None,
        "amendment_count": 0,
        "amendment_reason": None,
        "compliance_period_end_date": None,
        "extended_use_end_date": None,
    })
    return object_response(serialize.agreement(row), 201)


@bp.post("/regulatory-agreements/<row_id>/record")
def record_agreement(row_id):
    guard("POST /regulatory-agreements/{id}/record")
    body = v.body()
    instrument_number = v.req_str(body, "instrument_number", allow_empty=False)

    agreement = domain.get_or_404(db.agreements, row_id, "ERR_REG_AGREEMENT_NOT_FOUND")
    previous = agreement.get("status")
    if previous not in ("DRAFT", "AMENDMENT_PENDING"):
        fail("ERR_REG_AGREEMENT_STATE_INVALID",
             "An agreement in %s cannot be recorded." % previous)

    project = domain.project_of_row(agreement)
    if project is not None:
        ratio = calc.set_aside_compliance_ratio(
            project, agreement.get("set_aside_election"))
        if not ratio["set_aside_satisfied"]:
            fail("ERR_SET_ASIDE_NOT_SATISFIED",
                 "The development does not satisfy its set-aside election.")
        designated = calc.applicable_fraction(project)["designated_unit_count"]
        if designated != (project.get("total_units") or 0):
            fail("ERR_UNIT_COUNT_MISMATCH",
                 "Every unit of the development must carry a designation before recording.")

    agreement["status"] = "RECORDED"
    agreement["instrument_number"] = instrument_number
    agreement["recording_date"] = now_clock_iso()

    if previous == "AMENDMENT_PENDING":
        agreement["amendment_count"] = (agreement.get("amendment_count") or 0) + 1
        agreement["amendment_reason"] = None
        if project is not None and project.get("compliance_start_date"):
            domain.restamp_extended_use(project, agreement)
            touch(project)
    touch(agreement)

    if previous == "DRAFT" and project is not None:
        if project.get("compliance_status") == "UNRESTRICTED":
            project["compliance_status"] = "RESTRICTED"
            touch(project)

    return object_response(serialize.agreement(agreement))


@bp.post("/regulatory-agreements/<row_id>/amend")
def amend_agreement(row_id):
    guard("POST /regulatory-agreements/{id}/amend")
    body = v.body()
    amendment_reason = v.req_str(body, "amendment_reason", allow_empty=False)
    compliance_period_years = v.opt_int(body, "compliance_period_years")
    extended_use_years = v.opt_int(body, "extended_use_years")
    set_aside_election = v.opt_enum(body, "set_aside_election", calc.SET_ASIDE_ELECTIONS)

    agreement = domain.get_or_404(db.agreements, row_id, "ERR_REG_AGREEMENT_NOT_FOUND")
    if agreement.get("status") != "RECORDED":
        fail("ERR_REG_AGREEMENT_STATE_INVALID",
             "Only a RECORDED agreement may be amended.")

    project = domain.project_of_row(agreement)
    if set_aside_election is not None and project is not None:
        if set_aside_election != project.get("set_aside_election"):
            fail("ERR_SET_ASIDE_MISMATCH",
                 "The agreement's election must equal the development's election.")

    effective_compliance = (compliance_period_years
                            if compliance_period_years is not None
                            else agreement.get("compliance_period_years"))
    effective_extended = (extended_use_years
                          if extended_use_years is not None
                          else agreement.get("extended_use_years"))
    _check_terms(effective_compliance, effective_extended)

    agreement["status"] = "AMENDMENT_PENDING"
    agreement["amendment_reason"] = amendment_reason
    agreement["compliance_period_years"] = effective_compliance
    agreement["extended_use_years"] = effective_extended
    if set_aside_election is not None:
        agreement["set_aside_election"] = set_aside_election
    touch(agreement)
    return object_response(serialize.agreement(agreement))
