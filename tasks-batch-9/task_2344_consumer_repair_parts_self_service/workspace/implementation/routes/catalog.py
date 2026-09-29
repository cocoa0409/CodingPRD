"""The parts catalog: registration, publication, supersession, restriction, forecast."""
from flask import Blueprint, request

import db
from db import base_row, setf, touch
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_OFFICER, DOCUMENTATION_ENGINEER, \
    FAILURE_ANALYSIS_ENGINEER, PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, \
    SELF_REPAIR_CUSTOMER, endpoint
from response import collection, created, ok
from routes.helpers import filter_as_of_date, filter_bool, filter_eq, get_model, get_part
from serializers import compat_json, line_json, part_json
from services.compliance import compat_rows, in_window, reevaluate_model_obligations, \
    rollup_documentation_posture
from services.forecast import VARIANTS as FORECAST_VARIANTS, forecast
from validation import F, int_range, query_enum, query_int, read_body, str_len

bp = Blueprint("catalog", __name__)

PART_CLASSES = ("COMPONENT", "TOOL", "RENTAL_KIT", "CONSUMABLE")
SAFETY_CLASSES = (
    "UNRESTRICTED", "SAFETY_RESTRICTED_BATTERY", "SAFETY_RESTRICTED_HIGH_VOLTAGE",
    "PAIRED_SECURITY",
)
RESTRICTED_SAFETY_CLASSES = tuple(c for c in SAFETY_CLASSES if c != "UNRESTRICTED")

CREATE_FIELDS = [
    F("sku", "string", required=True),
    F("part_class", "enum", required=True, enum=PART_CLASSES),
    F("safety_class", "enum", required=True, enum=SAFETY_CLASSES),
    F("list_price_cents", "int", required=True),
    F("core_return_required", "bool", default=False),
    F("core_credit_cents", "int", default=0),
    F("rental_deposit_cents", "int", default=0),
    F("concurrent_rental_capacity", "int"),
    F("requires_authentication", "bool", default=False),
    F("requires_calibration", "bool", default=False),
    F("supersedes_part_id", "string"),
]


def _chain_would_cycle(part_id, predecessor_id):
    """True when predecessor transitively supersedes part_id (or is part_id)."""
    seen = set()
    cursor = predecessor_id
    while cursor is not None and cursor not in seen:
        if cursor == part_id:
            return True
        seen.add(cursor)
        row = db.db.parts.get(cursor)
        cursor = row.get("supersedes_part_id") if row is not None else None
    return False


def _check_supersession(part_id, part_class, predecessor):
    if _chain_would_cycle(part_id, predecessor["id"]):
        raise ApiError("ERR_SUPERSESSION_CYCLE")
    if predecessor["part_class"] != part_class:
        raise ApiError("ERR_SUPERSESSION_CLASS_MISMATCH")


def _supersede_predecessor(predecessor):
    if predecessor is not None and predecessor["status"] == "PUBLISHED":
        setf(predecessor, "status", "SUPERSEDED")


@bp.post("/part-catalog-items")
@endpoint([PROGRAM_ADMIN])
def create_part():
    body = read_body(CREATE_FIELDS)
    str_len(body["sku"], "sku", 3, 32)
    int_range(body["list_price_cents"], "list_price_cents", 0, None)
    int_range(body["core_credit_cents"], "core_credit_cents", 0, None)
    int_range(body["rental_deposit_cents"], "rental_deposit_cents", 0, None)
    int_range(body["concurrent_rental_capacity"], "concurrent_rental_capacity", 0, None)

    for existing in db.db.parts.all():
        if existing["sku"] == body["sku"]:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "sku already registered.")

    predecessor = None
    if body["supersedes_part_id"] is not None:
        predecessor = get_part(body["supersedes_part_id"])

    row = base_row()
    row.update({
        "sku": body["sku"],
        "part_class": body["part_class"],
        "safety_class": body["safety_class"],
        "list_price_cents": body["list_price_cents"],
        "core_return_required": body["core_return_required"],
        "core_credit_cents": body["core_credit_cents"],
        "rental_deposit_cents": body["rental_deposit_cents"],
        "concurrent_rental_capacity": body["concurrent_rental_capacity"],
        "requires_authentication": body["requires_authentication"],
        "requires_calibration": body["requires_calibration"],
        "supersedes_part_id": body["supersedes_part_id"],
        "status": "DRAFT",
        "restriction_reason": None,
        "core_face_value_committed_cents": 0,
        "core_liability_outstanding_cents": 0,
        "core_credit_settled_cents": 0,
        "core_credit_forfeited_cents": 0,
    })

    if predecessor is not None:
        _check_supersession(row["id"], row["part_class"], predecessor)

    db.db.parts.add(row)
    return created(part_json(row))


@bp.get("/part-catalog-items/<part_id>")
@endpoint(ALL_ROLES)
def read_part(part_id):
    return ok(part_json(get_part(part_id)))


@bp.get("/part-catalog-items")
@endpoint(ALL_ROLES)
def list_parts():
    rows = db.db.parts.all()
    for field in ("part_class", "safety_class", "status", "supersedes_part_id"):
        rows = filter_eq(rows, field)
    return collection(rows, part_json)


@bp.get("/part-catalog-items/<part_id>/successors")
@endpoint(ALL_ROLES)
def list_successors(part_id):
    get_part(part_id)
    rows = [p for p in db.db.parts.all() if p.get("supersedes_part_id") == part_id]
    return collection(rows, part_json)


