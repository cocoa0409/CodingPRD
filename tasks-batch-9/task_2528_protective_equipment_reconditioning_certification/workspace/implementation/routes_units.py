"""EquipmentUnit endpoints (PRD 3.3, 3.4, 3.7, 3.8)."""
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
from response import ok_list, paginate
from util import day_start

bp = Blueprint("units", __name__)

PLANT_READ = ("PlantManager", "IntakeClerk", "Technician", "CertifyingInspector",
              "ComplianceOfficer")


def _sub_listing(rows, serializer):
    rows = db.ordered(rows)
    page, meta = paginate(rows)
    return ok_list([serializer(row) for row in page], meta)


@bp.post("/equipment-units")
def create_unit():
    authorize(("IntakeClerk",))
    data = validate.body()
    intake_shipment_id = validate.req_id(data, "intake_shipment_id")
    serial_number = validate.req_str(data, "serial_number", max_len=80)
    declared_model_code = validate.opt_str(data, "declared_model_code", max_len=40)
    shipment = helpers.shipment(intake_shipment_id)

    if shipment["status"] not in ("COUNTED", "QUARANTINED"):
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "Units may only be registered against a counted shipment.")
    counted = shipment["counted_unit_count"] or 0
    if (shipment["units_registered"] or 0) + 1 > counted:
        raise ApiError("ERR_UNIT_COUNT_EXCEEDED",
                       "The shipment already carries every counted unit.")
    account_id = shipment["customer_account_id"]
    for row in db.db.equipment_units.values():
        if row["serial_number"] != serial_number:
            continue
        sibling = db.db.intake_shipments.get(row["intake_shipment_id"])
        if sibling is not None and sibling["customer_account_id"] == account_id:
            raise ApiError("ERR_SERIAL_DUPLICATE",
                           "This serial number already exists for the program.")

    record = db.base_record()
    record.update({
        "intake_shipment_id": intake_shipment_id,
        "serial_number": serial_number,
        "declared_model_code": declared_model_code,
        "model_spec_id": None,
        "manufacture_date": None,
        "age_basis": None,
        "service_age_years": None,
        "life_expired": False,
        "inspection_verdict_summary": "PENDING",
        "condemn_required": False,
        "warranty_coverage": "PENDING",
        "retest_count": 0,
        "current_si": None,
        "certified_at": None,
        "record_retention_until": None,
        "records_purged_at": None,
        "condemn_reason": None,
        "recon_status": "RECEIVED",
        "custody_status": "AT_PLANT",
        "released_to": None,
    })
    db.db.equipment_units[record["id"]] = record
    shipment["units_registered"] = (shipment["units_registered"] or 0) + 1
    touch(shipment)
    return helpers.single(record, serialize.equipment_unit, 201)


@bp.get("/equipment-units/<row_id>")
def get_unit(row_id):
    authorize(PLANT_READ)
    return helpers.single(helpers.unit(row_id), serialize.equipment_unit)


@bp.get("/equipment-units")
def list_units():
    authorize(PLANT_READ)
    filters = {
        "intake_shipment_id": validate.query_str("intake_shipment_id"),
        "model_spec_id": validate.query_str("model_spec_id"),
        "recon_status": validate.query_enum("recon_status", calc.RECON_STATUSES),
        "custody_status": validate.query_enum("custody_status", calc.CUSTODY_STATUSES),
    }
    return helpers.listing("equipment_units", serialize.equipment_unit, filters)


