"""Verification crews, appointment windows and sampling strata."""

from datetime import timedelta

from flask import Blueprint, g

import logic
import lookup
from core import (
    body_json, by_created_at, db, endpoint, fail, field, filter_arg, iso_ms,
    new_row, paginate, parse_datetime, parse_hhmm, read_pagination,
    respond_list, respond_object, touch, validate_body, dec,
)

bp = Blueprint("field", __name__)

METHODS = ("VISUAL_INSPECTION", "POTHOLE", "WATER_SAMPLING")
CREW_STATUSES = ("ACTIVE", "INACTIVE")
SIDES = ("UTILITY", "CUSTOMER")
MATERIALS = ("LEAD", "GRR", "COPPER", "PLASTIC", "UNKNOWN")
BARRIER_REASONS = ("LOCKED_PREMISE", "OCCUPANT_REFUSED", "UTILITY_CONFLICT", "WEATHER")
SAMPLE_TYPES = ("FIRST_DRAW", "FIFTH_LITER")
OCCUPYING_STATES = ("SCHEDULED", "ON_SITE", "COMPLETED")
TRAVEL_BUFFER = timedelta(minutes=45)

FIELD_ROLES = ["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
               "FieldTechnician"]


# ----------------------------------------------------------- VerificationCrew
@bp.post("/lsl/verification-crews")
@endpoint(["ProgramAdministrator"])
def create_crew():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("crew_name", "string", required=True, nonempty=True),
        field("shift_start_utc_time", "hhmm", required=True),
        field("shift_end_utc_time", "hhmm", required=True),
        field("daily_appointment_capacity", "integer", required=True, min=1),
        field("certified_methods", "array", required=True, nonempty=True,
              item_type="string", item_enum=METHODS),
    ])
    if parse_hhmm(data["shift_end_utc_time"]) <= parse_hhmm(data["shift_start_utc_time"]):
        fail("ERR_INVALID_DATE_RANGE",
             "shift_end_utc_time must be strictly later than shift_start_utc_time.")
    lookup.water_system(data["water_system_id"])

    crew = new_row()
    crew.update({
        "water_system_id": data["water_system_id"],
        "crew_name": data["crew_name"],
        "shift_start_utc_time": data["shift_start_utc_time"],
        "shift_end_utc_time": data["shift_end_utc_time"],
        "daily_appointment_capacity": data["daily_appointment_capacity"],
        "certified_methods": list(data["certified_methods"]),
        "status": "ACTIVE",
    })
    db.crews[crew["id"]] = crew
    return respond_object(logic.serialize_crew(crew), 201)


@bp.get("/lsl/verification-crews")
@endpoint(FIELD_ROLES)
def list_crews():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.crews.values()))
    for name in ("water_system_id", "status"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_crew(r) for r in page], limit, offset, total)


@bp.get("/lsl/verification-crews/<crew_id>")
@endpoint(FIELD_ROLES)
def read_crew(crew_id):
    crew = lookup.crew(crew_id)
    return respond_object(logic.serialize_crew(crew))


@bp.post("/lsl/verification-crews/<crew_id>/status")
@endpoint(["ProgramAdministrator"])
def set_crew_status(crew_id):
    data = validate_body(body_json(), [
        field("status", "string", required=True, enum=CREW_STATUSES),
    ])
    crew = lookup.crew(crew_id)
    crew["status"] = data["status"]
    touch(crew)
    return respond_object(logic.serialize_crew(crew))


# ---------------------------------------------------- VerificationAppointment
def _shift_gate(crew, start, end):
    """The window must sit inside the shift and on a single UTC calendar date."""
    if start.date() != end.date():
        fail("ERR_CREW_OUTSIDE_SHIFT",
             "The appointment window must sit on a single UTC calendar date.")
    open_at = parse_hhmm(crew["shift_start_utc_time"])
    close_at = parse_hhmm(crew["shift_end_utc_time"])
    for moment in (start.time(), end.time()):
        if moment < open_at or moment > close_at:
            fail("ERR_CREW_OUTSIDE_SHIFT",
                 "The appointment window must fall inside the crew's shift "
                 "[%s, %s]." % (crew["shift_start_utc_time"],
                                crew["shift_end_utc_time"]))


def _overlap_gate(crew, start, end, exclude_id=None):
    for other in db.appointments.values():
        if other["crew_id"] != crew["id"] or other["id"] == exclude_id:
            continue
        if other["state"] not in OCCUPYING_STATES:
            continue
        if start < other["_window_end"] + TRAVEL_BUFFER \
                and end > other["_window_start"]:
            fail("ERR_CREW_WINDOW_CONFLICT",
                 "The crew is already committed in a window that collides with "
                 "this one once the 45-minute travel buffer is applied.")


