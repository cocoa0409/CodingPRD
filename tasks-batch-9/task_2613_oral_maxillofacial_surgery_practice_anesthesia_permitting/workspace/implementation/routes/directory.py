"""Staff members and patients."""
from flask import Blueprint

from db import db, new_record, ordered
from middleware import authorize
from routes.helpers import (ALL_ROLES, send, send_list, view_patient)
from services.domain import STAFF_ROLE_TYPES, path_row, referenced_row
from validation import (q_enum, q_string, read_body, v_bool, v_enum, v_id,
                        v_instant, v_int, v_number, v_string)

bp = Blueprint("directory", __name__)


@bp.post("/staff-members")
def create_staff():
    authorize("PracticeAdministrator")
    body = read_body(required=("practice_id", "full_name", "role_type"),
                     optional=("monitoring_certified", "acls_expires_on"))
    practice_id = v_id(body, "practice_id")
    full_name = v_string(body, "full_name", min_len=1, max_len=120)
    role_type = v_enum(body, "role_type", STAFF_ROLE_TYPES)
    monitoring_certified = v_bool(body, "monitoring_certified", default=False)
    acls_expires_on = v_instant(body, "acls_expires_on", default=None)

    referenced_row(db.practices, practice_id)

    staff = new_record({
        "practice_id": practice_id,
        "full_name": full_name,
        "role_type": role_type,
        "monitoring_certified": monitoring_certified,
        "acls_expires_on": acls_expires_on,
    })
    db.staff[staff["id"]] = staff
    return send(staff, 201)


@bp.get("/staff-members/<staff_id>")
def read_staff(staff_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.staff, staff_id))


@bp.get("/staff-members")
def list_staff():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    role_type = q_enum("role_type", STAFF_ROLE_TYPES)
    rows = ordered([s for s in db.staff.values()
                    if (practice_id is None or s["practice_id"] == practice_id)
                    and (role_type is None or s["role_type"] == role_type)])
    return send_list(rows)


@bp.post("/patients")
def create_patient():
    authorize("PracticeAdministrator", "SchedulingCoordinator")
    body = read_body(
        required=("practice_id", "full_name", "date_of_birth", "asa_class",
                  "airway_class", "weight_kg"),
        optional=("medical_plan_active", "dental_plan_active",
                  "dental_annual_remaining_cents"),
    )
    practice_id = v_id(body, "practice_id")
    full_name = v_string(body, "full_name", min_len=1, max_len=160)
    date_of_birth = v_instant(body, "date_of_birth")
    asa_class = v_int(body, "asa_class", minimum=1, maximum=4)
    airway_class = v_int(body, "airway_class", minimum=1, maximum=4)
    weight_kg = v_number(body, "weight_kg", exclusive_min=0)
    medical_plan_active = v_bool(body, "medical_plan_active", default=False)
    dental_plan_active = v_bool(body, "dental_plan_active", default=False)
    dental_remaining = v_int(body, "dental_annual_remaining_cents", minimum=0,
                             default=150000)

    referenced_row(db.practices, practice_id)

    patient = new_record({
        "practice_id": practice_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "asa_class": asa_class,
        "airway_class": airway_class,
        "weight_kg": weight_kg,
        "medical_plan_active": medical_plan_active,
        "dental_plan_active": dental_plan_active,
        "dental_annual_remaining_cents": dental_remaining,
    })
    db.patients[patient["id"]] = patient
    return send(patient, 201, viewer=view_patient)


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.patients, patient_id), viewer=view_patient)


@bp.get("/patients")
def list_patients():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    rows = ordered([p for p in db.patients.values()
                    if practice_id is None or p["practice_id"] == practice_id])
    return send_list(rows, viewer=view_patient)
