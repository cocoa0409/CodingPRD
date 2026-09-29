"""Firm registration, responsible charge and plan sealing (PRD 3.8)."""
from flask import Blueprint

import calc
import cascade
import db
import guards
import schemas
from errors import ApiError
from middleware import actor, endpoint
from response import created, ok
from util import add_days
from validate import (body, q_enum, q_str, req_bool, req_id, req_int,
                      req_state_code, req_str)

bp = Blueprint("firms", __name__)

FIRM_STATUSES = ("ACTIVE", "LAPSED_NO_RESPONSIBLE_CHARGE", "EXPIRED", "REVOKED")
PLAN_STATUSES = ("DRAFT", "SEALED", "FLAGGED", "VOIDED")
FIRM_READ_ROLES = ("FirmAdmin", "Licensee", "BoardLicensingOfficer",
                   "BoardInvestigator", "BoardSecretary")
PLAN_READ_ROLES = ("FirmAdmin", "Licensee", "BoardInvestigator",
                   "BoardLicensingOfficer")


def _fetch_firm(firm_registration_id):
    return schemas.fetch("firm_registrations", firm_registration_id,
                         "ERR_FIRM_REGISTRATION_NOT_FOUND")


def _fetch_plan(plan_submission_id):
    return schemas.fetch("plan_submissions", plan_submission_id,
                         "ERR_PLAN_SUBMISSION_NOT_FOUND")


# --------------------------------------------------------- firm registrations
@bp.post("/firm-registrations")
@endpoint("BoardLicensingOfficer")
def create_firm():
    data = body()
    firm_name = req_str(data, "firm_name", max_len=160)
    state_code = req_state_code(data, "state_code")
    license_id = req_id(data, "responsible_charge_license_id")
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    for row in db.store["firm_registrations"].values():
        if row["firm_name"] == firm_name:
            raise ApiError("ERR_DUPLICATE_FIRM_NAME",
                           "firm name already on the register")
    if license_row["status"] != "ACTIVE":
        raise ApiError("ERR_RESPONSIBLE_CHARGE_LICENSE_INACTIVE",
                       "the nominated licence does not stand in ACTIVE")
    firm = db.insert("firm_registrations", {
        "firm_name": firm_name,
        "state_code": state_code,
        "responsible_charge_license_id": license_id,
        "status": "ACTIVE",
        "registration_expires_at": add_days(db.clock(),
                                            calc.FIRM_REGISTRATION_DAYS),
        "lapsed_at": None,
    })
    return created(schemas.view(firm, schemas.FIRM_REGISTRATION))


@bp.get("/firm-registrations/<firm_registration_id>")
@endpoint(*FIRM_READ_ROLES)
def read_firm(firm_registration_id):
    firm = _fetch_firm(firm_registration_id)
    return ok(schemas.view(firm, schemas.FIRM_REGISTRATION))


@bp.get("/firm-registrations")
@endpoint(*FIRM_READ_ROLES)
def list_firms():
    license_id = q_str("responsible_charge_license_id")
    status = q_enum("status", FIRM_STATUSES)
    state_code = q_str("state_code")

    def keep(row):
        if license_id is not None and row["responsible_charge_license_id"] != license_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if state_code is not None and row["state_code"] != state_code:
            return False
        return True

    return schemas.listing("firm_registrations", schemas.FIRM_REGISTRATION, keep)


@bp.post("/firm-registrations/<firm_registration_id>/responsible-charge")
@endpoint("FirmAdmin")
def nominate_responsible_charge(firm_registration_id):
    data = body()
    license_id = req_id(data, "responsible_charge_license_id")
    firm = _fetch_firm(firm_registration_id)
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    guards.owned_by_caller(firm["id"])
    if firm["status"] != "LAPSED_NO_RESPONSIBLE_CHARGE":
        raise ApiError("ERR_FIRM_STATE_INVALID",
                       "only a lapsed firm may nominate a replacement")
    if license_row["status"] != "ACTIVE":
        raise ApiError("ERR_RESPONSIBLE_CHARGE_LICENSE_INACTIVE",
                       "the nominated licence does not stand in ACTIVE")
    if firm["registration_expires_at"] is not None and db.clock() > firm["registration_expires_at"]:
        raise ApiError("ERR_FIRM_STATE_INVALID",
                       "the firm registration has run past its expiry")
    db.write(firm, responsible_charge_license_id=license_id,
             status="ACTIVE", lapsed_at=None)
    return ok(schemas.view(firm, schemas.FIRM_REGISTRATION))


