"""ProcedureBooking endpoints: CRUD, the parallel booking/prep axes, and all
day-of-procedure actions (PRD 3.2, 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BOOKING_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_PROCEDURE_TYPE_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
    ERR_SCOPE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_BOOKING_VERSION,
    ERR_BOOKING_NOT_SCHEDULED,
    ERR_BOOKING_NOT_CHECKED_IN,
    ERR_BOOKING_NOT_IN_PROGRESS,
    ERR_BOOKING_NOT_CANCELLABLE,
    ERR_PREP_NOT_CONFIRMED,
    ERR_PREP_ALREADY_ASSESSED,
    ERR_PREP_NOT_ASSESSED,
    ERR_PREP_NOT_INADEQUATE,
    ERR_PROVIDER_OWNERSHIP_MISMATCH,
    ERR_PROVIDER_SUSPENDED,
    ERR_ROOM_NOT_IN_SERVICE,
    ERR_ANESTHESIA_NOT_CONFIRMED,
    ERR_SCOPE_NOT_AVAILABLE,
    ERR_SCOPE_STORAGE_EXPIRED,
    ERR_NO_COMPATIBLE_SCOPE,
    ERR_SCOPE_TYPE_MISMATCH,
    ERR_CHECKIN_WINDOW_CLOSED,
    ERR_NO_SHOW_WINDOW_NOT_REACHED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, get_pagination
from services.booking_svc import (
    PREP_LEAD_HOURS,
    compute_window,
    check_temporal_gates,
    check_room_overlap_and_capacity,
    cancel_active_assignments,
    complete_confirmed_assignments,
    release_scope_after_procedure,
    compute_actual_duration_minutes,
)
from services.core import (
    new_record,
    public,
    scope_is_storage_current,
    scope_use_count,
    sort_key,
    touch,
)
from response import success_list
from middleware import ALL_READ_ROLES
from util import now, parse_date
from validate import (
    get_body,
    opt_enum,
    opt_str,
    opt_nullable_str,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_path_resource,
    resolve_ref,
)

bp = Blueprint("bookings", __name__)

INDICATIONS = {"SCREENING", "SURVEILLANCE", "DIAGNOSTIC"}
ANESTHESIA_TYPES = {"NONE", "MAC", "GENERAL"}

CHECK_IN_EARLY_MIN = 60
CHECK_IN_LATE_MIN = 30
NO_SHOW_GRACE_MIN = 30


def _fresh_booking_fields(patient_id, provider_id, procedure_type_id, room_id,
                          indication, anesthesia_type, notes, scheduled_start,
                          procedure_minutes, scheduled_end, room_block_end,
                          rescheduled_from_id=None):
    return {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "procedure_type_id": procedure_type_id,
        "room_id": room_id,
        "indication": indication,
        "anesthesia_type": anesthesia_type,
        "notes": notes,
        "scheduled_start": scheduled_start,
        "procedure_minutes": procedure_minutes,
        "scheduled_end": scheduled_end,
        "room_block_end": room_block_end,
        "status": "SCHEDULED",
        "prep_status": "PREP_PENDING",
        "bbps_left": None,
        "bbps_right": None,
        "bbps_transverse": None,
        "actual_start": None,
        "actual_end": None,
        "actual_duration_minutes": None,
        "cecum_intubated": None,
        "withdrawal_time_seconds": None,
        "adenomas_detected": None,
        "notification_flag": False,
        "rescheduled_from_id": rescheduled_from_id,
        "cancel_reason": None,
    }


@bp.post("/endoscopy/bookings")
def create_booking():
    authorized(["SchedulingCoordinator"])
    body = get_body()
    # Rung 3 (existence): body FK references resolve first, in declared order.
    patient = resolve_ref("patients", body.get("patient_id"), ERR_PATIENT_NOT_FOUND)
    provider = resolve_ref("providers", body.get("provider_id"), ERR_PROVIDER_NOT_FOUND)
    procedure_type = resolve_ref("procedure_types", body.get("procedure_type_id"), ERR_PROCEDURE_TYPE_NOT_FOUND)
    room = resolve_ref("rooms", body.get("room_id"), ERR_ROOM_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "patient_id")
    req_str(body, "provider_id")
    req_str(body, "procedure_type_id")
    req_str(body, "room_id")
    scheduled_start = req_datetime(body, "scheduled_start")
    indication = req_enum(body, "indication", INDICATIONS)
    anesthesia_type = req_enum(body, "anesthesia_type", ANESTHESIA_TYPES)
    notes = opt_nullable_str(body, "notes", None)
    # Rung 8 (compliance): provider must be ACTIVE.
    if provider["credential_status"] != "ACTIVE":
        raise_error(ERR_PROVIDER_SUSPENDED, "provider credential_status is SUSPENDED")
    # Rung 9 (temporal): strictly-future start, then prep lead time.
    check_temporal_gates(procedure_type, scheduled_start)
    # Window computation (needs the validated inputs).
    procedure_minutes, scheduled_end, room_block_end = compute_window(
        patient, procedure_type, room, scheduled_start, anesthesia_type)
    # Rung 10 (constraint): overlap, then day capacity, then room in service.
    check_room_overlap_and_capacity(room, scheduled_start, room_block_end)
    if room["status"] != "ACTIVE":
        raise_error(ERR_ROOM_NOT_IN_SERVICE, "room is OUT_OF_SERVICE")
    rec = new_record("bookings", _fresh_booking_fields(
        patient["id"], provider["id"], procedure_type["id"], room["id"],
        indication, anesthesia_type, notes, scheduled_start,
        procedure_minutes, scheduled_end, room_block_end))
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/bookings")
def list_bookings():
    authorized(ALL_READ_ROLES)
    items = list(db["bookings"].values())
    for field in ("patient_id", "provider_id", "room_id", "procedure_type_id",
                  "rescheduled_from_id", "status", "prep_status"):
        value = request.args.get(field)
        if value is not None:
            items = [b for b in items if b.get(field) == value]
    date_raw = request.args.get("date")
    if date_raw is not None and date_raw != "":
        day = parse_date(date_raw)
        if day is None:
            raise_error(ERR_INVALID_REQUEST, "date must be YYYY-MM-DD")
        items = [b for b in items if b["scheduled_start"].date() == day]
    items.sort(key=sort_key)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(b) for b in page], total, limit, offset)


@bp.get("/endoscopy/bookings/<rid>")
def get_booking(rid):
    return get_one("bookings", rid, ERR_BOOKING_NOT_FOUND)


@bp.patch("/endoscopy/bookings/<rid>")
def patch_booking(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    # Rung 4 (schema)
    expected_booking_version = req_int(body, "expected_booking_version")
    anesthesia_type = opt_enum(body, "anesthesia_type", ANESTHESIA_TYPES, None)
    notes_present = "notes" in body
    notes = opt_nullable_str(body, "notes", None)
    # Rung 5 (OCC)
    if expected_booking_version != booking["version"]:
        raise_error(ERR_STALE_BOOKING_VERSION,
                    "expected_booking_version does not match the booking's current version")
    # Rung 7 (state): only a SCHEDULED booking may be amended.
    if booking["status"] != "SCHEDULED":
        raise_error(ERR_BOOKING_NOT_SCHEDULED, "only a SCHEDULED booking may be amended")
    if anesthesia_type is not None and anesthesia_type != booking["anesthesia_type"]:
        # Changing the anesthesia level recomputes the window and re-runs the
        # lead-time, overlap and day-capacity validations of PRD 3.2.
        patient = db["patients"].get(booking["patient_id"])
        procedure_type = db["procedure_types"].get(booking["procedure_type_id"])
        room = db["rooms"].get(booking["room_id"])
        minutes, scheduled_end, room_block_end = compute_window(
            patient, procedure_type, room, booking["scheduled_start"], anesthesia_type)
        current = now()
        lead = PREP_LEAD_HOURS[procedure_type["prep_protocol"]]
        if booking["scheduled_start"] < current + timedelta(hours=lead):
            raise_error(ERR_PREP_LEAD_TIME_INSUFFICIENT,
                        "prep lead time insufficient under the new anesthesia level")
        check_room_overlap_and_capacity(room, booking["scheduled_start"],
                                        room_block_end, exclude_booking_id=booking["id"])
        booking["anesthesia_type"] = anesthesia_type
        booking["procedure_minutes"] = minutes
        booking["scheduled_end"] = scheduled_end
        booking["room_block_end"] = room_block_end
        if anesthesia_type == "NONE":
            # Setting anesthesia_type to NONE cancels active assignments.
            cancel_active_assignments(booking["id"])
    if notes_present:
        booking["notes"] = notes
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/confirm-prep")
def confirm_prep(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    get_body()
    # Rung 7: legal only while the booking axis remains SCHEDULED.
    if booking["status"] != "SCHEDULED":
        raise_error(ERR_BOOKING_NOT_SCHEDULED,
                    "prep confirmation requires booking axis SCHEDULED")
    booking["prep_status"] = "PREP_CONFIRMED"
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/check-in")
def check_in(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    get_body()
    # Rung 7: the booking axis must be SCHEDULED and the prep axis CONFIRMED
    # (state is evaluated before the temporal window per the ladder).
    if booking["status"] != "SCHEDULED":
        raise_error(ERR_BOOKING_NOT_SCHEDULED,
                    "check-in requires booking axis SCHEDULED")
    if booking["prep_status"] != "PREP_CONFIRMED":
        raise_error(ERR_PREP_NOT_CONFIRMED, "check-in requires prep_status PREP_CONFIRMED")
    # Rung 9: arrival window [start-60min, start+30min], inclusive both ends.
    current = now()
    start = booking["scheduled_start"]
    if current < start - timedelta(minutes=CHECK_IN_EARLY_MIN) or \
            current > start + timedelta(minutes=CHECK_IN_LATE_MIN):
        raise_error(ERR_CHECKIN_WINDOW_CLOSED,
                    "arrival outside the [start-60min, start+30min] check-in window")
    booking["status"] = "CHECKED_IN"
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/start")
def start_booking(rid):
    caller = authorized(["Endoscopist"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    # Rung 3: an explicit scope reference must resolve.
    explicit_scope = resolve_ref("scopes", body.get("scope_id"), ERR_SCOPE_NOT_FOUND)
    # Rung 4 (schema)
    if "scope_id" in body and body.get("scope_id") is not None \
            and not isinstance(body.get("scope_id"), str):
        raise_error(ERR_INVALID_REQUEST, "scope_id must be a string")
    # Rung 6 (ownership): the caller must be the booking's own endoscopist.
    if caller.user_id != booking["provider_id"]:
        raise_error(ERR_PROVIDER_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the booking's provider_id")
    # Rung 7 (state): booking axis CHECKED_IN; explicit scope AVAILABLE.
    if booking["status"] != "CHECKED_IN":
        raise_error(ERR_BOOKING_NOT_CHECKED_IN, "start requires booking axis CHECKED_IN")
    if explicit_scope is not None and explicit_scope["status"] != "AVAILABLE":
        raise_error(ERR_SCOPE_NOT_AVAILABLE, "explicit scope is not AVAILABLE")
    # Rung 8 (compliance): provider ACTIVE, room in service, anesthesia
    # confirmed when required, explicit scope storage-current.
    provider = db["providers"].get(booking["provider_id"])
    if provider is not None and provider["credential_status"] != "ACTIVE":
        raise_error(ERR_PROVIDER_SUSPENDED, "provider credential_status is SUSPENDED")
    room = db["rooms"].get(booking["room_id"])
    if room is not None and room["status"] != "ACTIVE":
        raise_error(ERR_ROOM_NOT_IN_SERVICE, "room is OUT_OF_SERVICE")
    if booking["anesthesia_type"] != "NONE":
        confirmed = any(
            a["booking_id"] == booking["id"] and a["status"] == "CONFIRMED"
            for a in db["anesthesia_assignments"].values()
        )
        if not confirmed:
            raise_error(ERR_ANESTHESIA_NOT_CONFIRMED,
                        "anesthesia_type != NONE requires a CONFIRMED assignment")
    if explicit_scope is not None and not scope_is_storage_current(explicit_scope):
        raise_error(ERR_SCOPE_STORAGE_EXPIRED, "explicit scope is past its storage limit")
    # Rung 10 (constraint): auto-selection pool non-empty.
    procedure_type = db["procedure_types"].get(booking["procedure_type_id"])
    if explicit_scope is None:
        scope = _select_scope(procedure_type)
    else:
        scope = explicit_scope
    # Rung 11 (referential): explicit scope type must match the procedure type.
    if explicit_scope is not None and \
            explicit_scope["scope_type"] != procedure_type["required_scope_type"]:
        raise_error(ERR_SCOPE_TYPE_MISMATCH,
                    "explicit scope_type does not match the procedure type's required_scope_type")
    # Effects
    current = now()
    booking["status"] = "IN_PROGRESS"
    booking["actual_start"] = current
    new_record("scope_usages", {
        "booking_id": booking["id"],
        "scope_id": scope["id"],
        "patient_id": booking["patient_id"],
        "used_at": current,
        "status": "ACTIVE",
        "void_reason": None,
        "exposure_flagged": False,
    })
    scope["status"] = "IN_USE"
    touch(scope)
    touch(booking)
    return success_object(public(booking))


def _select_scope(procedure_type):
    """scope_selection: eligible = type match + AVAILABLE + storage-current;
    ranked use_count ASC, storage_expires_at ASC NULLS LAST, created_at ASC."""
    eligible = [
        s for s in db["scopes"].values()
        if s["scope_type"] == procedure_type["required_scope_type"]
        and s["status"] == "AVAILABLE"
        and scope_is_storage_current(s)
    ]
    if not eligible:
        raise_error(ERR_NO_COMPATIBLE_SCOPE,
                    "no eligible scope (type match, AVAILABLE, storage-current)")

    def rank(s):
        exp = s["storage_expires_at"]
        return (
            scope_use_count(s["id"]),
            (1, None) if exp is None else (0, exp),  # NULLS LAST
            s["created_at"],
            s.get("_seq", 0),
        )

    eligible.sort(key=rank)
    return eligible[0]


@bp.post("/endoscopy/bookings/<rid>/record-prep-assessment")
def record_prep_assessment(rid):
    caller = authorized(["Endoscopist"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    # Rung 4 (schema): each segment is an integer in 0..3.
    bbps_left = req_int(body, "bbps_left", minimum=0, maximum=3)
    bbps_right = req_int(body, "bbps_right", minimum=0, maximum=3)
    bbps_transverse = req_int(body, "bbps_transverse", minimum=0, maximum=3)
    # Rung 6 (ownership)
    if caller.user_id != booking["provider_id"]:
        raise_error(ERR_PROVIDER_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the booking's provider_id")
    # Rung 7 (state): booking axis IN_PROGRESS; assessment is single-shot.
    if booking["status"] != "IN_PROGRESS":
        raise_error(ERR_BOOKING_NOT_IN_PROGRESS,
                    "prep assessment requires booking axis IN_PROGRESS")
    if booking["bbps_left"] is not None or booking["bbps_right"] is not None \
            or booking["bbps_transverse"] is not None:
        raise_error(ERR_PREP_ALREADY_ASSESSED, "BBPS assessment is single-shot")
    # bowel_prep_adequacy: total >= 6 AND every segment >= 2
    total = bbps_left + bbps_right + bbps_transverse
    adequate = total >= 6 and min(bbps_left, bbps_right, bbps_transverse) >= 2
    booking["bbps_left"] = bbps_left
    booking["bbps_right"] = bbps_right
    booking["bbps_transverse"] = bbps_transverse
    booking["prep_status"] = "PREP_ADEQUATE" if adequate else "PREP_INADEQUATE"
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/complete")
def complete_booking(rid):
    caller = authorized(["Endoscopist"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    # Rung 4 (schema)
    cecum_intubated = req_bool(body, "cecum_intubated")
    withdrawal_time_seconds = req_int(body, "withdrawal_time_seconds", minimum=0)
    adenomas_detected = req_int(body, "adenomas_detected", minimum=0)
    # Rung 6 (ownership)
    if caller.user_id != booking["provider_id"]:
        raise_error(ERR_PROVIDER_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the booking's provider_id")
    # Rung 7 (state)
    if booking["status"] != "IN_PROGRESS":
        raise_error(ERR_BOOKING_NOT_IN_PROGRESS,
                    "complete requires booking axis IN_PROGRESS")
    if booking["prep_status"] not in ("PREP_ADEQUATE", "PREP_INADEQUATE"):
        raise_error(ERR_PREP_NOT_ASSESSED,
                    "complete requires an assessed prep axis")
    booking["status"] = "COMPLETED"
    booking["actual_end"] = now()
    booking["actual_duration_minutes"] = compute_actual_duration_minutes(booking)
    booking["cecum_intubated"] = cecum_intubated
    booking["withdrawal_time_seconds"] = withdrawal_time_seconds
    booking["adenomas_detected"] = adenomas_detected
    release_scope_after_procedure(booking["id"])
    complete_confirmed_assignments(booking["id"])
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/abort")
def abort_booking(rid):
    caller = authorized(["Endoscopist"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    reason = req_str(body, "reason")
    # Rung 6 (ownership)
    if caller.user_id != booking["provider_id"]:
        raise_error(ERR_PROVIDER_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the booking's provider_id")
    # Rung 7 (state)
    if booking["status"] != "IN_PROGRESS":
        raise_error(ERR_BOOKING_NOT_IN_PROGRESS,
                    "abort requires booking axis IN_PROGRESS")
    if booking["prep_status"] != "PREP_INADEQUATE":
        raise_error(ERR_PREP_NOT_INADEQUATE,
                    "abort requires prep axis PREP_INADEQUATE")
    booking["status"] = "ABORTED_PREP_INADEQUATE"
    booking["actual_end"] = now()
    booking["actual_duration_minutes"] = compute_actual_duration_minutes(booking)
    booking["cancel_reason"] = reason
    release_scope_after_procedure(booking["id"])
    cancel_active_assignments(booking["id"])
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/cancel")
def cancel_booking(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    reason = opt_nullable_str(body, "reason", None)
    # Rung 7 (state)
    if booking["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise_error(ERR_BOOKING_NOT_CANCELLABLE,
                    "cancel requires booking axis in {SCHEDULED, CHECKED_IN}")
    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = reason
    # The prep axis is deliberately left untouched (parallel axes).
    cancel_active_assignments(booking["id"])
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/mark-no-show")
def mark_no_show(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    get_body()
    # Rung 7 (state)
    if booking["status"] != "SCHEDULED":
        raise_error(ERR_BOOKING_NOT_SCHEDULED,
                    "mark-no-show requires booking axis SCHEDULED")
    # Rung 9 (temporal): strictly later than start + 30 minutes.
    if now() <= booking["scheduled_start"] + timedelta(minutes=NO_SHOW_GRACE_MIN):
        raise_error(ERR_NO_SHOW_WINDOW_NOT_REACHED,
                    "no-show requires now strictly later than scheduled_start + 30min")
    booking["status"] = "NO_SHOW"
    cancel_active_assignments(booking["id"])
    touch(booking)
    return success_object(public(booking))


@bp.post("/endoscopy/bookings/<rid>/reschedule")
def reschedule_booking(rid):
    authorized(["SchedulingCoordinator"])
    booking = require_path_resource("bookings", rid, ERR_BOOKING_NOT_FOUND)
    body = get_body()
    # Rung 3 (existence): new_room_id must resolve when present.
    new_room = resolve_ref("rooms", body.get("new_room_id"), ERR_ROOM_NOT_FOUND)
    # Rung 4 (schema)
    expected_booking_version = req_int(body, "expected_booking_version")
    new_start = req_datetime(body, "new_scheduled_start")
    if "new_room_id" in body and body.get("new_room_id") is not None \
            and not isinstance(body.get("new_room_id"), str):
        raise_error(ERR_INVALID_REQUEST, "new_room_id must be a string")
    # Rung 5 (OCC): evaluated before the new slot is examined.
    if expected_booking_version != booking["version"]:
        raise_error(ERR_STALE_BOOKING_VERSION,
                    "expected_booking_version does not match the booking's current version")
    # Rung 7 (state)
    if booking["status"] != "SCHEDULED":
        raise_error(ERR_BOOKING_NOT_SCHEDULED,
                    "reschedule requires booking axis SCHEDULED")
    patient = db["patients"].get(booking["patient_id"])
    procedure_type = db["procedure_types"].get(booking["procedure_type_id"])
    room = new_room if new_room is not None else db["rooms"].get(booking["room_id"])
    # Rung 9 (temporal): the new slot is validated exactly like a fresh booking.
    check_temporal_gates(procedure_type, new_start)
    minutes, scheduled_end, room_block_end = compute_window(
        patient, procedure_type, room, new_start, booking["anesthesia_type"])
    # Rung 10 (constraint): overlap then capacity, against the new room/slot.
    # The superseded booking releases its time, so it is excluded.
    check_room_overlap_and_capacity(room, new_start, room_block_end,
                                    exclude_booking_id=booking["id"])
    # Effects: the old booking is superseded; a replacement is created.
    cancel_active_assignments(booking["id"])
    booking["status"] = "RESCHEDULED"
    touch(booking)
    rec = new_record("bookings", _fresh_booking_fields(
        booking["patient_id"], booking["provider_id"], booking["procedure_type_id"],
        room["id"], booking["indication"], booking["anesthesia_type"],
        booking["notes"], new_start, minutes, scheduled_end, room_block_end,
        rescheduled_from_id=booking["id"]))
    return success_object(public(rec), status=201)
