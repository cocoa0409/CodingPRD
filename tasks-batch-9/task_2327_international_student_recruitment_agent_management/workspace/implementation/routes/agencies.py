"""Agency onboarding, vetting, posture, training and scorecards (PRD 3.1, 3.8, 3.9)."""

from datetime import timedelta

from flask import Blueprint

import errors
import serializers
from db import db, base_record, touch, today
from errors import fail
from middleware import check_scope
from response import obj
from routes.common import auth, listing, need
from services import calc, domain
from validation import (body, fmt_date, opt_bool, opt_enum, opt_int, opt_str, parse_date,
                        query_enum, req_country, req_date, req_enum, req_int, req_str)

bp = Blueprint("agencies", __name__)

VETTING_TRANSITIONS = {
    "SUBMIT_FOR_SCREENING": ("DRAFT", "SCREENING"),
    "REQUEST_INFO": ("SCREENING", "INFO_REQUESTED"),
    "RESUBMIT": ("INFO_REQUESTED", "SCREENING"),
    "CLEAR": ("SCREENING", "CLEARED"),
    "REJECT": ("SCREENING", "REJECTED"),
    "RE_SCREEN": ("CLEARED", "SCREENING"),
}
VETTING_ACTIONS = tuple(VETTING_TRANSITIONS.keys())

POSTURE_ACTIONS = ("PLACE_ON_WATCH", "PLACE_ON_PROBATION", "SUSPEND", "REINSTATE",
                   "CLEAR_WATCH")
POSTURE_SOURCES = {
    "PLACE_ON_WATCH": (("GOOD_STANDING",), "WATCH"),
    "PLACE_ON_PROBATION": (("GOOD_STANDING", "WATCH"), "PROBATION"),
    "SUSPEND": (("GOOD_STANDING", "WATCH", "PROBATION"), "SUSPENDED"),
    "REINSTATE": (("PROBATION", "SUSPENDED"), "WATCH"),
    "CLEAR_WATCH": (("WATCH",), "GOOD_STANDING"),
}


def _agency(agency_id):
    return need(db.agencies, agency_id, errors.ERR_AGENCY_NOT_FOUND)


# --- registration and reads -------------------------------------------------

@bp.route("/recruitment/agencies", methods=["POST"])
def create_agency():
    auth("RecruitmentOfficer")
    data = body()
    legal_name = req_str(data, "legal_name", min_len=1, max_len=200)
    home_country_code = req_country(data, "home_country_code")
    ownership_disclosed = opt_bool(data, "ownership_disclosed", default=False)
    beneficial_owner_count = opt_int(data, "beneficial_owner_count", minimum=0, default=0)
    sanctions_screen_passed = opt_bool(data, "sanctions_screen_passed", default=False)
    reference_check_count = opt_int(data, "reference_check_count", minimum=0, default=0)

    record = base_record()
    record.update({
        "legal_name": legal_name,
        "home_country_code": home_country_code,
        "ownership_disclosed": ownership_disclosed,
        "beneficial_owner_count": beneficial_owner_count,
        "sanctions_screen_passed": sanctions_screen_passed,
        "reference_check_count": reference_check_count,
        "vetting_state": "DRAFT",
        "compliance_posture": "GOOD_STANDING",
        "rolling_risk_score": 0.0,
        "lifetime_risk_score": 0.0,
        "confirmed_incident_count": 0,
        "reviewed_document_count": 0,
        "confirmed_fraud_document_count": 0,
        "net_earned_commission_cents": 0,
        "clawback_liability_cents": 0,
        "current_tier": "UNRATED",
        "last_posture_reason": None,
    })
    db.agencies[record["id"]] = record
    return obj(serializers.agency(record), 201)


@bp.route("/recruitment/agencies/<agency_id>", methods=["GET"])
def read_agency(agency_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "Registrar", "AgencyOwner")
    check_scope(role, user_id, agency_id)
    return obj(serializers.agency(_agency(agency_id)))


@bp.route("/recruitment/agencies", methods=["GET"])
def list_agencies():
    auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer")
    vetting_state = query_enum("vetting_state", calc.VETTING_STATES)
    posture = query_enum("compliance_posture", calc.POSTURES)
    tier = query_enum("current_tier", calc.TIERS)
    records = list(db.agencies.values())
    if vetting_state is not None:
        records = [r for r in records if r["vetting_state"] == vetting_state]
    if posture is not None:
        records = [r for r in records if r["compliance_posture"] == posture]
    if tier is not None:
        records = [r for r in records if r["current_tier"] == tier]
    return listing(records, serializers.agency)


