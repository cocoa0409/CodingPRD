"""Battery units: shipment, field service, warranty settlement and core return."""
from decimal import Decimal

from flask import Blueprint, g

from authz import (
    FLEET_ENGINEER,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    WARRANTY_ADMINISTRATOR,
    endpoint,
)
from errors import ApiError
from helpers import apply_filters, logs_of_unit, lookup, paginated, unique_or_conflict
from response import object_response
from store import db
from util import q
from validation import forbid, present, require
from services.constants import (
    CHEM_LEAD,
    CORE_DEPOSIT_CENTS,
    CORE_MASS_TOLERANCE_RATIO,
    POSTURE_FROZEN,
)
from services.plant_service import refresh_plant
from services.warranty import (
    combined_usage_fraction,
    cycle_usage_fraction,
    recompute_service_figures,
    settlement,
)

bp = Blueprint("units", __name__)

UNIT_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, WARRANTY_ADMINISTRATOR, FLEET_ENGINEER]
LOG_READERS = [PLANT_ADMIN, WARRANTY_ADMINISTRATOR]

SHIP_SPEC = {
    "lot_id": {"type": "id", "required": True},
    "serial_number": {"type": "string", "required": True},
    "customer_name": {"type": "string", "required": True},
    "list_price_cents": {"type": "int", "gt": 0},
    "sizing_request_id": {"type": "id"},
    "shipped_at": {"type": "datetime"},
}

LOG_SPEC = {
    "event_type": {
        "type": "enum",
        "required": True,
        "values": ["WATERING", "EQUALIZE", "INSPECTION", "CYCLE_REPORT"],
    },
    "performed_at": {"type": "datetime", "required": True},
    "electrolyte_level_ok": {"type": "bool"},
    "cycles_delta": {"type": "int", "gte": 1, "lte": 2000},
    "technician_note": {"type": "string", "allow_blank": True},
}

CLAIM_SPEC = {
    "expected_battery_unit_version": {"type": "int", "required": True},
    "complaint_code": {"type": "string", "required": True},
    "reported_at": {"type": "datetime"},
}

ADJUDICATION_SPEC = {
    "inspection_finding": {
        "type": "enum",
        "required": True,
        "values": ["DEFECT_CONFIRMED", "NO_DEFECT_FOUND"],
    },
    "adjudication_note": {"type": "string", "allow_blank": True},
}

CORE_OPEN_SPEC = {"core_manifest_number": {"type": "string", "required": True}}

CORE_TRANSITION_SPEC = {
    "action": {
        "type": "enum",
        "required": True,
        "values": ["SHIP", "RECEIVE", "RECYCLE", "REJECT"],
    },
    "received_lead_kg": {"type": "number", "gte": 0},
    "transition_note": {"type": "string", "allow_blank": True},
}

UNIT_FILTERS = {
    "lot_id": "lot_id",
    "sizing_request_id": "sizing_request_id",
    "warranty_status": "warranty_status",
    "core_status": "core_status",
}
UNIT_ORDER = [("shipped_at", "asc"), ("created_at", "asc")]
LOG_ORDER = [("performed_at", "desc"), ("created_at", "asc")]

SETTLED_STATES = ("CLAIM_HONORED", "CLAIM_PRORATED")


def _check_log_discriminator(payload):
    event = payload["event_type"]
    if event == "WATERING":
        require(payload, "electrolyte_level_ok", "for a WATERING event")
        forbid(payload, "cycles_delta", "for a WATERING event")
    elif event == "CYCLE_REPORT":
        require(payload, "cycles_delta", "for a CYCLE_REPORT event")
        forbid(payload, "electrolyte_level_ok", "for a CYCLE_REPORT event")
    else:
        forbid(payload, "electrolyte_level_ok", "for a %s event" % event)
        forbid(payload, "cycles_delta", "for a %s event" % event)


def _check_core_transition_payload(payload):
    if payload["action"] == "RECEIVE":
        require(payload, "received_lead_kg", "for a RECEIVE transition")


def _design_of_unit(unit):
    lot = db.production_lots.get(unit["lot_id"])
    if lot is None:
        return None, None
    return lot, db.cell_designs.get(lot["cell_design_id"])


def _plant_of_unit(unit):
    lot = db.production_lots.get(unit["lot_id"])
    return db.plants.get(lot["plant_id"]) if lot else None


