"""Career-site content: optimization, compliance clearance and publication."""

from flask import Blueprint, g

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import budget, calc, channel_svc, serialize

bp = Blueprint("postings", __name__)

READ_ROLES = ("BrandProgramLead", "PersonaResearcher", "ComplianceReviewer",
              "MediaBuyer", "CommunityManager", "RecruitingOps", "Anonymous")
CONVERSION_ROLES = ("BrandProgramLead", "ComplianceReviewer", "MediaBuyer", "RecruitingOps")


def optimization_score(posting):
    words = posting["title_word_count"]
    if 3 <= words <= 12:
        w_title = 25
    elif words <= 20:
        w_title = 10
    else:
        w_title = 0
    responsibilities = posting["responsibility_count"]
    w_resp = 20 if responsibilities >= 5 else 4 * responsibilities
    low, high = posting["pay_range_min_cents"], posting["pay_range_max_cents"]
    w_pay = 15 if (low is not None and high is not None and high >= low) else 0
    w_eeo = 15 if posting["eeo_statement_included"] else 0
    w_benefit = 5 * min(5, posting["benefit_count"])
    return w_title + w_resp + w_pay + w_eeo + w_benefit


def _release_flights(posting, states, new_state, release_reason, ledger_reason):
    """Shared body of the compliance-suspension and archive cascades."""
    flights = sorted([f for f in db.flights.values()
                      if f["job_posting_id"] == posting["id"] and f["state"] in states],
                     key=lambda f: f["created_at"])
    for flight in flights:
        was_active = flight["state"] == "ACTIVE"
        flight["state"] = new_state
        flight["release_reason"] = release_reason
        flight["reserved_cents"] = 0
        family = db.job_families[flight["job_family_id"]]
        program = calc.program_of_family(family)
        if budget.release(program, flight["id"], ledger_reason):
            db.touch(program)
        db.touch(flight)
        channel = db.channels[flight["channel_id"]]
        if was_active:
            channel_svc.resolve_idle(channel)
            db.touch(channel)


