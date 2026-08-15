"""Patients and the membership program."""

from datetime import timedelta

from flask import Blueprint

from core import (
    ERR_INVALID_STATE, ERR_REINSTATE_WINDOW_EXPIRED, db, fail, get_body,
    list_response, must_exist, now_dt, now_iso, ok_object, require_roles,
    stamp_new, touch, v_date, v_enum, v_num, v_str,
)
from serialize import ser_membership, ser_patient

bp = Blueprint("patients", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

MEMBERSHIP_TIERS = {"STANDARD", "FAMILY"}
MEMBERSHIP_STATUSES = {"ACTIVE", "LAPSED", "TERMINATED"}


@bp.route("/air-ambulance/patients", methods=["POST"])
def create_patient():
    require_roles("Dispatcher")
    body = get_body()
    dob_raw, _ = v_date(body, "date_of_birth")
    rec = stamp_new({
        "full_name": v_str(body, "full_name"),
        "date_of_birth": dob_raw,
        "weight_kg": v_num(body, "weight_kg", minimum=0, exclusive_min=True),
    })
    db.patients[rec["id"]] = rec
    return ok_object(ser_patient(rec), 201)


@bp.route("/air-ambulance/patients/<rid>", methods=["GET"])
def get_patient(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.patients, rid, "Patient")
    return ok_object(ser_patient(rec))


@bp.route("/air-ambulance/memberships", methods=["POST"])
def create_membership():
    require_roles("BillingSpecialist")
    body = get_body()
    if "patient_id" in body and body["patient_id"] is not None:
        must_exist(db.patients, body["patient_id"], "Patient")
    eff_raw, _ = v_date(body, "effective_from")
    rec = stamp_new({
        "patient_id": v_str(body, "patient_id"),
        "tier": v_enum(body, "tier", MEMBERSHIP_TIERS),
        "effective_from": eff_raw,
        "status": "ACTIVE",
        "lapsed_at": None,
        "_lapsed_dt": None,
    })
    db.memberships[rec["id"]] = rec
    return ok_object(ser_membership(rec), 201)


@bp.route("/air-ambulance/memberships/<rid>", methods=["GET"])
def get_membership(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.memberships, rid, "MembershipSubscription")
    return ok_object(ser_membership(rec))


@bp.route("/air-ambulance/memberships", methods=["GET"])
def list_memberships():
    require_roles(*ALL_ROLES)
    return list_response(
        db.memberships.values(), ser_membership,
        {"patient_id": "patient_id", "status": "status"},
    )


@bp.route("/air-ambulance/memberships/<rid>", methods=["PUT"])
def update_membership(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.memberships, rid, "MembershipSubscription")
    body = get_body()
    target = v_enum(body, "status", MEMBERSHIP_STATUSES)
    current = rec["status"]
    if target == "LAPSED":
        if current != "ACTIVE":
            fail(ERR_INVALID_STATE, 409,
                 "Membership status %s cannot transition to LAPSED" % current)
        rec["status"] = "LAPSED"
        rec["lapsed_at"] = now_iso()
        rec["_lapsed_dt"] = now_dt()
    elif target == "ACTIVE":
        if current != "LAPSED":
            fail(ERR_INVALID_STATE, 409,
                 "Membership status %s cannot transition to ACTIVE" % current)
        # Reinstatement window: 30 days after lapse, inclusive.
        if now_dt() > rec["_lapsed_dt"] + timedelta(days=30):
            fail(ERR_REINSTATE_WINDOW_EXPIRED, 422,
                 "Reinstatement is only permitted within 30 days of lapse")
        rec["status"] = "ACTIVE"
        rec["lapsed_at"] = None
        rec["_lapsed_dt"] = None
    else:  # TERMINATED
        if current not in {"ACTIVE", "LAPSED"}:
            fail(ERR_INVALID_STATE, 409,
                 "Membership status %s cannot transition to TERMINATED" % current)
        rec["status"] = "TERMINATED"
    touch(rec)
    return ok_object(ser_membership(rec))
