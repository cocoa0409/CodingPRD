"""Registry surfaces: staff, patients, reference equation sets, rescue lots,
plus the logical clock."""
from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, ALL_ROLES, LAB_MANAGER, TECHNOLOGIST,
                  ORDERING_PHYSICIAN, INTERPRETING_PHYSICIAN,
                  COMPLIANCE_AUDITOR)
from calc import D, num
from errors import ApiError
from responses import object_response
from store import db, iso, iso_date, parse_date, stamp_new, touch
import validation as v

bp = Blueprint("registry", __name__)

ROLE_TYPES = ["TECHNOLOGIST", "ORDERING_PHYSICIAN", "INTERPRETING_PHYSICIAN"]
CREDENTIALS = ["CPFT", "RPFT", "MD"]
STAFF_STATUSES = ["ON_DUTY", "OFF_DUTY"]
SEXES = ["MALE", "FEMALE"]
SMOKING_STATUSES = ["NEVER", "FORMER", "CURRENT"]
SEX_SCOPES = ["MALE", "FEMALE", "ANY"]
BD_CRITERIA = ["PCT_BASELINE_2005", "PCT_PREDICTED_2021"]
DRUGS = ["ALBUTEROL_MDI", "ALBUTEROL_NEB"]

STAFF_READ_ROLES = [LAB_MANAGER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
                    COMPLIANCE_AUDITOR]
LOT_READ_ROLES = [LAB_MANAGER, TECHNOLOGIST, COMPLIANCE_AUDITOR]


# ----------------------------------------------------------------------- staff

@bp.route("/staff", methods=["POST"])
def create_staff():
    authenticate([LAB_MANAGER])
    body = v.get_body()
    employee_code = v.v_str(body, "employee_code")
    full_name = v.v_str(body, "full_name")
    role_type = v.v_enum(body, "role_type", ROLE_TYPES)
    credential = v.v_enum(body, "credential", CREDENTIALS)
    competency = v.v_date(body, "competency_expires_on")
    modalities = v.v_enum_array(body, "credentialed_modalities",
                                calc.MODALITIES)
    status = v.v_enum(body, "status", STAFF_STATUSES, required=False) \
        or "ON_DUTY"
    max_reports = v.v_int(body, "max_concurrent_reports", required=False,
                          minimum=1)
    if max_reports is None:
        max_reports = 1
    is_control = v.v_bool(body, "is_biologic_control", required=False,
                          default=False)
    baseline_fev1 = v.v_num(body, "baseline_fev1_l", required=bool(is_control),
                            minimum=0, exclusive_min=True)
    baseline_fvc = v.v_num(body, "baseline_fvc_l", required=bool(is_control),
                           minimum=0, exclusive_min=True)
    baseline_on = v.v_date(body, "baseline_established_on",
                           required=bool(is_control))
    for existing in db.staff.values():
        if existing["employee_code"] == employee_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "employee_code already exists.")
    record = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_type": role_type,
        "credential": credential,
        "competency_expires_on": iso_date(competency),
        "credentialed_modalities": modalities,
        "status": status,
        "max_concurrent_reports": max_reports,
        "is_biologic_control": bool(is_control),
        "baseline_fev1_l": baseline_fev1,
        "baseline_fvc_l": baseline_fvc,
        "baseline_established_on": iso_date(baseline_on),
        "open_report_count": 0,
    }
    stamp_new(record)
    db.staff[record["id"]] = record
    return object_response(svc.ser_staff(record), 201)


@bp.route("/staff/<staff_id>", methods=["GET"])
def read_staff(staff_id):
    authenticate(STAFF_READ_ROLES)
    return object_response(svc.ser_staff(svc.get_staff(staff_id)))


# -------------------------------------------------------------------- patients

@bp.route("/patients", methods=["POST"])
def create_patient():
    authenticate([LAB_MANAGER, ORDERING_PHYSICIAN])
    body = v.get_body()
    mrn = v.v_str(body, "mrn")
    full_name = v.v_str(body, "full_name")
    birth_date = v.v_date(body, "birth_date")
    sex = v.v_enum(body, "sex", SEXES)
    height_cm = v.v_num(body, "height_cm", minimum=90.0, maximum=220.0)
    weight_kg = v.v_num(body, "weight_kg", minimum=10.0, maximum=300.0)
    smoking = v.v_enum(body, "smoking_status", SMOKING_STATUSES)
    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "mrn already exists.")
    record = {
        "mrn": mrn,
        "full_name": full_name,
        "birth_date": iso_date(birth_date),
        "sex": sex,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "smoking_status": smoking,
        "completed_order_count": 0,
    }
    stamp_new(record)
    db.patients[record["id"]] = record
    return object_response(svc.ser_patient(record), 201)


