"""Referral intake / triage and appointments (PRD 3.2, 3.4)."""

from flask import Blueprint, g

from core import clock, db, gates
from core.auth import READ_ROLES, authenticate, authorize, require_owner
from core.constants import MODALITY_ENUM, PRIORITY_ENUM, SPECIES_ENUM, STUDY_KIND_ENUM
from core.errors import ApiError
from core.validate import body, enum_value, opt_id, opt_str, req_id, req_str
from routes.common import apply_filters, fk, listing, need, one
from services import cascades, derive, pricing

bp = Blueprint("intake", __name__)


# ==========================================================================
# Referral
# ==========================================================================

@bp.post("/referrals")
def create_referral():
    authenticate()
    authorize("ClinicUser")
    data = body()
    # rung 3 — a ClinicUser may only submit on behalf of their own clinic.  This
    # is a pure identity comparison and needs no lookup, so it runs before rung 4.
    raw_clinic = data.get("clinic_id")
    if isinstance(raw_clinic, str) and raw_clinic:
        require_owner(raw_clinic == g.user_id)
    # rung 4
    clinic = fk(data, "clinic_id", "clinics", "ERR_CLINIC_NOT_FOUND")
    # rung 5
    req_id(data, "clinic_id")
    patient_name = req_str(data, "patient_name")
    species = req_str(data, "species")
    study_kind = req_str(data, "study_kind")
    requested_modality = req_str(data, "requested_modality")
    priority = opt_str(data, "priority", "ROUTINE")
    clinical_history = opt_str(data, "clinical_history")
    # rung 6
    enum_value(species, SPECIES_ENUM, "species")
    enum_value(study_kind, STUDY_KIND_ENUM, "study_kind")
    enum_value(requested_modality, MODALITY_ENUM, "requested_modality")
    enum_value(priority, PRIORITY_ENUM, "priority")
    # rung 9 (G2)
    gates.g2_clinic_not_on_hold(clinic)
    # rung 15
    if clinic["status"] != "ACTIVE":
        raise ApiError("ERR_CLINIC_INACTIVE")

    rec = db.new_record()
    rec.update(
        {
            "clinic_id": clinic["id"],
            "patient_name": patient_name,
            "species": species,
            "study_kind": study_kind,
            "requested_modality": requested_modality,
            "priority": priority,
            "clinical_history": clinical_history,
            "status": "SUBMITTED",
            "return_reason": None,
            "reject_reason": None,
        }
    )
    db.insert("referrals", rec)
    return one("referrals", rec, 201)


