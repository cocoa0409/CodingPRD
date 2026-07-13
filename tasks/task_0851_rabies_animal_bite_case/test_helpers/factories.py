"""Payload factories — one per entity, input fields only."""


def create_owner_payload(**overrides) -> dict:
    payload = {"full_name": "Test Owner", "phone": "555-0100"}
    payload.update(overrides)
    return payload


def create_animal_payload(**overrides) -> dict:
    payload = {
        "species": "DOG",
        "animal_class": "DOMESTIC",
        "identified": True,
        "vaccination_status": "CURRENT",
    }
    payload.update(overrides)
    return payload


def create_bite_case_payload(**overrides) -> dict:
    payload = {
        "region_code": "RB-GEN",
        "incident_datetime": "2026-03-01T08:00:00Z",
        "exposure_type": "BITE",
        "body_site": "HAND",
        "wound_category": "CATEGORY_II",
        "victim_name": "Test Victim",
        "victim_age": 30,
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": "Test Facility",
        "facility_type": "SHELTER",
        "capacity": 5,
        "daily_boarding_cents": 4000,
    }
    payload.update(overrides)
    return payload


def create_quarantine_order_payload(expected_bite_case_version, animal_id,
                                    order_type="FACILITY", **overrides) -> dict:
    payload = {
        "expected_bite_case_version": expected_bite_case_version,
        "animal_id": animal_id,
        "order_type": order_type,
    }
    payload.update(overrides)
    return payload


def create_specimen_payload(animal_id, **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "collected_datetime": "2026-03-01T09:00:00Z",
        "condition": "SATISFACTORY",
    }
    payload.update(overrides)
    return payload


def create_pep_recommendation_payload(expected_bite_case_version, **overrides) -> dict:
    payload = {"expected_bite_case_version": expected_bite_case_version}
    payload.update(overrides)
    return payload


def create_citation_payload(owner_id, case_id, violations, **overrides) -> dict:
    payload = {"owner_id": owner_id, "case_id": case_id, "violations": list(violations)}
    payload.update(overrides)
    return payload


def create_surveillance_region_payload(region_code, **overrides) -> dict:
    payload = {"region_code": region_code}
    payload.update(overrides)
    return payload


def create_wildlife_report_payload(**overrides) -> dict:
    payload = {
        "species": "BAT",
        "exposure_datetime": "2026-03-01T20:00:00Z",
        "exposure_type": "INDOOR_FOUND_BAT",
    }
    payload.update(overrides)
    return payload
