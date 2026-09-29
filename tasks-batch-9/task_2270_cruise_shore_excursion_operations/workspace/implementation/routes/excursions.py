"""The excursion catalog and its lifecycle."""

from datetime import timedelta

from flask import Blueprint

from db import db
from errors import fail
from middleware import MANAGER, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import excursion_json
from services.cascades import departures_of_excursion, start_selling, withdraw_excursion
from services.timing import recompute_projections
from validation import (excursion_or_404, f, operator_or_404, paginate, pagination,
                        port_or_404, query_values, validate_body)

bp = Blueprint("excursions", __name__)

MOBILITY_LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4")
MEDICAL_CODES = ("CARDIAC", "RESPIRATORY", "PREGNANCY", "MOTION_SICKNESS", "ALTITUDE")
LANGUAGES = ("EN", "ES", "DE", "FR", "IT", "PT", "ZH")
PRICE_TIERS = ("VALUE", "STANDARD", "PREMIUM", "SIGNATURE")
CATALOG_STATUSES = ("DRAFT", "PENDING_REVIEW", "PUBLISHED", "WITHDRAWN", "ARCHIVED")
CATALOG_ACTIONS = ("SUBMIT_REVIEW", "RETURN_TO_DRAFT", "PUBLISH", "WITHDRAW", "ARCHIVE")

MIN_INSURANCE_RUNWAY_DAYS = 30

EXCURSION_CREATE = [
    f("port_id", "string", required=True),
    f("operator_id", "string", required=True),
    f("title", "string", required=True),
    f("duration_minutes", "int", required=True, lo=30, hi=720),
    f("min_age", "int", required=True, lo=0, hi=21),
    f("mobility_level", "enum", required=True, enum=MOBILITY_LEVELS),
    f("languages", "array", required=True, subset=LANGUAGES, nonempty=True),
    f("base_price_cents", "int", required=True, lo=100),
    f("price_tier", "enum", required=True, enum=PRICE_TIERS),
    f("is_line_operated", "bool", required=True),
    f("max_age", "int", lo=0, hi=120, nullable=True),
    f("medical_warning_codes", "array", subset=MEDICAL_CODES, nonempty=False),
    f("alternative_excursion_id", "string", nullable=True),
]

EXCURSION_PATCH = [
    f("title", "string"),
    f("duration_minutes", "int", lo=30, hi=720),
    f("min_age", "int", lo=0, hi=21),
    f("max_age", "int", lo=0, hi=120, nullable=True),
    f("mobility_level", "enum", enum=MOBILITY_LEVELS),
    f("medical_warning_codes", "array", subset=MEDICAL_CODES, nonempty=False),
    f("languages", "array", subset=LANGUAGES, nonempty=True),
    f("base_price_cents", "int", lo=100),
    f("price_tier", "enum", enum=PRICE_TIERS),
    f("alternative_excursion_id", "string", nullable=True),
]

CATALOG_ACTION = [
    f("action", "enum", required=True, enum=CATALOG_ACTIONS),
    f("note", "string"),
]


@bp.post(API_PREFIX + "/excursions")
@endpoint(MANAGER)
def create_excursion(caller):
    body = validate_body(EXCURSION_CREATE)
    port = port_or_404(body["port_id"])
    operator = operator_or_404(body["operator_id"])
    alternative_id = body.get("alternative_excursion_id")
    if alternative_id is not None:
        alternative_id = excursion_or_404(alternative_id)["id"]

    min_age = body["min_age"]
    max_age = body.get("max_age")
    if max_age is not None and max_age < min_age:
        fail("ERR_INVALID_TIME_WINDOW", "max_age must be greater than or equal to min_age")

    row = db.insert("excursions", {
        "port_id": port["id"],
        "operator_id": operator["id"],
        "alternative_excursion_id": alternative_id,
        "title": body["title"],
        "duration_minutes": body["duration_minutes"],
        "min_age": min_age,
        "max_age": max_age,
        "mobility_level": body["mobility_level"],
        "medical_warning_codes": body.get("medical_warning_codes", []),
        "languages": body["languages"],
        "base_price_cents": body["base_price_cents"],
        "price_tier": body["price_tier"],
        "is_line_operated": body["is_line_operated"],
        "return_guarantee": body["is_line_operated"],
        "catalog_status": "DRAFT",
        "published_at": None,
    })
    return object_response(excursion_json(row), 201)


@bp.get(API_PREFIX + "/excursions/<excursion_id>")
@endpoint()
def read_excursion(caller, excursion_id):
    return object_response(excursion_json(excursion_or_404(excursion_id)))


