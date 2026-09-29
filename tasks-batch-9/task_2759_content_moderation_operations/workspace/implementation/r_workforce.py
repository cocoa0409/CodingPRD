"""Review queues and the reviewer workforce (PRD §3.3 queues, §3.4, §3.6)."""

from datetime import timedelta

from flask import Blueprint

import ser
from core import (
    LANGUAGES, REVIEWER_STATUSES, ROLE_CLASSES, SPECIALTIES, base_fields, body,
    created, db, enum_filter, fail, listing, now, now_iso, ok, opt_int, opt_str,
    paginate_args, parse_iso, req_enum, req_enum_array,
    req_int, req_str, require, str_filter, touch,
)
from svc import find, plus_minutes, release_cases_to_queue

bp = Blueprint("workforce", __name__)


@bp.post("/review-queues")
def create_queue():
    require("TrustSafetyAdmin")
    payload = body()
    name = req_str(payload, "name", 1, 80)
    category_id = req_str(payload, "policy_category_id", 1, None)
    language = req_enum(payload, "language", LANGUAGES)
    specialty = req_enum(payload, "specialty", SPECIALTIES)

    category = find(db.policy_categories, category_id, "ERR_CATEGORY_NOT_FOUND")
    if specialty != category["specialty"]:
        fail("ERR_QUEUE_SPECIALTY_MISMATCH",
             "The queue's specialty must equal its category's specialty.")

    record = {
        "name": name,
        "policy_category_id": category_id,
        "language": language,
        "specialty": specialty,
        "open_case_count": 0,
        "unassigned_case_count": 0,
    }
    base_fields(record)
    db.review_queues[record["id"]] = record
    return created(ser.review_queue(record))


@bp.get("/review-queues/<queue_id>")
def get_queue(queue_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    record = find(db.review_queues, queue_id, "ERR_QUEUE_NOT_FOUND")
    return ok(ser.review_queue(record))


@bp.get("/review-queues")
def list_queues():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    limit, offset = paginate_args()
    category_id = str_filter("policy_category_id")
    language = enum_filter("language", LANGUAGES)
    records = []
    for record in db.review_queues.values():
        if category_id is not None and record["policy_category_id"] != category_id:
            continue
        if language is not None and record["language"] != language:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.review_queue)


@bp.post("/reviewers")
def create_reviewer():
    require("TrustSafetyAdmin")
    payload = body()
    display_name = req_str(payload, "display_name", 1, 80)
    languages = req_enum_array(payload, "languages", LANGUAGES)
    specialties = req_enum_array(payload, "specialties", SPECIALTIES)
    utc_offset_minutes = req_int(payload, "utc_offset_minutes", -720, 840)
    shift_start = req_int(payload, "shift_start_local_hour", 0, 23)
    shift_end = req_int(payload, "shift_end_local_hour", 1, 24)
    role_class = req_enum(payload, "role_class", ROLE_CLASSES)
    max_concurrent_cases = opt_int(payload, "max_concurrent_cases", 1, 20, 3)
    daily_exposure_cap_points = opt_int(payload, "daily_exposure_cap_points", 1, 200, 20)

    record = {
        "display_name": display_name,
        "languages": languages,
        "specialties": specialties,
        "utc_offset_minutes": utc_offset_minutes,
        "shift_start_local_hour": shift_start,
        "shift_end_local_hour": shift_end,
        "role_class": role_class,
        "max_concurrent_cases": max_concurrent_cases,
        "daily_exposure_cap_points": daily_exposure_cap_points,
        "certified_policy_version_ids": [],
        "pending_retraining_version_ids": [],
        "open_case_count": 0,
        "exposure_points_today": 0,
        "audited_count": 0,
        "agree_count": 0,
        "appealed_count": 0,
        "upheld_appeal_count": 0,
        "accuracy_score_audit_only": None,
        "accuracy_score_blended": None,
        "wellness_break_start": None,
        "wellness_break_end": None,
        "wellness_breaks_taken": 0,
        "status": "ACTIVE",
    }
    base_fields(record)
    db.reviewers[record["id"]] = record
    return created(ser.reviewer(record))


