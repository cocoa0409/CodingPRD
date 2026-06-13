"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the client-supplied input fields for the
corresponding create endpoint. Computed/system fields are never included.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="member") -> str:
    """Generate a per-call unique email (each test starts against an empty DB,
    but tests that register several members still need distinct addresses)."""
    return f"{prefix}{next(_email_counter)}@example.com"


# ---- Member ----
def create_member_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Foods Co",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def top_up_payload(amount_cents=100000, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def member_version_payload(expected_member_version, **overrides) -> dict:
    defaults = {"expected_member_version": expected_member_version}
    defaults.update(overrides)
    return defaults


# ---- Station ----
def create_station_payload(**overrides) -> dict:
    defaults = {
        "name": "Prep Table 1",
        "station_class": "PREP_TABLE",
    }
    defaults.update(overrides)
    return defaults


# ---- Booking ----
def create_booking_payload(station_id, start_utc, end_utc, expected_member_version, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


# ---- StorageUnit ----
def create_storage_unit_payload(**overrides) -> dict:
    defaults = {
        "name": "Walk-in Cooler",
        "temp_class": "DRY",
        "total_slots": 20,
        "temp_min_c": 10.0,
        "temp_max_c": 25.0,
    }
    defaults.update(overrides)
    return defaults


# ---- StorageAssignment ----
def create_storage_assignment_payload(temp_class, requested_slots, expected_member_version, **overrides) -> dict:
    defaults = {
        "temp_class": temp_class,
        "requested_slots": requested_slots,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Ingredient ----
def create_ingredient_payload(**overrides) -> dict:
    defaults = {
        "name": "Almond Flour",
        "unit_cost_cents": 100,
    }
    defaults.update(overrides)
    return defaults


# ---- Recipe + RecipeComponent ----
def create_recipe_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Recipe",
        "batch_yield_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_recipe_component_payload(ingredient_id, planned_qty, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "planned_qty": planned_qty,
    }
    defaults.update(overrides)
    return defaults


# ---- ProductionBatch ----
def create_batch_payload(recipe_id, planned_yield_units, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "planned_yield_units": planned_yield_units,
    }
    defaults.update(overrides)
    return defaults


def complete_batch_payload(actual_yield_units, actual_components=None, **overrides) -> dict:
    defaults = {"actual_yield_units": actual_yield_units}
    if actual_components is not None:
        defaults["actual_components"] = actual_components
    defaults.update(overrides)
    return defaults


# ---- IngredientOrder ----
def create_ingredient_order_payload(ingredient_id, order_qty, unit_cost_cents, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "order_qty": order_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- EventPackout ----
def create_packout_payload(event_name, batch_ids, **overrides) -> dict:
    defaults = {
        "event_name": event_name,
        "batch_ids": batch_ids,
    }
    defaults.update(overrides)
    return defaults


# ---- Invoice ----
def create_invoice_payload(period_start_utc, period_end_utc, **overrides) -> dict:
    defaults = {
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
    }
    defaults.update(overrides)
    return defaults
