"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _uniq(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def client_payload(**overrides) -> dict:
    d = {"name": "Test Client", "client_type": "INSTITUTION", "billing_email": "ap@test.example"}
    d.update(overrides)
    return d


def vault_payload(**overrides) -> dict:
    d = {"name": "Test Vault", "climate_class": "AMBIENT", "capacity_slots": 5}
    d.update(overrides)
    return d


def artwork_payload(client_id, **overrides) -> dict:
    d = {
        "client_id": client_id, "title": "Test Work", "artist": "Test Artist",
        "size_class": "MEDIUM", "fragility_class": "MEDIUM", "climate_class": "AMBIENT",
    }
    d.update(overrides)
    return d


def placement_payload(artwork_id, vault_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "vault_id": vault_id,
        "start_at": "2026-05-01T00:00:00Z", "scheduled_end_at": "2026-06-01T00:00:00Z",
    }
    d.update(overrides)
    return d


def condition_report_payload(artwork_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "report_type": "PERIODIC",
        "condition_grade": "A", "damage_noted": False, "notes": "routine",
    }
    d.update(overrides)
    return d


def appraisal_payload(artwork_id, expected_artwork_version, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "method": "FAIR_MARKET",
        "comparable_base_cents": 1000000, "appraiser_name": "Test Appraiser",
        "expected_artwork_version": expected_artwork_version,
    }
    d.update(overrides)
    return d


def policy_payload(artwork_id, expected_artwork_version, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "coverage_type": "ALL_RISK",
        "insured_value_cents": 1000000,
        "effective_start": "2026-05-01T00:00:00Z", "effective_end": "2027-05-01T00:00:00Z",
        "expected_artwork_version": expected_artwork_version,
    }
    d.update(overrides)
    return d


def crate_payload(artwork_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "crate_type": "HARD",
        "internal_length_cm": 100, "internal_width_cm": 70, "internal_height_cm": 12,
    }
    d.update(overrides)
    return d


def crew_payload(**overrides) -> dict:
    d = {"name": "Test Crew", "crew_size": 3, "certification_level": "FINE_ART"}
    d.update(overrides)
    return d


def transport_job_payload(artwork_id, crate_id, crew_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "crate_id": crate_id, "crew_id": crew_id,
        "origin_location": "Warehouse", "destination_location": "Gallery",
        "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T11:00:00Z",
        "requires_rigging": False, "estimated_hours": 2,
    }
    d.update(overrides)
    return d


def loan_payload(artwork_id, client_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "client_id": client_id,
        "borrower_name": "City Museum", "exhibition_name": "Exhibition",
        "loan_start": "2026-06-01T00:00:00Z", "loan_end": "2026-07-01T00:00:00Z",
        "is_international": False, "required_value_cents": 1000000,
    }
    d.update(overrides)
    return d


def carnet_payload(loan_id, **overrides) -> dict:
    d = {
        "loan_id": loan_id, "carnet_number": _uniq("ATA"), "countries": ["US", "FR"],
        "validity_start": "2026-05-01T00:00:00Z", "validity_end": "2026-12-01T00:00:00Z",
    }
    d.update(overrides)
    return d


def viewing_room_payload(**overrides) -> dict:
    d = {"name": "Salon", "capacity_persons": 4}
    d.update(overrides)
    return d


def viewing_booking_payload(artwork_id, viewing_room_id, client_id, **overrides) -> dict:
    d = {
        "artwork_id": artwork_id, "viewing_room_id": viewing_room_id, "client_id": client_id,
        "scheduled_start": "2026-05-02T14:00:00Z", "scheduled_end": "2026-05-02T15:00:00Z",
    }
    d.update(overrides)
    return d


def invoice_payload(client_id, **overrides) -> dict:
    d = {
        "client_id": client_id,
        "billing_period_start": "2026-05-01T00:00:00Z",
        "billing_period_end": "2026-05-31T00:00:00Z",
    }
    d.update(overrides)
    return d
