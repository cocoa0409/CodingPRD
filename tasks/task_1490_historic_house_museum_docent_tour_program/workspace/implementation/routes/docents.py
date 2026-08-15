"""Docent endpoints: recruitment, training, certification, deactivation."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    deactivate_docent_cascade,
    lookup,
    readiness_standard,
    ser_docent,
    ser_shift,
    sort_items,
    stamp,
    touch,
)
from util import body, pagination_args, req_enum, req_int, req_str

bp = Blueprint("docents", __name__)

DOCENT_READ_ROLES = ["MuseumAdmin", "DocentCoordinator", "Docent"]


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


@bp.post("/docents")
def create_docent():
    auth(["DocentCoordinator"])
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "status": "APPLICANT",
        "training_hours": 0,
        "shadow_tours_completed": 0,
        "quiz_score": None,
        "certified_route_ids": [],
    }
    stamp(rec)
    DB["docents"][rec["id"]] = rec
    return ok(ser_docent(rec), 201)


@bp.get("/docents/<did>")
def get_docent(did):
    user_id, role = auth(DOCENT_READ_ROLES)
    if role == "Docent" and did != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Docents may read only their own record")
    return ok(ser_docent(lookup("docents", did)))


@bp.post("/docents/<did>/advance")
def advance_docent(did):
    auth(["DocentCoordinator"])
    docent = lookup("docents", did)
    data = body()
    # Tier 3 (existence): route references inside route_ids, when provided.
    raw_routes = data.get("route_ids")
    if isinstance(raw_routes, list):
        for rid in raw_routes:
            lookup("routes", rid)
    # Tier 4 (request shape).
    to_status = req_enum(data, "to_status", ("TRAINEE", "CERTIFIED"))
    if to_status == "CERTIFIED" and (
        not isinstance(raw_routes, list)
        or len(raw_routes) < 1
        or not all(isinstance(x, str) for x in raw_routes)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "route_ids must be a non-empty array at certification",
        )
    # Tier 5 (lifecycle state).
    if to_status == "TRAINEE" and docent["status"] != "APPLICANT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an APPLICANT can advance to TRAINEE"
        )
    if to_status == "CERTIFIED" and docent["status"] != "TRAINEE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a TRAINEE can advance to CERTIFIED"
        )
    # Tier 8 (threshold gates).
    if to_status == "CERTIFIED":
        if (
            docent["training_hours"] < 20
            or docent["shadow_tours_completed"] < 3
            or (docent["quiz_score"] or 0) < 85
            or readiness_standard(docent) < 70
        ):
            raise ApiError(
                "ERR_CERTIFICATION_NOT_MET",
                422,
                "Certification thresholds are not met",
            )
        docent["certified_route_ids"] = list(raw_routes)
    docent["status"] = to_status
    touch(docent)
    return ok(ser_docent(docent))


@bp.post("/docents/<did>/deactivate")
def deactivate_docent(did):
    auth(["DocentCoordinator"])
    docent = lookup("docents", did)
    if docent["status"] not in ("TRAINEE", "CERTIFIED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a TRAINEE or CERTIFIED docent can be deactivated",
        )
    docent["status"] = "INACTIVE"
    touch(docent)
    deactivate_docent_cascade(docent)
    return ok(ser_docent(docent))


@bp.post("/docents/<did>/training-records")
def log_training(did):
    auth(["DocentCoordinator"])
    docent = lookup("docents", did)
    data = body()
    kind = req_enum(data, "kind", ("HOURS", "SHADOW_TOUR", "QUIZ"))
    value = req_int(data, "value")
    if kind == "HOURS":
        if value < 1:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "HOURS value must be at least 1"
            )
        docent["training_hours"] += value
    elif kind == "SHADOW_TOUR":
        if value != 1:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "SHADOW_TOUR value must be exactly 1"
            )
        docent["shadow_tours_completed"] += 1
    else:  # QUIZ
        if value < 0 or value > 100:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "QUIZ value must be between 0 and 100"
            )
        docent["quiz_score"] = value
    touch(docent)
    return ok(ser_docent(docent), 201)


@bp.get("/docents/<did>/shifts")
def list_docent_shifts(did):
    user_id, role = auth(DOCENT_READ_ROLES)
    if role == "Docent" and did != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Docents may read only their own shifts")
    docent = lookup("docents", did)
    items = sort_items(
        [s for s in DB["shifts"].values() if s["docent_id"] == docent["id"]]
    )
    return _paginate(items, ser_shift)
