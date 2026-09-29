"""Sailing guests and their eligibility declarations."""

from flask import Blueprint

from db import db
from middleware import DESK, MANAGER, RISK, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import guest_json
from validation import f, guest_or_404, paginate, pagination, query_values, validate_body

bp = Blueprint("guests", __name__)

GUEST_MOBILITY_LEVELS = ("WHEELCHAIR", "ASSISTED", "FULL")
MEDICAL_CODES = ("CARDIAC", "RESPIRATORY", "PREGNANCY", "MOTION_SICKNESS", "ALTITUDE")
LANGUAGES = ("EN", "ES", "DE", "FR", "IT", "PT", "ZH")
LOYALTY_TIERS = ("NONE", "SILVER", "GOLD", "PLATINUM")

READ_ROLES = (DESK, MANAGER, RISK)

GUEST_CREATE = [
    f("full_name", "string", required=True),
    f("birth_date", "instant", required=True),
    f("voyage_code", "string", required=True),
    f("mobility_level", "enum", required=True, enum=GUEST_MOBILITY_LEVELS),
    f("language_pref", "enum", required=True, enum=LANGUAGES),
    f("medical_flags", "array", subset=MEDICAL_CODES, nonempty=False),
    f("loyalty_tier", "enum", enum=LOYALTY_TIERS),
]


@bp.post(API_PREFIX + "/guests")
@endpoint(DESK)
def create_guest(caller):
    body = validate_body(GUEST_CREATE)
    row = db.insert("guests", {
        "full_name": body["full_name"],
        "birth_date": body["birth_date"],
        "voyage_code": body["voyage_code"],
        "mobility_level": body["mobility_level"],
        "language_pref": body["language_pref"],
        "medical_flags": body.get("medical_flags", []),
        "loyalty_tier": body.get("loyalty_tier", "NONE"),
    })
    return object_response(guest_json(row), 201)


@bp.get(API_PREFIX + "/guests/<guest_id>")
@endpoint(*READ_ROLES)
def read_guest(caller, guest_id):
    return object_response(guest_json(guest_or_404(guest_id)))


@bp.get(API_PREFIX + "/guests")
@endpoint(*READ_ROLES)
def list_guests(caller):
    limit, offset = pagination()
    filters = query_values([
        f("voyage_code", "string"),
        f("loyalty_tier", "enum", enum=LOYALTY_TIERS),
    ])
    rows = db.ordered("guests")
    for key in ("voyage_code", "loyalty_tier"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([guest_json(r) for r in page], limit, offset, total)
