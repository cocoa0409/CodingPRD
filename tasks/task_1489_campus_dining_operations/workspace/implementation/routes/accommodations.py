"""AccommodationRequest endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    ALLERGENS,
    DIETARY_REQUIREMENTS,
    get_accommodation,
    get_hall,
    ser,
    stamp,
    touch,
)
from util import as_enum, as_list, as_str, body, required
from routes.common import list_endpoint

bp = Blueprint("accommodations", __name__)


@bp.post("/accommodation-requests")
def create_accommodation():
    auth(["HallManager"])
    data = body()
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    student_ref = as_str(required(data, "student_ref"), "student_ref")
    exclusions = as_list(required(data, "allergen_exclusions"), "allergen_exclusions")
    for a in exclusions:
        as_enum(a, "allergen_exclusions", ALLERGENS)
    requirement = as_enum(
        required(data, "dietary_requirement"), "dietary_requirement", DIETARY_REQUIREMENTS
    )
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "student_ref": student_ref,
        "allergen_exclusions": exclusions,
        "dietary_requirement": requirement,
        "review_notes": "",
        "status": "SUBMITTED",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["accommodation_requests"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/accommodation-requests")
def list_accommodations():
    return list_endpoint(
        "accommodation_requests",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("status", "status"),
            ("student_ref", "student_ref"),
        ],
    )


@bp.get("/accommodation-requests/<aid>")
def get_one_accommodation(aid):
    auth(ALL_ROLES)
    return ok(ser(get_accommodation(aid)))


@bp.post("/accommodation-requests/<aid>/start-review")
def start_review(aid):
    auth(["Dietitian"])
    rec = get_accommodation(aid)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not SUBMITTED")
    rec["status"] = "NUTRITION_REVIEW"
    touch(rec)
    return ok(ser(rec))


@bp.post("/accommodation-requests/<aid>/request-info")
def request_info(aid):
    auth(["Dietitian"])
    rec = get_accommodation(aid)
    if rec["status"] != "NUTRITION_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not in NUTRITION_REVIEW")
    data = body()
    rec["review_notes"] = as_str(required(data, "review_notes"), "review_notes")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok(ser(rec))


@bp.post("/accommodation-requests/<aid>/approve")
def approve_accommodation(aid):
    auth(["Dietitian"])
    rec = get_accommodation(aid)
    if rec["status"] != "NUTRITION_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not in NUTRITION_REVIEW")
    # Tier 6 food-safety gate: a suitable menu item must exist at the hall.
    exclusions = set(rec["allergen_exclusions"])
    suitable = False
    for recipe in DB["recipes"].values():
        if recipe["dining_hall_id"] != rec["dining_hall_id"]:
            continue
        if recipe["status"] != "ACTIVE":
            continue
        if exclusions & set(recipe["allergen_tags"]):
            continue
        if rec["dietary_requirement"] != "OTHER" and rec["dietary_requirement"] not in recipe["dietary_flags"]:
            continue
        suitable = True
        break
    if not suitable:
        raise ApiError(
            "ERR_NO_SUITABLE_MENU",
            422,
            "No ACTIVE recipe at the hall satisfies the dietary requirement",
        )
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(ser(rec))


@bp.post("/accommodation-requests/<aid>/activate")
def activate_accommodation(aid):
    auth(["KitchenLead"])
    rec = get_accommodation(aid)
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not APPROVED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(ser(rec))


@bp.post("/accommodation-requests/<aid>/cancel")
def cancel_accommodation(aid):
    auth(["HallManager", "Dietitian"])
    rec = get_accommodation(aid)
    if rec["status"] not in ("SUBMITTED", "NUTRITION_REVIEW", "APPROVED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Request cannot be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(ser(rec))
