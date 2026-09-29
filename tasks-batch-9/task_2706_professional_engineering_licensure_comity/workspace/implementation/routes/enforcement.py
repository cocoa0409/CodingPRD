"""Complaints, findings, civil penalties and consent orders (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import db
import guards
import schemas
from errors import ApiError
from middleware import actor, endpoint
from response import created, ok
from util import add_months
from validate import (body, opt_id, opt_int, opt_str, q_enum, q_str, req_dt,
                      req_enum, req_id, req_int, req_str)

bp = Blueprint("enforcement", __name__)

ALLEGATION_TYPES = ("NEGLIGENCE", "UNLICENSED_PRACTICE", "PLAN_STAMPING",
                    "CPC_FRAUD")
INVESTIGATION_STATUSES = ("RECEIVED", "INVESTIGATING", "PROBABLE_CAUSE",
                          "NO_CAUSE", "CLOSED")
SANCTION_STATUSES = ("NONE", "PROPOSED", "CONSENT_EXECUTED", "HEARING_REFERRED")
SANCTION_TYPES = ("REPRIMAND", "SUSPENSION", "REVOCATION")
ORDER_STATUSES = ("PROPOSED", "SUPERSEDED", "EXECUTED")
CASE_ROLES = ("BoardInvestigator", "BoardLicensingOfficer", "BoardSecretary")


def _fetch_case(case_id):
    return schemas.fetch("cases", case_id, "ERR_CASE_NOT_FOUND")


def _fetch_order(consent_order_id):
    return schemas.fetch("consent_orders", consent_order_id,
                         "ERR_CONSENT_ORDER_NOT_FOUND")


def _case_state(condition, message):
    if not condition:
        raise ApiError("ERR_CASE_STATE_INVALID", message)


def _respondent_engineer(case):
    license_id = case["respondent_license_id"]
    if not license_id:
        return None
    return cascade.engineer_of_license(license_id)


# --------------------------------------------------------------------- cases
@bp.post("/cases")
@endpoint("BoardInvestigator")
def create_case():
    data = body()
    allegation_type = req_enum(data, "allegation_type", ALLEGATION_TYPES)
    complainant_name = req_str(data, "complainant_name", max_len=120)
    received_on = req_dt(data, "received_on")
    license_id = opt_id(data, "respondent_license_id")
    plan_id = opt_id(data, "subject_plan_submission_id")
    unlicensed_name = opt_str(data, "unlicensed_respondent_name")
    if license_id is not None:
        schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    if plan_id is not None:
        schemas.fetch("plan_submissions", plan_id, "ERR_PLAN_SUBMISSION_NOT_FOUND")
    if (license_id is None) == (unlicensed_name is None):
        raise ApiError("ERR_RESPONDENT_TARGET_INVALID",
                       "exactly one respondent target must be named")
    if allegation_type == "UNLICENSED_PRACTICE" and unlicensed_name is None:
        raise ApiError("ERR_RESPONDENT_TARGET_INVALID",
                       "an unlicensed-practice complaint needs a named respondent")
    if allegation_type == "PLAN_STAMPING" and plan_id is None:
        raise ApiError("ERR_RESPONDENT_TARGET_INVALID",
                       "a plan-stamping complaint needs a subject plan set")
    case = db.insert("cases", {
        "allegation_type": allegation_type,
        "respondent_license_id": license_id,
        "subject_plan_submission_id": plan_id,
        "unlicensed_respondent_name": unlicensed_name,
        "complainant_name": complainant_name,
        "received_on": received_on,
        "investigation_status": "RECEIVED",
        "sanction_status": "NONE",
        "assigned_investigator_user_id": None,
        "aggravating_factor_count": 0,
        "mitigating_factor_count": 0,
        "violation_count": 0,
        "penalty_factor": Decimal("0"),
        "assessed_penalty_cents": 0,
    })
    engineer_id = _respondent_engineer(case)
    if engineer_id is not None:
        cascade.recompute_open_case_count(engineer_id)
    return created(schemas.view(case, schemas.CASE))


@bp.get("/cases/<case_id>")
@endpoint(*CASE_ROLES)
def read_case(case_id):
    case = _fetch_case(case_id)
    return ok(schemas.view(case, schemas.CASE))


@bp.get("/cases")
@endpoint(*CASE_ROLES)
def list_cases():
    license_id = q_str("respondent_license_id")
    plan_id = q_str("subject_plan_submission_id")
    investigation_status = q_enum("investigation_status", INVESTIGATION_STATUSES)
    allegation_type = q_enum("allegation_type", ALLEGATION_TYPES)

    def keep(row):
        if license_id is not None and row["respondent_license_id"] != license_id:
            return False
        if plan_id is not None and row["subject_plan_submission_id"] != plan_id:
            return False
        if investigation_status is not None and row["investigation_status"] != investigation_status:
            return False
        if allegation_type is not None and row["allegation_type"] != allegation_type:
            return False
        return True

    return schemas.listing("cases", schemas.CASE, keep)


@bp.post("/cases/<case_id>/open-investigation")
@endpoint("BoardInvestigator")
def open_investigation(case_id):
    case = _fetch_case(case_id)
    _case_state(case["investigation_status"] == "RECEIVED",
                "only a RECEIVED complaint may be opened for investigation")
    db.write(case, investigation_status="INVESTIGATING",
             assigned_investigator_user_id=actor())
    return ok(schemas.view(case, schemas.CASE))


@bp.post("/cases/<case_id>/finding")
@endpoint("BoardInvestigator")
def record_finding(case_id):
    data = body()
    finding = req_enum(data, "finding", ("PROBABLE_CAUSE", "NO_CAUSE"))
    aggravating = req_int(data, "aggravating_factor_count", minimum=0, maximum=8)
    mitigating = req_int(data, "mitigating_factor_count", minimum=0, maximum=8)
    violations = req_int(data, "violation_count", minimum=0, maximum=20)
    case = _fetch_case(case_id)
    _case_state(case["investigation_status"] == "INVESTIGATING",
                "only a case under investigation may carry a finding")
    if finding == "PROBABLE_CAUSE":
        _case_state(violations >= 1,
                    "a probable-cause finding needs at least one violation")
    else:
        _case_state(violations == 0,
                    "a no-cause finding admits no violation")
    case["aggravating_factor_count"] = aggravating
    case["mitigating_factor_count"] = mitigating
    case["violation_count"] = violations
    if finding == "PROBABLE_CAUSE":
        factor, penalty = calc.assess_penalty(case)
        case["penalty_factor"] = factor
        case["assessed_penalty_cents"] = penalty
    else:
        case["penalty_factor"] = Decimal("0")
        case["assessed_penalty_cents"] = 0
    case["investigation_status"] = finding
    db.touch(case)
    if finding == "PROBABLE_CAUSE" and case["subject_plan_submission_id"]:
        plan = db.get("plan_submissions", case["subject_plan_submission_id"])
        if plan is not None and plan["status"] == "SEALED":
            db.write(plan, status="FLAGGED")
    return ok(schemas.view(case, schemas.CASE))


@bp.post("/cases/<case_id>/refer-hearing")
@endpoint("BoardInvestigator")
def refer_hearing(case_id):
    case = _fetch_case(case_id)
    _case_state(case["sanction_status"] in ("NONE", "PROPOSED"),
                "the sanction axis does not declare a referral from here")
    _case_state(case["investigation_status"] == "PROBABLE_CAUSE",
                "a hearing referral requires a probable-cause finding")
    for order in db.all_rows("consent_orders"):
        if order["case_id"] == case["id"] and order["status"] == "PROPOSED":
            db.write(order, status="SUPERSEDED")
    db.write(case, sanction_status="HEARING_REFERRED")
    return ok(schemas.view(case, schemas.CASE))


@bp.post("/cases/<case_id>/close")
@endpoint("BoardInvestigator")
def close_case(case_id):
    case = _fetch_case(case_id)
    _case_state(case["investigation_status"] in ("PROBABLE_CAUSE", "NO_CAUSE"),
                "the investigation axis does not declare a close from here")
    if case["investigation_status"] == "PROBABLE_CAUSE":
        if case["sanction_status"] not in ("CONSENT_EXECUTED", "HEARING_REFERRED"):
            raise ApiError("ERR_OPEN_SANCTION_BLOCKS_CLOSE",
                           "the sanction axis has not resolved")
    else:
        if case["sanction_status"] != "NONE":
            raise ApiError("ERR_OPEN_SANCTION_BLOCKS_CLOSE",
                           "a no-cause case may carry no sanction")
    db.write(case, investigation_status="CLOSED")
    engineer_id = _respondent_engineer(case)
    if engineer_id is not None:
        cascade.recompute_open_case_count(engineer_id)
    return ok(schemas.view(case, schemas.CASE))


# ------------------------------------------------------------- consent orders
@bp.post("/consent-orders")
@endpoint("BoardInvestigator")
def create_order():
    data = body()
    case_id = req_id(data, "case_id")
    sanction_type = req_enum(data, "sanction_type", SANCTION_TYPES)
    suspension_months = opt_int(data, "suspension_months", default=0,
                                minimum=0, maximum=60)
    penalty_paid_cents = opt_int(data, "penalty_paid_cents", default=0, minimum=0)
    expected_version = req_int(data, "expected_case_version")
    if sanction_type != "SUSPENSION" and suspension_months != 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "suspension_months must be 0 unless the sanction is a suspension")
    case = _fetch_case(case_id)
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION",
                       "the case has moved on since it was read")
    if case["investigation_status"] != "PROBABLE_CAUSE":
        raise ApiError("ERR_PROBABLE_CAUSE_REQUIRED",
                       "a consent order requires a probable-cause finding")
    for existing in db.all_rows("consent_orders"):
        if existing["case_id"] == case["id"] and existing["status"] == "PROPOSED":
            db.write(existing, status="SUPERSEDED")
    order = db.insert("consent_orders", {
        "case_id": case["id"],
        "sanction_type": sanction_type,
        "suspension_months": suspension_months,
        "penalty_cents": case["assessed_penalty_cents"],
        "penalty_paid_cents": penalty_paid_cents,
        "executed_on": None,
        "executed_by_user_id": None,
        "status": "PROPOSED",
    })
    case["sanction_status"] = "PROPOSED"
    db.touch(case)
    return created(schemas.view(order, schemas.CONSENT_ORDER))


@bp.get("/consent-orders/<consent_order_id>")
@endpoint(*CASE_ROLES)
def read_order(consent_order_id):
    order = _fetch_order(consent_order_id)
    return ok(schemas.view(order, schemas.CONSENT_ORDER))


@bp.get("/consent-orders")
@endpoint(*CASE_ROLES)
def list_orders():
    case_id = q_str("case_id")
    status = q_enum("status", ORDER_STATUSES)
    sanction_type = q_enum("sanction_type", SANCTION_TYPES)

    def keep(row):
        if case_id is not None and row["case_id"] != case_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if sanction_type is not None and row["sanction_type"] != sanction_type:
            return False
        return True

    return schemas.listing("consent_orders", schemas.CONSENT_ORDER, keep)


@bp.post("/consent-orders/<consent_order_id>/execute")
@endpoint("BoardInvestigator", "BoardLicensingOfficer")
def execute_order(consent_order_id):
    data = body()
    executed_on = req_dt(data, "executed_on")
    order = _fetch_order(consent_order_id)
    case = db.get("cases", order["case_id"])
    guards.segregation(case["assigned_investigator_user_id"] if case else None)
    if order["status"] != "PROPOSED":
        raise ApiError("ERR_CONSENT_ORDER_STATE_INVALID",
                       "only a PROPOSED order may be executed")
    if case is None or case["sanction_status"] != "PROPOSED":
        raise ApiError("ERR_CONSENT_ORDER_STATE_INVALID",
                       "the case carries no outstanding proposal")
    if order["penalty_paid_cents"] < order["penalty_cents"]:
        raise ApiError("ERR_PENALTY_UNPAID", "the civil penalty remains unpaid")

    # Link one: the order itself and the sanction axis.
    db.write(order, status="EXECUTED", executed_on=executed_on,
             executed_by_user_id=actor())
    db.write(case, sanction_status="CONSENT_EXECUTED")

    # Link two: the respondent's licence.
    license_row = db.get("licenses", case["respondent_license_id"])
    if license_row is not None:
        changes = {"discipline_flag": True}
        left_active = False
        if license_row["status"] == "ACTIVE":
            if order["sanction_type"] == "SUSPENSION":
                changes["status"] = "SUSPENDED"
                changes["suspension_ends_at"] = add_months(
                    executed_on, order["suspension_months"])
                left_active = True
            elif order["sanction_type"] == "REVOCATION":
                changes["status"] = "REVOKED"
                left_active = True
        db.write(license_row, **changes)
        if left_active:
            cascade.recompute_active_license_number(license_row["engineer_id"])
            # Links three and four: firm postures and their DRAFT plan sets.
            cascade.cascade_license_posture(license_row)
    return ok(schemas.view(order, schemas.CONSENT_ORDER))
