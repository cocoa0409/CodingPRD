"""Booking, custody termination and the two records-axis operations."""

from flask import Blueprint

import cascades
import serializers
import store
from constants import ADMISSION_TYPE, CUSTODY_LEVEL, MANNER
from envelope import created, ok
from errors import ApiError
from ladder import Ctx

bp = Blueprint("inmates", __name__)


@bp.post("/inmates")
def book_inmate():
    ctx = Ctx(roles=("IntakeOfficer",))
    ctx.require("booking_number", "full_name", "facility_code", "custody_level", "booked_at")
    ctx.check_type("booking_number", "nonempty_string")
    ctx.check_type("full_name", "string")
    ctx.check_type("facility_code", "string")
    ctx.check_type("booked_at", "datetime")
    ctx.check_type("prior_full_assessment_at", "datetime")
    ctx.check_type("scheduled_release_date", "datetime")
    ctx.enum("custody_level", CUSTODY_LEVEL)
    ctx.enum("admission_type", ADMISSION_TYPE)

    def unique_booking():
        number = ctx.body.get("booking_number")
        for row in store.inmates.values():
            if row["booking_number"] == number:
                raise ApiError("ERR_DUPLICATE_KEY", "booking_number is already in use")
    ctx.caps(unique_booking)
    ctx.run()

    row = store.base_row()
    row.update({
        "booking_number": ctx.body["booking_number"],
        "full_name": ctx.body["full_name"],
        "facility_code": ctx.body["facility_code"],
        "custody_level": ctx.body["custody_level"],
        "booked_at": ctx.dt_field("booked_at"),
        "admission_type": ctx.body.get("admission_type") or "NEW_BOOKING",
        "prior_full_assessment_at": ctx.dt_field("prior_full_assessment_at"),
        "scheduled_release_date": ctx.dt_field("scheduled_release_date"),
        "custody_status": "IN_CUSTODY",
        "records_state": "OPEN",
        "account_balance_cents": 0,
    })
    store.inmates[row["id"]] = row
    return created(serializers.inmate(row))


@bp.get("/inmates/<inmate_id>")
def read_inmate(inmate_id):
    ctx = Ctx(roles=("IntakeOfficer", "Nurse", "Provider", "HealthServicesAdmin",
                     "GrievanceCoordinator", "Inmate"))
    ctx.path_inmate(inmate_id)
    ctx.run()
    return ok(serializers.inmate(ctx.inmate))


@bp.post("/inmates/<inmate_id>/release")
def release_inmate(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.status_in(lambda: ctx.inmate, ("IN_CUSTODY",), field="custody_status")

    def finalized_plan():
        plans = [p for p in store.release_plans.values()
                 if p["inmate_id"] == inmate_id and p["status"] == "FINALIZED"]
        if not plans:
            raise ApiError("ERR_INVALID_STATE", "no FINALIZED release plan exists for this inmate")
    ctx.cross_state(finalized_plan)
    ctx.run()

    cascades.cascade_release(ctx.inmate)
    return ok(serializers.inmate(ctx.inmate))


@bp.post("/inmates/<inmate_id>/death-event")
def death_event(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.require("death_at", "manner")
    ctx.check_type("death_at", "datetime")
    ctx.enum("manner", MANNER)
    ctx.status_in(lambda: ctx.inmate, ("IN_CUSTODY",), field="custody_status")

    def no_prior_review():
        for row in store.mortality_reviews.values():
            if row["inmate_id"] == inmate_id:
                raise ApiError("ERR_INVALID_STATE",
                               "a mortality review already exists for this inmate")
    ctx.state(no_prior_review, sub=1)
    ctx.run()

    review = cascades.cascade_death(ctx.inmate, ctx.dt_field("death_at"), ctx.body["manner"])
    return created(serializers.mortality_review(review))


@bp.post("/inmates/<inmate_id>/records-freeze")
def records_freeze(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.status_in(lambda: ctx.inmate, ("OPEN",), field="records_state")
    ctx.run()

    ctx.inmate["records_state"] = "FROZEN"
    store.touch(ctx.inmate)
    return ok(serializers.inmate(ctx.inmate))


@bp.post("/inmates/<inmate_id>/records-unfreeze")
def records_unfreeze(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.status_in(lambda: ctx.inmate, ("FROZEN",), field="records_state")

    def not_deceased():
        if ctx.inmate["custody_status"] == "DECEASED":
            raise ApiError("ERR_INVALID_STATE",
                           "a death-induced records freeze is permanent")
    ctx.state(not_deceased, sub=1)
    ctx.run()

    ctx.inmate["records_state"] = "OPEN"
    store.touch(ctx.inmate)
    return ok(serializers.inmate(ctx.inmate))