@bp.route("/job-postings", methods=["POST"])
@require("BrandProgramLead")
def create_posting():
    data = V.body()
    job_family_id = V.field(data, "job_family_id", "string", required=True)
    title = V.field(data, "title", "string", required=True, min_len=1, max_len=200)
    responsibility_count = V.field(data, "responsibility_count", "integer",
                                   default=0, min_value=0, max_value=40)
    benefit_count = V.field(data, "benefit_count", "integer",
                            default=0, min_value=0, max_value=40)
    pay_min = V.field(data, "pay_range_min_cents", "integer", nullable=True, min_value=0)
    pay_max = V.field(data, "pay_range_max_cents", "integer", nullable=True, min_value=0)
    if pay_min is not None and pay_max is not None and pay_max < pay_min:
        V.bad_request("pay_range_max_cents must be at least pay_range_min_cents.")
    eeo = V.field(data, "eeo_statement_included", "boolean", default=False)
    superlative = V.field(data, "superlative_claim_included", "boolean", default=False)
    substantiation_url = V.field(data, "substantiation_url", "string",
                                 nullable=True, min_len=1, max_len=2000)
    family = calc.must_get(db.job_families, job_family_id, "ERR_JOB_FAMILY_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "job_family_id": family["id"],
        "title": title,
        "title_word_count": len(title.split()),
        "responsibility_count": responsibility_count,
        "benefit_count": benefit_count,
        "pay_range_min_cents": pay_min,
        "pay_range_max_cents": pay_max,
        "eeo_statement_included": eeo,
        "superlative_claim_included": superlative,
        "substantiation_url": substantiation_url,
        "content_status": "DRAFT",
        "compliance_status": "UNREVIEWED",
        "optimization_score": 0,
        "optimized_by_user_id": None,
        "cleared_by_user_id": None,
        "suspended_reason": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.postings[row["id"]] = row
    return response.ok(serialize.posting(row), 201)


@bp.route("/job-postings/<posting_id>/optimize", methods=["POST"])
@require("BrandProgramLead")
def optimize_posting(posting_id):
    data = V.body()
    expected = V.field(data, "expected_posting_version", "integer", required=True)
    edits = {
        "title": V.field(data, "title", "string", default=V.MISSING,
                         min_len=1, max_len=200),
        "responsibility_count": V.field(data, "responsibility_count", "integer",
                                        default=V.MISSING, min_value=0, max_value=40),
        "benefit_count": V.field(data, "benefit_count", "integer",
                                 default=V.MISSING, min_value=0, max_value=40),
        "pay_range_min_cents": V.field(data, "pay_range_min_cents", "integer",
                                       default=V.MISSING, nullable=True, min_value=0),
        "pay_range_max_cents": V.field(data, "pay_range_max_cents", "integer",
                                       default=V.MISSING, nullable=True, min_value=0),
        "eeo_statement_included": V.field(data, "eeo_statement_included", "boolean",
                                          default=V.MISSING),
        "superlative_claim_included": V.field(data, "superlative_claim_included",
                                              "boolean", default=V.MISSING),
        "substantiation_url": V.field(data, "substantiation_url", "string",
                                      default=V.MISSING, nullable=True,
                                      min_len=1, max_len=2000),
    }
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    if expected != posting["version"]:
        raise ApiError("ERR_STALE_POSTING_VERSION",
                       "expected_posting_version does not match the posting version.")
    if posting["content_status"] not in ("DRAFT", "OPTIMIZED"):
        raise ApiError("ERR_POSTING_NOT_OPTIMIZABLE",
                       "content_status must be DRAFT or OPTIMIZED.")
    merged = dict(posting)
    for key, value in edits.items():
        if value is not V.MISSING:
            merged[key] = value
    low, high = merged["pay_range_min_cents"], merged["pay_range_max_cents"]
    if low is not None and high is not None and high < low:
        raise ApiError("ERR_PAY_RANGE_INVALID",
                       "pay_range_max_cents must be at least pay_range_min_cents.")

    for key, value in edits.items():
        if value is not V.MISSING:
            posting[key] = value
    posting["title_word_count"] = len(posting["title"].split())
    posting["optimization_score"] = optimization_score(posting)
    posting["content_status"] = "OPTIMIZED"
    posting["optimized_by_user_id"] = g.user_id
    if posting["compliance_status"] == "CLEARED":
        posting["compliance_status"] = "UNREVIEWED"
        posting["cleared_by_user_id"] = None
    db.touch(posting)
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings/<posting_id>/compliance-review", methods=["POST"])
@require("ComplianceReviewer")
def compliance_review(posting_id):
    data = V.body()
    decision = V.field(data, "decision", "enum", required=True, values=("CLEAR", "FLAG"))
    note = V.field(data, "note", "string", nullable=True, min_len=0, max_len=2000)
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    if posting["optimized_by_user_id"] is not None and g.user_id == posting["optimized_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The optimizing user may not record the compliance decision.")
    if posting["content_status"] == "ARCHIVED":
        raise ApiError("ERR_POSTING_ALREADY_ARCHIVED", "The posting is archived.")
    if decision == "CLEAR":
        if posting["compliance_status"] not in ("UNREVIEWED", "FLAGGED"):
            raise ApiError("ERR_POSTING_ALREADY_CLEARED", "The posting is already cleared.")
        if not posting["eeo_statement_included"]:
            raise ApiError("ERR_EEO_STATEMENT_MISSING",
                           "eeo_statement_included must be true.")
        if posting["superlative_claim_included"] and not posting["substantiation_url"]:
            raise ApiError("ERR_UNSUBSTANTIATED_CLAIM",
                           "A superlative claim requires a substantiation_url.")
        posting["compliance_status"] = "CLEARED"
        posting["cleared_by_user_id"] = g.user_id
    else:
        if posting["compliance_status"] not in ("UNREVIEWED", "CLEARED"):
            raise ApiError("ERR_POSTING_ALREADY_FLAGGED", "The posting is already flagged.")
        posting["compliance_status"] = "FLAGGED"
        posting["cleared_by_user_id"] = None
        if posting["content_status"] == "PUBLISHED":
            posting["content_status"] = "SUSPENDED"
            posting["suspended_reason"] = "COMPLIANCE_FLAG"
            _release_flights(posting, ("ACTIVE", "PAUSED_PACING"),
                             "SUSPENDED_CONTENT", "COMPLIANCE_SUSPENSION",
                             "FLIGHT_COMPLIANCE_SUSPENSION")
    db.touch(posting)
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings/<posting_id>/publish", methods=["POST"])
@require("BrandProgramLead")
def publish_posting(posting_id):
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    if posting["content_status"] not in ("OPTIMIZED", "SUSPENDED"):
        raise ApiError("ERR_POSTING_NOT_PUBLISHABLE",
                       "content_status must be OPTIMIZED or SUSPENDED.")
    if not posting["eeo_statement_included"]:
        raise ApiError("ERR_EEO_STATEMENT_MISSING", "eeo_statement_included must be true.")
    if posting["compliance_status"] != "CLEARED":
        raise ApiError("ERR_POSTING_COMPLIANCE_NOT_CLEARED",
                       "compliance_status must be CLEARED.")
    approved = [p for p in db.personas.values()
                if p["job_family_id"] == posting["job_family_id"]
                and p["state"] == "APPROVED"]
    if not approved:
        raise ApiError("ERR_NO_APPROVED_PERSONA",
                       "The job family has no APPROVED persona.")
    if posting["optimization_score"] < 70:
        raise ApiError("ERR_OPTIMIZATION_SCORE_TOO_LOW",
                       "optimization_score must be at least 70.")
    low, high = posting["pay_range_min_cents"], posting["pay_range_max_cents"]
    if low is None or high is None or high < low:
        raise ApiError("ERR_PAY_RANGE_INVALID",
                       "Both pay range bounds are required to publish.")
    posting["content_status"] = "PUBLISHED"
    posting["suspended_reason"] = None
    db.touch(posting)
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings/<posting_id>/archive", methods=["POST"])
@require("BrandProgramLead")
def archive_posting(posting_id):
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    if posting["content_status"] == "ARCHIVED":
        raise ApiError("ERR_POSTING_ALREADY_ARCHIVED", "The posting is already archived.")
    posting["content_status"] = "ARCHIVED"
    _release_flights(posting,
                     ("RESERVED", "ACTIVE", "PAUSED_PACING", "SUSPENDED_CONTENT"),
                     "CANCELLED", "CANCELLED", "FLIGHT_CANCELLED")
    db.touch(posting)
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings/<posting_id>", methods=["GET"])
@require(*READ_ROLES)
def get_posting(posting_id):
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings/<posting_id>/conversion", methods=["GET"])
@require(*CONVERSION_ROLES)
def posting_conversion(posting_id):
    posting = calc.must_get(db.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    return response.ok(serialize.posting(posting))


@bp.route("/job-postings", methods=["GET"])
@require(*READ_ROLES)
def list_postings():
    limit, offset = V.pagination()
    rows = calc.by_created(db.postings.values())
    job_family_id = V.qs("job_family_id")
    if job_family_id:
        rows = [r for r in rows if r["job_family_id"] == job_family_id]
    content_status = V.qs("content_status")
    if content_status:
        rows = [r for r in rows if r["content_status"] == content_status]
    compliance_status = V.qs("compliance_status")
    if compliance_status:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.posting(r) for r in page], meta)
