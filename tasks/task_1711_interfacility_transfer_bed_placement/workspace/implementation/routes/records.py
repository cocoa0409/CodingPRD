"""Read models and the quality review process: physician communications,
refusal records, and quality reviews with segregation of duties (PRD 3.9)."""

from flask import Blueprint, g

from core import domain as D
from core import schema as S
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, bump

bp = Blueprint("records", __name__)


# ---------------------------------------------------------------------------
# Physician communications
# ---------------------------------------------------------------------------

@bp.get("/communications")
def list_communications():
    rows = db.ordered("communications")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "from_physician_id")
    rows = filter_exact(rows, "to_physician_id")
    return paginate(rows, D.serialize_communication)


@bp.get("/communications/<id>")
def get_communication(id):
    row = db.communications.get(id)
    if row is None:
        fail("ERR_COMMUNICATION_NOT_FOUND", "PhysicianCommunication id does not exist.", 404)
    return object_response(D.serialize_communication(row), 200)


# ---------------------------------------------------------------------------
# Refusal records
# ---------------------------------------------------------------------------

@bp.get("/refusal-records")
def list_refusal_records():
    rows = db.ordered("refusal_records")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "facility_id")
    rows = filter_exact(rows, "refusing_physician_id")
    return paginate(rows, D.serialize_refusal_record)


@bp.get("/refusal-records/<id>")
def get_refusal_record(id):
    row = db.refusal_records.get(id)
    if row is None:
        fail("ERR_REFUSAL_RECORD_NOT_FOUND", "RefusalRecord id does not exist.", 404)
    return object_response(D.serialize_refusal_record(row), 200)


# ---------------------------------------------------------------------------
# Quality reviews (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.get("/quality-reviews")
def list_reviews():
    rows = db.ordered("quality_reviews")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "reviewer_physician_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, D.serialize_review)


@bp.get("/quality-reviews/<id>")
def get_review(id):
    row = db.quality_reviews.get(id)
    if row is None:
        fail("ERR_REVIEW_NOT_FOUND", "QualityReview id does not exist.", 404)
    return object_response(D.serialize_review(row), 200)


@bp.post("/quality-reviews/<id>/begin")
def begin_review(id):
    row = db.quality_reviews.get(id)
    if row is None:
        fail("ERR_REVIEW_NOT_FOUND", "QualityReview id does not exist.", 404)
    case = D.get_case(row["transfer_case_id"])
    if g.user_id == case["sending_physician_id"] or g.user_id == case["receiving_physician_id"]:
        fail("ERR_REVIEWER_CONFLICT_OF_INTEREST",
             "The reviewer must not be the case's sending or receiving physician.", 403)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "The review is not OPEN.", 409)
    row["reviewer_physician_id"] = g.user_id
    row["status"] = "UNDER_REVIEW"
    bump(row)
    return object_response(D.serialize_review(row), 200)


@bp.post("/quality-reviews/<id>/close")
def close_review(id):
    b = S.body()
    outcome = S.need_enum(b, "outcome", D.REVIEW_OUTCOMES)
    findings = S.need_str(b, "findings")
    S.need_min_length(findings, "findings", 30, "ERR_FINDINGS_TOO_SHORT")
    row = db.quality_reviews.get(id)
    if row is None:
        fail("ERR_REVIEW_NOT_FOUND", "QualityReview id does not exist.", 404)
    if g.user_id != row["reviewer_physician_id"]:
        fail("ERR_NOT_REVIEWER", "X-User-ID is not the assigned reviewer.", 403)
    if row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "The review is not UNDER_REVIEW.", 409)
    case = D.get_case(row["transfer_case_id"])
    timeliness, documentation, protocol, composite = D.compute_review_scores(case)
    row["timeliness_score"] = timeliness
    row["documentation_score"] = documentation
    row["protocol_score"] = protocol
    row["composite_score"] = composite
    row["outcome"] = outcome
    row["findings"] = findings
    row["status"] = "CLOSED"
    bump(row)
    return object_response(D.serialize_review(row), 200)
