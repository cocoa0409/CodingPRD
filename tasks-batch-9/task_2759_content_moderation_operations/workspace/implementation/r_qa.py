"""Quality assurance sampling, verdicts and disputes (PRD §3.8)."""

from flask import Blueprint

import ser
from core import (
    AUDIT_STATUSES, OUTCOMES, SAMPLING_REASONS, VERDICTS, base_fields, body,
    created, db, enum_filter, fail, listing, now_iso, ok, opt_enum,
    paginate_args, present, req_enum, req_str, require, str_filter, touch,
)
from svc import find, recompute_reviewer_accuracy

bp = Blueprint("qa", __name__)


@bp.post("/audit-samples")
def draw_sample():
    actor = require("QAAuditor")
    # PRD §2.8 tier 2: drawing a sample requires the acting reviewer's
    # role_class to be QA, and that is an authorization failure.
    auditor = db.reviewers.get(actor.user_id)
    if auditor is None or auditor["role_class"] != "QA":
        fail("ERR_UNAUTHORIZED", "Audit sampling requires a reviewer whose role_class is QA.")

    payload = body()
    case_id = req_str(payload, "case_id", 1, None)
    sampling_reason = req_enum(payload, "sampling_reason", SAMPLING_REASONS)

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")

    if case.get("decided_by_reviewer_id") and case["decided_by_reviewer_id"] == actor.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "Nobody may audit their own decision.")
    if case["status"] != "DECIDED":
        fail("ERR_CASE_NOT_DECIDED", "Only a decided case can be drawn into the QA sample.")

    record = {
        "case_id": case_id,
        "auditor_reviewer_id": actor.user_id,
        "sampling_reason": sampling_reason,
        "verdict": None,
        "correct_outcome": None,
        "audited_at": None,
        "dispute_note": None,
        "disputed_at": None,
        "counts_toward_accuracy": True,
        "status": "SAMPLED",
    }
    base_fields(record)
    db.audit_samples[record["id"]] = record
    return created(ser.audit_sample(record))


@bp.post("/audit-samples/<sample_id>/audit")
def audit_sample(sample_id):
    require("QAAuditor")
    payload = body()
    verdict = req_enum(payload, "verdict", VERDICTS)
    correct_outcome = opt_enum(payload, "correct_outcome", OUTCOMES)
    if verdict != "AGREE" and not present(payload, "correct_outcome"):
        fail("ERR_INVALID_REQUEST",
             "correct_outcome is required whenever the verdict is a disagreement.")

    sample = find(db.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    if sample["status"] not in ("SAMPLED", "DISPUTED"):
        fail("ERR_AUDIT_NOT_AUDITABLE",
             "Only a SAMPLED or DISPUTED sample can carry a verdict.")

    sample["verdict"] = verdict
    sample["correct_outcome"] = None if verdict == "AGREE" else correct_outcome
    sample["audited_at"] = now_iso()
    sample["counts_toward_accuracy"] = True
    sample["status"] = "AUDITED"
    touch(sample)

    case = db.moderation_cases.get(sample["case_id"])
    decider = db.reviewers.get(case.get("decided_by_reviewer_id")) if case else None
    recompute_reviewer_accuracy(decider)

    return ok(ser.audit_sample(sample))


@bp.post("/audit-samples/<sample_id>/dispute")
def dispute_sample(sample_id):
    actor = require("Reviewer")
    payload = body()
    dispute_note = req_str(payload, "dispute_note", 1, None)

    sample = find(db.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    case = db.moderation_cases.get(sample["case_id"])

    if case is None or case.get("decided_by_reviewer_id") != actor.user_id:
        fail("ERR_NOT_CASE_OWNER",
             "Only the reviewer who decided the underlying case may dispute the verdict.")
    if sample["status"] != "AUDITED":
        fail("ERR_AUDIT_NOT_DISPUTABLE", "Only an AUDITED sample can be disputed.")

    sample["dispute_note"] = dispute_note
    sample["disputed_at"] = now_iso()
    sample["counts_toward_accuracy"] = False
    sample["status"] = "DISPUTED"
    touch(sample)

    decider = db.reviewers.get(case.get("decided_by_reviewer_id"))
    recompute_reviewer_accuracy(decider)

    return ok(ser.audit_sample(sample))


@bp.get("/audit-samples/<sample_id>")
def get_sample(sample_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    record = find(db.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    return ok(ser.audit_sample(record))


@bp.get("/audit-samples")
def list_samples():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    limit, offset = paginate_args()
    case_id = str_filter("case_id")
    auditor_reviewer_id = str_filter("auditor_reviewer_id")
    status = enum_filter("status", AUDIT_STATUSES)
    verdict = enum_filter("verdict", VERDICTS)
    records = []
    for record in db.audit_samples.values():
        if case_id is not None and record["case_id"] != case_id:
            continue
        if auditor_reviewer_id is not None and record["auditor_reviewer_id"] != auditor_reviewer_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if verdict is not None and record["verdict"] != verdict:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.audit_sample)