@bp.get("/referrals/<referral_id>")
def get_referral(referral_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("referrals", need("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND"))


@bp.get("/referrals")
def list_referrals():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("referrals")
    rows = apply_filters(
        rows, {"clinic_id": "clinic_id", "status": "status", "study_kind": "study_kind"}
    )
    return listing("referrals", rows)


@bp.post("/referrals/<referral_id>/accept")
def accept_referral(referral_id):
    authenticate()
    authorize("Scheduler")
    referral = need("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND")
    clinic = db.get("clinics", referral["clinic_id"])
    # rung 15
    if clinic is None or clinic["status"] != "ACTIVE":
        raise ApiError("ERR_CLINIC_INACTIVE")
    # rung 18
    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    # Adjudication of friction 4: the missing-clinical_history precondition is
    # reported as ERR_REFERRAL_INVALID_STATE (rung 18, second limb), not as
    # ERR_VALIDATION (rung 5).  Chosen in reachability terms: the accept call
    # carries no body at all, so a rung-5 failure here would fire on a stored
    # field, and — because rung 5 sits below rungs 15 and 18 — it would pre-empt
    # ERR_CLINIC_INACTIVE and the wrong-from-state error for every history-less
    # referral, stranding both on this endpoint.  Placing it at rung 18 keeps
    # every rung between 5 and 18 reachable on /accept, and ERR_VALIDATION stays
    # amply reachable on the endpoints that actually take a body.
    if referral["clinical_history"] is None:
        raise ApiError(
            "ERR_REFERRAL_INVALID_STATE",
            "The referral has no clinical_history and may not be accepted.",
        )
    referral["status"] = "ACCEPTED"
    db.touch(referral)
    return one("referrals", referral)


@bp.post("/referrals/<referral_id>/reject")
def reject_referral(referral_id):
    authenticate()
    authorize("Scheduler")
    referral = need("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND")
    data = body()
    reason = req_str(data, "reject_reason")
    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    referral["status"] = "REJECTED"
    referral["reject_reason"] = reason
    db.touch(referral)
    return one("referrals", referral)


@bp.post("/referrals/<referral_id>/return")
def return_referral(referral_id):
    authenticate()
    authorize("Scheduler")
    referral = need("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND")
    data = body()
    reason = req_str(data, "return_reason")
    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    referral["status"] = "RETURNED"
    referral["return_reason"] = reason
    db.touch(referral)
    # No notification row is appended for a return (PRD 3.2).
    return one("referrals", referral)


@bp.post("/referrals/<referral_id>/resubmit")
def resubmit_referral(referral_id):
    authenticate()
    authorize("ClinicUser")
    referral = need("referrals", referral_id, "ERR_REFERRAL_NOT_FOUND")
    require_owner(g.user_id == referral["clinic_id"])
    data = body()
    history = req_str(data, "clinical_history")
    if referral["status"] != "RETURNED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    referral["clinical_history"] = history
    referral["return_reason"] = None
    referral["status"] = "SUBMITTED"
    db.touch(referral)
    return one("referrals", referral)


# ==========================================================================
# Appointment
# ==========================================================================

@bp.post("/appointments")
def create_appointment():
    authenticate()
    authorize("Scheduler")
    data = body()
    # rung 4 — body FKs in the endpoint's input order
    referral = fk(data, "referral_id", "referrals", "ERR_REFERRAL_NOT_FOUND")
    stop = fk(data, "route_stop_id", "route_stops", "ERR_STOP_NOT_FOUND")
    # rung 5
    req_id(data, "referral_id")
    stop_id_supplied = opt_id(data, "route_stop_id")
    clinic = db.get("clinics", referral["clinic_id"])
    # rung 9 (G2)
    gates.g2_clinic_not_on_hold(clinic)
    # rung 14
    if referral["study_kind"] == "MOBILE" and stop_id_supplied is None:
        raise ApiError("ERR_MOBILE_REQUIRES_ROUTE_STOP")
    if referral["study_kind"] == "TELERAD" and stop_id_supplied is not None:
        raise ApiError("ERR_TELERAD_HAS_NO_ROUTE_STOP")
    # rung 15
    if clinic is None or clinic["status"] != "ACTIVE":
        raise ApiError("ERR_CLINIC_INACTIVE")
    # rung 18
    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")

    rec = db.new_record()
    rec.update(
        {
            "referral_id": referral["id"],
            "route_stop_id": stop["id"] if stop is not None else None,
            "status": "SCHEDULED",
            "cancel_reason": None,
            "cancelled_at": None,
        }
    )
    db.insert("appointments", rec)
    referral["status"] = "SCHEDULED"
    db.touch(referral)
    return one("appointments", rec, 201)


@bp.get("/appointments/<appointment_id>")
def get_appointment(appointment_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "appointments", need("appointments", appointment_id, "ERR_APPOINTMENT_NOT_FOUND")
    )


@bp.get("/appointments")
def list_appointments():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("appointments")
    rows = apply_filters(
        rows,
        {
            "referral_id": "referral_id",
            "route_stop_id": "route_stop_id",
            "status": "status",
        },
    )
    return listing("appointments", rows)


@bp.post("/appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    authenticate()
    authorize("ClinicUser", "Scheduler")
    appt = need("appointments", appointment_id, "ERR_APPOINTMENT_NOT_FOUND")
    referral = derive.referral_of_appointment(appt)
    if g.role == "ClinicUser":
        require_owner(referral is not None and g.user_id == referral["clinic_id"])
    data = body()
    cancel_reason = req_str(data, "cancel_reason")
    if appt["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE")

    if g.role == "Scheduler":
        gates.g1_no_frozen_lines(
            [
                s["id"]
                for s in derive.studies_of_appointment(appt)
                if s["workflow_status"] == "ORDERED"
            ]
        )
        cascades.cancel_appointment_provider(appt, cancel_reason, notify_clinic=True)
        return one("appointments", appt)

    # ClinicUser -> CANCELLED_BY_CLINIC with per-study lead-time fees.
    ordered = [
        s for s in derive.studies_of_appointment(appt) if s["workflow_status"] == "ORDERED"
    ]
    fees = {s["id"]: pricing.cancellation_fee_cents(s, "CLINIC") for s in ordered}
    appt["status"] = "CANCELLED_BY_CLINIC"
    appt["cancel_reason"] = cancel_reason
    appt["cancelled_at"] = clock.now()
    db.touch(appt)
    for study in ordered:
        fee = fees[study["id"]]
        study["workflow_status"] = "NOT_PERFORMED"
        study["cancellation_fee_cents"] = fee
        study["cancel_reason"] = cancel_reason
        study["billing_status"] = "NON_BILLABLE" if fee == 0 else "UNBILLED"
        db.touch(study)
    # Adjudication of friction 1 (clinic limb): see services/cascades.py — the
    # surviving billable set is re-derived, which is a no-op because every study
    # removed here was ORDERED and ORDERED studies are never in the billable set.
    stop = derive.stop_of_appointment(appt)
    if stop is not None:
        pricing.reprice_stop_siblings(stop)
    return one("appointments", appt)


@bp.post("/appointments/<appointment_id>/no-show")
def no_show_appointment(appointment_id):
    authenticate()
    authorize("FieldTech")
    appt = need("appointments", appointment_id, "ERR_APPOINTMENT_NOT_FOUND")
    stop = derive.stop_of_appointment(appt)
    route = derive.route_of_stop(stop)
    require_owner(route is not None and g.user_id == route["technician_id"])
    data = body()
    cancel_reason = opt_str(data, "cancel_reason")
    # rung 18 — both preconditions are enforced exactly as written.
    # Adjudication of friction 2: the appointment must be SCHEDULED AND its stop
    # must be ARRIVED, even though arriving moves that stop's SCHEDULED
    # appointments to IN_PROGRESS.  Chosen in reachability terms: keeping both
    # leaves the NO_SHOW terminal state reachable (book the appointment AFTER the
    # van has arrived — the stop is already ARRIVED and the new appointment is
    # created in SCHEDULED), whereas dropping either precondition would delete a
    # declared guard outright.  Both limbs report ERR_APPOINTMENT_INVALID_STATE:
    # rung 17 is declared to apply only to route and route-stop ACTION endpoints,
    # and this is an /appointments endpoint, so rung 18 is the only state rung
    # that reaches it.
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_INVALID_STATE")
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError(
            "ERR_APPOINTMENT_INVALID_STATE",
            "The appointment's route stop has not been arrived at.",
        )

    ordered = [
        s for s in derive.studies_of_appointment(appt) if s["workflow_status"] == "ORDERED"
    ]
    fees = {s["id"]: pricing.cancellation_fee_cents(s, "NO_SHOW") for s in ordered}
    appt["status"] = "NO_SHOW"
    if cancel_reason is not None:
        appt["cancel_reason"] = cancel_reason
    appt["cancelled_at"] = clock.now()
    db.touch(appt)
    for study in ordered:
        fee = fees[study["id"]]
        study["workflow_status"] = "NOT_PERFORMED"
        study["cancellation_fee_cents"] = fee
        if cancel_reason is not None:
            study["cancel_reason"] = cancel_reason
        study["billing_status"] = "NON_BILLABLE" if fee == 0 else "UNBILLED"
        db.touch(study)
    pricing.reprice_stop_siblings(stop)
    return one("appointments", appt)
