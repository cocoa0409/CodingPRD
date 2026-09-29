"""Roster and register: engineers and licences (PRD 3.1, 3.7)."""
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
from util import add_days, add_months
from validate import (body, opt_num, opt_str, q_enum, q_str, req_dt, req_enum,
                      req_id, req_num, req_state_code, req_str)

bp = Blueprint("roster", __name__)

ALL_HUMAN_ROLES = ("Applicant", "SupervisingEngineer", "Licensee", "FirmAdmin",
                   "BoardReviewer", "BoardLicensingOfficer", "BoardInvestigator",
                   "BoardSecretary")
BOARD_ROLES = ("BoardReviewer", "BoardLicensingOfficer", "BoardInvestigator",
               "BoardSecretary")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED")
LICENSE_TYPES = ("STANDARD", "COMITY")


# ------------------------------------------------------------------- engineers
@bp.post("/engineers")
@endpoint("BoardSecretary")
def create_engineer():
    data = body()
    full_name = req_str(data, "full_name", max_len=120)
    email = req_str(data, "email")
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST", "email must contain an @ character")
    home_jurisdiction = req_state_code(data, "home_jurisdiction")
    ncees_record_id = opt_str(data, "ncees_record_id", max_len=20, min_len=8)
    for row in db.store["engineers"].values():
        if row["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", "email already on the roster")
    engineer = db.insert("engineers", {
        "full_name": full_name,
        "email": email,
        "home_jurisdiction": home_jurisdiction,
        "ncees_record_id": ncees_record_id,
        "active_license_number": None,
        "open_case_count": 0,
    })
    return created(schemas.view(engineer, schemas.ENGINEER))


@bp.get("/engineers/<engineer_id>")
@endpoint(*ALL_HUMAN_ROLES)
def read_engineer(engineer_id):
    engineer = schemas.fetch("engineers", engineer_id, "ERR_ENGINEER_NOT_FOUND")
    return ok(schemas.view(engineer, schemas.ENGINEER))


@bp.get("/engineers")
@endpoint(*BOARD_ROLES)
def list_engineers():
    home_jurisdiction = q_str("home_jurisdiction")
    email = q_str("email")

    def keep(row):
        if home_jurisdiction is not None and row["home_jurisdiction"] != home_jurisdiction:
            return False
        if email is not None and row["email"] != email:
            return False
        return True

    return schemas.listing("engineers", schemas.ENGINEER, keep)


# -------------------------------------------------------------------- licences
def _new_license(engineer_id, license_type, issued_on, pdh_requirement):
    license_row = {
        "engineer_id": engineer_id,
        "license_number": db.next_license_number(),
        "license_type": license_type,
        "status": "ACTIVE",
        "issued_on": issued_on,
        "pdh_requirement": pdh_requirement,
        "reinstatement_eligible_until": None,
        "suspension_ends_at": None,
        "discipline_flag": False,
    }
    calc.lay_down_period(license_row, issued_on)
    db.insert("licenses", license_row)
    cascade.recompute_active_license_number(engineer_id)
    return license_row


def issue_license(engineer_id, license_type, issued_on, pdh_requirement):
    return _new_license(engineer_id, license_type, issued_on, pdh_requirement)


def has_active_license(engineer_id):
    return any(row["engineer_id"] == engineer_id and row["status"] == "ACTIVE"
               for row in db.store["licenses"].values())


@bp.post("/licenses")
@endpoint("BoardLicensingOfficer")
def create_license():
    data = body()
    engineer_id = req_id(data, "engineer_id")
    license_type = req_enum(data, "license_type", LICENSE_TYPES)
    issued_on = req_dt(data, "issued_on")
    pdh_requirement = opt_num(data, "pdh_requirement",
                              default=calc.DEFAULT_PDH_REQUIREMENT,
                              minimum=0, places=1)
    schemas.fetch("engineers", engineer_id, "ERR_ENGINEER_NOT_FOUND")
    if has_active_license(engineer_id):
        raise ApiError("ERR_DUPLICATE_ACTIVE_LICENSE",
                       "engineer already holds an ACTIVE licence")
    license_row = _new_license(engineer_id, license_type, issued_on, pdh_requirement)
    return created(schemas.view(license_row, schemas.LICENSE))


@bp.get("/licenses/<license_id>")
@endpoint(*ALL_HUMAN_ROLES)
def read_license(license_id):
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    return ok(schemas.view(license_row, schemas.LICENSE))