@bp.route("/recruitment/agencies/<agency_id>", methods=["PATCH"])
def update_agency(agency_id):
    user_id, role = auth("RecruitmentOfficer", "AgencyOwner")
    check_scope(role, user_id, agency_id)
    data = body()
    legal_name = opt_str(data, "legal_name", min_len=1, max_len=200)
    ownership_disclosed = opt_bool(data, "ownership_disclosed")
    beneficial_owner_count = opt_int(data, "beneficial_owner_count", minimum=0)
    sanctions_screen_passed = opt_bool(data, "sanctions_screen_passed")
    reference_check_count = opt_int(data, "reference_check_count", minimum=0)
    agency = _agency(agency_id)

    if legal_name is not None:
        agency["legal_name"] = legal_name
    if ownership_disclosed is not None:
        agency["ownership_disclosed"] = ownership_disclosed
    if beneficial_owner_count is not None:
        agency["beneficial_owner_count"] = beneficial_owner_count
    if sanctions_screen_passed is not None:
        agency["sanctions_screen_passed"] = sanctions_screen_passed
    if reference_check_count is not None:
        agency["reference_check_count"] = reference_check_count
    touch(agency)
    return obj(serializers.agency(agency))


# --- vetting dimension ------------------------------------------------------

@bp.route("/recruitment/agencies/<agency_id>/vetting", methods=["POST"])
def agency_vetting(agency_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    data = body()
    action = req_enum(data, "action", VETTING_ACTIONS)
    opt_str(data, "note")
    agency = _agency(agency_id)

    source, target = VETTING_TRANSITIONS[action]
    if agency["vetting_state"] != source:
        fail(errors.ERR_INVALID_VETTING_STATE,
             "Action %s is not defined from vetting_state %s" % (action, agency["vetting_state"]))

    if action == "CLEAR":
        if agency["compliance_posture"] in ("SUSPENDED", "DEBARRED"):
            fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
                 "Compliance posture %s blocks clearance" % agency["compliance_posture"])
        if (not agency["ownership_disclosed"] or not agency["sanctions_screen_passed"]
                or agency["beneficial_owner_count"] < 1 or agency["reference_check_count"] < 2):
            fail(errors.ERR_DUE_DILIGENCE_INCOMPLETE,
                 "The due-diligence checklist is incomplete")

    agency["vetting_state"] = target
    touch(agency)

    if action == "REJECT":
        for contract in db.contracts.values():
            if contract["agency_id"] != agency_id:
                continue
            if contract["status"] in ("DRAFT", "PENDING_AGENCY_SIGNATURE",
                                     "PENDING_COMPLIANCE_REVIEW"):
                domain.commit(contract, {"status": "TERMINATED",
                                         "termination_reason_code": "NON_RENEWAL"})
    return obj(serializers.agency(agency))


# --- posture dimension ------------------------------------------------------

@bp.route("/recruitment/agencies/<agency_id>/posture-actions", methods=["POST"])
def agency_posture(agency_id):
    auth("ComplianceOfficer")
    data = body()
    action = req_enum(data, "action", POSTURE_ACTIONS)
    reason = req_str(data, "reason")
    agency = _agency(agency_id)

    sources, target = POSTURE_SOURCES[action]
    current = agency["compliance_posture"]
    if current not in sources:
        fail(errors.ERR_INVALID_POSTURE_ACTION,
             "Action %s is not defined from compliance_posture %s" % (action, current))
    if action == "REINSTATE" and not (agency["rolling_risk_score"] < 65.00):
        fail(errors.ERR_INVALID_POSTURE_ACTION,
             "REINSTATE requires rolling_risk_score below 65.00")
    if action == "CLEAR_WATCH" and not (agency["rolling_risk_score"] < 40.00):
        fail(errors.ERR_INVALID_POSTURE_ACTION,
             "CLEAR_WATCH requires rolling_risk_score below 40.00")

    domain.set_posture(agency, target, reason)
    return obj(serializers.agency(agency))


