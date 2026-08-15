"""GiftedCase, MeasureScore, and CommitteeReview (case-scoped) endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_CYCLE_NOT_OPEN,
    ERR_DUPLICATE_CASE,
    ERR_DUPLICATE_MEASURE,
    ERR_EXTERNAL_ID_TOO_OLD,
    ERR_GRADE_BAND_MISMATCH,
    ERR_INCOMPLETE_MEASURES,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_CYCLE_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEASURE_OUTSIDE_VALIDITY,
    ERR_REFERRAL_WINDOW_CLOSED,
    ERR_REVIEW_ALREADY_OPEN,
    ERR_TRANSFER_WINDOW_LAPSED,
    ERR_GUARDIAN_MISMATCH,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_enum,
    optional_string,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    parse_date,
    one_decimal_ok,
    serialize_case,
    serialize_measure,
    serialize_review,
)
from services import domain

bp = Blueprint("cases", __name__)

PATHWAYS = {"UNIVERSAL_SCREEN", "REFERRAL", "TRANSFER_HONOR"}
REFERRAL_SOURCES = {"TEACHER", "PARENT", "SELF"}
MEASURE_TYPES = {"ABILITY", "ACHIEVEMENT", "RATING_SCALE", "PORTFOLIO"}

BAND_RANGES = {
    "ELEMENTARY": (0, 5),
    "MIDDLE": (6, 8),
    "HIGH": (9, 12),
}


def _grade_in_band(grade_level, band):
    lo, hi = BAND_RANGES[band]
    return lo <= grade_level <= hi


# ---------------------------------------------------------------------------
# Case intake
# ---------------------------------------------------------------------------


@bp.route("/gifted/cases", methods=["POST"])
def create_case():
    user_id, role = require_roles("GiftedCoordinator", "ReferringEducator", "ParentGuardian")
    body = get_json_body()
    require_fields(body, ["student_id", "cycle_id", "pathway"])
    student_id = require_string(body, "student_id")
    cycle_id = require_string(body, "cycle_id")
    pathway = require_enum(body, "pathway", PATHWAYS)

    # Pathway-conditional role gate (PRD §3.3):
    #  - UNIVERSAL_SCREEN: GiftedCoordinator only
    #  - TRANSFER_HONOR: GiftedCoordinator only
    #  - REFERRAL: ReferringEducator files TEACHER; ParentGuardian files PARENT;
    #    coordinators may file any referral (TEACHER/PARENT/SELF).
    referral_source = body.get("referral_source")
    external_district_name = body.get("external_district_name")
    external_identified_on = body.get("external_identified_on")

    if pathway == "REFERRAL":
        if referral_source not in REFERRAL_SOURCES:
            raise ApiError(ERR_INVALID_REQUEST, "referral_source is required for REFERRAL and must be TEACHER | PARENT | SELF", 400)
        if role == "ReferringEducator" and referral_source != "TEACHER":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "ReferringEducator files referral_source TEACHER", 403)
        if role == "ParentGuardian" and referral_source != "PARENT":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "ParentGuardian files referral_source PARENT", 403)
    else:
        if role != "GiftedCoordinator":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, f"pathway {pathway} requires GiftedCoordinator", 403)

    # existence, left to right: student then cycle (both are body FKs here;
    # PRD §3.6 names the site FK ERR_NOT_FOUND; the same treatment applies)
    student = get_or_404(db.students, student_id, "student")
    cycle = get_or_404(db.screening_cycles, cycle_id, "screening cycle")

    # pathway-conditional field shape (priority 5)
    if pathway == "UNIVERSAL_SCREEN":
        if referral_source is not None or external_district_name is not None or external_identified_on is not None:
            raise ApiError(ERR_INVALID_REQUEST, "UNIVERSAL_SCREEN forbids referral_source and external_* fields", 400)
    elif pathway == "REFERRAL":
        if external_district_name is not None or external_identified_on is not None:
            raise ApiError(ERR_INVALID_REQUEST, "REFERRAL forbids external_* fields", 400)
    else:  # TRANSFER_HONOR
        if referral_source is not None:
            raise ApiError(ERR_INVALID_REQUEST, "TRANSFER_HONOR forbids referral_source", 400)
        if not isinstance(external_district_name, str) or not external_district_name.strip():
            raise ApiError(ERR_INVALID_REQUEST, "external_district_name is required for TRANSFER_HONOR", 400)
        if external_identified_on is None:
            raise ApiError(ERR_INVALID_REQUEST, "external_identified_on is required for TRANSFER_HONOR", 400)
        parse_date(external_identified_on, "external_identified_on")

    # state gate: case intake requires cycle OPEN (priority 7)
    if cycle["status"] != "OPEN":
        raise ApiError(ERR_CYCLE_NOT_OPEN, "case intake requires cycle status OPEN", 409)

    # referential fit: grade band (priority 9)
    if not _grade_in_band(student["grade_level"], cycle["grade_band"]):
        raise ApiError(ERR_GRADE_BAND_MISMATCH, "student.grade_level not in the cycle's grade_band", 422)

    # uniqueness: one case per (student, cycle) (priority 10)
    for c in db.gifted_cases.values():
        if c["student_id"] == student_id and c["cycle_id"] == cycle_id:
            raise ApiError(ERR_DUPLICATE_CASE, "a case already exists for (student, cycle)", 409)

    # temporal windows (priority 11)
    today = db.today()
    if pathway == "REFERRAL":
        referral_close = parse_date(cycle["referral_close_on"], "referral_close_on")
        if today > referral_close:
            raise ApiError(ERR_REFERRAL_WINDOW_CLOSED, "referral filed after the cycle's referral_close_on", 422)
    elif pathway == "TRANSFER_HONOR":
        created_date = parse_date(student["created_at"][:10], "created_at")
        if (today - created_date).days > 45:
            raise ApiError(ERR_TRANSFER_WINDOW_LAPSED, "student record is more than 45 days old", 422)
        ext_date = parse_date(external_identified_on, "external_identified_on")
        if (today - ext_date).days > 730:
            raise ApiError(ERR_EXTERNAL_ID_TOO_OLD, "external identification is more than 730 days old", 422)

    ts = now_iso()
    case = {
        "id": new_id(),
        "student_id": student_id,
        "cycle_id": cycle_id,
        "pathway": pathway,
        "referral_source": referral_source if pathway == "REFERRAL" else None,
        "referrer_user_id": user_id if pathway == "REFERRAL" else None,
        "external_district_name": external_district_name if pathway == "TRANSFER_HONOR" else None,
        "external_identified_on": external_identified_on if pathway == "TRANSFER_HONOR" else None,
        "status": "SCREENING",
        "composite_score": None,
        "scored_variant": None,
        "appeal_used": False,
        "decided_on": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }

    if pathway == "TRANSFER_HONOR":
        case["status"] = "IDENTIFIED"
        case["decided_on"] = today.isoformat()
        student["gifted_status"] = "IDENTIFIED"
        domain.touch(student)

    db.gifted_cases[case["id"]] = case
    return success_object(serialize_case(case), 201)


@bp.route("/gifted/cases", methods=["GET"])
def list_cases():
    require_roles(*ALL_ROLES)
    student_id = request.args.get("student_id")
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    pathway = request.args.get("pathway")
    items = list(db.gifted_cases.values())
    if student_id:
        items = [c for c in items if c["student_id"] == student_id]
    if cycle_id:
        items = [c for c in items if c["cycle_id"] == cycle_id]
    if status:
        items = [c for c in items if c["status"] == status]
    if pathway:
        items = [c for c in items if c["pathway"] == pathway]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_case(c) for c in page], total, limit, offset)


@bp.route("/gifted/cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles(*ALL_ROLES)
    case = get_or_404(db.gifted_cases, cid, "case")
    return success_object(serialize_case(case), 200)


# ---------------------------------------------------------------------------
# MeasureScore
# ---------------------------------------------------------------------------


@bp.route("/gifted/cases/<cid>/measure-scores", methods=["POST"])
def create_measure_score(cid):
    require_roles("GiftedCoordinator")
    case = get_or_404(db.gifted_cases, cid, "case")
    body = get_json_body()
    require_fields(body, ["measure_type", "percentile", "administered_on"])
    measure_type = require_enum(body, "measure_type", MEASURE_TYPES)

    percentile = body["percentile"]
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "percentile must be a number", 400)
    if percentile < 1.0 or percentile > 99.9:
        raise ApiError(ERR_INVALID_REQUEST, "percentile must be between 1.0 and 99.9 inclusive", 400)
    if not one_decimal_ok(percentile):
        raise ApiError(ERR_INVALID_REQUEST, "percentile must have at most one decimal place", 400)

    administered_raw = body["administered_on"]
    administered = parse_date(administered_raw, "administered_on")

    # future date — shape tier (priority 5)
    today = db.today()
    if administered > today:
        raise ApiError(ERR_INVALID_REQUEST, "administered_on must not be in the future", 400)

    # state gates (priority 7): case SCREENING; cycle OPEN or SCORING
    if case["status"] != "SCREENING":
        raise ApiError(ERR_INVALID_CASE_STATE, "measure entry requires case status SCREENING", 409)
    cycle = db.screening_cycles.get(case["cycle_id"])
    if cycle is None or cycle["status"] not in {"OPEN", "SCORING"}:
        raise ApiError(ERR_INVALID_CYCLE_STATE, "measure entry requires cycle OPEN or SCORING", 409)

    # uniqueness: one score per (case, measure_type) (priority 10)
    for m in db.measure_scores.values():
        if m["case_id"] == cid and m["measure_type"] == measure_type:
            raise ApiError(ERR_DUPLICATE_MEASURE, "a MeasureScore with this measure_type already exists on the case", 409)

    # validity window at entry (priority 11), against the PUBLISHED profile
    profile = _published_profile(cycle)
    validity_days = profile["measure_validity_days"] if profile else 730
    if (today - administered).days > validity_days:
        raise ApiError(ERR_MEASURE_OUTSIDE_VALIDITY, "administered_on is earlier than today - measure_validity_days", 422)

    ts = now_iso()
    ms = {
        "id": new_id(),
        "case_id": cid,
        "measure_type": measure_type,
        "percentile": percentile,
        "administered_on": administered_raw,
        "weighted_contribution": None,
        "created_at": ts,
    }
    db.measure_scores[ms["id"]] = ms
    return success_object(serialize_measure(ms), 201)


@bp.route("/gifted/cases/<cid>/measure-scores", methods=["GET"])
def list_measure_scores(cid):
    require_roles(*ALL_ROLES)
    get_or_404(db.gifted_cases, cid, "case")
    items = [m for m in db.measure_scores.values() if m["case_id"] == cid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_measure(m) for m in page], total, limit, offset)


def _published_profile(cycle):
    pid = cycle.get("published_profile_id")
    if pid and pid in db.cut_score_profiles:
        return db.cut_score_profiles[pid]
    for p in db.cut_score_profiles.values():
        if p["cycle_id"] == cycle["id"] and p["status"] == "PUBLISHED":
            return p
    return None


# ---------------------------------------------------------------------------
# finalize-scoring
# ---------------------------------------------------------------------------


@bp.route("/gifted/cases/<cid>/finalize-scoring", methods=["POST"])
def finalize_scoring(cid):
    require_roles("GiftedCoordinator")
    case = get_or_404(db.gifted_cases, cid, "case")

    # state gates (priority 7)
    if case["status"] != "SCREENING":
        raise ApiError(ERR_INVALID_CASE_STATE, "finalize requires case status SCREENING", 409)
    cycle = db.screening_cycles.get(case["cycle_id"])
    if cycle is None or cycle["status"] != "SCORING":
        raise ApiError(ERR_INVALID_CYCLE_STATE, "finalize requires cycle status SCORING", 409)

    measures = [m for m in db.measure_scores.values() if m["case_id"] == cid]
    present = {m["measure_type"] for m in measures}
    if not {"ABILITY", "ACHIEVEMENT", "RATING_SCALE"}.issubset(present):
        raise ApiError(ERR_INCOMPLETE_MEASURES, "finalize requires ABILITY, ACHIEVEMENT, and RATING_SCALE scores", 422)

    profile = _published_profile(cycle)
    if profile is None:
        # A cycle in SCORING must have passed through OPEN which requires a
        # published profile; guard anyway.
        raise ApiError(ERR_INVALID_CYCLE_STATE, "no PUBLISHED cut-score profile for the cycle", 409)

    # freshness re-check at finalize (priority 11; PRD §3.4 — runs at entry
    # AND at finalize)
    today = db.today()
    for m in measures:
        administered = parse_date(m["administered_on"], "administered_on")
        if (today - administered).days > profile["measure_validity_days"]:
            raise ApiError(ERR_MEASURE_OUTSIDE_VALIDITY, "a measure is stale at finalize time", 422)

    student = db.students.get(case["student_id"])
    has_sped = any(sp["student_id"] == case["student_id"] for sp in db.sped_plans.values())

    composite, variant, contributions = domain.compute_composite(case, profile, measures, has_sped)

    for mid, line in contributions.items():
        db.measure_scores[mid]["weighted_contribution"] = float(line)

    case["composite_score"] = composite
    case["scored_variant"] = variant

    outcome = domain.cut_determination(composite, variant, profile)
    case["status"] = outcome
    if outcome in {"IDENTIFIED", "NOT_IDENTIFIED"}:
        case["decided_on"] = today.isoformat()
    if outcome == "IDENTIFIED" and student is not None:
        student["gifted_status"] = "IDENTIFIED"
        domain.touch(student)

    domain.touch(case)
    return success_object(serialize_case(case), 200)


# ---------------------------------------------------------------------------
# CommitteeReview (case-scoped create/list)
# ---------------------------------------------------------------------------


@bp.route("/gifted/cases/<cid>/committee-reviews", methods=["POST"])
def create_review(cid):
    user_id, role = require_roles("GiftedCoordinator", "ParentGuardian", "ReferringEducator")
    body = get_json_body()

    # review_kind-conditional role gate — PRD §2.5 priority 2 expressly
    # includes "review_kind-conditional roles", so it runs ahead of path-
    # parameter existence (priority 4). Peek at review_kind without consuming
    # shape validation (priority 5), which still runs after the 404 check.
    kind_peek = body.get("review_kind")
    if kind_peek == "BAND_REVIEW" and role != "GiftedCoordinator":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "BAND_REVIEW may be opened only by a GiftedCoordinator", 403)
    if kind_peek == "APPEAL" and role not in {"ParentGuardian", "ReferringEducator"}:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "APPEAL may be opened only by a ParentGuardian or ReferringEducator", 403)

    case = get_or_404(db.gifted_cases, cid, "case")
    require_fields(body, ["review_kind"])
    review_kind = require_enum(body, "review_kind", {"BAND_REVIEW", "APPEAL"})
    grounds = optional_string(body, "grounds", default=None)

    student = db.students.get(case["student_id"])
    cycle = db.screening_cycles.get(case["cycle_id"])

    # guardian ownership (priority 3)
    if review_kind == "APPEAL" and role == "ParentGuardian":
        if student is None or user_id != student.get("primary_guardian_user_id"):
            raise ApiError(ERR_GUARDIAN_MISMATCH, "guardian may appeal only for their own student", 403)

    # state gates (priority 7)
    if review_kind == "BAND_REVIEW":
        if case["status"] != "AWAITING_COMMITTEE":
            raise ApiError(ERR_INVALID_CASE_STATE, "BAND_REVIEW requires case AWAITING_COMMITTEE", 409)
        if cycle is None or cycle["status"] != "REVIEW":
            raise ApiError(ERR_INVALID_CYCLE_STATE, "BAND_REVIEW requires cycle REVIEW", 409)
    else:
        if case["status"] != "NOT_IDENTIFIED" or case["appeal_used"]:
            raise ApiError(ERR_INVALID_CASE_STATE, "APPEAL requires case NOT_IDENTIFIED with appeal unused", 409)
        if cycle is None or cycle["status"] != "REVIEW":
            raise ApiError(ERR_INVALID_CYCLE_STATE, "APPEAL requires cycle REVIEW", 409)

    # at most one non-DECIDED review per case (priority 10)
    for r in db.committee_reviews.values():
        if r["case_id"] == cid and r["status"] != "DECIDED":
            raise ApiError(ERR_REVIEW_ALREADY_OPEN, "a non-DECIDED review already exists for the case", 409)

    # appeal window (priority 11)
    if review_kind == "APPEAL":
        decided = parse_date(case["decided_on"], "decided_on")
        if (db.today() - decided).days > 30:
            raise ApiError(ERR_APPEAL_WINDOW_CLOSED, "appeal filed more than 30 days after decided_on", 422)

    ts = now_iso()
    review = {
        "id": new_id(),
        "case_id": cid,
        "review_kind": review_kind,
        "grounds": grounds,
        "status": "VOTING",
        "outcome": None,
        "decided_on": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.committee_reviews[review["id"]] = review

    if review_kind == "APPEAL":
        case["appeal_used"] = True
        case["status"] = "APPEAL_PENDING"
        domain.touch(case)

    return success_object(serialize_review(review), 201)


@bp.route("/gifted/cases/<cid>/committee-reviews", methods=["GET"])
def list_reviews(cid):
    require_roles(*ALL_ROLES)
    get_or_404(db.gifted_cases, cid, "case")
    items = [r for r in db.committee_reviews.values() if r["case_id"] == cid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_review(r) for r in page], total, limit, offset)