@bp.get("/licenses")
@endpoint("Licensee", "SupervisingEngineer", "FirmAdmin", *BOARD_ROLES)
def list_licenses():
    engineer_id = q_str("engineer_id")
    status = q_enum("status", LICENSE_STATUSES)
    license_type = q_enum("license_type", LICENSE_TYPES)

    def keep(row):
        if engineer_id is not None and row["engineer_id"] != engineer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if license_type is not None and row["license_type"] != license_type:
            return False
        return True

    return schemas.listing("licenses", schemas.LICENSE, keep)


@bp.post("/licenses/<license_id>/renew")
@endpoint("Licensee")
def renew_license(license_id):
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    guards.owned_by_caller(license_row["engineer_id"])
    if license_row["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_STATE_INVALID",
                       "only an ACTIVE licence may be renewed")
    now = db.clock()
    if now < license_row["renewal_window_opens_at"] or now > license_row["current_period_end"]:
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED",
                       "the renewal window is not open")
    period_end = license_row["current_period_end"]
    ok_report = None
    for report in db.all_rows("cpc_reports"):
        if report["license_id"] != license_row["id"]:
            continue
        if report["period_end"] != period_end:
            continue
        if report["status"] not in ("ACCEPTED", "AUDIT_CLEARED"):
            continue
        if report["shortfall_pdh"] != 0:
            continue
        ok_report = report
        break
    if ok_report is None:
        raise ApiError("ERR_CPC_SHORTFALL",
                       "no cleared competency report without shortfall for this period")
    calc.lay_down_period(license_row, period_end)
    db.touch(license_row)
    return ok(schemas.view(license_row, schemas.LICENSE))


@bp.post("/licenses/<license_id>/reinstate")
@endpoint("BoardLicensingOfficer")
def reinstate_license(license_id):
    data = body()
    makeup_pdh = req_num(data, "makeup_pdh", minimum=0, places=1)
    fee_cents = req_num(data, "reinstatement_fee_cents", minimum=0)
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    status = license_row["status"]
    if status not in ("EXPIRED", "SUSPENDED"):
        raise ApiError("ERR_LICENSE_STATE_INVALID",
                       "only an EXPIRED or SUSPENDED licence may be reinstated")
    orders = _executed_orders_against(license_row["id"])
    if status == "EXPIRED":
        if any(o["sanction_type"] == "REVOCATION" for o in orders):
            raise ApiError("ERR_LICENSE_STATE_INVALID",
                           "a revoked licence may never be reinstated")
    now = db.clock()
    if status == "EXPIRED":
        limit = license_row["reinstatement_eligible_until"]
        if limit is None or now > limit:
            raise ApiError("ERR_REINSTATEMENT_WINDOW_EXPIRED",
                           "the reinstatement grace window has closed")
    else:
        ends_at = license_row["suspension_ends_at"]
        if ends_at is None or now < ends_at:
            raise ApiError("ERR_REINSTATEMENT_WINDOW_EXPIRED",
                           "the suspension has not yet run its course")
    if makeup_pdh < calc.MIN_MAKEUP_PDH:
        raise ApiError("ERR_REINSTATEMENT_MAKEUP_INSUFFICIENT",
                       "at least 15 remedial hours are required")
    if fee_cents < calc.MIN_REINSTATEMENT_FEE_CENTS:
        raise ApiError("ERR_PENALTY_UNPAID", "the reinstatement fee is unpaid")
    if status == "SUSPENDED":
        for order in orders:
            if order["penalty_paid_cents"] < order["penalty_cents"]:
                raise ApiError("ERR_PENALTY_UNPAID",
                               "an executed consent order penalty remains unpaid")

    changes = {"status": "ACTIVE"}
    if status == "EXPIRED":
        changes["reinstatement_eligible_until"] = None
    else:
        changes["suspension_ends_at"] = None
    for key, value in changes.items():
        license_row[key] = value
    calc.lay_down_period(license_row, now)
    db.touch(license_row)
    cascade.recompute_active_license_number(license_row["engineer_id"])
    cascade.cascade_license_posture(license_row)
    return ok(schemas.view(license_row, schemas.LICENSE))


def _executed_orders_against(license_id):
    cases = {c["id"] for c in db.all_rows("cases")
             if c["respondent_license_id"] == license_id}
    return [o for o in db.all_rows("consent_orders")
            if o["case_id"] in cases and o["status"] == "EXECUTED"]
