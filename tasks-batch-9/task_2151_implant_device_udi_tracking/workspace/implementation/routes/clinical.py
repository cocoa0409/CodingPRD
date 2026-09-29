"""Patients, the operating-room schedule, reservations and case lifecycle."""
from flask import Blueprint

import serialize
from auth import (
    CIRC_CLINICIAN,
    CLINICAL_READERS,
    COMPLIANCE_OFFICER,
    INVENTORY_LEAD,
    REVENUE_ANALYST,
    endpoint,
)
from calc import PATIENT_RECOVERY_BUFFER_MINUTES, fefo_unit_selection
from derive import (
    case_close_readiness,
    compute_readiness,
    detach_reservation,
    readiness_counters,
    recompute_case_totals,
    recompute_catalog_available,
    recompute_patient_implant_count,
    set_custody,
)
from envelope import array_response, object_response
from errors import ApiError
from graph import catalog_of_unit, charges_of_record, lot_of, records_of_case
from resolve import maybe, must
from store import base_record, db, expiry_instant, clock_dt, ordered, parse_iso, touch
from validation import (
    apply_page,
    bad,
    body,
    filter_enum,
    filter_value,
    opt_enum,
    opt_str,
    pagination,
    present,
    req_dt,
    req_str,
)

bp = Blueprint("clinical", __name__)

CONSENT_VALUES = ("GRANTED", "DECLINED", "UNKNOWN")
CASE_STATES = ("SCHEDULED", "IN_PROGRESS", "CLOSED", "CANCELLED", "ABORTED")
BUFFER_SECONDS = PATIENT_RECOVERY_BUFFER_MINUTES * 60


# ----------------------------------------------------------------- patients
@bp.route("/udi/patients", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def create_patient():
    data = body()
    mrn = req_str(data, "mrn")
    display_name = req_str(data, "display_name")
    consent = opt_enum(data, "registry_consent", CONSENT_VALUES, "UNKNOWN")

    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "mrn already exists.")

    record = base_record()
    record.update(
        {
            "mrn": mrn,
            "display_name": display_name,
            "registry_consent": consent,
            "implant_count": 0,
        }
    )
    db.patients[record["id"]] = record
    return object_response(serialize.patient(record), 201)


@bp.route("/udi/patients/<patient_id>", methods=["PATCH"])
@endpoint([CIRC_CLINICIAN, COMPLIANCE_OFFICER])
def update_patient(patient_id):
    data = body()
    consent = opt_enum(data, "registry_consent", CONSENT_VALUES)
    display_name = opt_str(data, "display_name")

    patient = must("patient_id", patient_id)
    if consent is not None:
        patient["registry_consent"] = consent
    if display_name is not None:
        patient["display_name"] = display_name
    touch(patient)
    return object_response(serialize.patient(patient))


@bp.route("/udi/patients/<patient_id>", methods=["GET"])
@endpoint([CIRC_CLINICIAN, COMPLIANCE_OFFICER, REVENUE_ANALYST])
def get_patient(patient_id):
    return object_response(serialize.patient(must("patient_id", patient_id)))


@bp.route("/udi/patients", methods=["GET"])
@endpoint([CIRC_CLINICIAN, COMPLIANCE_OFFICER, REVENUE_ANALYST])
def list_patients():
    limit, offset = pagination()
    consent = filter_enum("registry_consent", CONSENT_VALUES)
    rows = [p for p in db.patients.values() if consent is None or p["registry_consent"] == consent]
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.patient(p) for p in page], limit, offset, total)


