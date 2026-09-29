"""Patient endpoints, including transfers, discharge and risk scoring."""
from decimal import Decimal

from flask import Blueprint

from calc import (
    initial_assessment_score,
    ongoing_surveillance_score,
    risk_factors,
)
from core import (
    ALL_ROLES,
    ROLE_AUDITOR,
    ROLE_INTAKE,
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ApiError,
    actor,
    authenticate,
    base_row,
    bool_filter,
    db,
    enum_filter,
    num2,
    order_key,
    paginate,
    pagination,
    parse_date_value,
    respond,
    sorted_rows,
    str_filter,
    today,
    touch,
)
from domain import (
    apply_risk_variant,
    contracts_for_patient,
    get_branch,
    get_patient,
    newest_cmn,
    patient_cmns,
)
from serial import patient_out
from validate import Field, validate

bp = Blueprint("patients", __name__)

PAYER_TYPES = (
    "MEDICARE_COMPETITIVE_BID",
    "MEDICARE_NON_BID",
    "MEDICAID",
    "COMMERCIAL",
)
MOBILITY_PROFILES = ("HOMEBOUND", "LIMITED_AMBULATORY", "ACTIVE_AMBULATORY")
PATIENT_STATUSES = ("ACTIVE", "TRANSFER_PENDING", "DISCHARGED")

CREATE_FIELDS = [
    Field("mrn", "string", required=True, min_len=1, max_len=40),
    Field("full_name", "string", required=True, min_len=1, max_len=120),
    Field("branch_id", "string", required=True, min_len=1),
    Field("payer_type", "enum", required=True, enum=PAYER_TYPES),
    Field("mobility_profile", "enum", required=True, enum=MOBILITY_PROFILES),
    Field("altitude_feet", "integer", default=0, minimum=0, maximum=15000),
]

PATCH_FIELDS = [
    Field("full_name", "string", min_len=1, max_len=120),
    Field("mobility_profile", "enum", enum=MOBILITY_PROFILES),
    Field("altitude_feet", "integer", minimum=0, maximum=15000),
]

TRANSFER_FIELDS = [
    Field("receiving_branch_id", "string", required=True, min_len=1),
    Field("transfer_effective_date", "date", required=True),
]


@bp.post("/patients")
def create_patient():
    authenticate((ROLE_INTAKE,))
    data = validate(CREATE_FIELDS)
    get_branch(data["branch_id"])
    for existing in db.patients.values():
        if existing["mrn"] == data["mrn"]:
            raise ApiError("ERR_DUPLICATE_MRN")
    row = base_row()
    row.update(
        {
            "mrn": data["mrn"],
            "full_name": data["full_name"],
            "branch_id": data["branch_id"],
            "payer_type": data["payer_type"],
            "mobility_profile": data["mobility_profile"],
            "altitude_feet": data["altitude_feet"],
            "status": "ACTIVE",
            "transfer_to_branch_id": None,
            "transfer_effective_date": None,
            "current_cmn_status": "NONE",
            "oxygen_safety_risk_score": Decimal("0.00"),
            "risk_variant_applied": "NONE",
            "compliance_hold": False,
        }
    )
    db.patients[row["id"]] = row
    return respond(patient_out(row), 201)


@bp.get("/patients")
def list_patients():
    authenticate(ALL_ROLES)
    branch_id = str_filter("branch_id")
    transfer_to = str_filter("transfer_to_branch_id")
    status = enum_filter("status", PATIENT_STATUSES)
    payer_type = enum_filter("payer_type", PAYER_TYPES)
    mobility = enum_filter("mobility_profile", MOBILITY_PROFILES)
    hold = bool_filter("compliance_hold")
    limit, offset = pagination()
    rows = sorted_rows(db.patients.values())
    if branch_id is not None:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if transfer_to is not None:
        rows = [r for r in rows if r["transfer_to_branch_id"] == transfer_to]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if payer_type is not None:
        rows = [r for r in rows if r["payer_type"] == payer_type]
    if mobility is not None:
        rows = [r for r in rows if r["mobility_profile"] == mobility]
    if hold is not None:
        rows = [r for r in rows if r["compliance_hold"] is hold]
    return paginate(rows, limit, offset, patient_out)


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    authenticate(ALL_ROLES)
    return respond(patient_out(get_patient(patient_id)))


@bp.patch("/patients/<patient_id>")
def patch_patient(patient_id):
    authenticate((ROLE_INTAKE,))
    row = get_patient(patient_id)
    data = validate(PATCH_FIELDS)
    for key in ("full_name", "mobility_profile", "altitude_feet"):
        if key in data:
            row[key] = data[key]
    touch(row)
    return respond(patient_out(row))


