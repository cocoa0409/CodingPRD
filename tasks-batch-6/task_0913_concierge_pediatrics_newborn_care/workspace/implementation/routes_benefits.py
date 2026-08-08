"""Entitlement grants and consult bookings."""
from flask import Blueprint, g

import constants as C
import serialize
import svc_booking
import svc_entitlement
import svc_line
import validate as V
from auth import begin, parent_family_scope, require_membership_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch

bp = Blueprint("benefits", __name__)

GRANT_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_BILLING_SPECIALIST,
    C.ROLE_PARENT,
]
BOOKING_READ_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_PHYSICIAN,
    C.ROLE_BILLING_SPECIALIST,
    C.ROLE_PARENT,
]
BOOKING_WRITE_ROLES = [C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PARENT]


def _membership_family(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None


# =========================================================== EntitlementGrant
@bp.get("/peds/entitlement-grants")
def list_grants():
    begin(GRANT_ROLES)
    benefit_type = V.enum_filter("benefit_type", C.BENEFIT_TYPES)     # RUNG 4 p10
    status = V.enum_filter("status", C.GRANT_STATUSES)
    limit, offset = V.pagination()                                    # RUNG 4 p11
    membership_id = V.filter_value("membership_id")
    year_raw = V.filter_value("membership_year_index")
    year_index = None
    if year_raw is not None:
        try:
            year_index = int(year_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "membership_year_index must be an integer.")
    scope = parent_family_scope()

    rows = []
    for grant in db.grants.values():
        if membership_id is not None and grant["membership_id"] != membership_id:
            continue
        if benefit_type is not None and grant["benefit_type"] != benefit_type:
            continue
        if year_index is not None and grant["membership_year_index"] != year_index:
            continue
        if status is not None and grant["status"] != status:
            continue
        if scope is not None and _membership_family(grant["membership_id"]) != scope:
            continue
        rows.append(grant)
    return paginated(rows, serialize.grant_json, limit, offset)


@bp.get("/peds/entitlement-grants/<grant_id>")
def read_grant(grant_id):
    begin(GRANT_ROLES)
    grant = db.grants.get(grant_id)                                   # RUNG 3 p8
    if grant is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(grant["membership_id"]))  # RUNG 7 p19
    return object_response(serialize.grant_json(grant), 200)


# ============================================================= ConsultBooking
@bp.post("/peds/consult-bookings")
def create_booking():
    begin(BOOKING_WRITE_ROLES)                                        # RUNG 1, 2
    body = V.json_body()
    membership_id = V.req_string(body, "membership_id")               # RUNG 4 p9
    consult_type = V.req_string(body, "consult_type")
    consultant_physician_id = V.req_string(body, "consultant_physician_id")
    V.req_string(body, "scheduled_start")
    V.req_string(body, "scheduled_end")
    modality = V.req_string(body, "modality")
    patient_state_code = V.req_string(body, "patient_state_code")

    V.enum_member(consult_type, C.BENEFIT_TYPES, "consult_type")      # RUNG 4 p10
    V.enum_member(modality, C.MODALITIES, "modality")

    scheduled_start = V.req_datetime(body, "scheduled_start")         # RUNG 5 p12
    scheduled_end = V.req_datetime(body, "scheduled_end")
    V.date_range(                                                     # RUNG 5 p13
        scheduled_end > scheduled_start,
        "scheduled_end must be strictly after scheduled_start.",
    )

    consultant = db.physicians.get(consultant_physician_id)           # RUNG 6 p17
    if consultant is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND")
    membership = db.memberships.get(membership_id)                    # RUNG 6 p18
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")

    require_membership_owner(membership)                              # RUNG 7 p19

    if membership["status"] != "ACTIVE":                              # RUNG 10 p23
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")

    if modality == "TELEHEALTH":                                      # RUNG 13 p27
        if patient_state_code not in consultant["licensed_state_codes"]:
            raise ApiError("ERR_LICENSURE_NOT_COVERED")

    if svc_booking.has_schedule_conflict(                             # RUNG 14 p30
        consultant_physician_id, scheduled_start, scheduled_end
    ):
        raise ApiError("ERR_SCHEDULE_CONFLICT")

    plan = db.plans.get(membership["plan_id"])
    grant = svc_entitlement.select_or_create_grant(
        membership, plan, consult_type, scheduled_start.date()
    )
    coverage_route = svc_entitlement.hold_unit(grant)

    booking = new_row(
        db.bookings,
        {
            "membership_id": membership_id,
            "grant_id": grant["id"],
            "consultant_physician_id": consultant_physician_id,
            "consult_type": consult_type,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "modality": modality,
            "patient_state_code": patient_state_code,
            "coverage_route": coverage_route,
            "reschedule_count": 0,
            "status": "SCHEDULED",
        },
    )
    return object_response(serialize.booking_json(booking), 201)


