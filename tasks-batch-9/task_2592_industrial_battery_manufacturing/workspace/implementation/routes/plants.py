"""Plant registration, amendment surfaces and the three computed ledgers."""
from decimal import Decimal

from flask import Blueprint, g

from authz import (
    ALL_ROLES,
    FLEET_ENGINEER,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    SAFETY_OFFICER,
    endpoint,
)
from helpers import apply_filters, lookup, paginated, unique_or_conflict
from response import object_response
from store import db
from util import q
from services.constants import CHEMISTRIES, POSTURE_OPEN
from services.plant_service import (
    derive_posture,
    emission_ledger,
    lead_mass_balance,
    refresh_plant,
)

bp = Blueprint("plants", __name__)

PERMIT_STATES = ["ACTIVE", "SUSPENDED"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]

CREATE_SPEC = {
    "name": {"type": "string", "required": True},
    "site_code": {"type": "string", "required": True, "pattern": r"[A-Z0-9]{4,12}"},
    "licensed_chemistries": {"type": "enum_list", "required": True, "values": CHEMISTRIES},
    "permit_status": {"type": "enum", "values": PERMIT_STATES, "default": "ACTIVE"},
    "monthly_lead_emission_permit_g": {"type": "number", "required": True, "gt": 0},
    "peak_tariff_cents_per_kwh": {"type": "number", "required": True, "gt": 0},
    "offpeak_tariff_cents_per_kwh": {"type": "number", "required": True, "gt": 0},
    "lead_initial_inventory_kg": {"type": "number", "required": True, "gte": 0},
}

PATCH_SPEC = {
    "monthly_lead_emission_permit_g": {"type": "number", "gt": 0},
    "licensed_chemistries": {"type": "enum_list", "values": CHEMISTRIES},
    "peak_tariff_cents_per_kwh": {"type": "number", "gt": 0},
    "offpeak_tariff_cents_per_kwh": {"type": "number", "gt": 0},
}

PERMIT_SPEC = {"permit_status": {"type": "enum", "required": True, "values": PERMIT_STATES}}

LIST_FILTERS = {"permit_status": "permit_status", "compliance_posture": "compliance_posture"}
PLANT_ORDER = [("created_at", "desc"), ("id", "asc")]


@bp.post("/plants")
@endpoint([PLANT_ADMIN], body=CREATE_SPEC)
def create_plant():
    payload = g.body
    unique_or_conflict("plants", "site_code", payload["site_code"])
    initial = payload["lead_initial_inventory_kg"]
    record = {
        "name": payload["name"],
        "site_code": payload["site_code"],
        "licensed_chemistries": payload["licensed_chemistries"],
        "permit_status": payload["permit_status"],
        "monthly_lead_emission_permit_g": payload["monthly_lead_emission_permit_g"],
        "peak_tariff_cents_per_kwh": payload["peak_tariff_cents_per_kwh"],
        "offpeak_tariff_cents_per_kwh": payload["offpeak_tariff_cents_per_kwh"],
        "lead_initial_inventory_kg": initial,
        "emission_reserved_g": Decimal("0.00"),
        "emission_consumed_g": Decimal("0.00"),
        "emission_utilization_ratio": Decimal("0.0000"),
        "open_medical_removal_count": 0,
        "compliance_posture": POSTURE_OPEN,
        "lead_inventory_kg": q(initial, 3),
        "lead_in_field_kg": Decimal("0.000"),
        "lead_recycled_kg": Decimal("0.000"),
        "lead_mass_variance_kg": Decimal("0.000"),
        "core_lead_variance_kg": Decimal("0.000"),
        "core_deposit_liability_cents": 0,
        "formation_energy_charge_cents": 0,
    }
    record["compliance_posture"] = derive_posture(record)
    db.insert("plants", record)
    return object_response(record, 201)


@bp.get("/plants")
@endpoint(ALL_ROLES, paginated=True)
def list_plants():
    return paginated(apply_filters(db.rows("plants"), LIST_FILTERS), PLANT_ORDER)


@bp.get("/plants/<plant_id>")
@endpoint(ALL_ROLES)
def read_plant(plant_id):
    return object_response(lookup("plants", plant_id))


@bp.patch("/plants/<plant_id>")
@endpoint([PLANT_ADMIN], body=PATCH_SPEC, at_least_one=True)
def amend_plant(plant_id):
    plant = lookup("plants", plant_id)
    for field in PATCH_SPEC:
        if field in g.body:
            plant[field] = g.body[field]
    db.touch(plant)
    refresh_plant(plant)
    return object_response(plant)


@bp.patch("/plants/<plant_id>/permit")
@endpoint([PLANT_ADMIN], body=PERMIT_SPEC)
def set_permit(plant_id):
    plant = lookup("plants", plant_id)
    target = g.body["permit_status"]
    plant["permit_status"] = target
    db.touch(plant)
    refresh_plant(
        plant,
        permit_suspended=(target == "SUSPENDED"),
        permit_reinstated=(target == "ACTIVE"),
    )
    return object_response(plant)


@bp.get("/plants/<plant_id>/emission-ledger")
@endpoint([PLANT_ADMIN, SAFETY_OFFICER, PRODUCTION_SUPERVISOR])
def read_emission_ledger(plant_id):
    return object_response(emission_ledger(lookup("plants", plant_id)))


@bp.get("/plants/<plant_id>/lead-mass-balance")
@endpoint([PLANT_ADMIN, SAFETY_OFFICER])
def read_lead_mass_balance(plant_id):
    return object_response(lead_mass_balance(lookup("plants", plant_id)))


@bp.get("/plants/<plant_id>/fleet-analysis")
@endpoint([PLANT_ADMIN, FLEET_ENGINEER])
def read_fleet_analysis(plant_id):
    plant = lookup("plants", plant_id)
    rows = [
        r
        for r in db.rows("fleet_sizing_requests")
        if r.get("plant_id") == plant["id"] and r.get("request_state") == "ACCEPTED"
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    batteries = sum(r.get("recommended_battery_count") or 0 for r in rows)
    chargers = sum(r.get("recommended_charger_count") or 0 for r in rows)
    capital = sum(r.get("fleet_capital_cents") or 0 for r in rows)
    lines = [
        {
            "sizing_request_id": r["id"],
            "application_name": r.get("application_name"),
            "forklift_class": r.get("forklift_class"),
            "forklift_count": r.get("forklift_count"),
            "selected_cell_design_id": r.get("selected_cell_design_id"),
            "selected_charger_id": r.get("selected_charger_id"),
            "required_ah": r.get("required_ah"),
            "selected_charge_hours": r.get("selected_charge_hours"),
            "recommended_battery_count": r.get("recommended_battery_count"),
            "recommended_charger_count": r.get("recommended_charger_count"),
            "fleet_capital_cents": r.get("fleet_capital_cents"),
        }
        for r in rows
    ]
    return object_response(
        {
            "plant_id": plant["id"],
            "accepted_request_count": len(rows),
            "recommended_battery_count": batteries,
            "recommended_charger_count": chargers,
            "fleet_capital_cents": capital,
            "lines": lines,
        }
    )
