"""Implant documentation, verification, amendment and explantation."""
from flask import Blueprint

import serialize
from auth import CIRC_CLINICIAN, CLINICAL_READERS, COMPLIANCE_OFFICER, actor, endpoint
from calc import REGISTRY_DEADLINE_DAYS, explant_return_credit
from derive import (
    case_close_readiness,
    recompute_case_totals,
    recompute_patient_implant_count,
    set_billing,
    set_custody,
)
from envelope import array_response, object_response
from errors import ApiError
from graph import (
    catalog_of_unit,
    charges_of_record,
    lot_of,
    submissions_of_record,
)
from resolve import maybe, must
from store import (
    base_record,
    clock_dt,
    clock_iso,
    db,
    expiry_instant,
    iso_like,
    ordered,
    parse_iso,
    plus_days,
    touch,
)
from validation import (
    apply_page,
    body,
    filter_enum,
    filter_value,
    opt_str,
    pagination,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("records", __name__)

RECORD_STATES = ("DOCUMENTED", "VERIFIED", "AMENDED", "EXPLANTED", "VOIDED")
LATERALITY = ("LEFT", "RIGHT", "BILATERAL", "NOT_APPLICABLE")
EXPLANT_REASONS = ("DEVICE_FAILURE", "INFECTION", "RECALL", "UPGRADE", "OTHER")


@bp.route("/udi/surgical-cases/<case_id>/implant-records", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def document_implant(case_id):
    data = body()
    device_unit_id = req_str(data, "device_unit_id")
    udi_di = req_str(data, "udi_di")
    udi_pi_serial = req_str(data, "udi_pi_serial")
    anatomic_site = req_str(data, "anatomic_site")
    laterality = req_enum(data, "laterality", LATERALITY)
    expected_case_version = req_int(data, "expected_case_version")
    patient_id = opt_str(data, "patient_id")

    case = must("case_id", case_id)                                 # step 4
    unit = must("device_unit_id", device_unit_id)                   # step 5
    maybe("patient_id", patient_id)

    if expected_case_version != case["version"]:                    # step 7
        raise ApiError("ERR_STALE_CASE_VERSION", "expected_case_version does not match the case.")

    if case["status"] != "IN_PROGRESS":                             # step 8
        raise ApiError("ERR_INVALID_CASE_STATE", "Documentation requires an IN_PROGRESS case.")

    lot = lot_of(unit)
    if unit["custody_state"] == "RECALL_HOLD" or (lot and lot["status"] == "RECALLED"):
        raise ApiError("ERR_UNIT_RECALLED", "The unit is under a field action.")      # step 10

    instant = expiry_instant(lot["expiration_date"]) if lot else None
    if instant is None or instant <= clock_dt():                    # step 11
        raise ApiError("ERR_UNIT_EXPIRED", "The lot has expired.")

    if udi_di != unit.get("udi_di_snapshot") or udi_pi_serial != unit.get("udi_serial"):
        raise ApiError("ERR_UDI_INCOMPLETE", "The transcribed UDI does not match the unit.")

    if patient_id is not None and patient_id != case["patient_id"]:  # step 13
        raise ApiError("ERR_PATIENT_LINK_MISMATCH", "patient_id does not match the case.")

    if lot["status"] != "AVAILABLE":                                # step 15
        raise ApiError("ERR_LOT_NOT_RELEASED", "The lot is still in QUARANTINE.")

    custody = unit["custody_state"]                                 # step 16
    if custody == "RESERVED":
        if unit.get("reserved_case_id") != case["id"]:
            raise ApiError("ERR_INVALID_UNIT_STATE", "The unit is reserved to another case.")
    elif custody == "AVAILABLE":
        if unit.get("reserved_case_id") is not None:
            raise ApiError("ERR_INVALID_UNIT_STATE", "The unit is reserved to another case.")
    else:
        raise ApiError("ERR_INVALID_UNIT_STATE", "The unit cannot be implanted from %s." % custody)

    record = base_record()
    record.update(
        {
            "surgical_case_id": case["id"],
            "device_unit_id": unit["id"],
            "patient_id": case["patient_id"],
            "status": "DOCUMENTED",
            "udi_di": udi_di,
            "udi_pi_serial": udi_pi_serial,
            "anatomic_site": anatomic_site,
            "laterality": laterality,
            "documented_by_user_id": actor(),
            "verified_by_user_id": None,
            "documented_at_utc": clock_iso(),
            "verified_at_utc": None,
            "amendment_count": 0,
        }
    )
    db.implant_records[record["id"]] = record

    unit["reserved_case_id"] = None
    unit["implanted_at_utc"] = clock_iso()
    set_custody(unit, "IMPLANTED")

    agreement = (
        db.agreements.get(unit["consignment_agreement_id"])
        if unit.get("consignment_agreement_id")
        else None
    )
    if (
        unit["ownership"] == "CONSIGNED"
        and agreement is not None
        and agreement["status"] == "ACTIVE"
        and agreement["billing_trigger"] == "ON_IMPLANT"
        and unit["billing_state"] == "NOT_BILLABLE"
    ):
        unit["contract_price_cents"] = unit["acquisition_cost_cents"]
        unit["price_list_version_at_billing"] = agreement["price_list_version"]
        set_billing(unit, "BILLABLE")

    recompute_patient_implant_count(db.patients.get(case["patient_id"]))
    recompute_case_totals(case)
    case_close_readiness(case)
    touch(case)
    return object_response(serialize.implant_record(record), 201)


@bp.route("/udi/implant-records/<implant_record_id>", methods=["GET"])
@endpoint(CLINICAL_READERS)
def get_record(implant_record_id):
    return object_response(serialize.implant_record(must("implant_record_id", implant_record_id)))


@bp.route("/udi/implant-records", methods=["GET"])
@endpoint(CLINICAL_READERS)
def list_records():
    limit, offset = pagination()
    surgical_case_id = filter_value("surgical_case_id")
    device_unit_id = filter_value("device_unit_id")
    patient_id = filter_value("patient_id")
    status = filter_enum("status", RECORD_STATES)
    rows = []
    for row in db.implant_records.values():
        if surgical_case_id is not None and row["surgical_case_id"] != surgical_case_id:
            continue
        if device_unit_id is not None and row["device_unit_id"] != device_unit_id:
            continue
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.implant_record(r) for r in page], limit, offset, total)