@bp.post("/equipment-units/<row_id>/identify")
def identify_unit(row_id):
    authorize(("IntakeClerk",))
    data = validate.body()
    model_spec_id = validate.req_id(data, "model_spec_id")
    manufacture_date, manufacture_raw = validate.req_dt(data, "manufacture_date")
    age_basis = validate.req_enum(data, "age_basis", calc.AGE_BASES)
    record = helpers.unit(row_id)
    helpers.model(model_spec_id)

    if record["recon_status"] != "RECEIVED":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Identification is only defined from RECEIVED.")
    shipment = cascades.shipment_of(record)
    if shipment is None or shipment["status"] not in ("ACCEPTED", "IN_PROCESS"):
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "The unit's shipment has not been accepted into work.")

    record["model_spec_id"] = model_spec_id
    record["manufacture_date"] = manufacture_date
    db.raw_set(record, "manufacture_date", manufacture_raw)
    record["age_basis"] = age_basis
    record["recon_status"] = "IDENTIFIED"
    cascades.refresh_unit_derived(record)
    touch(record)
    cascades.start_processing(shipment)
    return helpers.single(record, serialize.equipment_unit)


@bp.post("/equipment-units/<row_id>/disassemble")
def disassemble_unit(row_id):
    authorize(("Technician",))
    validate.body()
    record = helpers.unit(row_id)
    if record["recon_status"] != "IDENTIFIED" or not record["model_spec_id"]:
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Teardown is only defined from IDENTIFIED.")
    model = cascades.model_of(record)
    if model is not None and model["reconditionable"] is False:
        raise ApiError("ERR_MODEL_NOT_RECONDITIONABLE",
                       "The manufacturer has withdrawn this model from reconditioning.")

    record["recon_status"] = "DISASSEMBLED"
    touch(record)
    return helpers.single(record, serialize.equipment_unit)


@bp.post("/equipment-units/<row_id>/inspections")
def create_inspection(row_id):
    caller = authorize(("Technician",))
    data = validate.body()
    component_code = validate.req_enum(data, "component_code", calc.COMPONENT_CODES)
    measurement_value = validate.req_num(data, "measurement_value")
    measurement_unit = validate.req_str(data, "measurement_unit", max_len=40)
    note = validate.opt_str(data, "note", max_len=1000)
    unit = helpers.unit(row_id)

    if unit["recon_status"] != "DISASSEMBLED":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Inspections are only recorded against a DISASSEMBLED unit.")
    for row in db.db.component_inspections.values():
        if (row["equipment_unit_id"] == unit["id"]
                and row["component_code"] == component_code):
            raise ApiError("ERR_DUPLICATE_INSPECTION",
                           "This component has already been inspected on this unit.")

    model = cascades.model_of(unit)
    criteria = calc.criteria_for(model, component_code) if model else None
    if criteria is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The unit's model carries no criteria for %s." % component_code)
    verdict = calc.component_verdict(measurement_value,
                                     criteria["metric_direction"],
                                     criteria["replace_threshold"],
                                     criteria["fail_threshold"])

    record = db.base_record(versioned=False)
    record.update({
        "equipment_unit_id": unit["id"],
        "component_code": component_code,
        "measurement_value": measurement_value,
        "measurement_unit": measurement_unit,
        "note": note,
        "replace_threshold_applied": criteria["replace_threshold"],
        "fail_threshold_applied": criteria["fail_threshold"],
        "metric_direction_applied": criteria["metric_direction"],
        "verdict": verdict,
        "inspector_user_id": caller.user_id,
    })
    db.db.component_inspections[record["id"]] = record

    cascades.refresh_inspection_summary(unit)
    if (unit["recon_status"] == "DISASSEMBLED"
            and unit["inspection_verdict_summary"] != "PENDING"):
        unit["recon_status"] = "INSPECTED"
    cascades.refresh_condemn_required(unit)
    touch(unit)
    return helpers.single(record, serialize.component_inspection, 201)


@bp.get("/equipment-units/<row_id>/inspections")
def list_inspections(row_id):
    authorize(("PlantManager", "Technician", "CertifyingInspector",
               "ComplianceOfficer"))
    component_code = validate.query_enum("component_code", calc.COMPONENT_CODES)
    verdict = validate.query_enum("verdict", calc.VERDICTS)
    unit = helpers.unit(row_id)
    rows = [row for row in db.db.component_inspections.values()
            if row["equipment_unit_id"] == unit["id"]
            and (component_code is None or row["component_code"] == component_code)
            and (verdict is None or row["verdict"] == verdict)]
    return _sub_listing(rows, serialize.component_inspection)


