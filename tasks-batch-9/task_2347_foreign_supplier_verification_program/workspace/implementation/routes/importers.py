"""Importer, QualifiedIndividual and the inspection records package."""
from flask import Blueprint

import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import iso_ms, object_response
from routes._common import find, paged
from shapes import (
    body,
    opt_bool,
    opt_int,
    opt_str,
    pagination,
    present,
    query_dt,
    query_enum,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("importers", __name__)

DESIGNATION_ACTIONS = ("DESIGNATE", "RENEW_TRAINING", "LAPSE", "REVOKE")


# --------------------------------------------------------------- Importer
@bp.post("/fsvp/importers")
@endpoint([CO])
def create_importer():
    b = body()
    legal_name = req_str(b, "legal_name", minlen=1)
    dnb_number = req_str(b, "dnb_number")
    if len(dnb_number) != 9 or not dnb_number.isdigit() or not dnb_number.isascii():
        fail("ERR_INVALID_REQUEST", "dnb_number must be exactly 9 ASCII digits")
    ufi = req_str(b, "unique_facility_identifier", minlen=1, maxlen=32)
    small = opt_bool(b, "small_importer_flag", default=False)
    retention = opt_int(b, "record_retention_months", lo=24, hi=120, default=24)

    for row in store.importers.values():
        if row["dnb_number"] == dnb_number:
            fail("ERR_DUPLICATE_IDENTIFIER", "dnb_number already registered")
        if row["unique_facility_identifier"] == ufi:
            fail("ERR_DUPLICATE_IDENTIFIER", "unique_facility_identifier already registered")

    with write_txn():
        row = store.new_row("importer")
        row.update(
            {
                "legal_name": legal_name,
                "dnb_number": dnb_number,
                "unique_facility_identifier": ufi,
                "small_importer_flag": small,
                "record_retention_months": retention,
            }
        )
        store.insert(row)
    return object_response(serialize.importer_out(row), 201)


@bp.get("/fsvp/importers/<importer_id>")
@endpoint([CO, QI, FDA])
def read_importer(importer_id):
    row = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")
    return object_response(serialize.importer_out(row))


@bp.get("/fsvp/importers/<importer_id>/records-package")
@endpoint([FDA, CO])
def records_package(importer_id):
    record_type = query_enum("record_type", core.ACTIVITY_TYPES)
    as_of = query_dt("as_of_iso8601") or core.clock()
    importer = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")

    records = core.records_of_importer(importer["id"])
    if record_type is not None:
        filtered = []
        for record in records:
            activity = core.activity_of_record(record)
            if activity is not None and activity["activity_type"] == record_type:
                filtered.append(record)
        records = filtered

    retained = len(records)
    available = 0
    expired = 0
    rescinded = 0
    for record in records:
        if record["record_status"] == "RESCINDED":
            rescinded += 1
        elif as_of <= core.record_retained_until(record):
            available += 1
        else:
            expired += 1

    data = {
        "importer_id": importer["id"],
        "program_status": core.importer_program_status(importer),
        "retained_record_count": retained,
        "available_for_inspection_count": available,
        "expired_record_count": expired,
        "rescinded_record_count": rescinded,
        "qualified_individual_designated": core.importer_qi_designated(importer),
        "generated_at": iso_ms(core.clock()),
    }
    return object_response(data)


# ------------------------------------------------------ QualifiedIndividual
@bp.post("/fsvp/qualified-individuals")
@endpoint([CO])
def create_qi():
    b = body()
    importer_id = req_str(b, "importer_id")
    full_name = req_str(b, "full_name", minlen=1)
    email = req_str(b, "email", minlen=1)
    summary = req_str(b, "qualification_summary", minlen=20)
    training_completed_at = req_dt(b, "training_completed_at")
    capacity = opt_int(b, "concurrent_activity_capacity", lo=1, hi=6, default=2)

    find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")

    for row in store.qis.values():
        if row["importer_id"] == importer_id and row["email"] == email:
            fail("ERR_DUPLICATE_IDENTIFIER", "email already used for this importer")

    with write_txn():
        row = store.new_row("qi")
        row.update(
            {
                "importer_id": importer_id,
                "full_name": full_name,
                "email": email,
                "qualification_summary": summary,
                "training_completed_at": training_completed_at,
                "concurrent_activity_capacity": capacity,
                "status": "PROPOSED",
            }
        )
        store.insert(row)
    return object_response(serialize.qi_out(row), 201)


@bp.get("/fsvp/importers/<importer_id>/qualified-individuals")
@endpoint([CO, QI, FDA])
def list_importer_qis(importer_id):
    status = query_enum("status", core.QI_STATUSES)
    limit, offset = pagination()
    importer = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")
    rows = core.qis_of_importer(importer["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.qi_out, limit, offset)


@bp.post("/fsvp/qualified-individuals/<qi_id>/designation")
@endpoint([CO])
def qi_designation(qi_id):
    b = body()
    action = req_enum(b, "action", DESIGNATION_ACTIONS)
    opt_str(b, "note")
    training_completed_at = None
    if action == "RENEW_TRAINING":
        training_completed_at = req_dt(b, "training_completed_at")
        if training_completed_at > core.clock():
            fail("ERR_INVALID_REQUEST", "training_completed_at must not be in the future")
    elif present(b, "training_completed_at"):
        training_completed_at = req_dt(b, "training_completed_at")

    qi = find("qi", qi_id, "ERR_QI_NOT_FOUND")
    status = qi["status"]

    allowed = {
        "DESIGNATE": ("PROPOSED",),
        "LAPSE": ("ACTIVE",),
        "RENEW_TRAINING": ("ACTIVE", "LAPSED"),
        "REVOKE": ("PROPOSED", "ACTIVE", "LAPSED"),
    }
    if status not in allowed[action]:
        fail("ERR_INVALID_STATE_TRANSITION", "cannot %s a %s qualified individual" % (action, status))

    if action == "DESIGNATE":
        if core.qi_training_valid_until(qi) < core.clock():
            fail("ERR_QI_DESIGNATION_INVALID", "training is no longer current")
    if action == "RENEW_TRAINING" and status == "LAPSED":
        if core.add_months(training_completed_at, core.TRAINING_VALIDITY_MONTHS) < core.clock():
            fail("ERR_QI_DESIGNATION_INVALID", "the submitted training has already expired")

    with write_txn():
        if action == "DESIGNATE":
            qi["status"] = "ACTIVE"
        elif action == "LAPSE":
            qi["status"] = "LAPSED"
        elif action == "REVOKE":
            qi["status"] = "REVOKED"
        else:
            qi["training_completed_at"] = training_completed_at
            qi["status"] = "ACTIVE"
        store.touch(qi)
    return object_response(serialize.qi_out(qi))
