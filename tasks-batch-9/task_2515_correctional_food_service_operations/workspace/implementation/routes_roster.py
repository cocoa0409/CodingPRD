"""Inmate roster, movement and the diet-order lifecycle (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint

from core import (
    ApiError, Field, ROLE_CHAPLAIN_DESIGNEE, ROLE_COMPLIANCE_AUDITOR,
    ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
    ROLE_GRIEVANCE_COORDINATOR, ROLE_MEDICAL_PROVIDER,
    ROLE_REGISTERED_DIETITIAN, all_rows, authorize, base_row, body_json,
    filter_eq, insert, listing, now_logical, parse_instant, present, public,
    respond_object, touch, validate_fields,
)
from calc import (
    ALL_DIET_CODES, MAX_REVERIFICATIONS, MEDICAL_DIET_CODES,
    RELIGIOUS_DIET_CODES, inmate_diet_orders, rows_where,
    verification_window_days, window_conflict,
)
from ops import (
    census_after_diet_change, need_diet_order, need_facility, need_inmate,
    not_terminal, require_state,
)

bp = Blueprint("roster", __name__, url_prefix="/cfs")

HOUSING_UNITS = ("GENERAL", "SEGREGATION", "SATELLITE", "MEDICAL")
MOVEMENT_TYPES = ("RELEASE", "TRANSFER", "HOUSING_CHANGE")
LIVE_ORDER_STATUSES = ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED")
ORDER_TERMINAL = ("EXPIRED", "REVOKED")

INMATE_READ_ROLES = (
    ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
    ROLE_REGISTERED_DIETITIAN, ROLE_MEDICAL_PROVIDER, ROLE_CHAPLAIN_DESIGNEE,
    ROLE_GRIEVANCE_COORDINATOR, ROLE_COMPLIANCE_AUDITOR,
)
ORDER_READ_ROLES = (
    ROLE_REGISTERED_DIETITIAN, ROLE_MEDICAL_PROVIDER, ROLE_CHAPLAIN_DESIGNEE,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CORRECTIONAL_OFFICER,
    ROLE_GRIEVANCE_COORDINATOR, ROLE_COMPLIANCE_AUDITOR,
)


# --------------------------------------------------------------------------
# Inmates
# --------------------------------------------------------------------------
@bp.route("/inmates", methods=["POST"])
def create_inmate():
    authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("booking_number", "string", required=True),
        Field("housing_unit", "string", required=True, enum=HOUSING_UNITS),
        Field("religious_affiliation", "string"),
    ])
    facility = need_facility(body["facility_id"])
    for existing in rows_where("inmates", facility_id=facility["id"]):
        if existing["booking_number"] == body["booking_number"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "booking_number is already in use at this facility.")
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "booking_number": body["booking_number"],
        "housing_unit": body["housing_unit"],
        "religious_affiliation": body["religious_affiliation"] if present(body, "religious_affiliation") else "",
        "status": "IN_CUSTODY",
        "active_diet_order_count": 0,
    })
    insert("inmates", row)
    return respond_object(public(row), 201)


@bp.route("/inmates/<row_id>", methods=["GET"])
def read_inmate(row_id):
    authorize(*INMATE_READ_ROLES)
    return respond_object(public(need_inmate(row_id)), 200)


@bp.route("/inmates", methods=["GET"])
def list_inmates():
    authorize(ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
              ROLE_REGISTERED_DIETITIAN, ROLE_COMPLIANCE_AUDITOR)
    rows = filter_eq(all_rows("inmates"), "facility_id")
    rows = filter_eq(rows, "housing_unit")
    rows = filter_eq(rows, "status")
    return listing(rows)


@bp.route("/inmates/<row_id>/movement", methods=["POST"])
def inmate_movement(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [
        Field("movement_type", "string", required=True, enum=MOVEMENT_TYPES),
        Field("housing_unit", "string", enum=HOUSING_UNITS),
    ])
    inmate = need_inmate(row_id)
    movement = body["movement_type"]
    facility = need_facility(inmate["facility_id"])

    if movement == "RELEASE":
        inmate["status"] = "RELEASED"
    elif movement == "TRANSFER":
        inmate["status"] = "TRANSFERRED"
    elif present(body, "housing_unit"):
        inmate["housing_unit"] = body["housing_unit"]
    # The inmate's version moves on all three movement types.
    touch(inmate)

    if movement in ("RELEASE", "TRANSFER"):
        for order in inmate_diet_orders(inmate["id"]):
            if order["status"] in LIVE_ORDER_STATUSES:
                order["status"] = "REVOKED"
                touch(order)

    if movement == "HOUSING_CHANGE" and inmate.get("housing_unit") == "SEGREGATION":
        for worker in rows_where("inmate_workers", inmate_id=inmate["id"]):
            moved = False
            if worker["clearance_status"] == "CLEARED":
                worker["clearance_status"] = "SUSPENDED"
                moved = True
            if worker["assignment_status"] != "UNASSIGNED" or worker.get("work_area") is not None:
                worker["assignment_status"] = "UNASSIGNED"
                worker["work_area"] = None
                moved = True
            if moved:
                touch(worker)

    # Any movement at all invalidates the roster-driven drafts of that facility.
    for forecast in rows_where("meal_forecasts", facility_id=inmate["facility_id"]):
        if forecast["status"] == "DRAFT" and forecast["forecast_variant"] == "ROSTER_DRIVEN":
            forecast["status"] = "SUPERSEDED"
            touch(forecast)

    census_after_diet_change([inmate], [facility], skip=(inmate["id"],))
    return respond_object(public(inmate), 200)


# --------------------------------------------------------------------------
# Diet orders
# --------------------------------------------------------------------------
ORDER_FIELDS = [
    Field("inmate_id", "string", required=True),
    Field("order_type", "string", required=True, enum=("RELIGIOUS", "MEDICAL")),
    Field("diet_code", "string", required=True, enum=ALL_DIET_CODES),
    Field("effective_from", "datetime", required=True),
    Field("effective_to", "datetime", required=True),
    Field("expected_inmate_version", "integer", required=True),
    Field("clinical_indication", "string"),
    Field("supersedes_diet_order_id", "string"),
]


@bp.route("/diet-orders", methods=["POST"])
def create_diet_order():
    actor = authorize(ROLE_REGISTERED_DIETITIAN)
    body = body_json()
    validate_fields(body, ORDER_FIELDS)
    order_type = body["order_type"]
    indication = body.get("clinical_indication") or ""
    if order_type == "RELIGIOUS" and indication.strip():
        raise ApiError("ERR_INVALID_REQUEST",
                       "clinical_indication must be omitted on a RELIGIOUS order.")
    family = RELIGIOUS_DIET_CODES if order_type == "RELIGIOUS" else MEDICAL_DIET_CODES
    if body["diet_code"] not in family:
        raise ApiError("ERR_INVALID_ENUM_VALUE",
                       "diet_code must be one of %s for a %s order."
                       % (", ".join(family), order_type))
    inmate = need_inmate(body["inmate_id"])
    incumbent = None
    if present(body, "supersedes_diet_order_id"):
        incumbent = need_diet_order(body["supersedes_diet_order_id"])
        if incumbent["inmate_id"] != inmate["id"] or incumbent["order_type"] != order_type:
            raise ApiError("ERR_FACILITY_MISMATCH",
                           "The superseded order belongs to another inmate or diet family.")
    if int(body["expected_inmate_version"]) != int(inmate["version"]):
        raise ApiError("ERR_STALE_INMATE_VERSION")
    if inmate["status"] != "IN_CUSTODY":
        raise ApiError("ERR_INMATE_NOT_IN_CUSTODY")
    effective_from = parse_instant(body["effective_from"])
    effective_to = parse_instant(body["effective_to"])
    if effective_from >= effective_to or effective_to <= now_logical():
        raise ApiError("ERR_INVALID_WINDOW")
    exclude = incumbent["id"] if incumbent is not None else None
    if window_conflict(inmate["id"], order_type, effective_from, effective_to, exclude) is not None:
        raise ApiError("ERR_DIET_ORDER_WINDOW_CONFLICT")

    row = base_row()
    row.update({
        "inmate_id": inmate["id"],
        "order_type": order_type,
        "diet_code": body["diet_code"],
        "status": "PENDING_VERIFICATION",
        "clinical_indication": body["clinical_indication"] if present(body, "clinical_indication") else None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_diet_order_id": incumbent["id"] if incumbent is not None else None,
        "requested_by_user_id": actor.user_id,
        "verified_by_user_id": None,
        "verified_at": None,
        "verification_expires_at": None,
        "reverification_count": 0,
        "suspension_reason": None,
    })
    insert("diet_orders", row)
    # The inmate's diet picture changed even though no counter moved.
    touch(inmate)
    return respond_object(public(row), 201)


@bp.route("/diet-orders/<row_id>", methods=["GET"])
def read_diet_order(row_id):
    authorize(*ORDER_READ_ROLES)
    return respond_object(public(need_diet_order(row_id)), 200)


@bp.route("/diet-orders", methods=["GET"])
def list_diet_orders():
    authorize(ROLE_REGISTERED_DIETITIAN, ROLE_MEDICAL_PROVIDER,
              ROLE_CHAPLAIN_DESIGNEE, ROLE_FOOD_SERVICE_SUPERVISOR,
              ROLE_COMPLIANCE_AUDITOR)
    rows = filter_eq(all_rows("diet_orders"), "inmate_id")
    rows = filter_eq(rows, "supersedes_diet_order_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "order_type")
    return listing(rows)


def _order_context(order):
    inmate = need_inmate(order["inmate_id"])
    facility = need_facility(inmate["facility_id"])
    return inmate, facility


@bp.route("/diet-orders/<row_id>/verify", methods=["POST"])
def verify_diet_order(row_id):
    actor = authorize(ROLE_CHAPLAIN_DESIGNEE, ROLE_MEDICAL_PROVIDER)
    body = body_json()
    validate_fields(body, [Field("verification_note", "string")])
    order = need_diet_order(row_id)
    not_terminal(order, "status", ORDER_TERMINAL)
    require_state(order, "status", ("PENDING_VERIFICATION",))
    order_type = order["order_type"]
    if order_type == "MEDICAL" and not (order.get("clinical_indication") or "").strip():
        raise ApiError("ERR_CLINICAL_INDICATION_REQUIRED")
    expected_role = ROLE_CHAPLAIN_DESIGNEE if order_type == "RELIGIOUS" else ROLE_MEDICAL_PROVIDER
    if actor.role != expected_role:
        raise ApiError("ERR_VERIFIER_ROLE_MISMATCH")
    if actor.user_id == order.get("requested_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    inmate, facility = _order_context(order)
    if inmate["status"] != "IN_CUSTODY":
        raise ApiError("ERR_INMATE_NOT_IN_CUSTODY")
    verified_at = now_logical()
    if verified_at >= order["effective_to"]:
        raise ApiError("ERR_INVALID_WINDOW")

    order["status"] = "ACTIVE"
    order["verified_by_user_id"] = actor.user_id
    order["verified_at"] = verified_at
    order["verification_expires_at"] = verified_at + timedelta(
        days=verification_window_days(order_type))
    touch(order)

    incumbent_id = order.get("supersedes_diet_order_id")
    if incumbent_id:
        incumbent = need_diet_order(incumbent_id)
        if incumbent["status"] == "ACTIVE":
            incumbent["status"] = "REVOKED"
            touch(incumbent)
    # Both census counters are recounted from source; a supersede cancels out.
    census_after_diet_change([inmate], [facility])
    return respond_object(public(order), 200)


@bp.route("/diet-orders/<row_id>/suspend", methods=["POST"])
def suspend_diet_order(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [Field("suspension_reason", "string", required=True)])
    order = need_diet_order(row_id)
    not_terminal(order, "status", ORDER_TERMINAL)
    require_state(order, "status", ("ACTIVE",))
    inmate, facility = _order_context(order)
    order["status"] = "SUSPENDED"
    order["suspension_reason"] = body["suspension_reason"]
    touch(order)
    census_after_diet_change([inmate], [facility])
    return respond_object(public(order), 200)


@bp.route("/diet-orders/<row_id>/request-reverification", methods=["POST"])
def request_reverification(row_id):
    actor = authorize(ROLE_REGISTERED_DIETITIAN)
    order = need_diet_order(row_id)
    not_terminal(order, "status", ORDER_TERMINAL)
    require_state(order, "status", ("SUSPENDED",))
    if int(order["reverification_count"]) >= MAX_REVERIFICATIONS:
        raise ApiError("ERR_REVERIFICATION_LIMIT_REACHED")
    order["status"] = "PENDING_VERIFICATION"
    order["reverification_count"] = int(order["reverification_count"]) + 1
    order["verified_by_user_id"] = None
    order["verified_at"] = None
    order["verification_expires_at"] = None
    order["suspension_reason"] = None
    order["requested_by_user_id"] = actor.user_id
    touch(order)
    return respond_object(public(order), 200)


@bp.route("/diet-orders/<row_id>/revoke", methods=["POST"])
def revoke_diet_order(row_id):
    authorize(ROLE_REGISTERED_DIETITIAN)
    body = body_json()
    validate_fields(body, [Field("revocation_reason", "string", required=True)])
    order = need_diet_order(row_id)
    not_terminal(order, "status", ORDER_TERMINAL)
    require_state(order, "status", LIVE_ORDER_STATUSES)
    inmate, facility = _order_context(order)
    order["status"] = "REVOKED"
    order["suspension_reason"] = body["revocation_reason"]
    touch(order)
    census_after_diet_change([inmate], [facility])
    return respond_object(public(order), 200)
