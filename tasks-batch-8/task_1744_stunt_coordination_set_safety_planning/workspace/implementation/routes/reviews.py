"""PostStuntReview: open, close (drives sequence terminal/reshoot transitions)."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_review,
    gate_posture_active,
    serialize_review,
    stamp_new,
    stamp_mutable,
    touch,
    REVIEW_OUTCOMES,
    default_sort_key,
)
from errors import (
    err,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_REVIEW_INVALID_STATE,
    ERR_REVIEW_ALREADY_OPEN,
    ERR_CROSS_PRODUCTION_REFERENCE,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_enum,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("reviews", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
SAFETY = ["SafetyOfficer"]


@bp.post("/api/post-stunt-reviews")
def create_review():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, SAFETY)

    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])

    prod = get_production(seq["production_id"])
    gate_posture_active(prod)

    if seq["status"] != "EXECUTED":
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "A post-stunt review requires the sequence in EXECUTED", 409)

    for r in store.reviews.values():
        if r["sequence_id"] == seq["id"] and r["status"] == "OPEN":
            raise err(ERR_REVIEW_ALREADY_OPEN,
                      "An OPEN review already exists for this sequence", 409)

    if seq["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "production_id must equal the sequence's production", 422)

    review = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "reviewer_user_id": user_id,
                "status": "OPEN",
                "outcome": None,
                "findings": None,
            }
        )
    )
    store.reviews[review["id"]] = review
    return ok(serialize_review(review), 201)


@bp.get("/api/post-stunt-reviews")
def list_reviews():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    status = request.args.get("status")
    items = []
    for r in store.reviews.values():
        if production_id is not None and r["production_id"] != production_id:
            continue
        if sequence_id is not None and r["sequence_id"] != sequence_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_review(r) for r in page], total, limit, offset)


@bp.get("/api/post-stunt-reviews/<rid>")
def get_one_review(rid):
    _, role = auth()
    require_role(role, READ_ROLES)
    review = get_review(rid)
    return ok(serialize_review(review), 200)


@bp.post("/api/post-stunt-reviews/<rid>/close")
def close_review(rid):
    body = get_body()
    data = validate_payload(
        body,
        {
            "outcome": (v_enum(REVIEW_OUTCOMES), True, None),
            "findings": (v_string, True, None),
        },
    )
    _, role = auth()
    require_role(role, SAFETY)
    review = get_review(rid)
    prod = get_production(review["production_id"])
    gate_posture_active(prod)
    if review["status"] != "OPEN":
        raise err(ERR_REVIEW_INVALID_STATE, "close requires status OPEN", 409)

    review["status"] = "CLOSED"
    review["outcome"] = data["outcome"]
    review["findings"] = data["findings"]
    touch(review)

    seq = get_sequence(review["sequence_id"])
    outcome = data["outcome"]
    if seq["status"] == "EXECUTED":
        if outcome == "ACCEPTED_AS_SHOT":
            seq["status"] = "REVIEWED"
            touch(seq)
        elif outcome == "RESHOOT_REQUIRED":
            seq["status"] = "DESIGN_LOCKED"
            seq["design_revision"] += 1
            touch(seq)
        elif outcome == "SAFETY_DEFICIENCY":
            seq["status"] = "DESIGN_LOCKED"
            seq["design_revision"] += 1
            pinned_id = seq["current_assessment_id"]
            seq["current_assessment_id"] = None
            if pinned_id is not None:
                pinned = store.assessments.get(pinned_id)
                if pinned is not None and pinned["status"] == "APPROVED":
                    pinned["status"] = "SUPERSEDED"
                    touch(pinned)
            touch(seq)
    return ok(serialize_review(review), 200)