def _capacity_gate(crew, start, exclude_id=None):
    day = start.date()
    booked = 0
    for other in db.appointments.values():
        if other["crew_id"] != crew["id"] or other["id"] == exclude_id:
            continue
        if other["state"] not in OCCUPYING_STATES:
            continue
        if other["_window_start"].date() == day:
            booked += 1
    if booked >= crew["daily_appointment_capacity"]:
        fail("ERR_CREW_DAILY_CAPACITY_EXCEEDED",
             "The crew already holds %d appointments on %s, its full daily "
             "capacity." % (booked, day.isoformat()))


def _crew_identity_gate(appointment):
    if g.user_role == "FieldTechnician" and g.user_id != appointment["crew_id"]:
        fail("ERR_CREW_IDENTITY_MISMATCH",
             "A FieldTechnician may only act on appointments booked to its own crew.")


@bp.post("/lsl/verification-appointments")
@endpoint(["ProgramAdministrator", "FieldTechnician"])
def create_appointment():
    data = validate_body(body_json(), [
        field("service_line_id", "string", required=True),
        field("crew_id", "string", required=True),
        field("method", "string", required=True, enum=METHODS),
        field("window_start_utc", "datetime", required=True),
        field("window_end_utc", "datetime", required=True),
    ])
    start = parse_datetime(data["window_start_utc"])
    end = parse_datetime(data["window_end_utc"])
    if end <= start:
        fail("ERR_INVALID_DATE_RANGE",
             "window_end_utc must be strictly later than window_start_utc.")

    line = lookup.service_line(data["service_line_id"])
    crew = lookup.crew(data["crew_id"])

    if data["method"] not in crew["certified_methods"]:
        fail("ERR_CREW_METHOD_NOT_CERTIFIED",
             "Crew %s is not certified for %s." % (crew["id"], data["method"]))
    _shift_gate(crew, start, end)
    _overlap_gate(crew, start, end)
    _capacity_gate(crew, start)

    appointment = new_row()
    appointment.update({
        "service_line_id": line["id"],
        "crew_id": crew["id"],
        "method": data["method"],
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "_window_start": start,
        "_window_end": end,
        "state": "SCHEDULED",
        "attempt_count": 1,
        "barrier_reason": None,
        "observed_material": None,
        "observed_side": None,
        "emitted_evidence_item_id": None,
    })
    db.appointments[appointment["id"]] = appointment
    return respond_object(logic.serialize_appointment(appointment), 201)


