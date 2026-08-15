"""Physician endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION_FAILED
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import maybe_expire_conference
from services.common import init_common
from services.validation import get_json_body, reject_unknown_fields, validate_string, validate_bool

bp = Blueprint("physicians", __name__)

PHYSICIAN_FIELDS = ["full_name", "specialty", "is_advisor"]


@bp.post("/api/physicians")
def create_physician():
    require_roles(["URDirector"])
    body = get_json_body()
    reject_unknown_fields(body, PHYSICIAN_FIELDS)
    validate_string(body, "full_name")
    validate_string(body, "specialty")
    validate_bool(body, "is_advisor", required=False)

    physician = {
        **init_common(),
        "full_name": body["full_name"],
        "specialty": body["specialty"],
        "is_advisor": body.get("is_advisor", False),
    }
    db.physicians[physician["id"]] = physician
    return success_object(physician, 201)


@bp.get("/api/physicians")
def list_physicians():
    any_authenticated()
    items = sorted(db.physicians.values(), key=lambda p: p["created_at"])
    if "is_advisor" in request.args:
        raw = request.args["is_advisor"].lower()
        if raw not in ("true", "false"):
            raise ApiError(ERR_VALIDATION_FAILED, "is_advisor must be true or false", 400)
        flag = raw == "true"
        items = [p for p in items if p["is_advisor"] == flag]
    return paginate(items)


@bp.get("/api/physicians/<pid>")
def get_physician(pid):
    any_authenticated()
    return success_object(lookup(db.physicians, pid, "Physician"))


@bp.get("/api/physicians/<pid>/peer-to-peer-conferences")
def list_physician_conferences(pid):
    any_authenticated()
    lookup(db.physicians, pid, "Physician")
    items = [
        c for c in db.peer_to_peer_conferences.values()
        if c["advisor_physician_id"] == pid or c["attending_physician_id"] == pid
    ]
    for c in items:
        maybe_expire_conference(c)
    items.sort(key=lambda c: (c["scheduled_start_at"], c["created_at"]))
    return paginate(items)


@bp.get("/api/physicians/<pid>/condition-code-44-requests")
def list_physician_cc44(pid):
    any_authenticated()
    lookup(db.physicians, pid, "Physician")
    items = [
        r for r in db.condition_code_44_requests.values()
        if r.get("committee_reviewer_id") == pid
    ]
    items.sort(key=lambda r: r["created_at"])
    return paginate(items)
