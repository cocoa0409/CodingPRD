"""ServiceBenchmark endpoints: queries, fulfill, waive, rescind."""

from flask import Blueprint, request

from db import store, clock_date, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_BENCHMARK_NOT_PENDING,
    ERR_CASE_TRANSFER_PENDING,
    ERR_MEMBER_NOT_ELIGIBLE,
    ERR_EVIDENCE_NOTE_INVALID,
)
from helpers import body_dict, req_string, parse_date_value
from middleware import authenticate, authorize, CASE_MANAGER, AGENCY_DIRECTOR
from response import success_object, success_list
from serializers import ser_benchmark
from services import benchmarks_of_case, members_of, sorted_records
from routes.cases import get_case_or_404

bp = Blueprint("benchmarks", __name__)


def get_benchmark_or_404(benchmark_id):
    bm = store.benchmarks.get(benchmark_id)
    if bm is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Benchmark not found.")
    return bm


@bp.get("/cases/<case_id>/benchmarks")
def list_benchmarks_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    records = sorted_records(benchmarks_of_case(case["id"]))
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    service_type = request.args.get("service_type")
    if service_type is not None:
        records = [b for b in records if b["service_type"] == service_type]
    return success_list(records, ser_benchmark)


@bp.get("/benchmarks/<benchmark_id>")
def get_benchmark(benchmark_id):
    authenticate()
    return success_object(ser_benchmark(get_benchmark_or_404(benchmark_id)))


@bp.get("/benchmarks")
def list_benchmarks():
    authenticate()
    records = sorted_records(store.benchmarks.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        records = [b for b in records if b["case_id"] == case_id]
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    service_type = request.args.get("service_type")
    if service_type is not None:
        records = [b for b in records if b["service_type"] == service_type]
    evidence_note_id = request.args.get("evidence_note_id")
    if evidence_note_id is not None:
        records = [b for b in records if b["evidence_note_id"] == evidence_note_id]
    return success_list(records, ser_benchmark)


@bp.post("/benchmarks/<benchmark_id>/fulfill")
def fulfill_benchmark(benchmark_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    bm = get_benchmark_or_404(benchmark_id)
    d = body_dict()
    # Priority 3: body FK existence — a well-formed evidence_note_id that
    # identifies no existing CaseNote is a not-found (404).
    evidence_note_id = d.get("evidence_note_id")
    note = None
    if evidence_note_id is not None:
        if not isinstance(evidence_note_id, str):
            raise ApiError(ERR_VALIDATION, 400, "evidence_note_id must be a string.")
        note = store.case_notes.get(evidence_note_id)
        if note is None:
            raise ApiError(ERR_NOT_FOUND, 404, "evidence_note_id does not identify an existing note.")
    # Priority 4: schema — fulfilled_on present, valid, and inside
    # [case.actual_arrival_date, current logical clock date].
    fulfilled_on = d.get("fulfilled_on")
    if fulfilled_on is None:
        raise ApiError(ERR_VALIDATION, 400, "Missing required field: fulfilled_on.")
    fulfilled_on = parse_date_value(fulfilled_on, "fulfilled_on")
    case = store.cases[bm["case_id"]]
    if fulfilled_on < case["actual_arrival_date"] or fulfilled_on > clock_date():
        raise ApiError(
            ERR_VALIDATION,
            400,
            "fulfilled_on must be within [actual_arrival_date, current logical clock date].",
        )
    enrolled_member_ids = d.get("enrolled_member_ids")
    if enrolled_member_ids is not None:
        if not isinstance(enrolled_member_ids, list) or any(
            not isinstance(x, str) for x in enrolled_member_ids
        ):
            raise ApiError(ERR_VALIDATION, 400, "enrolled_member_ids must be a list of strings.")
    # Priority 6: state — fulfill requires PENDING
    if bm["status"] != "PENDING":
        raise ApiError(ERR_BENCHMARK_NOT_PENDING, 409, "Benchmark is not PENDING.")
    # Priority 9: transfer freeze, then school-enrollment member eligibility
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    if bm["service_type"] == "SCHOOL_ENROLLMENT":
        school_age_ids = {
            m["id"] for m in members_of(case["id"]) if m["school_age_at_arrival"] is True
        }
        if set(enrolled_member_ids or []) != school_age_ids:
            raise ApiError(
                ERR_MEMBER_NOT_ELIGIBLE,
                422,
                "enrolled_member_ids must equal exactly the school-age member set.",
            )
    # Priority 10: evidence linkage — note must exist, belong to this case,
    # and be a SERVICE_DELIVERY note (a missing note id is invalid evidence).
    if note is None:
        raise ApiError(ERR_EVIDENCE_NOTE_INVALID, 422, "evidence_note_id is missing.")
    if note["case_id"] != bm["case_id"] or note["note_type"] != "SERVICE_DELIVERY":
        raise ApiError(
            ERR_EVIDENCE_NOTE_INVALID,
            422,
            "Evidence note must be a SERVICE_DELIVERY note of the benchmark's case.",
        )
    bm["status"] = "MET"
    bm["fulfilled_on"] = fulfilled_on
    bm["evidence_note_id"] = note["id"]
    bm["on_time"] = fulfilled_on <= bm["due_date"]
    touch(bm)
    return success_object(ser_benchmark(bm), 200)


@bp.post("/benchmarks/<benchmark_id>/waive")
def waive_benchmark(benchmark_id):
    _uid, role = authenticate()
    authorize(role, {AGENCY_DIRECTOR})
    bm = get_benchmark_or_404(benchmark_id)
    d = body_dict()
    # Priority 4: schema
    reason = req_string(d, "reason")
    # Priority 6: state
    if bm["status"] != "PENDING":
        raise ApiError(ERR_BENCHMARK_NOT_PENDING, 409, "Benchmark is not PENDING.")
    # Priority 9: transfer freeze
    case = store.cases[bm["case_id"]]
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    bm["status"] = "WAIVED"
    bm["waived_reason"] = reason
    touch(bm)
    return success_object(ser_benchmark(bm), 200)


@bp.post("/benchmarks/<benchmark_id>/rescind")
def rescind_benchmark(benchmark_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    bm = get_benchmark_or_404(benchmark_id)
    # Priority 6: rescind is defined only from MET, and only for manually
    # fulfilled benchmarks (auto-fulfilled CULTURAL_ORIENTATION has no note).
    if bm["status"] != "MET":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a MET benchmark can be rescinded.")
    if bm["evidence_note_id"] is None:
        raise ApiError(
            ERR_INVALID_STATE, 409, "Auto-fulfilled benchmarks cannot be rescinded."
        )
    # Priority 9: transfer freeze
    case = store.cases[bm["case_id"]]
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    bm["status"] = "PENDING"
    bm["fulfilled_on"] = None
    bm["evidence_note_id"] = None
    bm["on_time"] = None
    touch(bm)
    return success_object(ser_benchmark(bm), 200)
