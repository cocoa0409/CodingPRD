"""ShelterAdmission endpoints: reservation, check-in, exit, cancellation,
location compromise and relocation."""

from flask import Blueprint

from db import clock_date, clock_iso, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
                        ROLE_SHELTER_MANAGER, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_admission, get_screening, get_unit,
                           insert, list_page)
from services import calc, cascade, derive
from validation import (date_out, get_body, opt_bool, q_enum, q_str, req_date, req_enum,
                        req_int, req_str)

bp = Blueprint("admissions", __name__)

OCCUPANCY_STATUSES = ("RESERVED", "CHECKED_IN", "EXITED", "CANCELLED")
LOCATION_STATUSES = ("SECURE", "COMPROMISED", "RELOCATED")
COMPROMISE_SOURCES = ("ABUSER_CONTACT", "DATA_BREACH", "COURT_FILING", "SOCIAL_MEDIA")
EXIT_DESTINATIONS = ("PERMANENT_HOUSING", "TRANSITIONAL_HOUSING", "FAMILY_FRIENDS", "UNKNOWN")
READ_ROLES = (ROLE_SHELTER_MANAGER, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
              ROLE_AGENCY_ADMIN)


def _fit_checks(unit, accessibility_required, minor_children_count):
    if accessibility_required and unit["unit_type"] != "ADA_ACCESSIBLE":
        raise ApiError("ERR_UNIT_ACCESSIBILITY_MISMATCH")
    if minor_children_count > 0 and unit["unit_type"] not in ("ADA_ACCESSIBLE", "FAMILY_SUITE"):
        raise ApiError("ERR_UNIT_COMPOSITION_MISMATCH")


def _capacity_check(unit, entry, planned_exit, household_size, exclude_admission_id=None):
    load = derive.window_load(unit["id"], entry, planned_exit, exclude_admission_id)
    if load + household_size > unit["bed_capacity"]:
        raise ApiError("ERR_UNIT_CAPACITY_EXCEEDED")


@bp.post("/shelter-admissions")
def create_admission():
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    screening_request_id = req_str(body, "screening_request_id")
    shelter_unit_id = req_str(body, "shelter_unit_id")
    entry_date = req_date(body, "entry_date")
    planned_exit_date = req_date(body, "planned_exit_date")
    expected_version = req_int(body, "expected_shelter_unit_version", 0)

    request_row = get_screening(screening_request_id)
    unit = get_unit(shelter_unit_id)

    if expected_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")

    for existing in derive.where("shelter_admissions", screening_request_id=request_row["id"]):
        if existing["occupancy_status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_ADMISSION")

    if request_row["status"] != "APPROVED":
        raise ApiError("ERR_SCREENING_NOT_APPROVED")

    if not entry_date < planned_exit_date:
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "planned_exit_date must be strictly after entry_date")

    _fit_checks(unit, request_row["accessibility_required"],
                request_row["minor_children_count"])
    _capacity_check(unit, entry_date, planned_exit_date, request_row["household_size"])

    shelter = db.shelters.get(unit["shelter_id"])
    projected = calc.projected_stay_cost(
        entry_date, planned_exit_date, shelter["nightly_rate_cents"],
        shelter["weekend_surcharge_cents"], shelter["child_supplement_cents"],
        request_row["minor_children_count"])

    admission = insert("shelter_admissions", {
        "screening_request_id": request_row["id"],
        "client_id": request_row["client_id"],
        "shelter_unit_id": unit["id"],
        "shelter_id": unit["shelter_id"],
        "prior_unit_id": None,
        "household_size": request_row["household_size"],
        "minor_children_count": request_row["minor_children_count"],
        "entry_date": date_out(entry_date),
        "planned_exit_date": date_out(planned_exit_date),
        "actual_exit_date": None,
        "occupancy_status": "RESERVED",
        "location_security_status": "SECURE",
        "compromise_source": None,
        "school_enrollment_status": ("PENDING" if request_row["minor_children_count"] > 0
                                    else "NOT_APPLICABLE"),
        "projected_stay_cost_cents": projected,
        "settled_stay_cost_cents": None,
        "exit_destination": None,
        "cancel_reason": None,
    })

    request_row["status"] = "ADMITTED"
    touch(request_row)
    derive.unit_ledger(unit)
    return created(public(admission))


@bp.get("/shelter-admissions/<admission_id>")
def read_admission(admission_id):
    auth(READ_ROLES)
    return ok(public(get_admission(admission_id)))


@bp.get("/shelter-admissions")
def list_admissions():
    auth(READ_ROLES)
    filters = {
        "screening_request_id": q_str("screening_request_id"),
        "client_id": q_str("client_id"),
        "shelter_unit_id": q_str("shelter_unit_id"),
        "shelter_id": q_str("shelter_id"),
        "prior_unit_id": q_str("prior_unit_id"),
        "occupancy_status": q_enum("occupancy_status", OCCUPANCY_STATUSES),
        "location_security_status": q_enum("location_security_status", LOCATION_STATUSES),
    }
    return list_page(by_created(filtered("shelter_admissions", filters)))


