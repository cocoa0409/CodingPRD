"""Circuit endpoints."""

from decimal import Decimal

from flask import Blueprint, g

import db
import validation as v
from errors import ApiError
from middleware import (
    ALL_ROLES,
    ASSET_INSPECTOR,
    COMMUNITY_LIAISON,
    FIELD_PATROL_SUPERVISOR,
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import list_response, object_response
from services import calc, events

bp = Blueprint("circuits", __name__)

HFTD_TIERS = ("TIER_1", "TIER_2", "TIER_3", "NON_HFTD")
ENERGIZATION_STATES = (
    "ENERGIZED",
    "DE_ENERGIZATION_PENDING",
    "DE_ENERGIZED",
    "PATROL_IN_PROGRESS",
    "CLEARED_FOR_RESTORE",
)
RISK_POSTURES = ("NORMAL", "ELEVATED", "EXTREME", "LOCKED")


def _page(rows, serializer):
    limit, offset = v.pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)


@bp.post("/circuits")
@roles(GRID_PLANNER)
def create_circuit():
    body = v.Body()
    circuit_code = body.string("circuit_code", 3, 40)
    district_code = body.string("district_code", 3, 40)
    hftd_tier = body.enum("hftd_tier", HFTD_TIERS)
    overhead_miles = body.number("overhead_miles", exclusive_minimum=0, max_decimals=1)
    equipment_condition_index = body.number("equipment_condition_index", minimum=0, maximum=100)
    inspection_cycle_months = body.integer(
        "inspection_cycle_months", minimum=1, maximum=120, required=False, default=36
    )
    last_inspection, last_inspection_raw = body.timestamp(
        "last_inspection_completed_at", required=False
    )
    upstream_circuit_id = body.string("upstream_circuit_id", required=False, default=None)
    fast_trip_enabled = body.boolean("fast_trip_enabled", default=False)

    v.unique_code(db.circuits, "circuit_code", circuit_code)

    row = db.new_row()
    row["circuit_code"] = circuit_code
    row["district_code"] = district_code
    row["hftd_tier"] = hftd_tier
    row["overhead_miles"] = overhead_miles
    row["equipment_condition_index"] = equipment_condition_index
    row["inspection_cycle_months"] = inspection_cycle_months
    db.set_dt(row, "last_inspection_completed_at", last_inspection, last_inspection_raw)
    row["upstream_circuit_id"] = upstream_circuit_id
    row["fast_trip_enabled"] = fast_trip_enabled
    row["covered_conductor_miles"] = Decimal("0.0")
    row["underground_miles"] = Decimal("0.0")
    row["hardened_fraction"] = Decimal("0.0000")
    row["customer_count"] = 0
    row["medical_baseline_count"] = 0
    row["critical_facility_count"] = 0
    row["energization_state"] = "ENERGIZED"
    row["risk_posture"] = "NORMAL"
    row["latest_forecast_fpi_score"] = None
    row["latest_forecast_fpi_tier"] = None
    db.circuits[row["id"]] = row
    return object_response(db.circuit_out(row), 201)


@bp.get("/circuits")
@roles(*ALL_ROLES)
def list_circuits():
    district_code = v.query_string("district_code")
    hftd_tier = v.query_enum("hftd_tier", HFTD_TIERS)
    energization_state = v.query_enum("energization_state", ENERGIZATION_STATES)
    risk_posture = v.query_enum("risk_posture", RISK_POSTURES)
    upstream_circuit_id = v.query_string("upstream_circuit_id")

    rows = db.in_order(db.circuits.values())
    if district_code is not None:
        rows = [r for r in rows if r["district_code"] == district_code]
    if hftd_tier is not None:
        rows = [r for r in rows if r["hftd_tier"] == hftd_tier]
    if energization_state is not None:
        rows = [r for r in rows if r["energization_state"] == energization_state]
    if risk_posture is not None:
        rows = [r for r in rows if r["risk_posture"] == risk_posture]
    if upstream_circuit_id is not None:
        rows = [r for r in rows if r["upstream_circuit_id"] == upstream_circuit_id]
    return _page(rows, db.circuit_out)


@bp.get("/circuits/<circuit_id>")
@roles(*ALL_ROLES)
def get_circuit(circuit_id):
    return object_response(db.circuit_out(v.circuit(circuit_id)))


@bp.get("/circuits/<circuit_id>/weather-stations")
@roles(
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)
def list_circuit_stations(circuit_id):
    circuit = v.circuit(circuit_id)
    telemetry_status = v.query_enum("telemetry_status", ("ONLINE", "DEGRADED", "OFFLINE"))
    rows = [
        s
        for s in db.in_order(db.weather_stations.values())
        if s["circuit_id"] == circuit["id"]
    ]
    if telemetry_status is not None:
        rows = [r for r in rows if r["telemetry_status"] == telemetry_status]
    return _page(rows, db.weather_station_out)