@bp.route("/recruitment/agencies/<agency_id>/risk-profile", methods=["GET"])
def agency_risk_profile(agency_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    agency = _agency(agency_id)
    rolling = calc.rhu(agency["rolling_risk_score"], 2)
    lifetime = calc.rhu(agency["lifetime_risk_score"], 2)
    return obj({
        "rolling_risk_score": float(rolling),
        "lifetime_risk_score": float(lifetime),
        "lifetime_minus_rolling_delta": float(calc.rhu(lifetime - rolling, 2)),
        "confirmed_incident_count": agency["confirmed_incident_count"],
        "reviewed_document_count": agency["reviewed_document_count"],
        "confirmed_fraud_document_count": agency["confirmed_fraud_document_count"],
        "posture_band": calc.posture_band(rolling),
    })


# --- training certifications ------------------------------------------------

@bp.route("/recruitment/agencies/<agency_id>/training-certifications", methods=["POST"])
def create_certification(agency_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    data = body()
    module_code = req_enum(data, "module_code", calc.MODULE_CODES)
    score = req_int(data, "score", minimum=0, maximum=100)
    issued_on = req_date(data, "issued_on")
    agency = _agency(agency_id)

    if score < 80:
        fail(errors.ERR_TRAINING_SCORE_INSUFFICIENT, "A training score below 80 is not accepted")
    if issued_on > today():
        fail(errors.ERR_FUTURE_DATE_NOT_ALLOWED, "issued_on may not be in the future")
    for cert in calc.agency_certifications(agency_id):
        if cert["module_code"] == module_code and cert["status"] == "VALID":
            fail(errors.ERR_DUPLICATE_RESOURCE,
                 "A VALID certification for module %s already exists" % module_code)

    expires_on = issued_on + timedelta(days=calc.MODULE_VALIDITY_DAYS[module_code])
    record = base_record()
    record.update({
        "agency_id": agency["id"],
        "module_code": module_code,
        "score": score,
        "issued_on": fmt_date(issued_on),
        "expires_on": fmt_date(expires_on),
        "status": "VALID",
        "revoked_reason": None,
    })
    db.certifications[record["id"]] = record
    return obj(serializers.certification(record), 201)


@bp.route("/recruitment/agencies/<agency_id>/training-certifications", methods=["GET"])
def list_certifications(agency_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    check_scope(role, user_id, agency_id)
    module_code = query_enum("module_code", calc.MODULE_CODES)
    status = query_enum("status", calc.CERT_STATUSES)
    _agency(agency_id)
    records = calc.agency_certifications(agency_id)
    if module_code is not None:
        records = [r for r in records if r["module_code"] == module_code]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return listing(records, serializers.certification)


# --- performance scorecards -------------------------------------------------

@bp.route("/recruitment/agencies/<agency_id>/scorecards", methods=["POST"])
def create_scorecard(agency_id):
    auth("RecruitmentOfficer")
    data = body()
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    agency = _agency(agency_id)

    if period_start > period_end or period_end > today():
        fail(errors.ERR_TERM_WINDOW_INVALID, "The scoring window is not coherent")

    figures = calc.scorecard_figures(agency_id, period_start, period_end)
    escalates = (figures["tier"] == "WATCH" and agency["compliance_posture"] == "GOOD_STANDING")

    record = base_record()
    record.update({
        "agency_id": agency["id"],
        "period_start_date": fmt_date(period_start),
        "period_end_date": fmt_date(period_end),
        "submitted_count": figures["submitted_count"],
        "enrolled_count": figures["enrolled_count"],
        "persisted_count": figures["persisted_count"],
        "reviewed_document_count": figures["reviewed_document_count"],
        "flagged_document_count": figures["flagged_document_count"],
        "yield_rate": float(figures["yield_rate"]),
        "persistence_rate": float(figures["persistence_rate"]),
        "quality_index": float(figures["quality_index"]),
        "composite_score": float(figures["composite_score"]),
        "tier": figures["tier"],
        "posture_action_applied": "ESCALATED_TO_WATCH" if escalates else "NONE",
    })
    db.scorecards[record["id"]] = record

    domain.refresh_current_tier(agency)
    if escalates:
        domain.escalate_posture(agency, "WATCH", "SCORECARD_TIER_WATCH")
    return obj(serializers.scorecard(record), 201)


@bp.route("/recruitment/agencies/<agency_id>/scorecards", methods=["GET"])
def list_scorecards(agency_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    check_scope(role, user_id, agency_id)
    tier = query_enum("tier", calc.TIERS)
    _agency(agency_id)
    records = calc.agency_scorecards(agency_id)
    if tier is not None:
        records = [r for r in records if r["tier"] == tier]
    return listing(records, serializers.scorecard)