@bp.get("/lsl/verification-appointments")
@endpoint(FIELD_ROLES)
def list_appointments():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.appointments.values()))
    for name in ("crew_id", "service_line_id", "state", "method"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_appointment(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/verification-appointments/<appointment_id>")
@endpoint(FIELD_ROLES)
def read_appointment(appointment_id):
    appointment = lookup.appointment(appointment_id)
    return respond_object(logic.serialize_appointment(appointment))


@bp.post("/lsl/verification-appointments/<appointment_id>/arrive")
@endpoint(["FieldTechnician"])
def arrive(appointment_id):
    appointment = lookup.appointment(appointment_id)
    _crew_identity_gate(appointment)
    if appointment["state"] != "SCHEDULED":
        fail("ERR_APPOINTMENT_STATE_INVALID",
             "Arrival requires state SCHEDULED, not %s." % appointment["state"])
    crew = db.crews.get(appointment["crew_id"])
    if crew is None or crew["status"] != "ACTIVE":
        fail("ERR_CREW_INACTIVE", "The assigned crew is not ACTIVE.")

    appointment["state"] = "ON_SITE"
    touch(appointment)
    return respond_object(logic.serialize_appointment(appointment))


@bp.post("/lsl/verification-appointments/<appointment_id>/complete")
@endpoint(["FieldTechnician"])
def complete_appointment(appointment_id):
    data = validate_body(body_json(), [
        field("observed_side", "string", required=True, enum=SIDES),
        field("observed_material", "string", required=True, enum=MATERIALS),
    ])
    appointment = lookup.appointment(appointment_id)
    _crew_identity_gate(appointment)
    if appointment["state"] != "ON_SITE":
        fail("ERR_APPOINTMENT_STATE_INVALID",
             "Completion requires state ON_SITE, not %s." % appointment["state"])
    if appointment["method"] == "WATER_SAMPLING" \
            and data["observed_side"] == "CUSTOMER":
        fail("ERR_EVIDENCE_SIDE_MISMATCH",
             "A WATER_SAMPLING appointment may only observe the UTILITY side.")

    appointment["observed_side"] = data["observed_side"]
    appointment["observed_material"] = data["observed_material"]
    appointment["state"] = "COMPLETED"

    line = db.service_lines.get(appointment["service_line_id"])
    item = logic.create_evidence_item(
        appointment["service_line_id"], appointment["method"],
        data["observed_side"], data["observed_material"], iso_ms(db.clock),
        notes=None, origin="APPOINTMENT_CASCADE",
    )
    appointment["emitted_evidence_item_id"] = item["id"]
    touch(appointment)
    if line is not None:
        logic.classification_recompute(line)
    return respond_object(logic.serialize_appointment(appointment))


@bp.post("/lsl/verification-appointments/<appointment_id>/no-access")
@endpoint(["FieldTechnician"])
def no_access(appointment_id):
    data = validate_body(body_json(), [
        field("barrier_reason", "string", required=True, enum=BARRIER_REASONS),
    ])
    appointment = lookup.appointment(appointment_id)
    _crew_identity_gate(appointment)
    if appointment["state"] != "ON_SITE":
        fail("ERR_APPOINTMENT_STATE_INVALID",
             "An access barrier may only be reported from ON_SITE, not %s."
             % appointment["state"])

    appointment["barrier_reason"] = data["barrier_reason"]
    if appointment["attempt_count"] < 3:
        appointment["state"] = "NO_ACCESS"
    else:
        appointment["state"] = "ABANDONED"
    touch(appointment)
    return respond_object(logic.serialize_appointment(appointment))


@bp.post("/lsl/verification-appointments/<appointment_id>/reschedule")
@endpoint(["ProgramAdministrator"])
def reschedule(appointment_id):
    data = validate_body(body_json(), [
        field("window_start_utc", "datetime", required=True),
        field("window_end_utc", "datetime", required=True),
    ])
    start = parse_datetime(data["window_start_utc"])
    end = parse_datetime(data["window_end_utc"])
    if end <= start:
        fail("ERR_INVALID_DATE_RANGE",
             "window_end_utc must be strictly later than window_start_utc.")

    appointment = lookup.appointment(appointment_id)
    if appointment["state"] != "NO_ACCESS":
        fail("ERR_APPOINTMENT_STATE_INVALID",
             "Only a NO_ACCESS appointment may be re-booked, not one in %s."
             % appointment["state"])
    crew = db.crews.get(appointment["crew_id"])
    if crew is not None:
        _shift_gate(crew, start, end)
        _overlap_gate(crew, start, end, exclude_id=appointment["id"])
        _capacity_gate(crew, start, exclude_id=appointment["id"])

    appointment["window_start_utc"] = data["window_start_utc"]
    appointment["window_end_utc"] = data["window_end_utc"]
    appointment["_window_start"] = start
    appointment["_window_end"] = end
    appointment["state"] = "SCHEDULED"
    appointment["attempt_count"] = appointment["attempt_count"] + 1
    touch(appointment)
    return respond_object(logic.serialize_appointment(appointment))


# ---------------------------------------------------------------- SamplingBatch
@bp.post("/lsl/sampling-batches")
@endpoint(["ComplianceOfficer"])
def create_batch():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("stratum_code", "string", required=True, nonempty=True),
        field("stratum_line_count", "integer", required=True, min=1),
    ])
    ws = lookup.water_system(data["water_system_id"])
    for row in db.batches.values():
        if row["water_system_id"] == ws["id"] \
                and row["stratum_code"] == data["stratum_code"]:
            fail("ERR_DUPLICATE_STRATUM_CODE",
                 "stratum_code %s already exists for this water system."
                 % data["stratum_code"])

    batch = new_row()
    batch.update({
        "water_system_id": ws["id"],
        "stratum_code": data["stratum_code"],
        "stratum_line_count": data["stratum_line_count"],
        "samples": [],
        "percentile_90_ppb": None,
        "exceedance_count": 0,
        "exceedance": False,
        "classification_confidence": None,
        "state": "OPEN",
        "reopen_count": 0,
        "rejection_reason": None,
    })
    db.batches[batch["id"]] = batch
    return respond_object(logic.serialize_batch(batch), 201)


