"""Photographer registration and fetch (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_auth, ROLE_ANONYMOUS, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN
from response import ok_object
from routes._helpers import get_body, require_str, require_int, serialize
from services.common import stamp_create

bp = Blueprint("photographers", __name__)

SKILL_VALUES = {"PHOTO", "VIDEO", "DRONE", "EDITING"}


@bp.post("/studio/photographers")
def create_photographer():
    require_auth([ROLE_ANONYMOUS, ROLE_STUDIO_ADMIN])
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")

    skills = body.get("skills")
    if not isinstance(skills, list) or len(skills) == 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "skills must be a non-empty list")
    for s in skills:
        if s not in SKILL_VALUES:
            raise APIError(ERR_INVALID_REQUEST, 422, f"invalid skill: {s}")

    hourly_rate_cents = require_int(body, "hourly_rate_cents", min_value=0)

    for p in db.photographers.values():
        if p["email"] == email:
            raise APIError(ERR_DUPLICATE_RESOURCE, 409, "Photographer email already exists")

    photographer = {
        "email": email,
        "full_name": full_name,
        "skills": list(skills),
        "hourly_rate_cents": hourly_rate_cents,
        "status": "ACTIVE",
    }
    stamp_create(photographer)
    db.photographers[photographer["id"]] = photographer
    return ok_object(serialize(photographer), 201)


@bp.get("/studio/photographers/<id>")
def get_photographer(id):
    require_auth([ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    p = db.photographers.get(id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Photographer not found")
    return ok_object(serialize(p), 200)