@bp.get(API_PREFIX + "/excursions")
@endpoint()
def list_excursions(caller):
    limit, offset = pagination()
    filters = query_values([
        f("port_id", "string"),
        f("operator_id", "string"),
        f("alternative_excursion_id", "string"),
        f("catalog_status", "enum", enum=CATALOG_STATUSES),
        f("price_tier", "enum", enum=PRICE_TIERS),
    ])
    rows = db.ordered("excursions")
    for key in ("port_id", "operator_id", "alternative_excursion_id", "catalog_status", "price_tier"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([excursion_json(r) for r in page], limit, offset, total)


@bp.patch(API_PREFIX + "/excursions/<excursion_id>")
@endpoint(MANAGER)
def patch_excursion(caller, excursion_id):
    body = validate_body(EXCURSION_PATCH)
    excursion = excursion_or_404(excursion_id)
    if "alternative_excursion_id" in body and body["alternative_excursion_id"] is not None:
        body["alternative_excursion_id"] = excursion_or_404(body["alternative_excursion_id"])["id"]

    min_age = body.get("min_age", excursion["min_age"])
    max_age = body["max_age"] if "max_age" in body else excursion["max_age"]
    if max_age is not None and max_age < min_age:
        fail("ERR_INVALID_TIME_WINDOW", "max_age must be greater than or equal to min_age")

    if excursion["catalog_status"] not in ("DRAFT", "PENDING_REVIEW"):
        fail("ERR_INVALID_CATALOG_ACTION",
             "a %s catalog item may not be amended" % excursion["catalog_status"])

    duration_changed = ("duration_minutes" in body
                        and body["duration_minutes"] != excursion["duration_minutes"])
    for key, value in body.items():
        excursion[key] = value
    db.touch(excursion)

    if duration_changed:
        for departure in departures_of_excursion(excursion["id"]):
            recompute_projections(departure)

    return object_response(excursion_json(excursion))


@bp.post(API_PREFIX + "/excursions/<excursion_id>/catalog-actions")
@endpoint(MANAGER)
def catalog_action(caller, excursion_id):
    body = validate_body(CATALOG_ACTION)
    excursion = excursion_or_404(excursion_id)
    action = body["action"]
    status = excursion["catalog_status"]

    allowed = {
        "SUBMIT_REVIEW": ("DRAFT",),
        "RETURN_TO_DRAFT": ("PENDING_REVIEW",),
        "PUBLISH": ("PENDING_REVIEW", "WITHDRAWN"),
        "WITHDRAW": ("PUBLISHED",),
        "ARCHIVE": ("DRAFT", "WITHDRAWN"),
    }[action]
    if status not in allowed:
        fail("ERR_INVALID_CATALOG_ACTION",
             "%s is not declared for a catalog item in %s" % (action, status))

    if action == "PUBLISH":
        operator = db.operators.get(excursion["operator_id"])
        runway = db.now() + timedelta(days=MIN_INSURANCE_RUNWAY_DAYS)
        if operator is None or operator["insurance_expiry_date"] < runway:
            fail("ERR_INSURANCE_EXPIRED",
                 "publication needs at least 30 days of remaining insurance cover")
        if operator["vetting_status"] != "APPROVED":
            fail("ERR_OPERATOR_NOT_APPROVED", "the delivering operator is not APPROVED")
        if status == "PENDING_REVIEW" and excursion["alternative_excursion_id"] is not None:
            alternative = db.excursions.get(excursion["alternative_excursion_id"])
            if (alternative is None or alternative["catalog_status"] != "PUBLISHED"
                    or alternative["port_id"] != excursion["port_id"]):
                fail("ERR_NO_ALTERNATIVE_AVAILABLE",
                     "the nominated alternative is not published at the same port")

        excursion["catalog_status"] = "PUBLISHED"
        excursion["published_at"] = db.now()
        db.touch(excursion)
        for departure in departures_of_excursion(excursion["id"]):
            call = db.port_calls.get(departure["port_call_id"])
            if departure["status"] == "SCHEDULED" and call and call["status"] == "OPEN_FOR_SALE":
                start_selling(departure)

    elif action == "SUBMIT_REVIEW":
        excursion["catalog_status"] = "PENDING_REVIEW"
        db.touch(excursion)
    elif action == "RETURN_TO_DRAFT":
        excursion["catalog_status"] = "DRAFT"
        db.touch(excursion)
    elif action == "WITHDRAW":
        withdraw_excursion(excursion)
    else:  # ARCHIVE
        if status == "WITHDRAWN":
            for departure in departures_of_excursion(excursion["id"]):
                if departure["status"] in ("SELLING", "CLOSED", "OPERATING"):
                    fail("ERR_INVALID_CATALOG_ACTION",
                         "a live departure still exists for this catalog item")
        excursion["catalog_status"] = "ARCHIVED"
        db.touch(excursion)

    return object_response(excursion_json(excursion))