@bp.post("/shelter-admissions/<admission_id>/check-in")
def check_in(admission_id):
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    school_confirmed = opt_bool(body, "school_enrollment_confirmed", False)
    admission = get_admission(admission_id)

    if admission["occupancy_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RESERVED admission may be checked in")
    if clock_date() < derive.as_date(admission["entry_date"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the stay window has not opened yet")
    if admission["location_security_status"] == "COMPROMISED":
        raise ApiError("ERR_LOCATION_COMPROMISED")

    admission["occupancy_status"] = "CHECKED_IN"
    if admission["school_enrollment_status"] == "PENDING" and school_confirmed:
        admission["school_enrollment_status"] = "ENROLLED"
    touch(admission)
    derive.unit_ledger(db.shelter_units.get(admission["shelter_unit_id"]))
    return ok(public(admission))


@bp.post("/shelter-admissions/<admission_id>/exit")
def exit_admission(admission_id):
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    actual_exit_date = req_date(body, "actual_exit_date")
    exit_destination = req_enum(body, "exit_destination", EXIT_DESTINATIONS)
    admission = get_admission(admission_id)

    if admission["occupancy_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a CHECKED_IN admission may be exited")
    if not actual_exit_date > derive.as_date(admission["entry_date"]):
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "actual_exit_date must be strictly after entry_date")

    unit = db.shelter_units.get(admission["shelter_unit_id"])
    shelter = db.shelters.get(admission["shelter_id"])

    # link 1 - settle the stay
    admission["occupancy_status"] = "EXITED"
    admission["actual_exit_date"] = date_out(actual_exit_date)
    admission["exit_destination"] = exit_destination
    admission["settled_stay_cost_cents"] = calc.settled_stay_cost(
        derive.as_date(admission["entry_date"]), actual_exit_date,
        shelter["nightly_rate_cents"], shelter["weekend_surcharge_cents"],
        shelter["child_supplement_cents"], admission["minor_children_count"])
    touch(admission)
    derive.shelter_revenue(shelter)

    # link 2 - release the beds and re-derive the ledger and the roll-up
    derive.unit_ledger(unit)

    # links 3 and 4 - waitlist promotion and the promoted advocate's re-derivation
    cascade.promote_from_waitlist(unit)

    return ok(public(admission))


@bp.post("/shelter-admissions/<admission_id>/cancel")
def cancel_admission(admission_id):
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    cancel_reason = req_str(body, "cancel_reason", 1, 2000)
    admission = get_admission(admission_id)

    if admission["occupancy_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RESERVED admission may be cancelled")

    admission["occupancy_status"] = "CANCELLED"
    admission["cancel_reason"] = cancel_reason
    touch(admission)

    request_row = db.screening_requests.get(admission["screening_request_id"])
    if request_row is not None and request_row["status"] == "ADMITTED":
        request_row["status"] = "APPROVED"
        touch(request_row)

    derive.unit_ledger(db.shelter_units.get(admission["shelter_unit_id"]))
    return ok(public(admission))


@bp.post("/shelter-admissions/<admission_id>/report-location-compromise")
def report_compromise(admission_id):
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    compromise_source = req_enum(body, "compromise_source", COMPROMISE_SOURCES)
    admission = get_admission(admission_id)

    if admission["location_security_status"] != "SECURE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a SECURE placement may be reported as compromised")
    if admission["occupancy_status"] not in ("RESERVED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "an exited or cancelled placement has no location to protect")

    # link 1 - the compromise itself; no bed counter and no occupancy moves
    admission["location_security_status"] = "COMPROMISED"
    admission["compromise_source"] = compromise_source
    touch(admission)

    client = db.clients.get(admission["client_id"])
    if client is not None:
        touch(client)
    cascade.compromise_cascade(admission, client)
    return ok(public(admission))


@bp.post("/shelter-admissions/<admission_id>/complete-relocation")
def complete_relocation(admission_id):
    auth((ROLE_SHELTER_MANAGER,))
    body = get_body()
    new_unit_id = req_str(body, "new_shelter_unit_id")
    expected_version = req_int(body, "expected_shelter_unit_version", 0)
    admission = get_admission(admission_id)
    new_unit = get_unit(new_unit_id)

    destination_shelter = db.shelters.get(new_unit["shelter_id"])
    if destination_shelter is None:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH",
                       "the destination unit belongs to no shelter")

    if expected_version != new_unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")

    if admission["location_security_status"] != "COMPROMISED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a COMPROMISED placement may be relocated")
    if admission["occupancy_status"] not in ("RESERVED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "an exited or cancelled placement may not be relocated")

    request_row = db.screening_requests.get(admission["screening_request_id"])
    accessibility_required = bool(request_row and request_row["accessibility_required"])
    _fit_checks(new_unit, accessibility_required, admission["minor_children_count"])

    if new_unit["id"] == admission["shelter_unit_id"]:
        raise ApiError("ERR_SAME_UNIT_RELOCATION")

    if new_unit["available_beds"] < admission["household_size"]:
        raise ApiError("ERR_UNIT_CAPACITY_EXCEEDED")
    _capacity_check(new_unit, derive.as_date(admission["entry_date"]),
                    derive.as_date(admission["planned_exit_date"]),
                    admission["household_size"], admission["id"])

    old_unit = db.shelter_units.get(admission["shelter_unit_id"])
    admission["location_security_status"] = "RELOCATED"
    admission["prior_unit_id"] = admission["shelter_unit_id"]
    admission["shelter_unit_id"] = new_unit["id"]
    admission["shelter_id"] = new_unit["shelter_id"]
    touch(admission)

    derive.unit_ledger(old_unit)
    derive.unit_ledger(new_unit)
    client = db.clients.get(admission["client_id"])
    if client is not None:
        touch(client)
    derive.recompute_client_posture(client)
    return ok(public(admission))