@bp.get("/circuits/<circuit_id>/customers")
@roles(
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)
def list_circuit_customers(circuit_id):
    circuit = v.circuit(circuit_id)
    customer_class = v.query_enum(
        "customer_class", ("RESIDENTIAL", "COMMERCIAL", "CRITICAL_FACILITY")
    )
    medical_baseline = v.query_bool("medical_baseline")
    rows = [c for c in db.in_order(db.customers.values()) if c["circuit_id"] == circuit["id"]]
    if customer_class is not None:
        rows = [r for r in rows if r["customer_class"] == customer_class]
    if medical_baseline is not None:
        rows = [r for r in rows if r["medical_baseline"] == medical_baseline]
    return _page(rows, db.customer_out)


@bp.get("/circuits/<circuit_id>/fire-potential-indices")
@roles(
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)
def list_circuit_indices(circuit_id):
    circuit = v.circuit(circuit_id)
    variant = v.query_enum("computation_variant", ("FORECAST", "VALIDATED"))
    forecast_date = v.query_string("forecast_date")
    rows = [
        i
        for i in db.in_order(db.fire_potential_indices.values())
        if i["circuit_id"] == circuit["id"]
    ]
    if variant is not None:
        rows = [r for r in rows if r["computation_variant"] == variant]
    if forecast_date is not None:
        rows = [r for r in rows if r["forecast_date"] == forecast_date]
    return _page(rows, db.fire_potential_index_out)


@bp.get("/circuits/<circuit_id>/mitigation-projects")
@roles(
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)
def list_circuit_projects(circuit_id):
    circuit = v.circuit(circuit_id)
    program_type = v.query_enum(
        "program_type",
        ("COVERED_CONDUCTOR", "UNDERGROUNDING", "FAST_TRIP_SETTING", "INSPECTION_CYCLE"),
    )
    status = v.query_enum(
        "status",
        (
            "DRAFT",
            "SUBMITTED",
            "REVISION_REQUESTED",
            "APPROVED",
            "IN_EXECUTION",
            "SUSPENDED",
            "COMPLETED",
            "WITHDRAWN",
        ),
    )
    rows = [
        p
        for p in db.in_order(db.mitigation_projects.values())
        if p["circuit_id"] == circuit["id"]
    ]
    if program_type is not None:
        rows = [r for r in rows if r["program_type"] == program_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _page(rows, db.mitigation_project_out)


@bp.get("/circuits/<circuit_id>/event-scopes")
@roles(
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    FIELD_PATROL_SUPERVISOR,
    TRANSMISSION_ENGINEER,
)
def list_circuit_scopes(circuit_id):
    circuit = v.circuit(circuit_id)
    scope_status = v.query_enum("scope_status", ("CONFIRMED", "EXCLUDED"))
    rows = [
        s for s in db.in_order(db.event_scopes.values()) if s["circuit_id"] == circuit["id"]
    ]
    if scope_status is not None:
        rows = [r for r in rows if r["scope_status"] == scope_status]
    return _page(rows, db.event_scope_out)


@bp.post("/circuits/<circuit_id>/re-energize")
@roles(PSPS_DUTY_OFFICER)
def re_energize_circuit(circuit_id):
    circuit = v.circuit(circuit_id)

    # Priority 8 - own state.
    if circuit["energization_state"] != "CLEARED_FOR_RESTORE":
        raise ApiError(
            "ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE",
            "The circuit is %s, not CLEARED_FOR_RESTORE." % circuit["energization_state"],
        )

    # Priority 9 - governing event must be in restoration.
    event, scope = events.governing_event_for_circuit(circuit)
    if event is None or event["scope_status"] != "RESTORING":
        raise ApiError(
            "ERR_EVENT_NOT_IN_RESTORATION",
            "The governing shutoff event is not in restoration.",
        )

    # Priority 10 - the clearing patrol must carry no unresolved ignition risk.
    completed = [
        p
        for p in db.patrol_assignments.values()
        if p["circuit_id"] == circuit["id"] and p["status"] == "COMPLETED"
    ]
    clearing = None
    if completed:
        clearing = max(
            completed, key=lambda p: (p["completed_at"], p["created_at"], p["_seq"])
        )
    if clearing is None or int(clearing["ignition_risk_finding_count"]) != 0:
        raise ApiError(
            "ERR_IGNITION_RISK_DAMAGE_UNRESOLVED",
            "The latest completed patrol reports unresolved ignition-risk damage.",
        )

    # Priority 12 - segregation of duties against the patrol lead.
    if clearing["patrol_lead_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The patrol lead who cleared the circuit may not re-energize it.",
        )

    events.re_energize(circuit, event, scope)
    return object_response(db.circuit_out(circuit))
