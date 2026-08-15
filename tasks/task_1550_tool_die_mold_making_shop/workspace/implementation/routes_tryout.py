"""Tryout sample endpoints: schedule, submit, buyoff, initiate-rework (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, bump)
from domain import ser_sample, tool_by_job, WARRANTY_DAYS

bp = Blueprint("tryout", __name__)


@bp.route("/tryout-samples", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def create_sample(uid, role):
    data = validate_payload(get_body(), [
        ("build_job_id", "str", True),
        ("press_reservation_id", "str", True),
    ])
    job = STORE.jobs.get(data["build_job_id"])
    if job is None:
        not_found("BUILD_JOB")
    res = STORE.press_res.get(data["press_reservation_id"])
    if res is None:
        not_found("PRESS_RESERVATION")
    if job["status"] not in ("IN_BUILD", "TRYOUT_PHASE"):
        raise ApiError("ERR_JOB_PHASE_MISMATCH", 409,
                       "Tryout scheduling requires the job in IN_BUILD or TRYOUT_PHASE")
    if res["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The press reservation must be RESERVED")
    sample = stamp_new({
        "build_job_id": job["id"],
        "press_reservation_id": res["id"],
        "round_number": 1,
        "sample_qty": None,
        "shots_used": None,
        "measured_report_ref": None,
        "defect_codes": None,
        "status": "SCHEDULED",
    })
    STORE.samples[sample["id"]] = sample
    # First sample moves the job from IN_BUILD into TRYOUT_PHASE.
    if job["status"] == "IN_BUILD":
        job["status"] = "TRYOUT_PHASE"
        bump(job)
    return created(ser_sample(sample))


@bp.route("/tryout-samples", methods=["GET"])
@endpoint(roles=None)
def list_samples(uid, role):
    items = sort_created(list(STORE.samples.values()))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_sample(s) for s in page], meta)


@bp.route("/tryout-samples/<sampleId>", methods=["GET"])
@endpoint(roles=None)
def get_sample(uid, role, sampleId):
    sample = STORE.samples.get(sampleId)
    if sample is None:
        not_found("TRYOUT_SAMPLE")
    return ok(ser_sample(sample))


@bp.route("/tryout-samples/<sampleId>/submit", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def submit_sample(uid, role, sampleId):
    data = validate_payload(get_body(), [
        ("sample_qty", "int", True, {"min": 0}),
        ("shots_used", "int", True, {"min": 0}),
        ("measured_report_ref", "str", True),
    ])
    sample = STORE.samples.get(sampleId)
    if sample is None:
        not_found("TRYOUT_SAMPLE")
    if sample["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED sample may be submitted")
    job = STORE.jobs.get(sample["build_job_id"])
    if job is None or job["status"] != "TRYOUT_PHASE":
        raise ApiError("ERR_JOB_PHASE_MISMATCH", 409,
                       "Tryout submit requires the job in TRYOUT_PHASE")
    res = STORE.press_res.get(sample["press_reservation_id"])
    if res is None or res["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The linked press reservation must be RESERVED")
    now_dt = now()
    if not (res["start_time"] <= now_dt < res["end_time"]):
        raise ApiError("ERR_OUTSIDE_RESERVATION_WINDOW", 409,
                       "Submit must fall inside the press window [start, end)")
    sample["sample_qty"] = data["sample_qty"]
    sample["shots_used"] = data["shots_used"]
    sample["measured_report_ref"] = data["measured_report_ref"]
    sample["status"] = "SUBMITTED"
    bump(sample)
    tool = tool_by_job(sample["build_job_id"])
    if tool is not None:
        tool["tryout_shots"] += data["shots_used"]
        if tool["physical_status"] == "IN_BUILD":
            tool["physical_status"] = "TRYOUT"
        bump(tool)
    return ok(ser_sample(sample))


@bp.route("/tryout-samples/<sampleId>/buyoff-decision", methods=["POST"])
@endpoint(roles=["QualityManager"])
def buyoff_decision(uid, role, sampleId):
    body = get_body()
    data = validate_payload(body, [
        ("decision", "enum", True, {"values": {"BOUGHT_OFF", "REJECTED"}}),
        ("defect_codes", "str_list", False),
    ])
    # Shape tier: REJECTED requires a non-empty defect_codes array.
    if data["decision"] == "REJECTED" and not data.get("defect_codes"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "defect_codes must be a non-empty array when rejecting")
    sample = STORE.samples.get(sampleId)
    if sample is None:
        not_found("TRYOUT_SAMPLE")
    if sample["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED sample may receive a buyoff decision")
    if data["decision"] == "REJECTED":
        sample["defect_codes"] = data["defect_codes"]
        sample["status"] = "REJECTED"
        bump(sample)
        return ok(ser_sample(sample))
    # BOUGHT_OFF: terminal for the sample, with bubble-up side effects.
    sample["status"] = "BOUGHT_OFF"
    bump(sample)
    job = STORE.jobs.get(sample["build_job_id"])
    if job is not None and job["status"] == "TRYOUT_PHASE":
        job["status"] = "BUYOFF_PASSED"
        bump(job)
    tool = tool_by_job(sample["build_job_id"])
    if tool is not None:
        if tool["physical_status"] == "TRYOUT":
            tool["physical_status"] = "AWAITING_SHIPMENT"
        tool["warranty_expires_at"] = now() + timedelta(days=WARRANTY_DAYS)
        bump(tool)
    return ok(ser_sample(sample))


@bp.route("/tryout-samples/<sampleId>/initiate-rework", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def initiate_rework(uid, role, sampleId):
    data = validate_payload(get_body(), [
        ("rework_authorization_id", "str", False),
    ])
    sample = STORE.samples.get(sampleId)
    if sample is None:
        not_found("TRYOUT_SAMPLE")
    # Tier 4: body FK existence when supplied.
    ra = None
    if data.get("rework_authorization_id") is not None:
        ra = STORE.ras.get(data["rework_authorization_id"])
        if ra is None:
            not_found("REWORK_AUTHORIZATION")
    # Tier 7: state gates.
    if sample["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REJECTED sample may initiate rework")
    job = STORE.jobs.get(sample["build_job_id"])
    if job is not None and job["status"] == "ON_HOLD":
        raise ApiError("ERR_JOB_ON_HOLD", 409,
                       "Rework may not be initiated while the job is ON_HOLD")
    if job is None or job["status"] not in ("TRYOUT_PHASE", "IN_BUILD"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rework requires the job in TRYOUT_PHASE or IN_BUILD")
    # Tier 10: from the third round onward a valid rework authorization is required.
    if sample["round_number"] >= 3:
        if (ra is None or ra["build_job_id"] != job["id"]
                or ra["status"] not in ("AUTHORIZED", "IN_PROGRESS")):
            raise ApiError("ERR_REWORK_REQUIRES_AUTHORIZATION", 409,
                           "Rework at round 3+ requires an authorization of this job "
                           "in AUTHORIZED or IN_PROGRESS status")
    sample["round_number"] += 1
    sample["sample_qty"] = None
    sample["shots_used"] = None
    sample["measured_report_ref"] = None
    sample["defect_codes"] = None
    sample["status"] = "SCHEDULED"
    bump(sample)
    if ra is not None and ra["status"] == "AUTHORIZED":
        ra["status"] = "IN_PROGRESS"
        bump(ra)
    if job["status"] == "IN_BUILD":
        job["status"] = "TRYOUT_PHASE"
        bump(job)
    return ok(ser_sample(sample))
