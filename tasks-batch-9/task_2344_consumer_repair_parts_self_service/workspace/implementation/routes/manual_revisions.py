"""Revision-controlled repair documentation (PRD 3.4)."""
from flask import Blueprint, g

import db
from db import base_row, setf, touch
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, DOCUMENTATION_ENGINEER, PROGRAM_ADMIN, \
    REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, get_model, get_revision
from serializers import revision_json
from services.compliance import published_revision, refresh_revision_coverage, \
    reevaluate_model_obligations, rollup_documentation_posture
from validation import F, int_range, read_body

bp = Blueprint("manual_revisions", __name__)

DOC_TYPES = ("DISASSEMBLY_GUIDE", "SAFETY_SHEET", "CALIBRATION_PROCEDURE", "PARTS_LIST")
WARNING_REQUIRED_TYPES = ("DISASSEMBLY_GUIDE", "SAFETY_SHEET")
REJECTION_CYCLE_CAP = 3

READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, DOCUMENTATION_ENGINEER, COMPLIANCE_OFFICER,
              SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH]


def _next_revision_number(model_id, doc_type):
    highest = 0
    for row in db.db.revisions.all():
        if row["model_id"] == model_id and row["doc_type"] == doc_type:
            if row["revision_number"] > highest:
                highest = row["revision_number"]
    return highest + 1


@bp.post("/manual-revisions")
@endpoint([DOCUMENTATION_ENGINEER, SAFETY_REVIEWER])
def create_revision():
    body = read_body([
        F("model_id", "string", required=True),
        F("doc_type", "enum", required=True, enum=DOC_TYPES),
        F("covered_part_skus", "string_list", required=True),
        F("safety_warning_count", "int", required=True),
        F("expected_model_version", "int", required=True),
    ])
    int_range(body["safety_warning_count"], "safety_warning_count", 0, None)
    model = get_model(body["model_id"])
    if body["expected_model_version"] != model.get("version"):
        raise ApiError("ERR_STALE_MODEL_VERSION")

    row = base_row()
    row.update({
        "model_id": model["id"],
        "doc_type": body["doc_type"],
        "revision_number": _next_revision_number(model["id"], body["doc_type"]),
        "covered_part_skus": list(body["covered_part_skus"]),
        "safety_warning_count": body["safety_warning_count"],
        "status": "DRAFT",
        "authored_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "rejection_cycle_count": 0,
        "effective_from": None,
        "published_at": None,
        "coverage_gap_sku_count": 0,
    })
    db.db.revisions.add(row)
    refresh_revision_coverage(row)
    touch(model)
    return created(revision_json(row))


@bp.get("/manual-revisions/<revision_id>")
@endpoint(READ_ROLES)
def read_revision(revision_id):
    return ok(revision_json(get_revision(revision_id)))


@bp.get("/manual-revisions")
@endpoint(READ_ROLES)
def list_revisions():
    rows = db.db.revisions.all()
    for field in ("model_id", "doc_type", "status"):
        rows = filter_eq(rows, field)
    return collection(rows, revision_json)


@bp.post("/manual-revisions/<revision_id>/submit")
@endpoint([DOCUMENTATION_ENGINEER, SAFETY_REVIEWER])
def submit_revision(revision_id):
    read_body([])
    revision = get_revision(revision_id)

    if revision["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if revision.get("rejection_cycle_count", 0) >= REJECTION_CYCLE_CAP:
        raise ApiError("ERR_REVISION_CYCLE_CAP_REACHED")
    if not revision.get("covered_part_skus"):
        raise ApiError("ERR_SAFETY_WARNINGS_REQUIRED",
                       "covered_part_skus may not be empty.")

    refresh_revision_coverage(revision)
    setf(revision, "status", "IN_REVIEW")
    return ok(revision_json(revision))


@bp.post("/manual-revisions/<revision_id>/review-decision")
@endpoint([SAFETY_REVIEWER])
def review_revision(revision_id):
    body = read_body([
        F("decision", "enum", required=True, enum=("APPROVE", "REJECT")),
        F("review_note", "string"),
    ])
    revision = get_revision(revision_id)

    # band 5: segregation of duties, before any state admissibility check
    if revision.get("authored_by_user_id") is not None \
            and revision["authored_by_user_id"] == g.user_id:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN")

    if revision["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    model = db.db.models.get(revision["model_id"])

    if body["decision"] == "REJECT":
        if revision.get("rejection_cycle_count", 0) >= REJECTION_CYCLE_CAP:
            raise ApiError("ERR_REVISION_CYCLE_CAP_REACHED")
        setf(revision, "status", "DRAFT")
        setf(revision, "rejection_cycle_count",
             revision.get("rejection_cycle_count", 0) + 1)
        setf(revision, "reviewed_by_user_id", g.user_id)
        touch(revision)
        return ok(revision_json(revision))

    if model is not None and model.get("support_state") == "SUPPORT_ENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Support has ended for this model.")
    if revision["doc_type"] == "DISASSEMBLY_GUIDE" \
            and revision.get("coverage_gap_sku_count", 0) != 0:
        raise ApiError("ERR_REVISION_COVERAGE_GAP")

    setf(revision, "status", "APPROVED")
    setf(revision, "reviewed_by_user_id", g.user_id)
    touch(revision)
    return ok(revision_json(revision))


@bp.post("/manual-revisions/<revision_id>/publish")
@endpoint([SAFETY_REVIEWER])
def publish_revision(revision_id):
    body = read_body([F("effective_from", "datetime")])
    revision = get_revision(revision_id)

    if revision["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    at = db.now()
    effective_from = body["effective_from"] if body["effective_from"] is not None else at
    current = published_revision(revision["model_id"], revision["doc_type"])
    if current is not None and current.get("effective_from") is not None \
            and effective_from < current["effective_from"]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "effective_from precedes the currently published revision's effective_from.",
        )

    if revision["doc_type"] in WARNING_REQUIRED_TYPES:
        if revision.get("safety_warning_count", 0) <= 0 or not revision.get("covered_part_skus"):
            raise ApiError("ERR_SAFETY_WARNINGS_REQUIRED")

    # hop 1
    setf(revision, "status", "PUBLISHED")
    setf(revision, "published_at", at)
    setf(revision, "effective_from", effective_from)

    # hop 2
    if current is not None:
        setf(current, "status", "SUPERSEDED")

    # hops 3 and 4
    model = db.db.models.get(revision["model_id"])
    if model is not None:
        rollup_documentation_posture(model)
        reevaluate_model_obligations(model)
        touch(model)

    return ok(revision_json(revision))
