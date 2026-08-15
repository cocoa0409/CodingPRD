"""ArchivedRecordRetrieval endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id, logical_now_iso, parse_iso, to_iso_ms
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    get_order,
    get_retrieval,
    get_student,
    logical_now,
    ref_lookup,
    ser_retrieval,
    sorted_created,
    stamp,
    touch,
    RETRIEVAL_SLA_HOURS,
)
from util import as_str, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("retrievals", __name__)

CREATE_ROLES = ["RegistrarOperator", "ArchiveClerk"]
READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "ArchiveClerk"]
STUDENT_READ = READ_ROLES + ["Student"]
CLERK = ["ArchiveClerk"]


def _check_sla(rec):
    """Advancing a retrieval after sla_due_at without escalation is rejected."""
    if logical_now() > parse_iso(rec["sla_due_at"]):
        raise ApiError(
            "ERR_RETRIEVAL_SLA_BREACHED",
            422,
            "Retrieval SLA has been breached",
        )


@bp.post("/registrar/archived-retrievals")
def create_retrieval():
    user_id, role = auth(CREATE_ROLES)
    data = body()
    reject_unknown_fields(data, {"student_id", "requested_by_order_id"})
    student_id = required(data, "student_id")
    requested_by_order_id = required(data, "requested_by_order_id")
    ref_lookup("students", student_id, "Student")
    ref_lookup("orders", requested_by_order_id, "TranscriptOrder")

    rec = {
        "id": new_id(),
        "student_id": student_id,
        "requested_by_order_id": requested_by_order_id,
        "retrieval_status": "REQUESTED",
        "sla_due_at": to_iso_ms(logical_now() + timedelta(hours=RETRIEVAL_SLA_HOURS)),
        "digitized_record_id": None,
    }
    stamp(rec)
    DB["archived_retrievals"][rec["id"]] = rec
    return ok(ser_retrieval(rec), status=201)


@bp.get("/registrar/archived-retrievals")
def list_retrievals():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["archived_retrievals"].values())
    sid = request.args.get("student_id")
    if sid is not None:
        items = [r for r in items if r["student_id"] == sid]
    st = request.args.get("retrieval_status")
    if st is not None:
        items = [r for r in items if r["retrieval_status"] == st]
    oid = request.args.get("requested_by_order_id")
    if oid is not None:
        items = [r for r in items if r["requested_by_order_id"] == oid]
    drid = request.args.get("digitized_record_id")
    if drid is not None:
        items = [r for r in items if r.get("digitized_record_id") == drid]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_retrieval(r) for r in page], total, limit, offset)


@bp.get("/registrar/archived-retrievals/<rid>")
def get_one_retrieval(rid):
    auth(READ_ROLES)
    return ok(ser_retrieval(get_retrieval(rid)))


@bp.get("/registrar/students/<sid>/archived-retrievals")
def list_student_retrievals(sid):
    auth(STUDENT_READ)
    get_student(sid)
    limit, offset = pagination_args()
    items = [r for r in DB["archived_retrievals"].values() if r["student_id"] == sid]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_retrieval(r) for r in page], total, limit, offset)


@bp.post("/registrar/archived-retrievals/<rid>/mark-pulled")
def mark_pulled(rid):
    auth(CLERK)
    rec = get_retrieval(rid)
    if rec["retrieval_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retrieval is not REQUESTED")
    _check_sla(rec)
    rec["retrieval_status"] = "PULLED"
    touch(rec)
    return ok(ser_retrieval(rec))


@bp.post("/registrar/archived-retrievals/<rid>/attach-record")
def attach_record(rid):
    auth(CLERK)
    rec = get_retrieval(rid)
    data = body()
    reject_unknown_fields(data, {"digitized_record_id"})
    record_id = as_str(required(data, "digitized_record_id"), "digitized_record_id")
    if rec["retrieval_status"] != "PULLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retrieval is not PULLED")
    # digitized_record_id must reference an existing StudentRecord for the
    # same student.
    record = DB["student_records"].get(record_id)
    if record is None or record["student_id"] != rec["student_id"]:
        raise ApiError(
            "ERR_REFERENCED_NOT_FOUND",
            404,
            "digitized_record_id does not reference a StudentRecord for this student",
        )
    _check_sla(rec)
    rec["digitized_record_id"] = record_id
    rec["retrieval_status"] = "DIGITIZED"
    touch(rec)
    return ok(ser_retrieval(rec))


@bp.post("/registrar/archived-retrievals/<rid>/attach-to-order")
def attach_to_order(rid):
    auth(CLERK)
    rec = get_retrieval(rid)
    if rec["retrieval_status"] != "DIGITIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retrieval is not DIGITIZED")
    order = get_order(rec["requested_by_order_id"])
    if order["fulfillment_status"] != "READY_TO_FULFILL":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Requested-by order is not READY_TO_FULFILL",
        )
    _check_sla(rec)
    rec["retrieval_status"] = "ATTACHED"
    touch(rec)
    # Cascade: dependent PENDING line items on the order become QUEUED.
    for line in DB["order_line_items"].values():
        if (
            line["order_id"] == order["id"]
            and line.get("archived_retrieval_id") == rec["id"]
            and line["line_status"] == "PENDING"
        ):
            line["line_status"] = "QUEUED"
            touch(line)
    return ok(ser_retrieval(rec))


@bp.post("/registrar/archived-retrievals/<rid>/mark-failed")
def mark_failed(rid):
    auth(CLERK)
    rec = get_retrieval(rid)
    if rec["retrieval_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retrieval is not REQUESTED")
    rec["retrieval_status"] = "FAILED"
    touch(rec)
    return ok(ser_retrieval(rec))
