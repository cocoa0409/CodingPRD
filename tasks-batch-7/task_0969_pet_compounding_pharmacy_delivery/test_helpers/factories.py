"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_owner_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "full_name": f"Test Owner {n}",
        "email": f"owner{n}@example.test",
        "phone": f"555-{n:04d}",
        "ship_to_address": f"{n} Main St",
    }
    defaults.update(overrides)
    return defaults


def create_pet_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Pet{n}",
        "species": "DOG",
        "weight_kg": 6.0,
        "allergies": [],
    }
    defaults.update(overrides)
    return defaults


def create_veterinarian_payload(with_dea: bool = True, **overrides) -> dict:
    n = _uniq()
    payload = {
        "full_name": f"Dr Test {n}",
        "license_number": f"LIC-{n}",
        "practice_state": "CA",
    }
    if with_dea:
        payload["dea_registration_number"] = f"DEA-{n}"
    payload.update(overrides)
    return payload


def create_drug_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "drug_name": f"Drug{n}",
        "schedule": "NON_CONTROLLED",
        "requires_cold_chain": False,
        "unit_cost_cents": 100,
        "default_beyond_use_days": 14,
    }
    defaults.update(overrides)
    return defaults


def create_flavoring_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Flavor{n}",
        "allergen_tags": [],
        "surcharge_cents": 250,
        "compatible_species": ["DOG", "CAT"],
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(drug_catalog_item_id: str, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "drug_catalog_item_id": drug_catalog_item_id,
        "name": f"Formula{n}",
        "dosage_form": "SUSPENSION",
        "strength_mg_per_ml": 25,
        "beyond_use_days": 14,
        "base_compounding_minutes": 45,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(drug_catalog_item_id: str, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "drug_catalog_item_id": drug_catalog_item_id,
        "lot_number": f"LOT-{n}",
        "received_qty": 50,
        "unit_cost_cents": 100,
        "expiration_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_bench_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "bench_code": f"BN-{n}",
        "supports_controlled": True,
    }
    defaults.update(overrides)
    return defaults


def create_cooler_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {"cooler_code": f"CLR-{n}"}
    defaults.update(overrides)
    return defaults


def create_wellness_plan_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Plan{n}",
        "monthly_fee_cents": 2000,
        "included_refill_credits": 5,
        "credit_value_cents": 2000,
        "discount_pct": 0,
        "covers_controlled": False,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(pet_id: str, plan_id: str, expected_owner_version: int,
                              **overrides) -> dict:
    defaults = {
        "pet_id": pet_id,
        "plan_id": plan_id,
        "expected_owner_version": expected_owner_version,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(pet_id: str, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "pet_id": pet_id,
        "insurer_name": "PetSure",
        "policy_number": f"POL-{n}",
        "deductible_cents": 0,
        "coverage_pct": 1.0,
        "annual_limit_cents": 100000,
        "renewal_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(compound_order_id: str, claimed_amount_cents: int,
                         expected_policy_version: int, **overrides) -> dict:
    defaults = {
        "compound_order_id": compound_order_id,
        "claimed_amount_cents": claimed_amount_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(pet_id: str, owner_id: str, veterinarian_id: str,
                                formula_id: str, **overrides) -> dict:
    defaults = {
        "pet_id": pet_id,
        "owner_id": owner_id,
        "veterinarian_id": veterinarian_id,
        "formula_id": formula_id,
        "quantity": 5,
        "days_supply": 5,
        "refills_authorized": 0,
        "directions": "QD",
        "written_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_compound_order_payload(expected_prescription_version: int,
                                  flavoring_id=None, is_refill: bool = False) -> dict:
    payload = {
        "is_refill": is_refill,
        "expected_prescription_version": expected_prescription_version,
    }
    if flavoring_id is not None:
        payload["flavoring_id"] = flavoring_id
    return payload


def create_shipment_payload(cooler_asset_id=None, **overrides) -> dict:
    defaults = {
        "carrier": "PetEx",
        "service_level": "STANDARD",
        "destination_zone": "Z1",
    }
    defaults.update(overrides)
    if cooler_asset_id is not None:
        defaults["cooler_asset_id"] = cooler_asset_id
    return defaults


def create_auto_ship_payload(prescription_id: str, expected_prescription_version: int,
                             **overrides) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "interval_days": 10,
        "next_run_date": "2026-06-01",
        "expected_prescription_version": expected_prescription_version,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "scope": "LOT",
        "reason": f"recall reason {n}",
        "severity": "CLASS_II",
    }
    defaults.update(overrides)
    return defaults


def create_temperature_reading_payload(recorded_at: str, temp_celsius) -> dict:
    return {"recorded_at": recorded_at, "temp_celsius": temp_celsius}
