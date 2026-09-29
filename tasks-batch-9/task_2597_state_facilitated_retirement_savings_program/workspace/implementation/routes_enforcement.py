"""Penalty assessments, dispositions and outside-agency referrals."""
from flask import Blueprint

import calc
import engine
import serializers
from auth import get_employer, get_penalty, own_employer, require
from errors import fail
from response import created, paginate, query_filter, single
from store import db
from util import parse_date
from validate import parse_body, present

bp = Blueprint("enforcement", __name__)

VIOLATION_TYPES = ("FAILURE_TO_REGISTER", "FAILURE_TO_REMIT", "FAILURE_TO_ENROLL")
DISPOSITIONS = ("ABATE", "AFFIRM")
AGENCIES = ("STATE_LABOR_COMMISSIONER", "STATE_TAX_AUTHORITY", "ATTORNEY_GENERAL")
REFERRAL_STATUSES = ("OPEN", "WITHDRAWN")
PENALTY_READ_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Employer"]
DEFAULT_CURE_DAYS = 30


@bp.route("/employers/<employer_id>/penalty-assessments", methods=["POST"])
def assess_penalty(employer_id):
    principal = require(["ComplianceOfficer"])
    employer = get_employer(employer_id)
    parsed = parse_body({
        "violation_type": {"type": "str", "required": True, "enum": VIOLATION_TYPES},
        "notice_date": {"type": "date", "required": True},
        "cure_days": {"type": "int", "default": DEFAULT_CURE_DAYS, "min": 0},
    })
    penalty = engine.mint_penalty(employer, parsed["violation_type"],
                                  parsed["notice_date"], parsed["cure_days"],
                                  principal.user_id, "MANUAL")
    calc.refresh_employer(employer)
    db.touch(employer)
    return created(serializers.penalty(penalty))


@bp.route("/penalty-assessments/<penalty_id>", methods=["GET"])
def read_penalty(penalty_id):
    principal = require(PENALTY_READ_ROLES)
    penalty = get_penalty(penalty_id)
    own_employer(principal, penalty["employer_id"])
    return single(serializers.penalty(penalty))


@bp.route("/penalty-assessments/<penalty_id>/disposition", methods=["POST"])
def dispose_penalty(penalty_id):
    principal = require(["ComplianceOfficer"])
    penalty = get_penalty(penalty_id)
    parsed = parse_body({
        "disposition": {"type": "str", "required": True, "enum": DISPOSITIONS},
        "disposition_note": {"type": "str", "nullable": True},
    })
    if penalty["status"] not in ("ASSESSED", "AFFIRMED"):
        fail("ERR_PENALTY_STATE_INVALID", "an abated assessment is terminal")
    if parsed["disposition"] == "AFFIRM" and penalty["status"] != "ASSESSED":
        fail("ERR_PENALTY_STATE_INVALID", "this assessment has already been affirmed")
    if principal.user_id == penalty["assessed_by_user_id"]:
        fail("ERR_SELF_DISPOSITION_FORBIDDEN",
             "the officer who assessed a penalty may not dispose of it")
    if parsed["disposition"] == "AFFIRM" and db.today() <= parse_date(penalty["cure_deadline"]):
        fail("ERR_CURE_PERIOD_ACTIVE",
             "the employer still has until %s to cure" % penalty["cure_deadline"])
    penalty["disposed_by_user_id"] = principal.user_id
    if present(parsed, "disposition_note"):
        penalty["disposition_note"] = parsed["disposition_note"]
    if parsed["disposition"] == "AFFIRM":
        penalty["status"] = "AFFIRMED"
    else:
        penalty["status"] = "ABATED"
        for referral in engine.referrals_of(penalty_id):
            if referral["status"] != "OPEN":
                continue
            referral["status"] = "WITHDRAWN"
            referral["withdrawn_reason"] = (
                parsed.get("disposition_note")
                or "The underlying assessment was abated")
            db.touch(referral)
    db.touch(penalty)
    employer = db.employers.get(penalty["employer_id"])
    if employer is not None:
        calc.refresh_employer(employer)
        db.touch(employer)
    return single(serializers.penalty(penalty))


@bp.route("/penalty-assessments/<penalty_id>/enforcement-referrals", methods=["POST"])
def refer_penalty(penalty_id):
    principal = require(["ComplianceOfficer"])
    penalty = get_penalty(penalty_id)
    parsed = parse_body({
        "agency": {"type": "str", "required": True, "enum": AGENCIES},
        "referral_basis": {"type": "str", "required": True},
    })
    if penalty["status"] != "AFFIRMED":
        fail("ERR_PENALTY_STATE_INVALID", "only an affirmed assessment may be referred out")
    employer = db.employers.get(penalty["employer_id"])
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "the employer of this assessment no longer exists")
    referral = engine.mint_referral(penalty, employer, parsed["agency"],
                                   parsed["referral_basis"], principal.user_id)
    calc.refresh_employer(employer)
    db.touch(employer)
    return created(serializers.referral(referral))


@bp.route("/penalty-assessments/<penalty_id>/enforcement-referrals", methods=["GET"])
def list_referrals(penalty_id):
    principal = require(PENALTY_READ_ROLES)
    penalty = get_penalty(penalty_id)
    own_employer(principal, penalty["employer_id"])
    status = query_filter("status", REFERRAL_STATUSES)
    agency = query_filter("agency", AGENCIES)
    rows = engine.referrals_of(penalty_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if agency is not None:
        rows = [r for r in rows if r["agency"] == agency]
    return paginate(rows, serializers.referral)