# ----------------------------------------------------------- surgical cases
@bp.route("/udi/surgical-cases", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def create_case():
    data = body()
    patient_id = req_str(data, "patient_id")
    case_number = req_str(data, "case_number")
    or_room_code = req_str(data, "or_room_code")
    start = req_dt(data, "scheduled_start_utc")
    end = req_dt(data, "scheduled_end_utc")
    surgeon_code = req_str(data, "surgeon_code")
    if not end > start:
        raise bad("scheduled_end_utc must be strictly after scheduled_start_utc.")

    patient = must("patient_id", patient_id)

    for existing in db.cases.values():                              # step 19
        if existing["case_number"] == case_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "case_number already exists.")

    # step 21 — OR room occupancy: half-open, unbuffered
    for existing in ordered(db.cases.values()):
        if existing["or_room_code"] != or_room_code:
            continue
        if existing["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = parse_iso(existing["scheduled_start_utc"])
        other_end = parse_iso(existing["scheduled_end_utc"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_OR_ROOM_CONFLICT", "The operating room is already booked.")

    # step 22 — patient recovery occupancy: closed, buffered 120 minutes a side
    for existing in ordered(db.cases.values()):
        if existing["patient_id"] != patient["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = parse_iso(existing["scheduled_start_utc"])
        other_end = parse_iso(existing["scheduled_end_utc"])
        a_lo = start.timestamp() - BUFFER_SECONDS
        a_hi = end.timestamp() + BUFFER_SECONDS
        b_lo = other_start.timestamp() - BUFFER_SECONDS
        b_hi = other_end.timestamp() + BUFFER_SECONDS
        if a_lo <= b_hi and b_lo <= a_hi:
            raise ApiError(
                "ERR_PATIENT_SCHEDULE_CONFLICT", "The patient needs recovery time between cases."
            )

    record = base_record()
    record.update(
        {
            "patient_id": patient["id"],
            "case_number": case_number,
            "or_room_code": or_room_code,
            "scheduled_start_utc": data["scheduled_start_utc"],
            "scheduled_end_utc": data["scheduled_end_utc"],
            "surgeon_code": surgeon_code,
            "status": "SCHEDULED",
            "readiness_status": "READY",
            "blocked_reservation_count": 0,
            "total_posted_charge_cents": 0,
            "implant_record_count": 0,
        }
    )
    db.cases[record["id"]] = record
    return object_response(serialize.case(record), 201)


@bp.route("/udi/surgical-cases/<case_id>", methods=["GET"])
@endpoint(CLINICAL_READERS)
def get_case(case_id):
    return object_response(serialize.case(must("case_id", case_id)))


@bp.route("/udi/surgical-cases", methods=["GET"])
@endpoint(CLINICAL_READERS)
def list_cases():
    limit, offset = pagination()
    patient_id = filter_value("patient_id")
    status = filter_enum("status", CASE_STATES)
    or_room_code = filter_value("or_room_code")
    rows = []
    for row in db.cases.values():
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if or_room_code is not None and row["or_room_code"] != or_room_code:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.case(r) for r in page], limit, offset, total)


@bp.route("/udi/surgical-cases/<case_id>/readiness", methods=["GET"])
@endpoint(CLINICAL_READERS)
def case_readiness(case_id):
    case = must("case_id", case_id)
    unverified, outstanding, unfinalized = readiness_counters(case)
    return object_response(
        {
            "readiness_status": compute_readiness(case),
            "blocked_reservation_count": case.get("blocked_reservation_count", 0),
            "unverified_record_count": unverified,
            "outstanding_registry_count": outstanding,
            "unfinalized_charge_count": unfinalized,
            "total_posted_charge_cents": case.get("total_posted_charge_cents", 0),
        }
    )


@bp.route("/udi/surgical-cases/<case_id>/reservations", methods=["POST"])
@endpoint([CIRC_CLINICIAN, INVENTORY_LEAD])
def create_reservation(case_id):
    data = body()
    has_catalog = present(data, "catalog_item_id")
    has_unit = present(data, "device_unit_id")
    if has_catalog == has_unit:
        raise bad("Supply exactly one of catalog_item_id and device_unit_id.")
    catalog_item_id = req_str(data, "catalog_item_id") if has_catalog else None
    device_unit_id = req_str(data, "device_unit_id") if has_unit else None

    case = must("case_id", case_id)                                 # step 4
    maybe("catalog_item_id", catalog_item_id)                       # step 5
    unit = maybe("device_unit_id", device_unit_id)

    if case["status"] != "SCHEDULED":                               # step 8
        raise ApiError("ERR_INVALID_CASE_STATE", "Reservations require a SCHEDULED case.")

    scheduled_end = parse_iso(case["scheduled_end_utc"])

    if unit is not None:
        lot = lot_of(unit)
        if unit["custody_state"] == "RECALL_HOLD" or (lot and lot["status"] == "RECALLED"):
            raise ApiError("ERR_UNIT_RECALLED", "The unit is under a field action.")   # step 10
        instant = expiry_instant(lot["expiration_date"]) if lot else None
        if instant is None or instant <= clock_dt() or instant <= scheduled_end:
            raise ApiError("ERR_UNIT_EXPIRED", "The lot does not survive the booking.")  # step 11
        if lot["status"] != "AVAILABLE":                            # step 15
            raise ApiError("ERR_LOT_NOT_RELEASED", "The lot is still in QUARANTINE.")
        if unit["custody_state"] != "AVAILABLE" or unit.get("reserved_case_id") is not None:
            raise ApiError("ERR_INVALID_UNIT_STATE", "The unit is not available.")       # step 16
    else:
        unit = fefo_unit_selection(catalog_item_id, case)           # step 23
        if unit is None:
            raise ApiError("ERR_NO_ELIGIBLE_UNIT", "No eligible unit for this catalog item.")

    set_custody(unit, "RESERVED")
    unit["reserved_case_id"] = case["id"]
    touch(unit)
    case["blocked_reservation_count"] = max(0, case.get("blocked_reservation_count", 0) - 1)
    touch(case)
    recompute_catalog_available(catalog_of_unit(unit))
    case_close_readiness(case)
    return object_response(serialize.device_unit(unit), 201)


@bp.route("/udi/surgical-cases/<case_id>/start", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def start_case(case_id):
    case = must("case_id", case_id)
    if case["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_CASE_STATE", "Only a SCHEDULED case can be started.")
    case["status"] = "IN_PROGRESS"
    touch(case)
    case_close_readiness(case)
    return object_response(serialize.case(case))


@bp.route("/udi/surgical-cases/<case_id>/close", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def close_case(case_id):
    case = must("case_id", case_id)
    if case["status"] != "IN_PROGRESS":                             # step 8
        raise ApiError("ERR_INVALID_CASE_STATE", "Only an IN_PROGRESS case can be closed.")

    posture = compute_readiness(case)
    if posture in ("BLOCKED_RESERVATION", "BLOCKED_DOCUMENTATION"):  # step 24
        raise ApiError("ERR_CASE_READINESS_UNMET", "The case is not ready to close.")
    if posture == "BLOCKED_REGISTRY":                                # step 25
        raise ApiError("ERR_REGISTRY_OUTSTANDING", "A registry obligation is outstanding.")
    if posture == "BLOCKED_CHARGE":                                  # step 30
        raise ApiError("ERR_CHARGE_VARIANCE_UNRESOLVED", "A charge line is unresolved.")

    case["status"] = "CLOSED"
    touch(case)
    for unit in ordered(db.device_units.values()):
        if unit.get("reserved_case_id") == case["id"]:
            unit["reserved_case_id"] = None
            set_custody(unit, "AVAILABLE")
            recompute_catalog_available(catalog_of_unit(unit))
    case_close_readiness(case)
    return object_response(serialize.case(case))


@bp.route("/udi/surgical-cases/<case_id>/cancel", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def cancel_case(case_id):
    case = must("case_id", case_id)
    if case["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_CASE_STATE", "A terminal case cannot be cancelled.")

    aborting = case["status"] == "IN_PROGRESS"
    case["status"] = "ABORTED" if aborting else "CANCELLED"
    touch(case)

    for unit in ordered(db.device_units.values()):
        if unit.get("reserved_case_id") == case["id"]:
            unit["reserved_case_id"] = None
            set_custody(unit, "AVAILABLE")
            recompute_catalog_available(catalog_of_unit(unit))

    if aborting:
        touched_patients = []
        for record in records_of_case(case["id"]):
            if record["status"] != "DOCUMENTED":
                continue
            record["status"] = "VOIDED"
            touch(record)
            for charge in charges_of_record(record["id"]):
                if charge["status"] in ("DRAFT", "POSTED", "CORRECTION_REQUIRED"):
                    charge["status"] = "VOIDED"
                    touch(charge)
                    recompute_case_totals(case)
            patient = db.patients.get(record["patient_id"])
            if patient is not None:
                recompute_patient_implant_count(patient)
        recompute_case_totals(case)

    case["blocked_reservation_count"] = 0
    touch(case)
    recompute_case_totals(case)
    case_close_readiness(case)
    return object_response(serialize.case(case))