@bp.route("/patients/<patient_id>", methods=["GET"])
def read_patient(patient_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_patient(svc.get_patient(patient_id)))


# ------------------------------------------------------ reference equation sets

@bp.route("/reference-equations", methods=["POST"])
def create_reference_equation():
    authenticate([LAB_MANAGER])
    body = v.get_body()
    equation_code = v.v_str(body, "equation_code")
    modality_scope = v.v_enum_array(body, "modality_scope", calc.MODALITIES)
    sex_scope = v.v_enum(body, "sex_scope", SEX_SCOPES)
    age_min = v.v_num(body, "applicable_age_min", minimum=0)
    age_max = v.v_num(body, "applicable_age_max", minimum=0)
    if D(age_min) > D(age_max):
        raise v.bad("applicable_age_min may not exceed applicable_age_max.")
    lln_percentile = v.v_num(body, "lln_percentile")
    ratio_lln = v.v_num(body, "ratio_lln")
    coefficients = {}
    for field in ("a_fev1", "b_fev1", "c_fev1", "a_fvc", "b_fvc", "c_fvc",
                  "rsd_frac"):
        coefficients[field] = v.v_num(body, field)
    bd_criterion = v.v_enum(body, "bd_criterion", BD_CRITERIA)
    status = v.v_enum(body, "status", ["ACTIVE", "SUPERSEDED"],
                      required=False) or "ACTIVE"
    record = {
        "equation_code": equation_code,
        "modality_scope": modality_scope,
        "sex_scope": sex_scope,
        "applicable_age_min": age_min,
        "applicable_age_max": age_max,
        "lln_percentile": lln_percentile,
        "ratio_lln": ratio_lln,
        "a_fev1": coefficients["a_fev1"],
        "b_fev1": coefficients["b_fev1"],
        "c_fev1": coefficients["c_fev1"],
        "a_fvc": coefficients["a_fvc"],
        "b_fvc": coefficients["b_fvc"],
        "c_fvc": coefficients["c_fvc"],
        "rsd_frac": coefficients["rsd_frac"],
        "bd_criterion": bd_criterion,
        "status": status,
    }
    stamp_new(record)
    if status == "ACTIVE":
        for existing in svc.by_created(list(db.equations.values())):
            if existing["equation_code"] == equation_code and \
                    existing["status"] == "ACTIVE":
                existing["status"] = "SUPERSEDED"
                touch(existing)
    db.equations[record["id"]] = record
    return object_response(svc.ser_equation(record), 201)


# ---------------------------------------------------------------- rescue lots

@bp.route("/rescue-lots", methods=["POST"])
def create_rescue_lot():
    authenticate([LAB_MANAGER])
    body = v.get_body()
    lot_number = v.v_str(body, "lot_number")
    drug = v.v_enum(body, "drug", DRUGS)
    doses = v.v_int(body, "doses_at_receipt", minimum=0)
    expires_on = v.v_date(body, "expires_on")
    for existing in db.lots.values():
        if existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "lot_number already exists.")
    record = {
        "lot_number": lot_number,
        "drug": drug,
        "doses_at_receipt": doses,
        "doses_remaining": doses,
        "doses_reserved": 0,
        "expires_on": iso_date(expires_on),
        "status": "STOCKED",
    }
    stamp_new(record)
    db.lots[record["id"]] = record
    return object_response(svc.ser_lot(record), 201)


@bp.route("/rescue-lots/<lot_id>", methods=["GET"])
def read_rescue_lot(lot_id):
    authenticate(LOT_READ_ROLES)
    return object_response(svc.ser_lot(svc.get_lot(lot_id)))


# ------------------------------------------------------------- logical clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate([LAB_MANAGER])
    body = v.get_body()
    target = v.v_datetime(body, "to_iso8601")
    db.clock = target
    new_date = db.clock.date()
    for lot in svc.by_created(list(db.lots.values())):
        if lot["status"] != "STOCKED":
            continue
        expires = parse_date(lot["expires_on"])
        if expires is not None and expires < new_date:
            lot["status"] = "EXPIRED"
            touch(lot)
    return object_response({"current_utc": iso(db.clock)}, 200)