@bp.get("/patients/<patient_id>/risk-assessment")
def risk_assessment(patient_id):
    authenticate((ROLE_THERAPIST, ROLE_MANAGER, ROLE_AUDITOR))
    patient = get_patient(patient_id)
    factors = risk_factors(patient)
    return respond(
        {
            "patient_id": patient["id"],
            "factor_smoking": num2(factors["factor_smoking"]),
            "factor_electrical": num2(factors["factor_electrical"]),
            "factor_teachback": num2(factors["factor_teachback"]),
            "factor_flow": num2(factors["factor_flow"]),
            "factor_incident": num2(factors["factor_incident"]),
            "initial_assessment_score": num2(initial_assessment_score(factors)),
            "ongoing_surveillance_score": num2(ongoing_surveillance_score(factors)),
            "persisted_score": num2(patient["oxygen_safety_risk_score"]),
            "persisted_variant": patient["risk_variant_applied"],
            "compliance_hold": patient["compliance_hold"],
        }
    )


@bp.post("/patients/<patient_id>/risk-reassessments")
def risk_reassessment(patient_id):
    authenticate((ROLE_THERAPIST,))
    patient = get_patient(patient_id)
    apply_risk_variant(patient, "ONGOING_SURVEILLANCE")
    return respond(patient_out(patient))


def _suspend_for_transfer(patient):
    for contract in sorted(contracts_for_patient(patient["id"]), key=order_key):
        if contract["billing_status"] in ("ACCRUING", "CAP_REACHED"):
            contract["billing_status"] = "SUSPENDED"
            contract["suspension_reason"] = "TRANSFER"
            touch(contract)


def _resume_after_transfer(patient):
    for contract in sorted(contracts_for_patient(patient["id"]), key=order_key):
        if (
            contract["billing_status"] == "SUSPENDED"
            and contract["suspension_reason"] == "TRANSFER"
        ):
            contract["billing_status"] = "ACCRUING"
            contract["suspension_reason"] = "NONE"
            touch(contract)


@bp.post("/patients/<patient_id>/transfer-requests")
def open_transfer(patient_id):
    authenticate((ROLE_INTAKE,))
    patient = get_patient(patient_id)
    data = validate(TRANSFER_FIELDS)
    branch = get_branch(data["receiving_branch_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if branch["id"] == patient["branch_id"]:
        raise ApiError("ERR_RECEIVING_BRANCH_INVALID")
    effective = parse_date_value(data["transfer_effective_date"])
    if effective < today():
        raise ApiError("ERR_TRANSFER_DATE_IN_PAST")
    patient["transfer_to_branch_id"] = branch["id"]
    patient["transfer_effective_date"] = data["transfer_effective_date"]
    patient["status"] = "TRANSFER_PENDING"
    _suspend_for_transfer(patient)
    touch(patient)
    return respond(patient_out(patient))


@bp.post("/patients/<patient_id>/transfer-requests/complete")
def complete_transfer(patient_id):
    authenticate((ROLE_MANAGER,))
    patient = get_patient(patient_id)
    if patient["status"] != "TRANSFER_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    effective = parse_date_value(patient["transfer_effective_date"])
    if effective is not None and today() < effective:
        raise ApiError("ERR_TRANSFER_NOT_DUE")
    patient["branch_id"] = patient["transfer_to_branch_id"]
    patient["transfer_to_branch_id"] = None
    patient["transfer_effective_date"] = None
    patient["status"] = "ACTIVE"
    _resume_after_transfer(patient)
    touch(patient)
    return respond(patient_out(patient))


@bp.post("/patients/<patient_id>/transfer-requests/cancel")
def cancel_transfer(patient_id):
    authenticate((ROLE_INTAKE,))
    patient = get_patient(patient_id)
    if patient["status"] != "TRANSFER_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    patient["transfer_to_branch_id"] = None
    patient["transfer_effective_date"] = None
    patient["status"] = "ACTIVE"
    _resume_after_transfer(patient)
    touch(patient)
    return respond(patient_out(patient))


@bp.post("/patients/<patient_id>/discharge")
def discharge_patient(patient_id):
    authenticate((ROLE_MANAGER,))
    patient = get_patient(patient_id)
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    for contract in contracts_for_patient(patient["id"]):
        if contract["service_status"] in (
            "PENDING_SETUP",
            "IN_SERVICE",
            "PICKUP_SCHEDULED",
        ):
            raise ApiError("ERR_PATIENT_HAS_ACTIVE_SERVICE")
    for contract in sorted(contracts_for_patient(patient["id"]), key=order_key):
        if contract["billing_status"] != "CLOSED":
            contract["billing_status"] = "CLOSED"
            contract["monthly_allowable_cents"] = 0
            touch(contract)
    for cmn in sorted(patient_cmns(patient["id"]), key=order_key):
        if cmn["status"] == "ACTIVE":
            cmn["status"] = "VOIDED"
            cmn["void_reason"] = "PATIENT_DISCHARGED"
            touch(cmn)
    newest = newest_cmn(patient["id"])
    patient["current_cmn_status"] = newest["status"] if newest else "NONE"
    patient["status"] = "DISCHARGED"
    touch(patient)
    return respond(patient_out(patient))