@bp.post("/battery-units")
@endpoint([PRODUCTION_SUPERVISOR], body=SHIP_SPEC)
def ship_unit():
    payload = g.body
    lot = lookup("production_lots", payload["lot_id"])
    quote = None
    if payload.get("sizing_request_id") is not None:
        quote = lookup(
            "fleet_sizing_requests",
            payload["sizing_request_id"],
            "ERR_SIZING_REQUEST_NOT_FOUND",
        )
    unique_or_conflict("battery_units", "serial_number", payload["serial_number"])
    if lot["process_state"] != "RELEASED":
        raise ApiError("ERR_LOT_STATE_INVALID", "Units may only ship from a RELEASED lot")
    if quote is not None and quote["request_state"] != "ACCEPTED":
        raise ApiError(
            "ERR_SIZING_REQUEST_STATE_INVALID",
            "Only an ACCEPTED sizing request may be named at shipment",
        )
    plant = db.plants.get(lot["plant_id"])
    if plant is not None and plant.get("compliance_posture") == POSTURE_FROZEN:
        raise ApiError("ERR_PLANT_FROZEN", "The plant's compliance posture is FROZEN")
    if quote is not None and quote["plant_id"] != lot["plant_id"]:
        raise ApiError(
            "ERR_PLANT_SCOPE_MISMATCH",
            "The sizing request belongs to a different plant than the lot",
        )
    design = db.cell_designs.get(lot["cell_design_id"])
    declared = q(design["lead_content_kg"], 3)
    if plant["lead_inventory_kg"] < declared:
        raise ApiError(
            "ERR_LEAD_INVENTORY_INSUFFICIENT",
            "The plant's on-hand lead inventory cannot cover this shipment",
        )
    lead_acid = design["chemistry"] == CHEM_LEAD
    record = {
        "lot_id": lot["id"],
        "sizing_request_id": quote["id"] if quote else None,
        "serial_number": payload["serial_number"],
        "customer_name": payload["customer_name"],
        "list_price_cents": payload.get("list_price_cents") or design["list_price_cents"],
        "shipped_at": payload.get("shipped_at") or db.now(),
        "warranty_status": "IN_SERVICE",
        "core_status": "DEPOSIT_HELD" if lead_acid else "NOT_APPLICABLE",
        "cycle_count": 0,
        "months_in_service": 0,
        "watering_events_expected": 0,
        "watering_events_ok": 0,
        "watering_compliance_ratio": Decimal("1.0000"),
        "usage_fraction": Decimal("0.0000"),
        "claim_count": 0,
        "last_claim_at": None,
        "warranty_decision": None,
        "warranty_credit_cents": 0,
        "core_manifest_number": None,
        "declared_lead_kg": declared,
        "received_lead_kg": None,
        "core_credit_issued_cents": 0,
    }
    db.insert("battery_units", record)
    refresh_plant(plant)
    return object_response(record, 201)


@bp.get("/battery-units")
@endpoint(UNIT_READERS, paginated=True)
def list_units():
    return paginated(apply_filters(db.rows("battery_units"), UNIT_FILTERS), UNIT_ORDER)


