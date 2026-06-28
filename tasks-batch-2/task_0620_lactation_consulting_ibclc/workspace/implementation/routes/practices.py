"""Practice and logical-clock endpoints."""
from flask import Blueprint

import db
from middleware import get_auth, require_roles
from response import object_response
from services.common import (
    init_full, touch, serialize, get_body,
    require_str, optional_bool, parse_iso,
)
from services.lookups import get_or_404

bp = Blueprint("practices", __name__)

DEFAULT_NOW_UTC = "2026-01-01T00:00:00Z"


@bp.post("/practices")
def create_practice():
    # PRD §3.1: PracticeAdmin only.
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin"})
    body = get_body()
    name = require_str(body, "name")
    # aca_preventive_enabled defaults to true (PRD §3.1).
    aca = optional_bool(body, "aca_preventive_enabled", True)
    record = {
        "name": name,
        "aca_preventive_enabled": aca,
        # Logical clock initialized to the fixed default (PRD §2.4).
        "now_utc": DEFAULT_NOW_UTC,
    }
    init_full(record)
    db.practices[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/practices/<rid>")
def get_practice(rid):
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin", "BillingSpecialist", "Consultant",
                         "FrontDesk", "Client"})
    record = get_or_404(db.practices, rid)
    return object_response(serialize(record), 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # PRD §2.4 / §4: test-driving capability, PracticeAdmin only.
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin"})
    body = get_body()
    practice_id = require_str(body, "practice_id")
    to_iso8601 = require_str(body, "to_iso8601")
    # Validate the new clock value is a well-formed ISO8601 timestamp.
    parse_iso(to_iso8601)
    practice = get_or_404(db.practices, practice_id)
    practice["now_utc"] = to_iso8601
    touch(practice)
    return object_response(serialize(practice), 200)