@bp.get("/lsl/sampling-batches")
@endpoint(FIELD_ROLES)
def list_batches():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.batches.values()))
    for name in ("water_system_id", "state"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_batch(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/sampling-batches/<batch_id>")
@endpoint(FIELD_ROLES)
def read_batch(batch_id):
    batch = lookup.batch(batch_id)
    return respond_object(logic.serialize_batch(batch))


@bp.post("/lsl/sampling-batches/<batch_id>/samples")
@endpoint(["FieldTechnician", "ComplianceOfficer"])
def append_sample(batch_id):
    data = validate_body(body_json(), [
        field("service_line_id", "string", required=True),
        field("lead_ppb", "number", required=True, min=0),
        field("collected_at", "datetime", required=True),
        field("sample_type", "string", required=True, enum=SAMPLE_TYPES),
    ])
    batch = lookup.batch(batch_id)
    lookup.service_line(data["service_line_id"])
    if batch["state"] != "OPEN":
        fail("ERR_BATCH_STATE_INVALID",
             "Samples may only be appended to an OPEN batch, not one in %s."
             % batch["state"])

    batch["samples"].append({
        "sample_seq": len(batch["samples"]) + 1,
        "service_line_id": data["service_line_id"],
        "lead_ppb": data["lead_ppb"],
        "collected_at": data["collected_at"],
        "_collected_at": parse_datetime(data["collected_at"]),
        "sample_type": data["sample_type"],
        "invalidated": False,
        "invalidation_reason": None,
    })
    touch(batch)
    return respond_object(logic.serialize_batch(batch))


@bp.post("/lsl/sampling-batches/<batch_id>/invalidate-sample")
@endpoint(["ComplianceOfficer"])
def invalidate_sample(batch_id):
    data = validate_body(body_json(), [
        field("sample_seq", "integer", required=True),
        field("reason", "string", required=True, nonempty=True),
    ])
    batch = lookup.batch(batch_id)
    if batch["state"] != "OPEN":
        fail("ERR_BATCH_STATE_INVALID",
             "Samples may only be voided while the batch is OPEN, not in %s."
             % batch["state"])

    target = None
    for sample in batch["samples"]:
        if sample["sample_seq"] == data["sample_seq"]:
            target = sample
            break
    if target is None:
        fail("ERR_SAMPLE_NOT_FOUND",
             "No sample with sample_seq %s in this batch." % data["sample_seq"])

    target["invalidated"] = True
    target["invalidation_reason"] = data["reason"]
    touch(batch)
    return respond_object(logic.serialize_batch(batch))


@bp.post("/lsl/sampling-batches/<batch_id>/validate")
@endpoint(["ComplianceOfficer"])
def validate_batch(batch_id):
    batch = lookup.batch(batch_id)
    if batch["state"] != "OPEN":
        fail("ERR_BATCH_STATE_INVALID",
             "Validation runs only from OPEN, not from %s." % batch["state"])
    required = logic.required_sample_count(batch["stratum_line_count"])
    valid = logic.valid_samples(batch)
    if len(valid) < required:
        fail("ERR_SAMPLE_COUNT_INSUFFICIENT",
             "%d valid samples is fewer than the required %d."
             % (len(valid), required))

    stats = logic.sampling_statistics(batch)
    batch["percentile_90_ppb"] = stats["percentile_90_ppb"]
    batch["exceedance_count"] = stats["exceedance_count"]
    batch["exceedance"] = stats["exceedance"]
    batch["classification_confidence"] = stats["classification_confidence"]

    if dec(stats["classification_confidence"]) >= logic.CONFIDENCE_FLOOR:
        batch["state"] = "VALIDATED"
        batch["rejection_reason"] = None
        if stats["exceedance"]:
            ws = db.water_systems.get(batch["water_system_id"])
            if ws is not None:
                ws["cct_optimization_status"] = "PENDING_REOPTIMIZATION"
                touch(ws)
    else:
        batch["state"] = "REJECTED"
        batch["rejection_reason"] = "CONFIDENCE_BELOW_FLOOR"
    touch(batch)
    return respond_object(logic.serialize_batch(batch))


@bp.post("/lsl/sampling-batches/<batch_id>/reopen")
@endpoint(["ComplianceOfficer"])
def reopen_batch(batch_id):
    data = validate_body(body_json(), [
        field("reason", "string", required=True, nonempty=True),
    ])
    batch = lookup.batch(batch_id)
    if batch["state"] != "REJECTED":
        fail("ERR_BATCH_STATE_INVALID",
             "Only a REJECTED batch may be reopened, not one in %s." % batch["state"])

    # A reopened batch is indistinguishable from a freshly opened one: every
    # statistic of the superseded round is cleared, exceedance_count included.
    batch["state"] = "OPEN"
    batch["reopen_count"] = batch["reopen_count"] + 1
    batch["percentile_90_ppb"] = None
    batch["classification_confidence"] = None
    batch["rejection_reason"] = None
    batch["exceedance"] = False
    batch["exceedance_count"] = 0
    touch(batch)
    return respond_object(logic.serialize_batch(batch))
