"""Quality-control sampling and validation (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response, paginated
from routes.batches import require_approved_protocol
from routes.matters import require_not_suspended
from services import cascade, compute
from services.compute import dec, round_half_up
from validation import present, req_id, req_int

bp = Blueprint("qc", __name__)


def _first_pass_assignment(batch_id):
    for assignment in compute.assignments_of_batch(batch_id):
        if assignment["pass_type"] == "FIRST_PASS" and assignment["status"] != "VOIDED":
            return assignment
    return None


@bp.route("/batches/<batch_id>/qc-samples", methods=["POST"])
def draw_sample(batch_id):
    require_roles(ROLE_QC_LEAD)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)
    payload = body()

    # Rank 5.
    validator = None
    if present(payload, "validated_by_reviewer_id") \
            and isinstance(payload["validated_by_reviewer_id"], str):
        validator = compute.get_reviewer(payload["validated_by_reviewer_id"])
    req_id(payload, "validated_by_reviewer_id")
    if validator is None:
        validator = compute.get_reviewer(payload["validated_by_reviewer_id"])

    if batch["status"] != "QC_SAMPLING":
        raise ApiError("ERR_INVALID_STATE",
                       "A sample is drawn from a batch in QC_SAMPLING only.")
    require_not_suspended(matter)
    require_approved_protocol(matter)

    # Rank 21 - segregation of duties.
    for assignment in compute.assignments_of_batch(batch["id"]):
        if assignment["reviewer_id"] == validator["id"] and assignment["status"] != "VOIDED":
            raise ApiError("ERR_QC_VALIDATOR_CONFLICT",
                           "The validating reviewer holds an assignment on this batch.")

    sampled = min(compute.qc_sample_target_size(batch), batch["document_count"])
    row = base_row()
    row.update({
        "batch_id": batch["id"],
        "validated_by_reviewer_id": validator["id"],
        "sampled_document_count": sampled,
        "coding_error_count": 0,
        "privilege_error_count": 0,
        "discrepancy_rate": Decimal("0.0000"),
        "outcome": "PENDING",
        "validated_at": None,
    })
    db.qc_samples[row["id"]] = row
    return created_response(compute.qc_sample_out(row))


@bp.route("/qc-samples/<sample_id>", methods=["GET"])
def read_sample(sample_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    sample = compute.get_qc_sample(sample_id)
    return object_response(compute.qc_sample_out(sample))


@bp.route("/qc-samples", methods=["GET"])
def list_samples():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    rows = by_creation(list(db.qc_samples.values()))
    batch_id = request.args.get("batch_id")
    validated_by = request.args.get("validated_by_reviewer_id")
    outcome = request.args.get("outcome")
    if batch_id:
        rows = [r for r in rows if r["batch_id"] == batch_id]
    if validated_by:
        rows = [r for r in rows if r["validated_by_reviewer_id"] == validated_by]
    if outcome:
        rows = [r for r in rows if r["outcome"] == outcome]
    return paginated(rows, compute.qc_sample_out)


@bp.route("/qc-samples/<sample_id>/validate", methods=["POST"])
def validate_sample(sample_id):
    require_roles(ROLE_QC_LEAD)
    sample = compute.get_qc_sample(sample_id)
    batch = compute.get_batch(sample["batch_id"])
    matter = compute.matter_of_batch(batch)
    payload = body()
    coding_error_count = req_int(payload, "coding_error_count", 0)
    privilege_error_count = req_int(payload, "privilege_error_count", 0)

    if sample["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING sample may be validated.")
    require_not_suspended(matter)

    # Rank 40.
    combined = coding_error_count + privilege_error_count
    if combined > sample["sampled_document_count"]:
        raise ApiError("ERR_ERROR_COUNT_EXCEEDS_SAMPLE",
                       "The error counts exceed the sampled document count.")

    protocol = compute.effective_protocol(matter["id"])
    threshold = dec(protocol["max_discrepancy_pct"]) if protocol else Decimal(0)
    rate = round_half_up(dec(combined) / dec(sample["sampled_document_count"]), 4)

    sample["coding_error_count"] = coding_error_count
    sample["privilege_error_count"] = privilege_error_count
    sample["discrepancy_rate"] = rate
    sample["validated_at"] = db.now_iso()
    sample["outcome"] = "FAILED" if rate >= threshold else "PASSED"
    touch(sample)

    first_pass = _first_pass_assignment(batch["id"])
    reviewer = None
    if first_pass is not None:
        reviewer = compute.get_reviewer(first_pass["reviewer_id"])

    if sample["outcome"] == "PASSED":
        batch["status"] = "QC_PASSED"
        touch(batch)
        if coding_error_count == 0 and privilege_error_count == 0 and reviewer is not None:
            cascade.append_scorecard_event(
                reviewer["id"], "CLEARED_STRIKE",
                "Clean quality-control sample on batch %s." % batch["batch_number"],
                batch["batch_number"])
            cascade.evaluate_removal(reviewer)
        return object_response(compute.qc_sample_out(sample))

    # The failure cascade, in order.
    batch["status"] = "QC_FAILED"
    touch(batch)
    if first_pass is not None:
        if first_pass["status"] == "SUBMITTED":
            first_pass["status"] = "REOPENED"
            touch(first_pass)
        cascade.append_scorecard_event(
            reviewer["id"], "QC_FAILURE",
            "Quality-control sample failed on batch %s." % batch["batch_number"],
            batch["batch_number"])
        if privilege_error_count > 0:
            cascade.append_scorecard_event(
                reviewer["id"], "PRIVILEGE_MISS",
                "Privilege errors found in the sample of batch %s." % batch["batch_number"],
                batch["batch_number"])
        cascade.evaluate_removal(reviewer)
    return object_response(compute.qc_sample_out(sample))