@bp.post("/equipment-units/<row_id>/condemn")
def condemn_unit(row_id):
    authorize(("CertifyingInspector",))
    data = validate.body()
    # PRD 3.8 supplies a condemn_reason with the request but the persisted value
    # is "derived rather than trusted", so the submitted text is not constrained.
    validate.req_str(data, "condemn_reason", max_len=200)
    record = helpers.unit(row_id)

    if (record["recon_status"] not in ("IDENTIFIED", "DISASSEMBLED", "INSPECTED")
            or not record["condemn_required"]):
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Pre-test condemnation is not defined for this unit.")

    # PRD 3.8: the persisted reason is derived, never trusted from the request.
    if record["life_expired"]:
        reason = "LIFE_EXPIRED"
    elif record["inspection_verdict_summary"] == "FAIL":
        reason = "COMPONENT_FAIL"
    else:
        reason = "NOT_RECONDITIONABLE"
    cascades.condemn_cascade(record, reason)
    return helpers.single(record, serialize.equipment_unit)


@bp.post("/equipment-units/<row_id>/stage-return")
def stage_return(row_id):
    authorize(("IntakeClerk",))
    validate.body()
    record = helpers.unit(row_id)
    if record["custody_status"] != "AT_PLANT" or record["recon_status"] != "CERTIFIED":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Staging is only defined for a certified unit at the plant.")
    record["custody_status"] = "STAGED_FOR_RETURN"
    touch(record)
    return helpers.single(record, serialize.equipment_unit)


@bp.post("/equipment-units/<row_id>/release")
def release_unit(row_id):
    authorize(("IntakeClerk",))
    data = validate.body()
    released_to = validate.req_str(data, "released_to", max_len=200)
    record = helpers.unit(row_id)

    if (record["custody_status"] != "STAGED_FOR_RETURN"
            or record["recon_status"] != "CERTIFIED"):
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Release is only defined for a staged certified unit.")
    account = cascades.account_of_unit(record)
    if account is None or account["liability_waiver_status"] != "ON_FILE":
        raise ApiError("ERR_LIABILITY_WAIVER_MISSING",
                       "The program has no current liability waiver on file.")

    record["custody_status"] = "RETURNED"
    record["released_to"] = released_to
    touch(record)
    cascades.release_unit_counters(record)
    return helpers.single(record, serialize.equipment_unit)


@bp.post("/equipment-units/<row_id>/purge-records")
def purge_records(row_id):
    authorize(("ComplianceOfficer",))
    validate.body()
    record = helpers.unit(row_id)
    retention = record["record_retention_until"]
    if retention is None or retention >= db.now():
        raise ApiError("ERR_RETENTION_ACTIVE",
                       "The record retention term has not yet elapsed.")
    record["records_purged_at"] = db.now()
    touch(record)
    return helpers.single(record, serialize.equipment_unit)


@bp.get("/equipment-units/<row_id>/certification-labels")
def list_unit_labels(row_id):
    authorize(("PlantManager", "IntakeClerk", "CertifyingInspector",
               "ComplianceOfficer"))
    status = validate.query_enum("status", calc.LABEL_STATUSES)
    unit = helpers.unit(row_id)
    rows = [row for row in db.db.certification_labels.values()
            if row["equipment_unit_id"] == unit["id"]
            and (status is None or row["status"] == status)]
    return _sub_listing(rows, serialize.certification_label)


@bp.get("/equipment-units/<row_id>/destruction-records")
def list_unit_destructions(row_id):
    authorize(("PlantManager", "CertifyingInspector", "ComplianceOfficer"))
    status = validate.query_enum("status", calc.DESTRUCTION_STATUSES)
    unit = helpers.unit(row_id)
    rows = [row for row in db.db.destruction_records.values()
            if row["equipment_unit_id"] == unit["id"]
            and (status is None or row["status"] == status)]
    return _sub_listing(rows, serialize.destruction_record)