@bp.get("/battery-units/<unit_id>")
@endpoint(UNIT_READERS)
def read_unit(unit_id):
    return object_response(lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND"))


@bp.post("/battery-units/<unit_id>/maintenance-logs")
@endpoint([WARRANTY_ADMINISTRATOR], body=LOG_SPEC, schema_check=_check_log_discriminator)
def create_maintenance_log(unit_id):
    payload = g.body
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    now = db.now()
    performed = payload["performed_at"]
    if performed < unit["shipped_at"] or performed > now:
        raise ApiError(
            "ERR_EVENT_TIME_OUT_OF_RANGE",
            "performed_at must fall between the shipment instant and the logical clock",
        )
    lot, design = _design_of_unit(unit)
    row = {
        "battery_unit_id": unit["id"],
        "event_type": payload["event_type"],
        "performed_at": performed,
        "electrolyte_level_ok": payload.get("electrolyte_level_ok"),
        "cycles_delta": payload.get("cycles_delta"),
        "technician_note": payload.get("technician_note"),
        "resulting_cycle_count": 0,
        "resulting_compliance_ratio": Decimal("1.0000"),
    }
    db.insert("maintenance_logs", row, versioned=False)
    recompute_service_figures(unit, design, now)
    if payload["event_type"] == "CYCLE_REPORT":
        unit["usage_fraction"] = cycle_usage_fraction(unit, design)
    db.touch(unit)
    row["resulting_cycle_count"] = unit["cycle_count"]
    row["resulting_compliance_ratio"] = unit["watering_compliance_ratio"]
    return object_response(row, 201)


@bp.get("/battery-units/<unit_id>/maintenance-logs")
@endpoint(LOG_READERS, paginated=True)
def list_maintenance_logs(unit_id):
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    rows = apply_filters(logs_of_unit(unit["id"]), {"event_type": "event_type"})
    return paginated(rows, LOG_ORDER)


@bp.get("/battery-units/<unit_id>/warranty-evaluation")
@endpoint(LOG_READERS)
def warranty_evaluation(unit_id):
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    lot, design = _design_of_unit(unit)
    # Pure projection: every figure is computed on a copy, nothing is written.
    preview = dict(unit)
    recompute_service_figures(preview, design)
    usage = combined_usage_fraction(preview, design)
    decision, credit, _ = settlement(preview, design, "DEFECT_CONFIRMED", usage)
    return object_response(
        {
            "battery_unit_id": unit["id"],
            "usage_fraction": usage,
            "watering_compliance_ratio": preview["watering_compliance_ratio"],
            "months_in_service": preview["months_in_service"],
            "warranty_months": design["warranty_months"],
            "would_decide": decision,
            "would_credit_cents": credit,
            "governing_gate": decision,
        }
    )


@bp.post("/battery-units/<unit_id>/warranty-claims")
@endpoint([WARRANTY_ADMINISTRATOR], body=CLAIM_SPEC)
def open_warranty_claim(unit_id):
    payload = g.body
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    if payload["expected_battery_unit_version"] != unit.get("version"):
        raise ApiError(
            "ERR_STALE_BATTERY_UNIT_VERSION",
            "expected_battery_unit_version does not match the unit's current version",
        )
    status = unit["warranty_status"]
    if status in SETTLED_STATES:
        raise ApiError(
            "ERR_WARRANTY_ALREADY_SETTLED", "This unit's warranty is settled for good"
        )
    if status not in ("IN_SERVICE", "CLAIM_DENIED"):
        raise ApiError(
            "ERR_WARRANTY_STATE_INVALID", "A claim is already open on this unit"
        )
    lot, design = _design_of_unit(unit)
    unit["warranty_status"] = "CLAIM_OPEN"
    unit["claim_count"] = unit.get("claim_count", 0) + 1
    unit["last_claim_at"] = payload.get("reported_at") or db.now()
    unit["warranty_decision"] = None
    unit["warranty_credit_cents"] = 0
    recompute_service_figures(unit, design)
    db.touch(unit)
    return object_response(unit, 201)


@bp.post("/battery-units/<unit_id>/warranty-adjudication")
@endpoint([WARRANTY_ADMINISTRATOR], body=ADJUDICATION_SPEC)
def adjudicate_warranty(unit_id):
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    if unit["warranty_status"] != "CLAIM_OPEN":
        raise ApiError("ERR_WARRANTY_STATE_INVALID", "No claim is open on this unit")
    lot, design = _design_of_unit(unit)
    usage = combined_usage_fraction(unit, design)
    unit["usage_fraction"] = usage
    decision, credit, status = settlement(
        unit, design, g.body["inspection_finding"], usage
    )
    unit["warranty_decision"] = decision
    unit["warranty_credit_cents"] = credit
    unit["warranty_status"] = status
    db.touch(unit)
    return object_response(unit)


@bp.post("/battery-units/<unit_id>/core-return")
@endpoint([WARRANTY_ADMINISTRATOR], body=CORE_OPEN_SPEC)
def open_core_return(unit_id):
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    unique_or_conflict(
        "battery_units", "core_manifest_number", g.body["core_manifest_number"]
    )
    lot, design = _design_of_unit(unit)
    if design is None or design["chemistry"] != CHEM_LEAD:
        raise ApiError(
            "ERR_CORE_NOT_APPLICABLE", "A LITHIUM_LFP unit has no core-return programme"
        )
    if unit["core_status"] != "DEPOSIT_HELD":
        raise ApiError(
            "ERR_CORE_STATE_INVALID", "A core return may only be opened while the deposit is held"
        )
    if (unit.get("declared_lead_kg") or Decimal("0")) <= 0:
        raise ApiError(
            "ERR_CORE_NOT_APPLICABLE", "The unit carries no declared lead mass to return"
        )
    unit["core_status"] = "RETURN_OPEN"
    unit["core_manifest_number"] = g.body["core_manifest_number"]
    db.touch(unit)
    return object_response(unit)


@bp.post("/battery-units/<unit_id>/core-return/transitions")
@endpoint(
    [WARRANTY_ADMINISTRATOR],
    body=CORE_TRANSITION_SPEC,
    schema_check=_check_core_transition_payload,
)
def core_return_transition(unit_id):
    payload = g.body
    action = payload["action"]
    unit = lookup("battery_units", unit_id, "ERR_BATTERY_UNIT_NOT_FOUND")
    lot, design = _design_of_unit(unit)
    if design is None or design["chemistry"] != CHEM_LEAD:
        raise ApiError(
            "ERR_CORE_NOT_APPLICABLE", "A LITHIUM_LFP unit has no core-return programme"
        )
    required_state = {
        "SHIP": "RETURN_OPEN",
        "RECEIVE": "IN_TRANSIT",
        "REJECT": "IN_TRANSIT",
        "RECYCLE": "RECEIVED",
    }[action]
    if unit["core_status"] != required_state:
        raise ApiError(
            "ERR_CORE_STATE_INVALID",
            "%s requires the core to be %s" % (action, required_state),
        )
    if action == "RECEIVE":
        declared = design["lead_content_kg"]
        weighed = q(payload["received_lead_kg"], 3)
        if abs(weighed - declared) > declared * CORE_MASS_TOLERANCE_RATIO:
            raise ApiError(
                "ERR_CORE_MASS_VARIANCE_EXCEEDED",
                "received_lead_kg differs from the manifest mass by more than 2 percent",
            )
        unit["received_lead_kg"] = weighed
        unit["core_status"] = "RECEIVED"
    elif action == "SHIP":
        unit["core_status"] = "IN_TRANSIT"
    elif action == "RECYCLE":
        unit["core_status"] = "RECYCLED"
        unit["core_credit_issued_cents"] = CORE_DEPOSIT_CENTS
    else:
        unit["core_status"] = "REJECTED"
    db.touch(unit)
    plant = _plant_of_unit(unit)
    if plant is not None:
        refresh_plant(plant)
    return object_response(unit)
