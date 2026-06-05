"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so tests can
control the values that matter. Only fields with source: input appear here;
computed and system fields are never sent.
"""
import itertools

_email_counter = itertools.count(1)
_plate_counter = itertools.count(1)


def unique_email(prefix="cust") -> str:
    """A process-unique email so customer-creation in independent tests never collides."""
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_plate(prefix="TRK") -> str:
    """A process-unique truck plate."""
    return f"{prefix}-{next(_plate_counter)}"


# ─── Customer (PRD §3.1) ──────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Customer",
        "origin_state_code": "CA",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


# ─── MoveJob (PRD §3.2) ───────────────────────────────────────────────────────
def create_move_job_payload(customer_id, service_type="LOCAL", **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_type": service_type,
        "origin_zip": "90001",
        "destination_zip": "90002",
        "distance_miles": 0,
        "requested_move_date": "2026-07-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── InventorySurvey (PRD §3.2) ───────────────────────────────────────────────
def create_survey_payload(move_job_id, survey_method="IN_HOME", **overrides) -> dict:
    defaults = {"move_job_id": move_job_id, "survey_method": survey_method}
    defaults.update(overrides)
    return defaults


def create_survey_item_payload(label="box", quantity=40, cubic_feet_each=3, **overrides) -> dict:
    defaults = {"label": label, "quantity": quantity, "cubic_feet_each": cubic_feet_each}
    defaults.update(overrides)
    return defaults


# ─── PackingOrder (PRD §3.3) ──────────────────────────────────────────────────
def create_packing_order_payload(move_job_id, packing_lines=None, **overrides) -> dict:
    defaults = {
        "move_job_id": move_job_id,
        "crate_count": 0,
        "packing_lines": packing_lines if packing_lines is not None else [],
    }
    defaults.update(overrides)
    return defaults


# ─── Estimate (PRD §3.4) ──────────────────────────────────────────────────────
def create_estimate_payload(move_job_id, survey_id, expected_move_job_version,
                            binding_type="NON_BINDING", valuation_coverage="RELEASED",
                            **overrides) -> dict:
    defaults = {
        "move_job_id": move_job_id,
        "survey_id": survey_id,
        "binding_type": binding_type,
        "valuation_coverage": valuation_coverage,
        "expected_move_job_version": expected_move_job_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Truck (PRD §3.1) ─────────────────────────────────────────────────────────
def create_truck_payload(plate=None, capacity_cubic_feet=2000, home_state_code="CA",
                         **overrides) -> dict:
    defaults = {
        "plate": plate if plate is not None else unique_plate(),
        "capacity_cubic_feet": capacity_cubic_feet,
        "home_state_code": home_state_code,
    }
    defaults.update(overrides)
    return defaults


# ─── Crew (PRD §3.1) ──────────────────────────────────────────────────────────
def create_crew_payload(name="Test Crew", head_count=3, home_state_code="CA",
                        **overrides) -> dict:
    defaults = {"name": name, "head_count": head_count, "home_state_code": home_state_code}
    defaults.update(overrides)
    return defaults


# ─── Dispatch (PRD §3.6) ──────────────────────────────────────────────────────
def create_dispatch_payload(move_job_id, truck_id, crew_id,
                            window_start="2026-07-01T09:00:00Z",
                            window_end="2026-07-01T12:00:00Z",
                            required_crew_size=3, **overrides) -> dict:
    defaults = {
        "move_job_id": move_job_id,
        "truck_id": truck_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "required_crew_size": required_crew_size,
    }
    defaults.update(overrides)
    return defaults


# ─── StorageLot (PRD §3.8) ────────────────────────────────────────────────────
def create_storage_lot_payload(move_job_id, intake_date="2026-07-01T00:00:00Z",
                               **overrides) -> dict:
    defaults = {"move_job_id": move_job_id, "intake_date": intake_date}
    defaults.update(overrides)
    return defaults


# ─── DamageClaim + ClaimItem (PRD §3.10) ──────────────────────────────────────
def create_damage_claim_payload(move_job_id, **overrides) -> dict:
    defaults = {"move_job_id": move_job_id}
    defaults.update(overrides)
    return defaults


def create_claim_item_payload(label="mirror", item_weight_lbs=40,
                              repair_cost_cents=90000, replacement_value_cents=150000,
                              **overrides) -> dict:
    defaults = {
        "label": label,
        "item_weight_lbs": item_weight_lbs,
        "repair_cost_cents": repair_cost_cents,
        "replacement_value_cents": replacement_value_cents,
    }
    defaults.update(overrides)
    return defaults
