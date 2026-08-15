"""SelfStudyRating endpoints."""
from flask import Blueprint, request

from db import DB, fmt_iso, clock_now, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404, recompute_campus_composite
from util import as_int, body, paginate, pagination, required, stamp_new, touch

bp = Blueprint("ratings", __name__)


def rating_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.post("/accreditation/ratings")
def create_rating():
    auth(["SchoolLeader"])
    data = body()
    term_id = required(data, "term_id")
    campus_id = required(data, "campus_id")
    standard_id = required(data, "standard_id")
    rating = as_int(required(data, "rating"), "rating")
    if rating < 1 or rating > 4:
        raise ApiError("ERR_VALIDATION", 400, "rating must be in 1..4")
    expected_term_version = as_int(
        required(data, "expected_term_version"), "expected_term_version"
    )

    term = DB["terms"].get(term_id)
    campus = DB["campuses"].get(campus_id)
    standard = DB["standards"].get(standard_id)

    # Referential integrity: campus belongs to the term's system; standard exists.
    if term is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"AccreditationTerm not found: {term_id}")
    if campus is None or campus["system_id"] != term["system_id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "campus_id does not belong to the term's system",
        )
    if standard is None:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "standard_id does not exist")

    # OCC check on the term.
    if term["version"] != expected_term_version:
        raise ApiError(
            "ERR_STALE_TERM_VERSION",
            412,
            "expected_term_version does not match the term's current version",
        )

    # Uniqueness per (term, campus, standard).
    for r in DB["ratings"].values():
        if (
            r["term_id"] == term_id
            and r["campus_id"] == campus_id
            and r["standard_id"] == standard_id
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "A rating already exists for this (term, campus, standard)",
            )

    record = {
        "id": new_id(),
        "term_id": term_id,
        "campus_id": campus_id,
        "standard_id": standard_id,
        "rating": rating,
        "status": "DRAFT",
        "finalized_at": None,
    }
    stamp_new(record, with_version=True)
    DB["ratings"][record["id"]] = record
    # Creating a rating increments the term's version (per endpoint side_effects).
    touch(term)
    return ok(rating_view(record), status=201)


@bp.get("/accreditation/terms/<id>/ratings")
def list_term_ratings(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    rows = [r for r in DB["ratings"].values() if r["term_id"] == id]
    rows.sort(key=lambda r: r["created_at"])
    campus_id = request.args.get("campus_id")
    standard_id = request.args.get("standard_id")
    status = request.args.get("status")
    if campus_id:
        rows = [r for r in rows if r["campus_id"] == campus_id]
    if standard_id:
        rows = [r for r in rows if r["standard_id"] == standard_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([rating_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/ratings/<id>")
def get_rating(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    row = get_or_404("ratings", id, "SelfStudyRating")
    return ok(rating_view(row))


@bp.post("/accreditation/ratings/<id>/submit")
def submit_rating(id):
    auth(["SchoolLeader"])
    rating_row = get_or_404("ratings", id, "SelfStudyRating")
    if rating_row["status"] not in ("DRAFT", "REOPENED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Rating must be DRAFT or REOPENED to submit"
        )
    # rating field is always in 1..4 because create validates it; nothing more to check.
    term = DB["terms"].get(rating_row["term_id"])
    if term is None or term["status"] != "SELF_STUDY":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Owning term must be in SELF_STUDY"
        )
    if rating_row["status"] == "DRAFT":
        campus = DB["campuses"].get(rating_row["campus_id"])
        if campus is None or campus["campus_status"] != "IN_SCOPE":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Campus must be IN_SCOPE"
            )
    # REOPENED -> SUBMITTED skips the campus-scope re-check per PRD 3.3.
    rating_row["status"] = "SUBMITTED"
    touch(rating_row)
    return ok(rating_view(rating_row))


@bp.post("/accreditation/ratings/<id>/finalize")
def finalize_rating(id):
    auth(["AccreditationOfficer"])
    rating_row = get_or_404("ratings", id, "SelfStudyRating")
    if rating_row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Rating must be SUBMITTED to finalize")
    standard = DB["standards"].get(rating_row["standard_id"])
    min_items = standard["evidence_min_items"] if standard else 0
    approved = sum(
        1
        for e in DB["evidence"].values()
        if e["rating_id"] == id and e["review_status"] == "APPROVED"
    )
    if approved < min_items:
        raise ApiError(
            "ERR_THRESHOLD_NOT_MET",
            422,
            f"Evidence quorum not met: {approved} APPROVED < min {min_items}",
        )
    rating_row["status"] = "FINALIZED"
    rating_row["finalized_at"] = fmt_iso(clock_now())
    touch(rating_row)
    campus = DB["campuses"].get(rating_row["campus_id"])
    if campus is not None:
        recompute_campus_composite(campus)
        touch(campus)
    return ok(rating_view(rating_row))


@bp.post("/accreditation/ratings/<id>/reopen")
def reopen_rating(id):
    auth(["AccreditationOfficer"])
    rating_row = get_or_404("ratings", id, "SelfStudyRating")
    if rating_row["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Rating must be FINALIZED to reopen")
    term = DB["terms"].get(rating_row["term_id"])
    if term is None or term["status"] != "SELF_STUDY":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Owning term must be in SELF_STUDY"
        )
    rating_row["status"] = "REOPENED"
    rating_row["finalized_at"] = None
    touch(rating_row)
    campus = DB["campuses"].get(rating_row["campus_id"])
    if campus is not None:
        recompute_campus_composite(campus)
        touch(campus)
    return ok(rating_view(rating_row))
