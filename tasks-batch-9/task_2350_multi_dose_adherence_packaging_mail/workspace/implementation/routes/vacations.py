"""Travel early-supply exceptions: requesting and deciding."""

from flask import Blueprint

import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("vacations", __name__)


@bp.post("/vacation-exceptions")
def create_request():
    user_id, role = middleware.authenticate(("Patient", "PharmacyOperations"))
    body = validators.json_body()
    patient_id = validators.string(body, "patient_id")
    travel_start_date = validators.date_field(body, "travel_start_date")
    travel_end_date = validators.date_field(body, "travel_end_date")
    requested_extra_days = validators.integer(
        body, "requested_extra_days", minimum=1, maximum=30
    )
    if travel_start_date > travel_end_date:
        raise validators.bad("Field 'travel_start_date' must not be after the end date.")

    patient = middleware.lookup("patient", patient_id)
    middleware.enforce_patient_id_scope(role, user_id, patient_id)

    inclusive_days = store.day_diff(travel_end_date, travel_start_date) + 1
    if travel_start_date < clock.today() or inclusive_days < requested_extra_days:
        raise ApiError("ERR_VACATION_WINDOW_INVALID")

    plan = engine.plan_of(patient)
    if patient["vacation_exceptions_used_this_year"] >= plan["vacation_overrides_per_year"]:
        raise ApiError("ERR_VACATION_LIMIT_EXCEEDED")

    request_row = store.create(
        db.vacation_exceptions,
        {
            "patient_id": patient_id,
            "travel_start_date": store.fmt_date(travel_start_date),
            "travel_end_date": store.fmt_date(travel_end_date),
            "requested_extra_days": requested_extra_days,
            "status": "SUBMITTED",
            "approved_extra_days": None,
            "waives_refill_too_soon": False,
            "denial_reason": None,
            "decided_by_user_id": None,
            "decided_at": None,
        },
    )
    return response.object_response(store.serialize(request_row), 201)


@bp.post("/vacation-exceptions/<request_id>/decide")
def decide(request_id):
    user_id, _role = middleware.authenticate(("VerifyingPharmacist",))
    body = validators.json_body()
    decision = validators.enum(body, "decision", enums.VACATION_DECISIONS)
    approved_extra_days = validators.integer(
        body, "approved_extra_days", required=False, default=None
    )
    denial_reason = validators.string(body, "denial_reason", required=False, default=None)

    request_row = middleware.lookup("vacation_exception", request_id)

    if request_row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_VACATION_STATE")

    patient = db.patients[request_row["patient_id"]]
    approving = decision in ("APPROVE_PHARMACIST", "APPROVE_PAYER_OVERRIDE")

    if approving:
        for prescription in engine.prescriptions_of_patient(patient["id"]):
            if prescription["status"] == "ACTIVE" and prescription["is_controlled"]:
                raise ApiError("ERR_CONTROLLED_SUBSTANCE_NO_OVERRIDE")
    if decision == "APPROVE_PAYER_OVERRIDE":
        if not engine.plan_of(patient)["allows_payer_vacation_override"]:
            raise ApiError("ERR_PAYER_OVERRIDE_NOT_ALLOWED")
    if approving:
        if (
            approved_extra_days is None
            or approved_extra_days < 1
            or approved_extra_days > request_row["requested_extra_days"]
        ):
            raise ApiError("ERR_INVALID_APPROVED_DAYS")
    elif denial_reason is None:
        raise ApiError("ERR_INVALID_APPROVED_DAYS")

    if decision == "APPROVE_PHARMACIST":
        request_row["status"] = "PHARMACIST_APPROVED"
        request_row["approved_extra_days"] = approved_extra_days
    elif decision == "APPROVE_PAYER_OVERRIDE":
        request_row["status"] = "PAYER_OVERRIDE_APPROVED"
        request_row["approved_extra_days"] = approved_extra_days
        request_row["waives_refill_too_soon"] = True
    else:
        request_row["status"] = "DENIED"
        request_row["denial_reason"] = denial_reason

    request_row["decided_by_user_id"] = user_id
    request_row["decided_at"] = clock.now_iso()
    store.touch(request_row)

    if approving:
        patient["vacation_exceptions_used_this_year"] += 1
        store.touch(patient)

    store.commit()
    return response.object_response(store.serialize(request_row))
