"""Diagnostic review endpoints (PRD §3.2)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REVIEW_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_TEAM_SCHEDULE_BUFFER,
)
from helpers import (
    body_or_empty,
    get_or_404,
    paginate,
    query_filter,
    reject_unknown,
    req_date,
    req_str,
)
from middleware import auth
from response import ok, ok_list

bp = Blueprint("diagnostic_reviews", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

REVIEW_STATUSES = (
    "SCHEDULED",
    "IN_SESSION",
    "RECOMMENDATIONS_ISSUED",
    "ACCEPTED",
    "SUPERSEDED",
    "CANCELLED",
)

RECOMMENDATION_CODES = (
    "UPGRADE_DEVICES",
    "CLOSE_CROSSING",
    "CONSOLIDATE",
    "INSTALL_PREEMPTION",
    "NO_ACTION",
)

TEAM_REVIEW_MIN_GAP_DAYS = 2


def serialize_review(r):
    return {
        "id": r["id"],
        "crossing_id": r["crossing_id"],
        "team_id": r["team_id"],
        "scheduled_date": r["scheduled_date"],
        "status": r["status"],
        "recommendations": r["recommendations"],
        "accepted_at": r["accepted_at"],
        "superseded_by_review_id": r["superseded_by_review_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/diagnostic-reviews")
def create_review():
    auth(["ProgramAdministrator"])
    body = body_or_empty()

    # Priority 3: body FKs left-to-right (crossing_id, then team_id).
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    team_id = body.get("team_id")
    if isinstance(team_id, str) and team_id and team_id not in store.teams:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, f"Diagnostic team {team_id} does not exist")

    # Priority 4: the crossing must be ACTIVE.
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")

    # Priority 7: request shape.
    reject_unknown(body, ("crossing_id", "team_id", "scheduled_date"))
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    team_id = req_str(body, "team_id")
    if team_id not in store.teams:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, f"Diagnostic team {team_id} does not exist")
    scheduled_date, scheduled_dt = req_date(body, "scheduled_date")

    # Priority 9: team scheduling buffer — a team's non-CANCELLED reviews must
    # be at least TEAM_REVIEW_MIN_GAP_DAYS apart.
    for other in store.reviews.values():
        if other["team_id"] != team_id or other["status"] == "CANCELLED":
            continue
        gap = abs((other["_scheduled_dt"] - scheduled_dt).days)
        if gap < TEAM_REVIEW_MIN_GAP_DAYS:
            raise ApiError(
                ERR_TEAM_SCHEDULE_BUFFER,
                409,
                "Team already has a review scheduled less than 2 days from the requested date",
            )

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "team_id": team_id,
        "scheduled_date": scheduled_date,
        "_scheduled_dt": scheduled_dt,
        "status": "SCHEDULED",
        "recommendations": None,
        "accepted_at": None,
        "superseded_by_review_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.reviews[rec["id"]] = rec
    return ok(serialize_review(rec), 201)


@bp.get("/diagnostic-reviews")
def list_reviews():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    team_f = query_filter("team_id")
    status_f = query_filter("status")
    items = []
    for r in store.reviews.values():
        if crossing_f is not None and r["crossing_id"] != crossing_f:
            continue
        if team_f is not None and r["team_id"] != team_f:
            continue
        if status_f is not None and r["status"] != status_f:
            continue
        items.append(r)
    items = sorted(items, key=lambda r: r["created_at"])
    page, meta = paginate([serialize_review(r) for r in items])
    return ok_list(page, meta)


@bp.get("/diagnostic-reviews/<review_id>")
def get_review(review_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.reviews, review_id, ERR_REVIEW_NOT_FOUND,
                     f"Diagnostic review {review_id} does not exist")
    return ok(serialize_review(rec))


def _parse_to_status(body):
    to_status = body.get("to_status")
    if not isinstance(to_status, str) or to_status not in REVIEW_STATUSES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"to_status must be one of: {', '.join(REVIEW_STATUSES)}",
        )
    return to_status


@bp.post("/diagnostic-reviews/<review_id>/transition")
def transition_review(review_id):
    auth(["ProgramAdministrator", "RailSafetyOfficer"])
    rec = get_or_404(store.reviews, review_id, ERR_REVIEW_NOT_FOUND,
                     f"Diagnostic review {review_id} does not exist")
    body = body_or_empty()
    reject_unknown(body, ("to_status",))
    to_status = _parse_to_status(body)

    if to_status == "IN_SESSION":
        if rec["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to IN_SESSION from {rec['status']}")
        rec["status"] = "IN_SESSION"
    elif to_status == "ACCEPTED":
        if rec["status"] != "RECOMMENDATIONS_ISSUED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to ACCEPTED from {rec['status']}")
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is None or crossing["status"] != "ACTIVE":
            raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                           "The crossing under review is not ACTIVE")
        rec["status"] = "ACCEPTED"
        rec["accepted_at"] = now_iso()
        # Supersede the unique prior ACCEPTED review for the same crossing.
        for other in store.reviews.values():
            if (
                other["id"] != rec["id"]
                and other["crossing_id"] == rec["crossing_id"]
                and other["status"] == "ACCEPTED"
            ):
                other["status"] = "SUPERSEDED"
                other["superseded_by_review_id"] = rec["id"]
                other["updated_at"] = now_iso()
    elif to_status == "CANCELLED":
        if rec["status"] not in ("SCHEDULED", "IN_SESSION"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to CANCELLED from {rec['status']}")
        rec["status"] = "CANCELLED"
    else:
        # SCHEDULED / RECOMMENDATIONS_ISSUED / SUPERSEDED are never valid targets
        # of this endpoint's declared transitions.
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_review(rec))


@bp.post("/diagnostic-reviews/<review_id>/issue-recommendations")
def issue_recommendations(review_id):
    auth(["RailSafetyOfficer"])
    rec = get_or_404(store.reviews, review_id, ERR_REVIEW_NOT_FOUND,
                     f"Diagnostic review {review_id} does not exist")
    if rec["status"] != "IN_SESSION":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Recommendations can be issued only from IN_SESSION (current: {rec['status']})")
    body = body_or_empty()
    reject_unknown(body, ("recommendations",))
    recommendations = body.get("recommendations")
    if (
        not isinstance(recommendations, list)
        or len(recommendations) == 0
        or any(not isinstance(r, str) or r not in RECOMMENDATION_CODES for r in recommendations)
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "recommendations must be a non-empty list of: " + ", ".join(RECOMMENDATION_CODES),
        )
    rec["recommendations"] = list(recommendations)
    rec["status"] = "RECOMMENDATIONS_ISSUED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_review(rec))
