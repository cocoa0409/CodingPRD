"""VerificationRecord: filing, attestation and compensating rescission."""
from datetime import timedelta

from flask import Blueprint, g

import cascades
import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import find, paged, require_qi_current
from shapes import (
    body,
    opt_int,
    pagination,
    query_dt,
    query_enum,
    query_str,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("records", __name__)

COOL_OFF = timedelta(days=core.AUDIT_COOL_OFF_DAYS)


def _audit_conflict(supplier_id, performed_start, performed_end):
    """Ladder rung 39 — pairwise closed-interval comparison, never a merged union."""
    widened_start = performed_start - COOL_OFF
    widened_end = performed_end + COOL_OFF
    for existing in core.records_of_supplier(supplier_id):
        if existing["record_status"] == "RESCINDED":
            continue
        activity = core.activity_of_record(existing)
        if activity is None or activity["activity_type"] != "ONSITE_AUDIT":
            continue
        # closed intervals: touching endpoints conflict
        if widened_start <= existing["performed_end"] and existing["performed_start"] <= widened_end:
            fail(
                "ERR_AUDIT_WINDOW_CONFLICT",
                "an onsite audit on this supplier falls inside the 30-day cool-off",
            )


@bp.post("/fsvp/verification-records")
@endpoint([QI])
def create_record():
    b = body()
    activity_id = req_str(b, "activity_id")
    outcome = req_enum(b, "outcome", core.OUTCOMES)
    performed_start = req_dt(b, "performed_start")
    performed_end = req_dt(b, "performed_end")
    findings_count = opt_int(b, "findings_count", lo=0, hi=50, default=0)
    document_reference = req_str(b, "document_reference", minlen=4)

    # rung 10
    activity = find("activity", activity_id, "ERR_ACTIVITY_NOT_FOUND")

    # rung 25
    if activity["status"] != "APPROVED":
        fail("ERR_ACTIVITY_NOT_APPROVED", "evidence may only be filed against an approved activity")

    # rung 26
    require_qi_current()

    # rung 36
    if performed_start > performed_end:
        fail("ERR_INVALID_WINDOW", "performed_start must not be after performed_end")

    # rung 37
    if (
        performed_start < activity["window_start"]
        or performed_end >= activity["window_end"]
    ):
        fail(
            "ERR_RECORD_OUTSIDE_ACTIVITY_WINDOW",
            "the performed interval must lie inside the activity window",
        )

    # rung 38
    if performed_end > core.clock():
        fail("ERR_RECORD_IN_FUTURE", "evidence cannot be filed for work that has not happened yet")

    # rung 39
    pair = core.pair_of_activity(activity)
    if activity["activity_type"] == "ONSITE_AUDIT" and pair is not None:
        _audit_conflict(pair["supplier_id"], performed_start, performed_end)

    with write_txn():
        row = store.new_row("record")
        row.update(
            {
                "activity_id": activity_id,
                "submitted_by_qi_id": g.user_id,
                "attested_by_qi_id": None,
                "outcome": outcome,
                "performed_start": performed_start,
                "performed_end": performed_end,
                "findings_count": findings_count,
                "document_reference": document_reference,
                "record_status": "RECEIVED",
            }
        )
        store.insert(row)
    return object_response(serialize.record_out(row), 201)


@bp.get("/fsvp/verification-records/<record_id>")
@endpoint([CO, QI, FDA])
def read_record(record_id):
    as_of = query_dt("as_of_iso8601")
    row = find("record", record_id, "ERR_RECORD_NOT_FOUND")
    return object_response(serialize.record_out(row, as_of))


@bp.get("/fsvp/verification-records")
@endpoint([CO, QI, FDA])
def list_records():
    activity_id = query_str("activity_id")
    submitted_by = query_str("submitted_by_qi_id")
    attested_by = query_str("attested_by_qi_id")
    record_status = query_enum("record_status", core.RECORD_STATUSES)
    outcome = query_enum("outcome", core.OUTCOMES)
    limit, offset = pagination()

    rows = list(store.records.values())
    if activity_id is not None:
        rows = [r for r in rows if r["activity_id"] == activity_id]
    if submitted_by is not None:
        rows = [r for r in rows if r["submitted_by_qi_id"] == submitted_by]
    if attested_by is not None:
        rows = [r for r in rows if r["attested_by_qi_id"] == attested_by]
    if record_status is not None:
        rows = [r for r in rows if r["record_status"] == record_status]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return paged(rows, serialize.record_out, limit, offset)


@bp.post("/fsvp/verification-records/<record_id>/attestation")
@endpoint([QI])
def attest_record(record_id):
    b = body()
    req_str(b, "attestation_note", minlen=1)

    record = find("record", record_id, "ERR_RECORD_NOT_FOUND")

    # rung 24
    if record["record_status"] != "RECEIVED":
        fail(
            "ERR_RECORD_NOT_ATTESTABLE",
            "a %s record cannot be attested" % record["record_status"],
        )

    # rung 26
    require_qi_current()

    # rung 43
    if g.user_id == record["submitted_by_qi_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the submitting qualified individual may not attest")

    pair = core.pair_of_record(record)
    supplier = store.suppliers.get(pair["supplier_id"]) if pair is not None else None

    with write_txn():
        # HOP 1
        record["record_status"] = "ATTESTED"
        record["attested_by_qi_id"] = g.user_id
        store.touch(record)
        if supplier is not None:
            # the supplier's score always moves on attestation
            store.touch(supplier)
            # HOPS 2-6
            cascades.suspension_cascade(supplier)
    return object_response(serialize.record_out(record))


@bp.post("/fsvp/verification-records/<record_id>/rescission")
@endpoint([QI])
def rescind_record(record_id):
    b = body()
    req_str(b, "reason", minlen=1)

    record = find("record", record_id, "ERR_RECORD_NOT_FOUND")

    # rung 24
    if record["record_status"] not in ("RECEIVED", "ATTESTED"):
        fail(
            "ERR_RECORD_NOT_ATTESTABLE",
            "a %s record cannot be rescinded" % record["record_status"],
        )

    pair = core.pair_of_record(record)
    supplier = store.suppliers.get(pair["supplier_id"]) if pair is not None else None

    with write_txn():
        record["record_status"] = "RESCINDED"
        store.touch(record)
        # the compensating reversal restores the pre-attestation score; a suspended
        # supplier is NEVER reinstated here (PRD section 3.6).
        if supplier is not None:
            store.touch(supplier)
    return object_response(serialize.record_out(record))
