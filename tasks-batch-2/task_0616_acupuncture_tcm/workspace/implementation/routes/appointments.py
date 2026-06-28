"""Appointment routes (PRD 3.5, 3.6) — booking, add-ons, lifecycle transitions.

Also serves the read-only AddOn / Charge / Superbill list+get endpoints.
"""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    parse_iso8601,
    public,
    require_fields,
    require_int_min,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import (
    get_appointment,
    get_or_404,
    get_package,
    get_patient,
    get_plan,
    get_practitioner,
    get_room,
)
from middleware import get_auth, require_role
from response import success
from services import appointment as appt_svc
from services.package import reconcile_series

bp = Blueprint("appointments", __name__)

CHARGE_SOURCES = ("PER_VISIT", "PACKAGE")
MODALITIES = ("CUPPING", "MOXA")


# ==========================================================================
# Booking
# ==========================================================================
@bp.route("/appointments", methods=["POST"])
def book_appointment():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "treatment_plan_id",
            "practitioner_id",
            "room_id",
            "scheduled_start",
            "scheduled_end",
            "base_fee_cents",
            "expected_treatment_plan_version",
        ],
    )

    # ---- Priority 5: body FK existence (left to right). ----
    patient = get_patient(body["patient_id"])
    plan = get_plan(body["treatment_plan_id"])
    practitioner = get_practitioner(body["practitioner_id"])
    room = get_room(body["room_id"])

    charge_source = body.get("charge_source", "PER_VISIT")
    if charge_source is None:
        charge_source = "PER_VISIT"
    if charge_source not in CHARGE_SOURCES:
        raise err("ERR_INVALID_REQUEST", "charge_source must be PER_VISIT or PACKAGE.")

    series = None
    if charge_source == "PACKAGE":
        if not body.get("package_series_id"):
            raise err("ERR_INVALID_REQUEST", "package_series_id required for PACKAGE.")
        series = get_package(body["package_series_id"])

    # ---- Priority 6: well-formedness of the body. ----
    start = parse_iso8601(body["scheduled_start"])
    end = parse_iso8601(body["scheduled_end"])
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_start/scheduled_end must be ISO 8601.")
    if not (end > start):
        raise err("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start.")
    base_fee_cents = require_int_min(body, "base_fee_cents", 0)
    expected = body.get("expected_treatment_plan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_treatment_plan_version must be an integer.")

    # ---- Priority 8: referenced plan must be ACTIVE. ----
    if plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Booking requires the plan to be ACTIVE.")

    # ---- Priority 9: patient intake complete. ----
    if patient["intake_status"] != "INTAKE_COMPLETE":
        raise err("ERR_INTAKE_REQUIRED", "Booking requires Patient.intake_status == INTAKE_COMPLETE.")

    # ---- Priority 12: room temporal availability. ----
    _check_room_conflict(room, start, end)
    # ---- Priority 13: practitioner temporal availability. ----
    _check_practitioner_conflict(practitioner, start, end)

    # ---- Priority 14: package fiscal check. ----
    if charge_source == "PACKAGE":
        if series["status"] == "CANCELLED" or series["provisional_remaining_credits"] < 1:
            raise err(
                "ERR_NO_CREDITS_REMAINING",
                "Booking requires provisional_remaining_credits >= 1 and series not CANCELLED.",
            )

    # ---- Priority 15: OCC on plan version. ----
    if expected != plan["version"]:
        raise err("ERR_STALE_VERSION", "expected_treatment_plan_version does not match.")

    # ---- Commit. ----
    rec = {
        "patient_id": patient["id"],
        "treatment_plan_id": plan["id"],
        "practitioner_id": practitioner["id"],
        "room_id": room["id"],
        "package_series_id": series["id"] if series is not None else None,
        "charge_source": charge_source,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "base_fee_cents": base_fee_cents,
        "checked_in_at": None,
        "arrival_class": "PENDING",
        "clinical_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    }
    stamp_new(rec)
    db.appointments[rec["id"]] = rec

    # Plan version increments by one on a successful booking.
    touch(plan)

    # PACKAGE: reserve a credit (reconcile recomputes + bumps series version).
    if charge_source == "PACKAGE":
        reconcile_series(series)

    return success(public(rec), status=201)


def _non_terminal_appts():
    return [
        a
        for a in db.appointments.values()
        if a["clinical_status"] in ("SCHEDULED", "CHECKED_IN")
    ]


def _check_room_conflict(room, new_start, new_end):
    cleanup = room.get("cleanup_buffer_minutes", 0) * 60
    for a in _non_terminal_appts():
        if a["room_id"] != room["id"]:
            continue
        ex_start = parse_iso8601(a["scheduled_start"])
        ex_end = parse_iso8601(a["scheduled_end"])
        room_end = ex_end.timestamp() + cleanup
        # [new_start, new_end) intersects [ex_start, ex_end + cleanup)
        if new_start.timestamp() < room_end and ex_start.timestamp() < new_end.timestamp():
            raise err("ERR_ROOM_CONFLICT", "Room interval overlap.")


def _check_practitioner_conflict(practitioner, new_start, new_end):
    buffer = practitioner.get("turnover_buffer_minutes", 0) * 60
    ns = new_start.timestamp()
    ne = new_end.timestamp()
    for a in _non_terminal_appts():
        if a["practitioner_id"] != practitioner["id"]:
            continue
        es = parse_iso8601(a["scheduled_start"]).timestamp()
        ee = parse_iso8601(a["scheduled_end"]).timestamp()
        # conflict if new_start < existing_end + buffer AND existing_start < new_end + buffer
        if ns < ee + buffer and es < ne + buffer:
            raise err("ERR_PRACTITIONER_CONFLICT", "Practitioner gap below turnover buffer.")


# ==========================================================================
# Reads
# ==========================================================================
@bp.route("/appointments", methods=["GET"])
def list_appointments():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = list(db.appointments.values())
    if role == "Patient":
        items = [a for a in items if a["patient_id"] == user_id]
    else:
        pf = request.args.get("patient_id")
        if pf is not None:
            items = [a for a in items if a["patient_id"] == pf]
    for field in ("treatment_plan_id", "practitioner_id", "room_id", "package_series_id"):
        v = request.args.get(field)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/appointments/<rid>", methods=["GET"])
def get_appointment_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_appointment(rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own appointments.")
    return success(public(rec), status=200)


# ==========================================================================
# Add-on attach
# ==========================================================================
@bp.route("/appointments/<rid>/addons", methods=["POST"])
def attach_addon(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner"])
    appt = get_appointment(rid)
    body = get_json_body()
    require_fields(body, ["modality", "fee_cents"])
    modality = body.get("modality")
    if modality not in MODALITIES:
        raise err("ERR_INVALID_REQUEST", "modality must be CUPPING or MOXA.")
    fee_cents = require_int_min(body, "fee_cents", 0)
    rec = {
        "appointment_id": appt["id"],
        "modality": modality,
        "fee_cents": fee_cents,
        "status": "ATTACHED",
    }
    stamp_new(rec)
    db.addons[rec["id"]] = rec
    # Attaching an add-on increments the parent appointment's version.
    touch(appt)
    return success(public(rec), status=201)


# ==========================================================================
# Transitions
# ==========================================================================
@bp.route("/appointments/<rid>/check-in", methods=["POST"])
def check_in_appointment(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    appt = get_appointment(rid)
    if appt["clinical_status"] != "SCHEDULED":
        raise err("ERR_APPT_NOT_SCHEDULED", "Check-in requires clinical_status == SCHEDULED.")
    plan = db.treatment_plans.get(appt["treatment_plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Check-in requires the governing plan to be ACTIVE.")
    appt_svc.check_in(appt)
    return success(public(appt), status=200)


@bp.route("/appointments/<rid>/complete", methods=["POST"])
def complete_appointment(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    appt = get_appointment(rid)
    if appt["clinical_status"] != "CHECKED_IN":
        raise err("ERR_APPT_NOT_CHECKED_IN", "Complete requires clinical_status == CHECKED_IN.")
    patient = db.patients.get(appt["patient_id"])
    appt_svc.complete(appt, patient)
    return success(public(appt), status=200)


@bp.route("/appointments/<rid>/no-show", methods=["POST"])
def no_show_appointment(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    appt = get_appointment(rid)
    if appt["clinical_status"] != "SCHEDULED":
        raise err("ERR_APPT_NOT_SCHEDULED", "No-show requires clinical_status == SCHEDULED.")
    patient = db.patients.get(appt["patient_id"])
    appt_svc.no_show(appt, patient)
    return success(public(appt), status=200)


@bp.route("/appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment_route(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    appt = get_appointment(rid)
    if appt["clinical_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise err(
            "ERR_APPT_NOT_CANCELLABLE",
            "Cancel requires clinical_status IN {SCHEDULED, CHECKED_IN}.",
        )
    patient = db.patients.get(appt["patient_id"])
    appt_svc.cancel(appt, patient)
    return success(public(appt), status=200)


# ==========================================================================
# AddOn / Charge / Superbill reads (flat, filter by appointment_id)
# ==========================================================================
def _filter_by_appointment(collection_name):
    items = list(getattr(db, collection_name).values())
    af = request.args.get("appointment_id")
    if af is not None:
        items = [x for x in items if x["appointment_id"] == af]
    return items


def _patient_owns_appointment(user_id, appointment_id):
    appt = db.appointments.get(appointment_id)
    return appt is not None and appt["patient_id"] == user_id


@bp.route("/addons", methods=["GET"])
def list_addons():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = _filter_by_appointment("addons")
    if role == "Patient":
        items = [x for x in items if _patient_owns_appointment(user_id, x["appointment_id"])]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/addons/<rid>", methods=["GET"])
def get_addon_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_or_404("addons", rid)
    if role == "Patient" and not _patient_owns_appointment(user_id, rec["appointment_id"]):
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own add-ons.")
    return success(public(rec), status=200)


@bp.route("/charges", methods=["GET"])
def list_charges():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = _filter_by_appointment("charges")
    if role == "Patient":
        items = [x for x in items if _patient_owns_appointment(user_id, x["appointment_id"])]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/charges/<rid>", methods=["GET"])
def get_charge_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_or_404("charges", rid)
    if role == "Patient" and not _patient_owns_appointment(user_id, rec["appointment_id"]):
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own charges.")
    return success(public(rec), status=200)


@bp.route("/superbills", methods=["GET"])
def list_superbills():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = _filter_by_appointment("superbills")
    if role == "Patient":
        items = [x for x in items if _patient_owns_appointment(user_id, x["appointment_id"])]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/superbills/<rid>", methods=["GET"])
def get_superbill_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_or_404("superbills", rid)
    if role == "Patient" and not _patient_owns_appointment(user_id, rec["appointment_id"]):
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own superbills.")
    return success(public(rec), status=200)
