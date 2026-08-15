"""PlacementRecommendation endpoints with OCC on field version."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_NOT_OPEN,
    ERR_STALE_FIELD_VERSION,
)
from middleware import authenticate, check_grower_ownership
from response import success_obj, success_list
from routes import make_blueprint
from services import compute_placement_score, check_trait_gate
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks

bp = make_blueprint("recommendations")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]


@bp.post("/recommendations")
def create_recommendation():
    authenticate(["Agronomist"])
    body = body_json()
    exist_body_fks(body, {
        "field_id": ("fields", "field"),
        "variety_id": ("varieties", "variety"),
        "program_id": ("programs", "program"),
    })
    check_shape(body, {
        "field_id": {"type": "string", "required": True},
        "variety_id": {"type": "string", "required": True},
        "program_id": {"type": "string", "required": True},
        "seeding_rate_seeds_per_acre": {"type": "integer", "required": True, "min": 1},
        "expected_yield_index": {"type": "number", "required": True},
        "expected_field_version": {"type": "integer", "required": True},
    })
    field = db.get("fields", body["field_id"])
    variety = db.get("varieties", body["variety_id"])
    if body["expected_field_version"] != field["version"]:
        raise ApiError(ERR_STALE_FIELD_VERSION, 412, "field version has advanced")
    rec = db.new_entity("recommendations", {
        "field_id": body["field_id"],
        "variety_id": body["variety_id"],
        "program_id": body["program_id"],
        "grower_id": field["grower_id"],
        "seeding_rate_seeds_per_acre": body["seeding_rate_seeds_per_acre"],
        "expected_yield_index": body["expected_yield_index"],
        "placement_score": compute_placement_score(field, variety),
        "status": "DRAFT",
        "supersedes_recommendation_id": None,
        "published_at": None,
        "decided_at": None,
    })
    db.touch(field)  # successful create increments the field's version
    return success_obj(db.public(rec), 201)


@bp.get("/recommendations/<rid>")
def get_recommendation(rid):
    uid, role = authenticate(ALL_ROLES)
    rec = require_fk("recommendations", rid, "recommendation")
    check_grower_ownership(uid, role, rec["grower_id"])
    return success_obj(db.public(rec), 200)


@bp.get("/recommendations")
def list_recommendations():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("recommendations")
    if role == "Grower":
        items = [r for r in items if r["grower_id"] == uid]
    items = apply_filters(items, [
        "field_id", "variety_id", "program_id", "grower_id",
        "supersedes_recommendation_id", "status",
    ])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.post("/recommendations/<rid>/publish")
def publish_recommendation(rid):
    authenticate(["Agronomist"])
    rec = require_fk("recommendations", rid, "recommendation")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a DRAFT recommendation can be published")
    program = db.get("programs", rec["program_id"])
    if program is None or program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not OPEN")
    field = db.get("fields", rec["field_id"])
    if field is None or field["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "field is not ACTIVE")
    variety = db.get("varieties", rec["variety_id"])
    if field is not None and variety is not None:
        rec["placement_score"] = compute_placement_score(field, variety)
    prior = None
    for other in db.all_of("recommendations"):
        if (
            other["id"] != rec["id"]
            and other["field_id"] == rec["field_id"]
            and other["program_id"] == rec["program_id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            db.touch(other)
            prior = other
    rec["supersedes_recommendation_id"] = prior["id"] if prior else None
    rec["status"] = "PUBLISHED"
    rec["published_at"] = db.fmt_ts(db.now())
    db.touch(rec)
    return success_obj(db.public(rec), 200)


@bp.post("/recommendations/<rid>/accept")
def accept_recommendation(rid):
    uid, role = authenticate(["Grower"])
    rec = require_fk("recommendations", rid, "recommendation")
    check_grower_ownership(uid, role, rec["grower_id"])
    if rec["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a PUBLISHED recommendation can be accepted")
    program = db.get("programs", rec["program_id"])
    if program is None or program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not OPEN")
    variety = db.get("varieties", rec["variety_id"])
    if variety is not None:
        check_trait_gate(rec["grower_id"], variety)
    rec["status"] = "ACCEPTED"
    rec["decided_at"] = db.fmt_ts(db.now())
    db.touch(rec)
    return success_obj(db.public(rec), 200)


@bp.post("/recommendations/<rid>/withdraw")
def withdraw_recommendation(rid):
    authenticate(["Agronomist", "DealerAdmin"])
    rec = require_fk("recommendations", rid, "recommendation")
    if rec["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a DRAFT or PUBLISHED recommendation can be withdrawn")
    rec["status"] = "WITHDRAWN"
    rec["decided_at"] = db.fmt_ts(db.now())
    db.touch(rec)
    return success_obj(db.public(rec), 200)
