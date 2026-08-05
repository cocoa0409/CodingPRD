"""Well visits and the immunization record."""
from flask import Blueprint, g

import calc
import constants as C
import serialize
import svc_immunization
import svc_line
import validate as V
from auth import (
    begin,
    parent_family_scope,
    require_child_owner,
    require_membership_owner,
    require_physician_clinical_owner,
)
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch

bp = Blueprint("clinical", __name__)

WELL_VISIT_READ_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_PHYSICIAN,
    C.ROLE_PARENT,
]
DOSE_READ_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_PHYSICIAN,
    C.ROLE_PARENT,
]


def _membership_family(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None


# ================================================================= WellVisit
@bp.get("/peds/well-visits")
def list_well_visits():
    begin(WELL_VISIT_READ_ROLES)
    milestone_code = V.enum_filter("milestone_code", C.MILESTONE_CODES)   # RUNG 4 p10
    status = V.enum_filter("status", C.WELL_VISIT_STATUSES)
    limit, offset = V.pagination()                                        # RUNG 4 p11
    membership_id = V.filter_value("membership_id")
    child_id = V.filter_value("child_id")
    scope = parent_family_scope()

    rows = []
    for visit in db.well_visits.values():
        if membership_id is not None and visit["membership_id"] != membership_id:
            continue
        if child_id is not None and visit["child_id"] != child_id:
            continue
        if milestone_code is not None and visit["milestone_code"] != milestone_code:
            continue
        if status is not None and visit["status"] != status:
            continue
        if scope is not None and _membership_family(visit["membership_id"]) != scope:
            continue
        rows.append(visit)
    return paginated(rows, serialize.well_visit_json, limit, offset)


@bp.get("/peds/well-visits/<well_visit_id>")
def read_well_visit(well_visit_id):
    begin(WELL_VISIT_READ_ROLES)
    visit = db.well_visits.get(well_visit_id)                             # RUNG 3 p8
    if visit is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(visit["membership_id"]))  # RUNG 7 p19
    return object_response(serialize.well_visit_json(visit), 200)


@bp.post("/peds/well-visits/<well_visit_id>/schedule")
def schedule_well_visit(well_visit_id):
    begin([C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN])
    visit = db.well_visits.get(well_visit_id)                             # RUNG 3 p8
    if visit is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    body = V.json_body()
    V.req_string(body, "scheduled_date")                                  # RUNG 4 p9
    scheduled_date = V.req_date(body, "scheduled_date")                   # RUNG 5 p12
    V.date_range(                                                         # RUNG 5 p13
        scheduled_date >= db.today(), "scheduled_date may not be earlier than today."
    )

    if visit["status"] != "DUE":                                          # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a DUE well visit can be scheduled.")
    membership = db.memberships.get(visit["membership_id"])
    if membership is None or membership["status"] not in ("PENDING_ACTIVATION", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The owning membership must be PENDING_ACTIVATION or ACTIVE.",
        )

    visit["status"] = "SCHEDULED"
    visit["scheduled_date"] = scheduled_date
    touch(visit, g.touched)
    return object_response(serialize.well_visit_json(visit), 200)


@bp.post("/peds/well-visits/<well_visit_id>/complete")
def complete_well_visit(well_visit_id):
    begin([C.ROLE_PHYSICIAN, C.ROLE_PRACTICE_ADMIN])
    visit = db.well_visits.get(well_visit_id)                             # RUNG 3 p8
    if visit is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    body = V.json_body()
    V.req_string(body, "completed_date")                                  # RUNG 4 p9
    completed_date = V.req_date(body, "completed_date")                   # RUNG 5 p12

    membership = db.memberships.get(visit["membership_id"])
    require_physician_clinical_owner(membership)                          # RUNG 7 p19

    if visit["status"] not in ("DUE", "SCHEDULED"):                       # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "The well visit is not open for completion.")
    if membership is None or membership["status"] != "ACTIVE":            # RUNG 10 p23
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    if completed_date > db.today():                                       # RUNG 13 p29
        raise ApiError("ERR_FUTURE_DATED", "completed_date may not be after today.")

    visit["status"] = "COMPLETED"
    visit["completed_date"] = completed_date
    visit["punctuality"] = calc.well_visit_punctuality(
        completed_date, visit["window_open_date"], visit["window_close_date"]
    )
    touch(visit, g.touched)

    plan = db.plans.get(membership["plan_id"])
    svc_line.create_service_line(
        membership,
        "WELL_VISIT",
        C.SERVICE_BILLED_AMOUNT_CENTS["WELL_VISIT"],
        plan,
        g.user_id,
        well_visit_id=visit["id"],
    )
    return object_response(serialize.well_visit_json(visit), 200)