@bp.route("/udi/implant-records/<implant_record_id>/verify", methods=["POST"])
@endpoint([CIRC_CLINICIAN, COMPLIANCE_OFFICER])
def verify_record(implant_record_id):
    record = must("implant_record_id", implant_record_id)

    if record["status"] not in ("DOCUMENTED", "AMENDED"):           # step 8
        raise ApiError("ERR_INVALID_RECORD_STATE", "Only a DOCUMENTED or AMENDED record verifies.")

    if actor() == record.get("documented_by_user_id"):              # step 9
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The documenting user may not verify the record."
        )

    record["status"] = "VERIFIED"
    record["verified_by_user_id"] = actor()
    record["verified_at_utc"] = clock_iso()
    touch(record)

    unit = db.device_units.get(record["device_unit_id"])
    item = catalog_of_unit(unit)
    patient = db.patients.get(record["patient_id"])
    if (
        item is not None
        and item.get("registry_required")
        and not submissions_of_record(record["id"])
    ):
        declined = patient is not None and patient.get("registry_consent") == "DECLINED"
        submission = base_record()
        submission.update(
            {
                "implant_record_id": record["id"],
                "status": "EXEMPT" if declined else "REQUIRED",
                "registry_code": None,
                "submitted_at_utc": None,
                "adjudicated_at_utc": None,
                "rejection_reason": None,
                "resubmission_count": 0,
                "deadline_utc": iso_like(
                    plus_days(clock_dt(), REGISTRY_DEADLINE_DAYS), clock_iso()
                ),
            }
        )
        db.registry_submissions[submission["id"]] = submission

    case_close_readiness(db.cases.get(record["surgical_case_id"]))
    return object_response(serialize.implant_record(record))


@bp.route("/udi/implant-records/<implant_record_id>/amend", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def amend_record(implant_record_id):
    record = must("implant_record_id", implant_record_id)

    if record["status"] != "VERIFIED":                              # step 8
        raise ApiError("ERR_INVALID_RECORD_STATE", "Only a VERIFIED record can be amended.")

    record["status"] = "AMENDED"
    record["amendment_count"] = record.get("amendment_count", 0) + 1
    touch(record)

    for submission in submissions_of_record(record["id"]):
        if submission["status"] == "SUBMITTED":
            submission["status"] = "REQUIRED"
            touch(submission)

    case_close_readiness(db.cases.get(record["surgical_case_id"]))
    return object_response(serialize.implant_record(record))


@bp.route("/udi/implant-records/<implant_record_id>/explants", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def create_explant(implant_record_id):
    data = body()
    reason = req_enum(data, "reason", EXPLANT_REASONS)
    replacement_id = opt_str(data, "replacement_device_unit_id")

    record = must("implant_record_id", implant_record_id)           # step 4
    maybe("replacement_device_unit_id", replacement_id)             # step 5

    if record["status"] != "VERIFIED":                              # step 8
        raise ApiError("ERR_INVALID_RECORD_STATE", "Only a VERIFIED record can be explanted.")

    unit = db.device_units.get(record["device_unit_id"])
    if unit is None or unit["custody_state"] != "IMPLANTED":        # step 16
        raise ApiError("ERR_INVALID_UNIT_STATE", "The device unit is not IMPLANTED.")

    explant = base_record()
    explant.update(
        {
            "implant_record_id": record["id"],
            "replacement_device_unit_id": replacement_id,
            "status": "RECORDED",
            "reason": reason,
            "explanted_at_utc": clock_iso(),
            "return_authorization_no": None,
            "credit_expected_cents": explant_return_credit(unit),
            "credit_issued_cents": None,
        }
    )
    db.explant_records[explant["id"]] = explant

    record["status"] = "EXPLANTED"
    touch(record)

    set_custody(unit, "EXPLANTED")
    if unit["billing_state"] in ("BILLABLE", "INVOICED"):
        set_billing(unit, "CREDIT_PENDING")

    case = db.cases.get(record["surgical_case_id"])
    for charge in charges_of_record(record["id"]):
        if charge["status"] == "POSTED":
            charge["status"] = "CORRECTION_REQUIRED"
            touch(charge)
    recompute_case_totals(case)
    case_close_readiness(case)
    return object_response(serialize.explant_record(explant), 201)
