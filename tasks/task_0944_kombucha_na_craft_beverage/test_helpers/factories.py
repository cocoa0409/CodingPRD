"""Payload factories — one per resource, carrying only the declared input fields."""

from .constants import required_label_elements

DEFAULTS = {
    "RECIPE_NAME": "House Ginger",
    "RECIPE_STYLE": "KOMBUCHA",
    "TARGET_PH_CEILING": 3.5,
    "PLANNED_F1_DAYS": 6,
    "PLANNED_F2_DAYS": 3,
    "BASE_GRAVITY_BRIX": 7.0,
    "F2_SUGAR": 4,
    "VESSEL_CAPACITY": 500.0,
    "PITCHED_LITERS": 400.0,
    "CREDIT_LIMIT": 5000.0,
    "CREDIT_TERMS_DAYS": 30,
    "KEG_CAPACITY": 19.5,
    "MAX_UNITS_REQUESTED": 300,
}


def create_recipe_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RECIPE_NAME"],
        "style": DEFAULTS["RECIPE_STYLE"],
        "target_ph_ceiling": DEFAULTS["TARGET_PH_CEILING"],
        "planned_f1_days": DEFAULTS["PLANNED_F1_DAYS"],
        "planned_f2_days": DEFAULTS["PLANNED_F2_DAYS"],
        "base_gravity_brix": DEFAULTS["BASE_GRAVITY_BRIX"],
        "intended_abv_class": "NON_ALCOHOLIC",
    }
    payload.update(overrides)
    return payload


def create_label_approval_payload(recipe_id: str, **overrides) -> dict:
    abv_class = overrides.pop("abv_class", "NON_ALCOHOLIC")
    pasteurized = overrides.pop("pasteurized", False)
    declared = overrides.pop(
        "declared_elements", required_label_elements(abv_class, pasteurized)
    )
    payload = {
        "recipe_id": recipe_id,
        "abv_class": abv_class,
        "pasteurized": pasteurized,
        "declared_elements": list(declared),
    }
    payload.update(overrides)
    return payload


def create_scoby_culture_payload(label: str = "Mother", **overrides) -> dict:
    payload = {"label": label}
    payload.update(overrides)
    return payload


def create_vessel_payload(code: str = "FV-1", **overrides) -> dict:
    payload = {"code": code, "capacity_liters": DEFAULTS["VESSEL_CAPACITY"]}
    payload.update(overrides)
    return payload


def create_ingredient_lot_payload(**overrides) -> dict:
    payload = {
        "ingredient_type": "TEA",
        "supplier_lot_code": "TEA-001",
        "received_on_date": "2026-04-20T00:00:00.000Z",
        "expiry_date": "2027-01-01T00:00:00.000Z",
        "quantity_received": 50.0,
    }
    payload.update(overrides)
    return payload


def create_batch_payload(recipe_id: str, culture_id: str, vessel_id: str, **overrides) -> dict:
    payload = {
        "batch_code": "B-1001",
        "recipe_id": recipe_id,
        "scoby_culture_id": culture_id,
        "vessel_id": vessel_id,
        "pitched_liters": DEFAULTS["PITCHED_LITERS"],
        "planned_f2_days": DEFAULTS["PLANNED_F2_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_qa_reading_payload(**overrides) -> dict:
    payload = {
        "reading_type": "F1",
        "reading_at": "2026-05-03T00:00:00.000Z",
        "ph": 3.80,
        "temperature_c": 24.0,
        "brix": 6.0,
        "abv_pct": 0.10,
    }
    payload.update(overrides)
    return payload


def create_ingredient_use_payload(ingredient_lot_id: str, quantity_used: float) -> dict:
    return {"ingredient_lot_id": ingredient_lot_id, "quantity_used": quantity_used}


def create_packaging_run_payload(recipe_id: str, label_approval_id: str, **overrides) -> dict:
    payload = {
        "run_code": "PR-1",
        "recipe_id": recipe_id,
        "label_approval_id": label_approval_id,
        "format": "BOTTLE",
        "pasteurized": False,
        "max_units_requested": DEFAULTS["MAX_UNITS_REQUESTED"],
    }
    payload.update(overrides)
    return payload


def create_source_draw_payload(batch_id: str, liters_drawn: float, expected_batch_version: int) -> dict:
    return {
        "batch_id": batch_id,
        "liters_drawn": liters_drawn,
        "expected_batch_version": expected_batch_version,
    }


def create_keg_payload(asset_code: str = "KEG-001", **overrides) -> dict:
    payload = {"asset_code": asset_code, "capacity_liters": DEFAULTS["KEG_CAPACITY"]}
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_name": "Harbor Foods",
        "channel": "WHOLESALE_DISTRIBUTOR",
        "credit_limit": DEFAULTS["CREDIT_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(account_id: str, **overrides) -> dict:
    payload = {"account_id": account_id}
    payload.update(overrides)
    return payload


def create_shipment_line_payload(
    finished_lot_id: str, units: int, unit_price: float, expected_finished_lot_version: int
) -> dict:
    return {
        "finished_lot_id": finished_lot_id,
        "units": units,
        "unit_price": unit_price,
        "expected_finished_lot_version": expected_finished_lot_version,
    }


def create_subscription_payload(preferred_recipe_id: str, **overrides) -> dict:
    payload = {
        "subscriber_email": "kai@example.com",
        "subscriber_birth_date": "1990-03-11T00:00:00.000Z",
        "preferred_recipe_id": preferred_recipe_id,
    }
    payload.update(overrides)
    return payload


def create_allocation_payload(
    subscription_id: str, cycle_index: int, expected_finished_lot_version: int, **overrides
) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "cycle_index": cycle_index,
        "expected_finished_lot_version": expected_finished_lot_version,
    }
    payload.update(overrides)
    return payload


def create_taproom_fill_payload(keg_id: str, **overrides) -> dict:
    payload = {
        "keg_id": keg_id,
        "container_type": "GLASS_POUR",
        "requested_liters": 0.5,
    }
    payload.update(overrides)
    return payload


def create_keg_fill_payload(finished_lot_id: str, fill_liters: float = 19.5) -> dict:
    return {"finished_lot_id": finished_lot_id, "fill_liters": fill_liters}


def create_payment_payload(shipment_id: str, amount: float) -> dict:
    return {"shipment_id": shipment_id, "amount": amount}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