@bp.get("/part-catalog-items/<part_id>/part-compatibilities")
@endpoint([PROGRAM_ADMIN, SAFETY_REVIEWER, DOCUMENTATION_ENGINEER, SELF_REPAIR_CUSTOMER,
           REPAIR_PROVIDER_TECH])
def list_part_compats(part_id):
    get_part(part_id)
    rows = compat_rows(part_id=part_id)
    rows = filter_eq(rows, "model_id")
    rows = filter_eq(rows, "required_tool_part_id")
    rows = filter_bool(rows, "self_service_eligible")
    rows = filter_as_of_date(rows)
    return collection(rows, compat_json)


@bp.get("/part-catalog-items/<part_id>/order-lines")
@endpoint([PROGRAM_ADMIN, SAFETY_REVIEWER, FAILURE_ANALYSIS_ENGINEER])
def list_part_lines(part_id):
    get_part(part_id)
    rows = [l for l in db.db.lines.all() if l["part_id"] == part_id]
    for field in ("order_id", "calibration_status", "authentication_status"):
        rows = filter_eq(rows, field)
    return collection(rows, line_json)


@bp.post("/part-catalog-items/<part_id>/publish")
@endpoint([PROGRAM_ADMIN])
def publish_part(part_id):
    read_body([])
    part = get_part(part_id)

    if part["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if part["part_class"] == "RENTAL_KIT":
        capacity = part.get("concurrent_rental_capacity")
        if capacity is None or capacity < 1:
            raise ApiError("ERR_INVALID_RANGE",
                           "A rental kit requires concurrent_rental_capacity of at least 1.")
    if part.get("core_return_required") and part.get("core_credit_cents", 0) < 1:
        raise ApiError("ERR_INVALID_RANGE",
                       "A core-return part requires core_credit_cents of at least 1.")

    setf(part, "status", "PUBLISHED")

    predecessor = None
    if part.get("supersedes_part_id") is not None:
        predecessor = db.db.parts.get(part["supersedes_part_id"])
    _supersede_predecessor(predecessor)

    at = db.now()
    for compat in compat_rows(part_id=part["id"]):
        if not in_window(compat, at):
            continue
        model = db.db.models.get(compat["model_id"])
        if model is None:
            continue
        rollup_documentation_posture(model)
        reevaluate_model_obligations(model)
        touch(model)

    return ok(part_json(part))


@bp.post("/part-catalog-items/<part_id>/supersession")
@endpoint([PROGRAM_ADMIN])
def repoint_supersession(part_id):
    body = read_body([
        F("supersedes_part_id", "string", required=True),
        F("supersession_note", "string"),
    ])
    part = get_part(part_id)
    predecessor = get_part(body["supersedes_part_id"])
    _check_supersession(part["id"], part["part_class"], predecessor)

    setf(part, "supersedes_part_id", predecessor["id"])
    _supersede_predecessor(predecessor)
    touch(part)
    return ok(part_json(part))


@bp.post("/part-catalog-items/<part_id>/restrict")
@endpoint([SAFETY_REVIEWER])
def restrict_part(part_id):
    body = read_body([
        F("safety_class", "enum", required=True, enum=SAFETY_CLASSES),
        F("restriction_reason", "string"),
    ])
    if body["safety_class"] == "UNRESTRICTED":
        raise ApiError("ERR_INVALID_REQUEST",
                       "safety_class must be a restricted class.")
    part = get_part(part_id)
    if part["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # hop 1
    setf(part, "status", "RESTRICTED")
    setf(part, "safety_class", body["safety_class"])
    setf(part, "restriction_reason", body["restriction_reason"])

    # hop 2
    changed_pairs = set()
    for compat in compat_rows(part_id=part["id"]):
        if compat.get("self_service_eligible") is not True:
            continue
        setf(compat, "self_service_eligible", False)
        setf(compat, "superseded_by_safety_restriction", True)
        changed_pairs.add((compat["part_id"], compat["model_id"]))

    # hop 3
    revoked = []
    for assessment in db.ordered(db.db.assessments.all()):
        if assessment["status"] != "VALID":
            continue
        if assessment.get("decision") not in ("ELIGIBLE", "ELIGIBLE_WITH_TOOL_RENTAL"):
            continue
        if (assessment["part_id"], assessment["model_id"]) not in changed_pairs:
            continue
        setf(assessment, "status", "REVOKED_BY_SAFETY")
        revoked.append(assessment["id"])

    # hop 4
    for order in db.ordered(db.db.orders.all()):
        if order.get("assessment_id") not in revoked:
            continue
        if order["fulfillment_status"] != "PENDING_DISCLOSURE":
            continue
        if order.get("disclosure_acknowledged_at") is not None:
            continue
        setf(order, "fulfillment_status", "BLOCKED_SAFETY_HOLD")
        setf(order, "blocked_reason", "SAFETY_RESTRICTION_ON_PART")

    return ok(part_json(part))


@bp.get("/part-catalog-items/<part_id>/demand-forecast")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER])
def demand_forecast(part_id):
    model_id = request.args.get("model_id")
    if model_id is None or model_id == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'model_id' is required.")
    horizon = query_int("horizon_months", required=True)
    int_range(horizon, "horizon_months", 1, 60)
    variant = query_enum("variant", FORECAST_VARIANTS, default="TRAILING_ONLY")

    part = get_part(part_id)
    model = get_model(model_id)
    result = forecast(part, model, horizon, variant)
    result["part_id"] = part["id"]
    result["model_id"] = model["id"]
    result["horizon_months"] = horizon
    return ok(result)