# ========================================================== ImmunizationDose
@bp.post("/peds/immunization-doses")
def create_dose():
    begin([C.ROLE_PHYSICIAN, C.ROLE_PRACTICE_ADMIN])
    body = V.json_body()
    child_id = V.req_string(body, "child_id")                             # RUNG 4 p9
    vaccine_code = V.req_string(body, "vaccine_code")
    V.req_string(body, "administered_date")
    V.enum_member(vaccine_code, C.VACCINE_CODES, "vaccine_code")          # RUNG 4 p10
    administered_date = V.req_date(body, "administered_date")             # RUNG 5 p12

    child = db.children.get(child_id)                                     # RUNG 6 p15
    if child is None:
        raise ApiError("ERR_CHILD_NOT_FOUND")

    # RUNG 7 never applies here: a dose belongs to a child, not to a panel.

    if administered_date > db.today():                                    # RUNG 13 p29
        raise ApiError("ERR_FUTURE_DATED", "administered_date may not be after today.")

    dose = new_row(
        db.doses,
        {
            "child_id": child_id,
            "prior_valid_dose_id": None,
            "vaccine_code": vaccine_code,
            "administered_date": administered_date,
            "age_days_at_administration": 0,
            "effective_series_index": 1,
            "interval_days_since_prior": None,
            "manually_invalidated": False,
            "invalidation_reason_note": None,
            "invalid_reason": None,
            "validity": "VALID",
        },
    )
    svc_immunization.reevaluate_series(child, vaccine_code)
    return object_response(serialize.dose_json(dose), 201)


@bp.get("/peds/immunization-doses")
def list_doses():
    begin(DOSE_READ_ROLES)
    vaccine_code = V.enum_filter("vaccine_code", C.VACCINE_CODES)         # RUNG 4 p10
    validity = V.enum_filter("validity", C.VALIDITY_VALUES)
    limit, offset = V.pagination()                                        # RUNG 4 p11
    child_id = V.filter_value("child_id")
    prior_valid_dose_id = V.filter_value("prior_valid_dose_id")
    scope = parent_family_scope()

    rows = []
    for dose in db.doses.values():
        if child_id is not None and dose["child_id"] != child_id:
            continue
        if vaccine_code is not None and dose["vaccine_code"] != vaccine_code:
            continue
        if validity is not None and dose["validity"] != validity:
            continue
        if (
            prior_valid_dose_id is not None
            and dose["prior_valid_dose_id"] != prior_valid_dose_id
        ):
            continue
        if scope is not None:
            child = db.children.get(dose["child_id"])
            if child is None or child["family_id"] != scope:
                continue
        rows.append(dose)
    return paginated(rows, serialize.dose_json, limit, offset)


@bp.get("/peds/immunization-doses/<dose_id>")
def read_dose(dose_id):
    begin(DOSE_READ_ROLES)
    dose = db.doses.get(dose_id)                                          # RUNG 3 p8
    if dose is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    child = db.children.get(dose["child_id"])
    if child is not None:
        require_child_owner(child)                                        # RUNG 7 p19
    return object_response(serialize.dose_json(dose), 200)


@bp.post("/peds/immunization-doses/<dose_id>/invalidate")
def invalidate_dose(dose_id):
    begin([C.ROLE_PHYSICIAN, C.ROLE_PRACTICE_ADMIN])
    dose = db.doses.get(dose_id)                                          # RUNG 3 p8
    if dose is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    body = V.json_body()
    reason = V.req_string(body, "reason")                                 # RUNG 4 p9

    # RUNG 7 never applies here either.

    if dose["validity"] != "VALID":                                       # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a VALID dose can be invalidated.")

    child = db.children.get(dose["child_id"])
    svc_immunization.invalidate_dose(dose, child, reason)  # CASCADE B
    return object_response(serialize.dose_json(dose), 200)
