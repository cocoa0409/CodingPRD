"""/deviations and /batch-record-reviews - the CAPA loop and record review."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import acting_user, endpoint
from common import ApiError, clock_now
from listing import list_response, object_response
from store import (
    DB,
    by_created,
    deviations_of_batch,
    ipcs_of_batch,
    new_row,
    review_of_batch,
    touch,
)
from validate import (
    CAPA_OUTCOMES,
    DEVIATION_CLASSES,
    f_enum,
    f_int,
    f_str,
    parse_body,
)

bp = Blueprint("qa", __name__)

DEVIATION_FIELDS = [
    f_str("batch_order_id", 1, None),
    f_str("summary", 1, 200),
    f_str("em_sample_id", 1, None, required=False),
]


@bp.post("/deviations")
@endpoint(["QaReviewer"])
def create_deviation():
    body = parse_body(request.get_json(silent=True), DEVIATION_FIELDS)
    batch = services.require("batch", body["batch_order_id"])
    sample = None
    if body["em_sample_id"] is not None:
        sample = services.require("em_sample", body["em_sample_id"])
    row = new_row(
        {
            "batch_order_id": batch["id"],
            "em_sample_id": sample["id"] if sample else None,
            "opened_by_user_id": acting_user(),
            "summary": body["summary"],
            "classification": None,
            "capa_rejection_count": 0,
            "risk_score": 0,
            "status": "OPEN",
            "capa_summary": None,
        }
    )
    DB.deviations[row["id"]] = row
    return object_response(serialize.deviation_out(row), 201)


@bp.get("/deviations/<deviation_id>")
@endpoint(["QaReviewer", "QualifiedPerson", "ProgramManager", "MicrobiologyAnalyst"])
def read_deviation(deviation_id):
    row = services.require("deviation", deviation_id)
    return object_response(serialize.deviation_out(row))


@bp.get("/deviations")
@endpoint(["QaReviewer", "QualifiedPerson", "ProgramManager", "MicrobiologyAnalyst"])
def list_deviations():
    rows = by_created(list(DB.deviations.values()))
    return list_response(
        rows,
        serialize.deviation_out,
        {
            "batch_order_id": "batch_order_id",
            "em_sample_id": "em_sample_id",
            "status": "status",
            "classification": "classification",
        },
    )


@bp.post("/deviations/<deviation_id>/classify")
@endpoint(["QaReviewer"])
def classify_deviation(deviation_id):
    deviation = services.require("deviation", deviation_id)
    body = parse_body(
        request.get_json(silent=True),
        [
            f_enum("classification", DEVIATION_CLASSES),
            f_str("classification_rationale", 1, None),
        ],
    )
    if deviation["status"] != "OPEN":
        raise services.state_conflict(
            "ERR_DEVIATION_STATE_INVALID", "Only an OPEN deviation can be classified."
        )
    deviation["classification"] = body["classification"]
    deviation["risk_score"] = calc.deviation_risk_score(
        body["classification"],
        deviation["capa_rejection_count"],
        deviation["em_sample_id"],
    )
    deviation["status"] = "UNDER_INVESTIGATION"
    touch(deviation)
    if body["classification"] == "CRITICAL":
        services.critical_deviation_cascade(deviation)
    return object_response(serialize.deviation_out(deviation))


@bp.post("/deviations/<deviation_id>/submit-capa")
@endpoint(["QaReviewer"])
def submit_capa(deviation_id):
    deviation = services.require("deviation", deviation_id)
    body = parse_body(request.get_json(silent=True), [f_str("capa_summary", 1, None)])
    if deviation["status"] != "UNDER_INVESTIGATION":
        raise services.state_conflict(
            "ERR_DEVIATION_STATE_INVALID",
            "A CAPA can only be submitted from UNDER_INVESTIGATION.",
        )
    deviation["capa_summary"] = body["capa_summary"]
    deviation["status"] = "CAPA_PENDING"
    touch(deviation)
    return object_response(serialize.deviation_out(deviation))


@bp.post("/deviations/<deviation_id>/decide-capa")
@endpoint(["QaReviewer"])
def decide_capa(deviation_id):
    deviation = services.require("deviation", deviation_id)
    body = parse_body(
        request.get_json(silent=True),
        [f_enum("outcome", CAPA_OUTCOMES), f_str("decision_note", 1, None)],
    )
    if deviation["status"] != "CAPA_PENDING":
        raise services.state_conflict(
            "ERR_DEVIATION_STATE_INVALID",
            "A CAPA decision is only accepted from CAPA_PENDING.",
        )
    if acting_user() == deviation["opened_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The deciding user must differ from the user who opened the deviation.",
        )
    if body["outcome"] == "REJECTED":
        deviation["capa_rejection_count"] += 1
        deviation["risk_score"] = calc.deviation_risk_score(
            deviation["classification"],
            deviation["capa_rejection_count"],
            deviation["em_sample_id"],
        )
        deviation["status"] = "UNDER_INVESTIGATION"
        touch(deviation)
    else:
        deviation["status"] = "CLOSED"
        touch(deviation)
        services.maybe_close_quarantine_loop(
            DB.batches.get(deviation["batch_order_id"])
        )
    return object_response(serialize.deviation_out(deviation))


# --------------------------------------------------------------------------
# Batch record review
# --------------------------------------------------------------------------


@bp.post("/batch-record-reviews")
@endpoint(["QaReviewer"])
def create_review():
    body = parse_body(
        request.get_json(silent=True), [f_str("batch_order_id", 1, None)]
    )
    batch = services.require("batch", body["batch_order_id"])
    if batch["production_status"] != "FILLED":
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "The batch must have finished filling.",
        )
    if batch["quality_status"] != "IN_PROCESS_REVIEW":
        raise services.state_conflict(
            "ERR_BATCH_QUALITY_STATE_INVALID",
            "The batch's quality_status must be IN_PROCESS_REVIEW.",
        )
    checks = ipcs_of_batch(batch["id"])
    present = set(c["check_type"] for c in checks)
    for required in ("FILL_WEIGHT", "CCI", "VISUAL_INSPECTION"):
        if required not in present:
            raise ApiError(
                "ERR_REQUIRED_IPC_MISSING",
                422,
                "The batch has no %s in-process control." % required,
            )
    for check in checks:
        if check["result"] == "FAIL":
            raise services.state_conflict(
                "ERR_IPC_FAILED", "An in-process control of this batch FAILED."
            )
    if review_of_batch(batch["id"]) is not None:
        raise services.state_conflict(
            "ERR_BR_REVIEW_ALREADY_EXISTS",
            "This batch already has a batch record review.",
        )
    seeded = len(
        [
            d
            for d in deviations_of_batch(batch["id"])
            if d["classification"] == "MAJOR" and d["status"] != "CLOSED"
        ]
    )
    row = new_row(
        {
            "batch_order_id": batch["id"],
            "reviewer_user_id": acting_user(),
            "open_findings_count": seeded,
            "status": "IN_PROGRESS",
            "closed_at": None,
        }
    )
    DB.reviews[row["id"]] = row
    batch["quality_status"] = "BR_REVIEW"
    touch(batch)
    return object_response(serialize.review_out(row), 201)


@bp.get("/batch-record-reviews/<review_id>")
@endpoint(["QaReviewer", "QualifiedPerson", "ProgramManager"])
def read_review(review_id):
    row = services.require("review", review_id)
    return object_response(serialize.review_out(row))


@bp.get("/batch-record-reviews")
@endpoint(["QaReviewer", "QualifiedPerson", "ProgramManager"])
def list_reviews():
    rows = by_created(list(DB.reviews.values()))
    return list_response(
        rows,
        serialize.review_out,
        {"batch_order_id": "batch_order_id", "status": "status"},
    )


@bp.post("/batch-record-reviews/<review_id>/record-findings")
@endpoint(["QaReviewer"])
def record_findings(review_id):
    review = services.require("review", review_id)
    body = parse_body(
        request.get_json(silent=True),
        [f_int("open_findings_count", 0), f_str("findings_note", 1, None)],
    )
    if review["status"] not in ("IN_PROGRESS", "COMPLETE_WITH_FINDINGS"):
        raise services.state_conflict(
            "ERR_BR_REVIEW_STATE_INVALID",
            "Findings can only be recorded on an open review.",
        )
    review["open_findings_count"] = body["open_findings_count"]
    review["status"] = "COMPLETE_WITH_FINDINGS"
    touch(review)
    return object_response(serialize.review_out(review))


@bp.post("/batch-record-reviews/<review_id>/close")
@endpoint(["QaReviewer"])
def close_review(review_id):
    review = services.require("review", review_id)
    parse_body(request.get_json(silent=True), [])
    batch = DB.batches.get(review["batch_order_id"])
    if batch is None or batch["quality_status"] != "BR_REVIEW":
        raise services.state_conflict(
            "ERR_BATCH_QUALITY_STATE_INVALID",
            "The owning batch is no longer in BR_REVIEW.",
        )
    if review["status"] not in ("IN_PROGRESS", "COMPLETE_WITH_FINDINGS") \
            or review["open_findings_count"] != 0:
        raise services.state_conflict(
            "ERR_BR_REVIEW_STATE_INVALID",
            "A review closes only from an open status with zero findings.",
        )
    review["status"] = "CLOSED"
    review["closed_at"] = clock_now()
    touch(review)
    batch["quality_status"] = "QP_REVIEW"
    batch["final_releasable_units"] = calc.final_releasable_units(batch)
    touch(batch)
    return object_response(serialize.review_out(review))