# ------------------------------------------------------------- plan submissions
@bp.post("/plan-submissions")
@endpoint("FirmAdmin")
def create_plan():
    data = body()
    firm_id = req_id(data, "firm_registration_id")
    project_name = req_str(data, "project_name", max_len=160)
    sheet_count = req_int(data, "sheet_count", minimum=1, maximum=500)
    firm = _fetch_firm(firm_id)
    guards.owned_by_caller(firm["id"])
    plan = db.insert("plan_submissions", {
        "firm_registration_id": firm["id"],
        "project_name": project_name,
        "sheet_count": sheet_count,
        "sealing_license_id": None,
        "responsible_charge_attested": False,
        "seal_affixed_at": None,
        "status": "DRAFT",
    })
    return created(schemas.view(plan, schemas.PLAN_SUBMISSION))


@bp.get("/plan-submissions/<plan_submission_id>")
@endpoint(*PLAN_READ_ROLES)
def read_plan(plan_submission_id):
    plan = _fetch_plan(plan_submission_id)
    return ok(schemas.view(plan, schemas.PLAN_SUBMISSION))


@bp.get("/plan-submissions")
@endpoint(*PLAN_READ_ROLES)
def list_plans():
    firm_id = q_str("firm_registration_id")
    sealing_license_id = q_str("sealing_license_id")
    status = q_enum("status", PLAN_STATUSES)

    def keep(row):
        if firm_id is not None and row["firm_registration_id"] != firm_id:
            return False
        if sealing_license_id is not None and row["sealing_license_id"] != sealing_license_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return schemas.listing("plan_submissions", schemas.PLAN_SUBMISSION, keep)


@bp.post("/plan-submissions/<plan_submission_id>/seal")
@endpoint("Licensee")
def seal_plan(plan_submission_id):
    data = body()
    license_id = req_id(data, "sealing_license_id")
    attested = req_bool(data, "responsible_charge_attested")
    plan = _fetch_plan(plan_submission_id)
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    guards.owned_by_caller(license_row["engineer_id"])
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "only a DRAFT plan set may be sealed")
    firm = db.get("firm_registrations", plan["firm_registration_id"])
    if firm is None or firm["status"] != "ACTIVE":
        raise ApiError("ERR_FIRM_STATE_INVALID",
                       "the firm does not stand in ACTIVE")
    if license_row["status"] != "ACTIVE":
        raise ApiError("ERR_SEAL_LICENSE_NOT_ACTIVE",
                       "the sealing licence does not stand in ACTIVE")
    if firm["responsible_charge_license_id"] != license_row["id"]:
        raise ApiError("ERR_NOT_RESPONSIBLE_CHARGE",
                       "the sealing licence is not the firm's responsible charge")
    if not attested:
        raise ApiError("ERR_ATTESTATION_MISSING",
                       "responsible-charge attestation is required")
    db.write(plan, sealing_license_id=license_row["id"],
             responsible_charge_attested=True, seal_affixed_at=db.clock(),
             status="SEALED")
    return ok(schemas.view(plan, schemas.PLAN_SUBMISSION))


@bp.post("/plan-submissions/<plan_submission_id>/flag")
@endpoint("BoardInvestigator")
def flag_plan(plan_submission_id):
    data = body()
    req_str(data, "reason")
    plan = _fetch_plan(plan_submission_id)
    if plan["status"] != "SEALED":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "only a SEALED plan set may be flagged")
    db.write(plan, status="FLAGGED")
    return ok(schemas.view(plan, schemas.PLAN_SUBMISSION))