@bp.get("/peds/consult-bookings")
def list_bookings():
    begin(BOOKING_READ_ROLES)
    status = V.enum_filter("status", C.BOOKING_STATUSES)              # RUNG 4 p10
    limit, offset = V.pagination()                                    # RUNG 4 p11
    membership_id = V.filter_value("membership_id")
    grant_id = V.filter_value("grant_id")
    consultant_physician_id = V.filter_value("consultant_physician_id")
    scope = parent_family_scope()

    rows = []
    for booking in db.bookings.values():
        if membership_id is not None and booking["membership_id"] != membership_id:
            continue
        if grant_id is not None and booking["grant_id"] != grant_id:
            continue
        if (
            consultant_physician_id is not None
            and booking["consultant_physician_id"] != consultant_physician_id
        ):
            continue
        if status is not None and booking["status"] != status:
            continue
        if scope is not None and _membership_family(booking["membership_id"]) != scope:
            continue
        rows.append(booking)
    return paginated(rows, serialize.booking_json, limit, offset)


@bp.get("/peds/consult-bookings/<booking_id>")
def read_booking(booking_id):
    begin(BOOKING_READ_ROLES)
    booking = db.bookings.get(booking_id)                             # RUNG 3 p8
    if booking is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(booking["membership_id"]))  # RUNG 7 p19
    return object_response(serialize.booking_json(booking), 200)


@bp.post("/peds/consult-bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    begin(BOOKING_WRITE_ROLES)
    booking = db.bookings.get(booking_id)                             # RUNG 3 p8
    if booking is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    body = V.json_body()
    V.req_string(body, "scheduled_start")                             # RUNG 4 p9
    V.req_string(body, "scheduled_end")
    scheduled_start = V.req_datetime(body, "scheduled_start")         # RUNG 5 p12
    scheduled_end = V.req_datetime(body, "scheduled_end")
    V.date_range(                                                     # RUNG 5 p13
        scheduled_end > scheduled_start,
        "scheduled_end must be strictly after scheduled_start.",
    )

    membership = db.memberships.get(booking["membership_id"])
    require_membership_owner(membership)                              # RUNG 7 p19

    if booking["status"] != "SCHEDULED":                              # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED booking can be rescheduled.")
    if membership is None or membership["status"] != "ACTIVE":        # RUNG 10 p23
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")

    if svc_booking.has_schedule_conflict(                             # RUNG 14 p30
        booking["consultant_physician_id"],
        scheduled_start,
        scheduled_end,
        exclude_booking_id=booking["id"],
    ):
        raise ApiError("ERR_SCHEDULE_CONFLICT")

    if booking["reschedule_count"] >= C.MAX_CONSULT_RESCHEDULES:      # RUNG 17 p35
        raise ApiError("ERR_RESCHEDULE_LIMIT_REACHED")

    booking["scheduled_start"] = scheduled_start
    booking["scheduled_end"] = scheduled_end
    booking["reschedule_count"] += 1
    touch(booking, g.touched)  # no entitlement counter moves on a reschedule
    return object_response(serialize.booking_json(booking), 200)


@bp.post("/peds/consult-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    begin([C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PHYSICIAN])
    booking = db.bookings.get(booking_id)                             # RUNG 3 p8
    if booking is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    if booking["status"] != "SCHEDULED":                              # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED booking can be completed.")
    if booking["scheduled_end"] > db.now():                           # RUNG 10 p22
        raise ApiError(
            "ERR_INVALID_STATE", "A consult cannot be completed before it has finished."
        )

    booking["status"] = "COMPLETED"
    touch(booking, g.touched)

    grant = db.grants.get(booking["grant_id"])
    if grant is not None:
        svc_entitlement.consume_unit(grant, booking["coverage_route"])

    membership = db.memberships.get(booking["membership_id"])
    plan = db.plans.get(membership["plan_id"]) if membership else None
    if booking["coverage_route"] == "ENTITLEMENT":
        billed = 0
    else:
        billed = plan["overage_consult_fee_cents"] if plan else 0
    svc_line.create_service_line(
        membership,
        booking["consult_type"],
        billed,
        plan,
        g.user_id,
        consult_booking_id=booking["id"],
        booking=booking,
    )
    return object_response(serialize.booking_json(booking), 200)


@bp.post("/peds/consult-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    begin(BOOKING_WRITE_ROLES)
    booking = db.bookings.get(booking_id)                             # RUNG 3 p8
    if booking is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(booking["membership_id"]))  # RUNG 7 p19
    if booking["status"] != "SCHEDULED":                              # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED booking can be cancelled.")

    svc_booking.cancel_booking(booking)  # CASCADE C; no ServiceLine is created
    return object_response(serialize.booking_json(booking), 200)
