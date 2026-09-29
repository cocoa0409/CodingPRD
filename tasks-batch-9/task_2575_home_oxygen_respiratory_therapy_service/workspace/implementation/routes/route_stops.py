"""Route stop endpoints.

This module carries the heaviest cascades in the system: the four-hop
setup-failure chain (stop -> contract -> placements -> equipment units), the
pickup completion chain, the compensating cancellation and the route
bubble-up that derives the parent route's state from its children.
"""
from datetime import timedelta

from flask import Blueprint

from core import (
    LOGISTICS_READERS,
    ROLE_DRIVER,
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ApiError,
    actor,
    authenticate,
    base_row,
    current_month,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    parse_datetime,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import (
    apply_risk_variant,
    bubble_up_route,
    get_branch,
    get_contract,
    get_route,
    get_route_stop,
    placements_for_contract,
    recompute_allowable,
    recompute_route_rollups,
    route_stops,
    stop_liters,
    stop_sort_key,
)
from serial import route_stop_out
from validate import Field, validate

bp = Blueprint("route_stops", __name__)

STOP_TYPES = (
    "SETUP_DELIVERY",
    "TANK_EXCHANGE",
    "PORTABLE_REFILL",
    "PICKUP",
    "MAINTENANCE_SWAP",
)
STOP_STATUSES = ("PLANNED", "COMPLETED", "MISSED", "CANCELLED")
IN_SERVICE_TYPES = ("TANK_EXCHANGE", "PORTABLE_REFILL", "PICKUP", "MAINTENANCE_SWAP")
NO_CYLINDER_TYPES = ("PICKUP", "PORTABLE_REFILL")
EDITABLE_ROUTE_STATES = ("PLANNING", "LOCKED")
TEACHBACK_FINDING_THRESHOLD = 3

CREATE_FIELDS = [
    Field("route_id", "string", required=True, min_len=1),
    Field("contract_id", "string", required=True, min_len=1),
    Field("stop_type", "enum", required=True, enum=STOP_TYPES),
    Field("window_start_utc", "datetime", required=True),
    Field("window_end_utc", "datetime", required=True),
    Field("service_minutes", "integer", required=True, minimum=5, maximum=240),
    Field("cylinders_requested", "integer", default=0, minimum=0, maximum=6),
]

SETUP_FIELDS = [
    Field("smoking_in_home", "boolean", required=True),
    Field("electrical_pass", "boolean", required=True),
    Field("patient_teachback_score", "integer", required=True, minimum=0, maximum=5),
    Field(
        "education_topics_covered",
        "array",
        item_kind="string",
        nullable=True,
        default=None,
    ),
]


def _resequence(route, skip_touch=()):
    """Renumber non-cancelled stops; a freshly created row is not bumped."""
    stops = [s for s in route_stops(route["id"]) if s["status"] != "CANCELLED"]
    stops.sort(key=stop_sort_key)
    for index, stop in enumerate(stops, start=1):
        if stop["sequence_index"] != index:
            stop["sequence_index"] = index
            if stop["id"] not in tuple(skip_touch):
                touch(stop)


def _has_liquid_portable(contract):
    for placement in placements_for_contract(contract["id"], ("PLACED",)):
        unit = db.equipment_units.get(placement["equipment_unit_id"])
        if unit is not None and unit["equipment_class"] == "LIQUID_PORTABLE":
            return True
    return False


def _stop_route(stop):
    return get_route(stop["route_id"])


def _buffer(route):
    branch = get_branch(route["branch_id"])
    return timedelta(minutes=branch["tank_exchange_buffer_minutes"])


@bp.post("/route-stops")
def create_stop():
    """Schedule a stop onto an editable route."""
    authenticate((ROLE_MANAGER,))
    data = validate(CREATE_FIELDS)
    contract = get_contract(data["contract_id"])
    route = get_route(data["route_id"])
    stop_type = data["stop_type"]
    if stop_type in IN_SERVICE_TYPES and contract["service_status"] != "IN_SERVICE":
        raise ApiError("ERR_CONTRACT_NOT_IN_SERVICE")
    if route["status"] not in EDITABLE_ROUTE_STATES:
        raise ApiError("ERR_ROUTE_NOT_EDITABLE")
    if stop_type == "PORTABLE_REFILL" and not _has_liquid_portable(contract):
        raise ApiError("ERR_REFILL_REQUIRES_LIQUID_PORTABLE")
    if stop_type == "SETUP_DELIVERY" and not placements_for_contract(
        contract["id"], ("RESERVED",)
    ):
        raise ApiError("ERR_NO_RESERVED_EQUIPMENT")
    patient = db.patients.get(contract["patient_id"])
    if patient is None or route["branch_id"] != patient["branch_id"]:
        raise ApiError("ERR_STOP_BRANCH_MISMATCH")
    start = parse_datetime(data["window_start_utc"])
    end = parse_datetime(data["window_end_utc"])
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    buffer = _buffer(route)
    buffered_end = end + buffer
    if start < route["shift_start_utc"] or buffered_end > route["shift_end_utc"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_SHIFT")
    for other in route_stops(route["id"]):
        if other["status"] != "PLANNED":
            continue
        other_end = other["window_end_utc"] + buffer
        if start < other_end and other["window_start_utc"] < buffered_end:
            raise ApiError("ERR_ROUTE_STOP_WINDOW_CONFLICT")
    if stop_type in NO_CYLINDER_TYPES and data["cylinders_requested"]:
        raise ApiError("ERR_CYLINDERS_NOT_APPLICABLE")
    if stop_type == "PICKUP" and route["status"] != "PLANNING":
        # The IN_SERVICE -> PICKUP_SCHEDULED transition requires a PLANNING route.
        raise ApiError("ERR_INVALID_STATE")
    row = base_row()
    row.update(
        {
            "route_id": route["id"],
            "contract_id": contract["id"],
            "stop_type": stop_type,
            "window_start_utc": start,
            "window_end_utc": end,
            "service_minutes": data["service_minutes"],
            "cylinders_requested": data["cylinders_requested"],
            "sequence_index": 0,
            "liters_committed": 0,
            "status": "PLANNED",
            "safety_result": "NOT_ASSESSED",
            "smoking_in_home": None,
            "electrical_pass": None,
            "patient_teachback_score": None,
            "education_topics_covered": [],
            "safety_findings_count": 0,
            "completed_at": None,
            "completed_by_user_id": None,
        }
    )
    row["liters_committed"] = stop_liters(row)
    db.route_stops[row["id"]] = row
    recompute_route_rollups(route)
    _resequence(route, (row["id"],))
    touch(route)
    if stop_type == "PICKUP" and contract["service_status"] == "IN_SERVICE":
        contract["service_status"] = "PICKUP_SCHEDULED"
        touch(contract)
    return respond(route_stop_out(row), 201)


@bp.get("/route-stops")
def list_stops():
    authenticate(LOGISTICS_READERS)
    route_id = str_filter("route_id")
    contract_id = str_filter("contract_id")
    stop_type = enum_filter("stop_type", STOP_TYPES)
    status = enum_filter("status", STOP_STATUSES)
    limit, offset = pagination()
    rows = sorted_rows(db.route_stops.values())
    if route_id is not None:
        rows = [r for r in rows if r["route_id"] == route_id]
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if stop_type is not None:
        rows = [r for r in rows if r["stop_type"] == stop_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, route_stop_out)


@bp.get("/route-stops/<stop_id>")
def read_stop(stop_id):
    authenticate(LOGISTICS_READERS)
    return respond(route_stop_out(get_route_stop(stop_id)))


@bp.post("/route-stops/<stop_id>/complete")
def complete_stop(stop_id):
    """Close a non-setup stop; a PICKUP completion returns the contract."""
    authenticate((ROLE_DRIVER,))
    stop = get_route_stop(stop_id)
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    route = _stop_route(stop)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED")
    if stop["stop_type"] not in IN_SERVICE_TYPES:
        raise ApiError("ERR_STOP_TYPE_MISMATCH")
    stop["completed_at"] = now()
    stop["completed_by_user_id"] = actor()
    stop["status"] = "COMPLETED"
    touch(stop)
    if stop["stop_type"] == "PICKUP":
        contract = db.contracts.get(stop["contract_id"])
        if contract is not None and contract["service_status"] == "PICKUP_SCHEDULED":
            for placement in placements_for_contract(contract["id"], ("PLACED",)):
                placement["status"] = "REMOVED"
                placement["removal_reason"] = "PICKUP"
                placement["removed_at"] = now()
                touch(placement)
                unit = db.equipment_units.get(placement["equipment_unit_id"])
                if unit is not None and unit["status"] == "DEPLOYED":
                    unit["status"] = "IN_STOCK"
                    touch(unit)
            contract["service_status"] = "RETURNED"
            contract["monthly_allowable_cents"] = 0
            touch(contract)
    bubble_up_route(route)
    return respond(route_stop_out(stop))


@bp.post("/route-stops/<stop_id>/complete-setup")
def complete_setup(stop_id):
    """Close a SETUP_DELIVERY stop; smoking in the home fails the setup."""
    authenticate((ROLE_THERAPIST,))
    stop = get_route_stop(stop_id)
    data = validate(SETUP_FIELDS)
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    route = _stop_route(stop)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED")
    if stop["stop_type"] != "SETUP_DELIVERY":
        raise ApiError("ERR_STOP_TYPE_MISMATCH")
    contract = get_contract(stop["contract_id"])
    if contract["service_status"] != "PENDING_SETUP":
        raise ApiError("ERR_INVALID_STATE")
    smoking = data["smoking_in_home"]
    electrical = data["electrical_pass"]
    teachback = data["patient_teachback_score"]
    reserved = placements_for_contract(contract["id"], ("RESERVED",))
    if not smoking and not reserved:
        raise ApiError("ERR_INVALID_STATE")
    findings = 0
    if smoking:
        findings += 1
    if not electrical:
        findings += 1
    if teachback < TEACHBACK_FINDING_THRESHOLD:
        findings += 1
    # HOP 1: the stop records the in-home assessment.
    stop["smoking_in_home"] = smoking
    stop["electrical_pass"] = electrical
    stop["patient_teachback_score"] = teachback
    topics = data.get("education_topics_covered")
    stop["education_topics_covered"] = list(topics) if topics else []
    stop["safety_result"] = "FAIL" if smoking else "PASS"
    stop["safety_findings_count"] = findings
    stop["completed_at"] = now()
    stop["completed_by_user_id"] = actor()
    stop["status"] = "COMPLETED"
    touch(stop)
    if smoking:
        # HOP 2: the failing safety result fails the contract on both dimensions.
        contract["service_status"] = "SETUP_FAILED"
        if contract["billing_status"] in ("ACCRUING", "CAP_REACHED"):
            contract["billing_status"] = "SUSPENDED"
            contract["suspension_reason"] = "SETUP_FAILED"
        # HOP 3: the failed contract removes its reserved placements.
        for placement in reserved:
            placement["status"] = "REMOVED"
            placement["removal_reason"] = "SETUP_FAILED"
            placement["removed_at"] = now()
            touch(placement)
            # HOP 4: the removed placements quarantine their fleet units.
            unit = db.equipment_units.get(placement["equipment_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                unit["status"] = "IN_QUARANTINE"
                unit["quarantine_reason"] = "SAFETY"
                touch(unit)
        contract["monthly_allowable_cents"] = 0
        touch(contract)
    else:
        for placement in reserved:
            placement["status"] = "PLACED"
            placement["placed_at"] = now()
            touch(placement)
            unit = db.equipment_units.get(placement["equipment_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                unit["status"] = "DEPLOYED"
                touch(unit)
        contract["service_status"] = "IN_SERVICE"
        contract["first_service_month"] = current_month()
        contract["_service_started_at"] = now()
        recompute_allowable(contract)
        touch(contract)
    patient = db.patients.get(contract["patient_id"])
    if patient is not None:
        apply_risk_variant(patient, "INITIAL_ASSESSMENT")
    bubble_up_route(route)
    return respond(route_stop_out(stop))


@bp.post("/route-stops/<stop_id>/miss")
def miss_stop(stop_id):
    """Record a missed stop; its litres stay committed for the day."""
    authenticate((ROLE_DRIVER,))
    stop = get_route_stop(stop_id)
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    route = _stop_route(stop)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED")
    stop["completed_at"] = now()
    stop["completed_by_user_id"] = actor()
    stop["status"] = "MISSED"
    touch(stop)
    route["planned_stop_count"] = max(0, route["planned_stop_count"] - 1)
    if not bubble_up_route(route):
        touch(route)
    return respond(route_stop_out(stop))


@bp.post("/route-stops/<stop_id>/cancel")
def cancel_stop(stop_id):
    """Compensating counterpart of stop creation."""
    authenticate((ROLE_MANAGER,))
    stop = get_route_stop(stop_id)
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    route = _stop_route(stop)
    if route["status"] not in EDITABLE_ROUTE_STATES:
        raise ApiError("ERR_ROUTE_NOT_EDITABLE")
    stop["status"] = "CANCELLED"
    touch(stop)
    recompute_route_rollups(route)
    _resequence(route)
    touch(route)
    if stop["stop_type"] == "PICKUP":
        contract = db.contracts.get(stop["contract_id"])
        if contract is not None and contract["service_status"] == "PICKUP_SCHEDULED":
            others = [
                s
                for s in db.route_stops.values()
                if s["contract_id"] == contract["id"]
                and s["stop_type"] == "PICKUP"
                and s["status"] == "PLANNED"
            ]
            if not others:
                contract["service_status"] = "IN_SERVICE"
                touch(contract)
    return respond(route_stop_out(stop))
