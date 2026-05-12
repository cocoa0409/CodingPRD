"""User endpoints."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth
from response import success


bp = Blueprint("users", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _require_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise err("ERR_BAD_REQUEST", f"{key} is required and must be a string")
    return v


@bp.post("/users")
@require_auth(roles={"PlatformAdmin"})
def create_user():
    body = _get_body()
    external_user_id = _require_str(body, "external_user_id")
    full_name = _require_str(body, "full_name")
    department = _require_str(body, "department")
    affiliation = _require_str(body, "affiliation")
    if affiliation not in ("WITHIN_SCHOOL", "INTER_SCHOOL", "EXTERNAL"):
        raise err("ERR_BAD_REQUEST", "affiliation must be WITHIN_SCHOOL|INTER_SCHOOL|EXTERNAL")
    training = body.get("training_certificates", [])
    if not isinstance(training, list) or not all(isinstance(x, str) for x in training):
        raise err("ERR_BAD_REQUEST", "training_certificates must be an array of strings")

    # Idempotent on external_user_id
    existing_id = db.user_external_index.get(external_user_id)
    if existing_id is not None:
        return success(db.public(db.users[existing_id]), status=201)

    user = {
        "external_user_id": external_user_id,
        "full_name": full_name,
        "department": department,
        "affiliation": affiliation,
        "training_certificates": list(training),
        "identity_verified": False,
    }
    db.stamp_create(user)
    db.users[user["id"]] = user
    db.user_external_index[external_user_id] = user["id"]
    return success(db.public(user), status=201)


@bp.get("/users/<user_id>")
@require_auth(roles={"PlatformAdmin", "LabOwner", "User"})
def get_user(user_id):
    user = db.users.get(user_id)
    if user is None:
        raise err("ERR_NOT_FOUND", "user not found")
    if g.user_role == "User" and user["id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "User can only see own record")
    return success(db.public(user))
