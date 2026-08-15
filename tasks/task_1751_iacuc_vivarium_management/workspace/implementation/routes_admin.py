"""Clock, investigators, grants, personnel, training, occ-health routes."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, iso, now, set_clock, new_rec
from domain import apply_clock_transitions, ser_grant, ser_investigator, ser_occ_health_enrollment, ser_personnel, ser_training_enrollment
from envelope import get_body, list_response, ok_obj
from errors import ApiError, ERR_DUPLICATE, invalid_request, invalid_state, not_found
from validation import authenticate, require_role, req_dt, req_enum, req_int, req_str

bp = Blueprint("admin", __name__)

SPECIES = {"MOUSE", "RAT", "RABBIT", "ZEBRAFISH"}
PERSONNEL_ROLES = {"TECHNICIAN", "CO_PI", "STUDENT"}
COURSES = {"ANIMAL_HANDLING", "ASEPTIC_TECHNIQUE", "EUTHANASIA", "SPECIES_SPECIFIC"}


def fetch(store_name, rid):
    r = STORE[store_name].get(rid)
    if r is None:
        raise not_found(f"Resource {rid} not found")
    return r


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/iacuc/_clock/set_current_utc")
def set_current_utc():
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    to = req_dt(body, "to_iso8601")
    set_clock(to)
    apply_clock_transitions()
    return ok_obj({"current_utc": iso(now())})


# ---------------------------------------------------------------------------
# Investigators
# ---------------------------------------------------------------------------

@bp.post("/iacuc/investigators")
def create_investigator():
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    department = req_str(body, "department")
    if any(i.email == email for i in STORE["investigators"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "email already registered")
    r = new_rec(
        "investigators",
        full_name=full_name,
        email=email,
        department=department,
        status="ACTIVE",
    )
    return ok_obj(ser_investigator(r), 201)


@bp.get("/iacuc/investigators/<rid>")
def get_investigator(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "Investigator")
    return ok_obj(ser_investigator(fetch("investigators", rid)))


@bp.get("/iacuc/investigators/<rid>/grants")
def list_investigator_grants(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "Investigator")
    fetch("investigators", rid)
    rows = [g for g in STORE["grants"].values() if g.investigator_id == rid]
    return list_response(rows, ser_grant)


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

@bp.post("/iacuc/grants")
def create_grant():
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    grant_number = req_str(body, "grant_number")
    investigator_id = req_str(body, "investigator_id")
    budget_total_cents = req_int(body, "budget_total_cents", minimum=0)
    expires_on = req_dt(body, "expires_on")
    fetch("investigators", investigator_id)
    if any(g.grant_number == grant_number for g in STORE["grants"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "grant_number already registered")
    r = new_rec(
        "grants",
        grant_number=grant_number,
        investigator_id=investigator_id,
        budget_total_cents=budget_total_cents,
        expires_on=expires_on,
    )
    return ok_obj(ser_grant(r), 201)


@bp.get("/iacuc/grants/<rid>")
def get_grant(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "Investigator", "BillingCoordinator")
    return ok_obj(ser_grant(fetch("grants", rid)))


# ---------------------------------------------------------------------------
# Personnel
# ---------------------------------------------------------------------------

@bp.post("/iacuc/personnel")
def create_personnel():
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    role_on_protocols = req_enum(body, "role_on_protocols", PERSONNEL_ROLES)
    if any(p.email == email for p in STORE["personnel"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "email already registered")
    r = new_rec(
        "personnel",
        full_name=full_name,
        email=email,
        role_on_protocols=role_on_protocols,
        status="ACTIVE",
    )
    return ok_obj(ser_personnel(r), 201)


@bp.get("/iacuc/personnel/<rid>")
def get_personnel(rid):
    uid, role = authenticate()
    require_role(
        role, "IacucAdministrator", "TrainingCoordinator", "OccHealthNurse",
        "AttendingVeterinarian",
    )
    return ok_obj(ser_personnel(fetch("personnel", rid)))


# ---------------------------------------------------------------------------
# Training enrollments
# ---------------------------------------------------------------------------

@bp.post("/iacuc/training-enrollments")
def create_training_enrollment():
    uid, role = authenticate()
    require_role(role, "TrainingCoordinator")
    body = get_body()
    personnel_id = req_str(body, "personnel_id")
    course_code = req_enum(body, "course_code", COURSES)
    fetch("personnel", personnel_id)
    r = new_rec(
        "training_enrollments",
        personnel_id=personnel_id,
        course_code=course_code,
        state="ENROLLED",
        completed_at=None,
        expires_at=None,
    )
    return ok_obj(ser_training_enrollment(r), 201)


@bp.get("/iacuc/personnel/<rid>/training-enrollments")
def list_training_enrollments(rid):
    uid, role = authenticate()
    require_role(role, "TrainingCoordinator", "IacucAdministrator")
    fetch("personnel", rid)
    rows = [
        e for e in STORE["training_enrollments"].values() if e.personnel_id == rid
    ]
    return list_response(rows, ser_training_enrollment)


@bp.post("/iacuc/training-enrollments/<rid>/complete")
def complete_training_enrollment(rid):
    uid, role = authenticate()
    require_role(role, "TrainingCoordinator")
    e = fetch("training_enrollments", rid)
    if e.state != "ENROLLED":
        raise invalid_state("TrainingEnrollment is not ENROLLED")
    e.state = "COMPLETED"
    e.completed_at = now()
    e.expires_at = e.completed_at + timedelta(days=365)
    e.touch()
    return ok_obj(ser_training_enrollment(e))


# ---------------------------------------------------------------------------
# Occupational-health enrollments
# ---------------------------------------------------------------------------

@bp.post("/iacuc/occ-health-enrollments")
def create_occ_health_enrollment():
    uid, role = authenticate()
    require_role(role, "OccHealthNurse")
    body = get_body()
    personnel_id = req_str(body, "personnel_id")
    fetch("personnel", personnel_id)
    r = new_rec(
        "occ_health_enrollments",
        personnel_id=personnel_id,
        state="ENROLLED",
        cleared_at=None,
        expires_at=None,
    )
    return ok_obj(ser_occ_health_enrollment(r), 201)


@bp.get("/iacuc/personnel/<rid>/occ-health-enrollments")
def list_occ_health_enrollments(rid):
    uid, role = authenticate()
    require_role(role, "OccHealthNurse", "IacucAdministrator")
    fetch("personnel", rid)
    rows = [
        e for e in STORE["occ_health_enrollments"].values() if e.personnel_id == rid
    ]
    return list_response(rows, ser_occ_health_enrollment)


@bp.post("/iacuc/occ-health-enrollments/<rid>/clear")
def clear_occ_health_enrollment(rid):
    uid, role = authenticate()
    require_role(role, "OccHealthNurse")
    e = fetch("occ_health_enrollments", rid)
    if e.state != "ENROLLED":
        raise invalid_state("OccHealthEnrollment is not ENROLLED")
    e.state = "CLEARED"
    e.cleared_at = now()
    e.expires_at = e.cleared_at + timedelta(days=365)
    e.touch()
    return ok_obj(ser_occ_health_enrollment(e))