@bp.post("/reviewers/<reviewer_id>/certifications")
def grant_certification(reviewer_id):
    require("PolicyManager")
    payload = body()
    version_id = req_str(payload, "policy_version_id", 1, None)
    expected_reviewer_version = req_int(payload, "expected_reviewer_version", 0, None)

    reviewer = find(db.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    version = find(db.policy_versions, version_id, "ERR_POLICY_VERSION_NOT_FOUND")

    if version["status"] not in ("BACKTESTING", "ACTIVE"):
        fail("ERR_POLICY_VERSION_NOT_CERTIFIABLE",
             "Only a BACKTESTING or ACTIVE version can be certified on.")

    # PRD §2.9 / §2.8 tier 11: optimistic concurrency is always evaluated last.
    if expected_reviewer_version != reviewer["version"]:
        fail("ERR_STALE_REVIEWER_VERSION",
             "expected_reviewer_version does not match the reviewer's current version.")

    certified = list(reviewer.get("certified_policy_version_ids") or [])
    if version_id not in certified:
        certified.append(version_id)
    reviewer["certified_policy_version_ids"] = certified
    reviewer["pending_retraining_version_ids"] = [
        vid for vid in (reviewer.get("pending_retraining_version_ids") or [])
        if vid != version_id]

    if reviewer["status"] == "SUSPENDED":
        reviewer["status"] = "ACTIVE"
    elif reviewer["status"] == "PENDING_RETRAINING" and not reviewer["pending_retraining_version_ids"]:
        reviewer["status"] = "ACTIVE"

    touch(reviewer)
    return ok(ser.reviewer(reviewer))


@bp.post("/reviewers/<reviewer_id>/wellness-break")
def wellness_break(reviewer_id):
    require("TrustSafetyAdmin")
    payload = body()
    break_minutes = req_int(payload, "break_minutes", 1, None)
    opt_str(payload, "reason", 0, None)

    reviewer = find(db.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    if reviewer["status"] != "ACTIVE":
        fail("ERR_REVIEWER_NOT_ACTIVE", "Only an ACTIVE reviewer can be placed on a break.")

    start = now()
    end = start + timedelta(minutes=break_minutes)
    retained_start = parse_iso(reviewer.get("wellness_break_start")) \
        if reviewer.get("wellness_break_start") else None
    retained_end = parse_iso(reviewer.get("wellness_break_end")) \
        if reviewer.get("wellness_break_end") else None
    if retained_start is not None and retained_end is not None:
        # Both windows are half-open, so touching at an endpoint is not an overlap.
        if start < retained_end and retained_start < end:
            fail("ERR_WELLNESS_BREAK_OVERLAP",
                 "The requested break window overlaps the reviewer's retained window.")

    reviewer["status"] = "ON_WELLNESS_BREAK"
    reviewer["wellness_break_start"] = now_iso()
    reviewer["wellness_break_end"] = plus_minutes(start, break_minutes)
    reviewer["wellness_breaks_taken"] = int(reviewer.get("wellness_breaks_taken") or 0) + 1
    release_cases_to_queue(reviewer)
    touch(reviewer)
    return ok(ser.reviewer(reviewer))


@bp.post("/reviewers/<reviewer_id>/return-to-duty")
def return_to_duty(reviewer_id):
    require("TrustSafetyAdmin")
    reviewer = find(db.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    if reviewer["status"] != "ON_WELLNESS_BREAK":
        fail("ERR_REVIEWER_NOT_ON_BREAK",
             "Only a reviewer on a wellness break can be returned to duty.")
    reviewer["status"] = "ACTIVE"
    touch(reviewer)
    return ok(ser.reviewer(reviewer))


@bp.get("/reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    record = find(db.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    return ok(ser.reviewer(record))


@bp.get("/reviewers")
def list_reviewers():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    limit, offset = paginate_args()
    status = enum_filter("status", REVIEWER_STATUSES)
    language = enum_filter("language", LANGUAGES)
    specialty = enum_filter("specialty", SPECIALTIES)
    role_class = enum_filter("role_class", ROLE_CLASSES)
    records = []
    for record in db.reviewers.values():
        if status is not None and record["status"] != status:
            continue
        if language is not None and language not in record["languages"]:
            continue
        if specialty is not None and specialty not in record["specialties"]:
            continue
        if role_class is not None and record["role_class"] != role_class:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.reviewer)
