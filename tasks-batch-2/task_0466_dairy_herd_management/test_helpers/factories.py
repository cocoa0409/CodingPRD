"""Payload factories — one per entity, input fields only."""


def create_herd_payload(**overrides) -> dict:
    payload = {"name": "Test Dairy", "federal_order_number": "30"}
    payload.update(overrides)
    return payload


def create_parlor_payload(herd_id, **overrides) -> dict:
    payload = {
        "herd_id": herd_id,
        "name": "North Double-12",
        "stall_capacity": 24,
    }
    payload.update(overrides)
    return payload


def create_ration_payload(herd_id, **overrides) -> dict:
    payload = {
        "herd_id": herd_id,
        "name": "High Group TMR",
        "ingredients": [
            {"ingredient_name": "corn silage", "lbs_as_fed": 55, "price_per_lb": 0.045},
            {"ingredient_name": "alfalfa", "lbs_as_fed": 18, "price_per_lb": 0.125},
            {"ingredient_name": "corn grain", "lbs_as_fed": 21, "price_per_lb": 0.075},
            {"ingredient_name": "protein mix", "lbs_as_fed": 9, "price_per_lb": 0.405},
        ],
    }
    payload.update(overrides)
    return payload


def create_price_sheet_payload(herd_id, settlement_month="2026-06", **overrides) -> dict:
    payload = {
        "herd_id": herd_id,
        "settlement_month": settlement_month,
        "fat_price_per_lb": 2.805,
        "protein_price_per_lb": 3.515,
        "other_solids_price_per_lb": 0.405,
        "ppd_per_cwt": 1.205,
        "advance_rate_per_cwt": 16.00,
        "hauling_rate_per_cwt": 0.85,
    }
    payload.update(overrides)
    return payload


def create_animal_payload(herd_id, ear_tag="A-001", birth_date="2023-01-01", **overrides) -> dict:
    payload = {
        "herd_id": herd_id,
        "ear_tag": ear_tag,
        "birth_date": birth_date,
    }
    payload.update(overrides)
    return payload


def create_test_day_record_payload(lactation_id, test_date, **overrides) -> dict:
    payload = {
        "lactation_id": lactation_id,
        "test_date": test_date,
        "milk_weight_lbs": 85.0,
        "fat_pct": 3.8,
        "protein_pct": 3.1,
        "scc_thousands": 150,
    }
    payload.update(overrides)
    return payload


def create_milking_shift_payload(parlor_id, start_at, end_at, cows_milked=24, **overrides) -> dict:
    payload = {
        "parlor_id": parlor_id,
        "start_at": start_at,
        "end_at": end_at,
        "cows_milked": cows_milked,
    }
    payload.update(overrides)
    return payload


def create_breeding_event_payload(animal_id, service_date, sire_code="S-1", **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "service_date": service_date,
        "sire_code": sire_code,
    }
    payload.update(overrides)
    return payload


def create_calving_event_payload(animal_id, breeding_event_id, calving_date, **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "breeding_event_id": breeding_event_id,
        "calving_date": calving_date,
    }
    payload.update(overrides)
    return payload


def create_health_treatment_payload(animal_id, administered_at, **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "drug_name": "Penicillin",
        "administered_at": administered_at,
        "milk_withhold_hours": 96,
        "meat_withdrawal_hours": 240,
    }
    payload.update(overrides)
    return payload


def create_milk_check_payload(herd_id, price_sheet_id, **overrides) -> dict:
    payload = {
        "herd_id": herd_id,
        "price_sheet_id": price_sheet_id,
    }
    payload.update(overrides)
    return payload


def create_cull_decision_payload(animal_id, reason, disposition, decided_at, **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "reason": reason,
        "disposition": disposition,
        "decided_at": decided_at,
    }
    payload.update(overrides)
    return payload
