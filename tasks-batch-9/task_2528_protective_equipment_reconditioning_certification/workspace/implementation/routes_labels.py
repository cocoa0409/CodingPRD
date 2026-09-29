"""CertificationLabel and DestructionRecord endpoints (PRD 3.7, 3.8)."""
from flask import Blueprint

import calc
import cascades
import db
import helpers
import serialize
import validate
from auth import authorize
from db import touch
from errors import ApiError
from util import add_days, day_start

bp = Blueprint("labels", __name__)

LABEL_READ_ROLES = ("PlantManager", "IntakeClerk", "CertifyingInspector",
                    "ComplianceOfficer")
DESTRUCTION_READ_ROLES = ("PlantManager", "CertifyingInspector", "ComplianceOfficer")


def _latest_determined_at(unit_id):
    """The instant the unit's most recent DETERMINED session was signed."""
    signed = [row for row in db.db.shell_tests.values()
              if row["equipment_unit_id"] == unit_id and row["status"] == "DETERMINED"]
    if not signed:
        return None
    signed.sort(key=lambda r: (r["updated_at"], r["_seq"]))
    return signed[-1]["updated_at"]


@bp.post("/certification-labels")
def issue_label():
    caller = authorize(("CertifyingInspector",))
    data = validate.body()
    equipment_unit_id = validate.req_id(data, "equipment_unit_id")
    expected_version = validate.req_int(data, "expected_equipment_unit_version")
    unit = helpers.unit(equipment_unit_id)

    if unit["recon_status"] != "TEST_PASSED":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Only a TEST_PASSED unit can be labelled.")
    if unit["condemn_required"]:
        raise ApiError("ERR_CONDEMN_REQUIRED",
                       "This unit is flagged for condemnation and cannot be certified.")
    anchor = _latest_determined_at(unit["id"])
    if anchor is not None and db.now() > add_days(anchor,
                                                 calc.LABEL_ISSUE_WINDOW_DAYS):
        raise ApiError("ERR_LABEL_WINDOW_EXPIRED",
                       "A two-week-old pass is not a current certification.")
    account = cascades.account_of_unit(unit)
    if account is not None and account["status"] == "BILLING_HOLD":
        raise ApiError("ERR_ACCOUNT_ON_HOLD",
                       "The owning program's account is on a billing hold.")
    if expected_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION",
                       "The unit has moved on since it was read.")

    model = cascades.model_of(unit)
    standard_code_snapshot = model["standard_code"] if model else None
    certified_on = day_start(db.now())
    label_code, daily_sequence = calc.certification_label_code(
        standard_code_snapshot, certified_on)

    record = db.base_record()
    record.update({
        "equipment_unit_id": unit["id"],
        "label_code": label_code,
        "standard_code_snapshot": standard_code_snapshot,
        "certified_on": certified_on,
        "daily_sequence": daily_sequence,
        "issued_by_user_id": caller.user_id,
        "void_reason": None,
        "voided_at": None,
        "voided_by_user_id": None,
        "status": "ACTIVE",
    })
    db.db.certification_labels[record["id"]] = record

    unit["recon_status"] = "CERTIFIED"
    unit["certified_at"] = db.now()
    retention_years = model["record_retention_years"] if model else 0
    unit["record_retention_until"] = calc.retention_until(unit["certified_at"],
                                                          retention_years)
    touch(unit)
    cascades.certify_unit_counters(unit)
    return helpers.single(record, serialize.certification_label, 201)


@bp.get("/certification-labels/<row_id>")
def get_label(row_id):
    authorize(LABEL_READ_ROLES)
    return helpers.single(helpers.label(row_id), serialize.certification_label)


@bp.post("/certification-labels/<row_id>/void")
def void_label(row_id):
    caller = authorize(("ComplianceOfficer",))
    data = validate.body()
    void_reason = validate.req_str(data, "void_reason", max_len=500)
    record = helpers.label(row_id)

    if record["status"] != "ACTIVE":
        raise ApiError("ERR_LABEL_ALREADY_VOIDED",
                       "This label has already been voided.")
    unit = db.db.equipment_units.get(record["equipment_unit_id"])
    if (unit is None
            or unit["custody_status"] not in ("AT_PLANT", "STAGED_FOR_RETURN")
            or unit["recon_status"] != "CERTIFIED"):
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "A unit no longer in the plant's hands cannot be un-certified.")
    shipment = cascades.shipment_of(unit)
    if shipment is not None and shipment["settlement_locked"]:
        raise ApiError("ERR_SETTLEMENT_LOCKED",
                       "The shipment has already been settled.")

    # hop 1 — the label itself
    record["status"] = "VOIDED"
    record["voided_at"] = db.now()
    record["voided_by_user_id"] = caller.user_id
    record["void_reason"] = void_reason
    touch(record)
    # hop 2 — the unit reverts and its retention clock is unwound
    unit["recon_status"] = "REPAIR_PENDING"
    unit["certified_at"] = None
    unit["record_retention_until"] = None
    touch(unit)
    # hops 3 and 4 — the disposition ledger and the shipment/account rollback
    cascades.void_unit_counters(unit)
    return helpers.single(record, serialize.certification_label)


@bp.get("/destruction-records/<row_id>")
def get_destruction_record(row_id):
    authorize(DESTRUCTION_READ_ROLES)
    return helpers.single(helpers.destruction(row_id), serialize.destruction_record)


@bp.post("/destruction-records/<row_id>/witness")
def witness_destruction(row_id):
    caller = authorize(("ComplianceOfficer",))
    data = validate.body()
    method = validate.req_enum(data, "method", calc.DESTRUCTION_METHODS)
    witness_name = validate.req_str(data, "witness_name", max_len=200)
    record = helpers.destruction(row_id)

    if record["status"] != "PENDING":
        raise ApiError("ERR_DESTRUCTION_STATE_INVALID",
                       "Only a PENDING destruction record can be witnessed.")
    unit = db.db.equipment_units.get(record["equipment_unit_id"])
    if unit is None or unit["custody_status"] != "PENDING_DISPOSAL":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "The unit is not awaiting disposal.")

    record["method"] = method
    record["witness_name"] = witness_name
    record["witnessed_by_user_id"] = caller.user_id
    record["witnessed_at"] = db.now()
    record["status"] = "WITNESSED"
    touch(record)
    return helpers.single(record, serialize.destruction_record)


@bp.post("/destruction-records/<row_id>/verify")
def verify_destruction(row_id):
    caller = authorize(("ComplianceOfficer",))
    data = validate.body()
    verification_ref = validate.req_str(data, "verification_ref", max_len=200)
    record = helpers.destruction(row_id)

    if record["status"] != "WITNESSED":
        raise ApiError("ERR_DESTRUCTION_STATE_INVALID",
                       "Only a WITNESSED destruction record can be verified.")
    if caller.user_id is not None and caller.user_id == record["witnessed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The witnessing officer cannot also certify the evidence.")

    record["verification_ref"] = verification_ref
    record["verified_by_user_id"] = caller.user_id
    record["verified_at"] = db.now()
    record["status"] = "VERIFIED"
    touch(record)

    unit = db.db.equipment_units.get(record["equipment_unit_id"])
    if unit is not None:
        unit["custody_status"] = "DISPOSED"
        model = cascades.model_of(unit)
        retention_years = model["record_retention_years"] if model else 0
        unit["record_retention_until"] = calc.retention_until(record["verified_at"],
                                                              retention_years)
        touch(unit)
    return helpers.single(record, serialize.destruction_record)
