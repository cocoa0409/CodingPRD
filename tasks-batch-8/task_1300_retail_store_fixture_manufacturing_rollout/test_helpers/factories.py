"""Payload factories — one per entity, input fields only.

Optional fields are omitted entirely when not supplied, so tests exercise the
PRD's documented defaults.
"""

DEFAULT_BOM_LINES = [
    {"part_number": "PN-600", "quantity": 1, "list_unit_cost_cents": 3000},
]
DEFAULT_CONFIG_LINES = [
    {"part_number": "PN-600", "quantity": 10, "unit_cost_cents": 1000},
]


def create_rollout_program_payload(program_name="P-1", retailer_code="RTL-1",
                                   budget_total_cents=1_000_000,
                                   contingency_budget_cents=100_000,
                                   **overrides):
    payload = {
        "program_name": program_name,
        "retailer_code": retailer_code,
        "budget_total_cents": budget_total_cents,
        "contingency_budget_cents": contingency_budget_cents,
    }
    payload.update(overrides)
    return payload


def create_fixture_prototype_payload(program_id, fixture_code="GONDOLA-4FT",
                                     bom_lines=None, target_cost_cents=999_999,
                                     **overrides):
    payload = {
        "program_id": program_id,
        "fixture_code": fixture_code,
        "bom_lines": list(bom_lines) if bom_lines is not None
        else [dict(line) for line in DEFAULT_BOM_LINES],
        "target_cost_cents": target_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_store_kit_config_payload(program_id, prototype_id,
                                    store_code="STORE-0001", config_lines=None,
                                    **overrides):
    payload = {
        "program_id": program_id,
        "prototype_id": prototype_id,
        "store_code": store_code,
    }
    if config_lines is not None:
        payload["config_lines"] = [dict(line) for line in config_lines]
    payload.update(overrides)
    return payload


def create_production_wave_payload(program_id, wave_label="WAVE-1",
                                   start_date="2026-09-01",
                                   end_date="2026-09-10", capacity_units=100,
                                   **overrides):
    payload = {
        "program_id": program_id,
        "wave_label": wave_label,
        "start_date": start_date,
        "end_date": end_date,
        "capacity_units": capacity_units,
    }
    payload.update(overrides)
    return payload


def create_staging_reservation_payload(kit_id, staging_bay_code="BAY-1",
                                       start_ts="2026-09-05T10:00:00Z",
                                       end_ts="2026-09-05T12:00:00Z",
                                       **overrides):
    payload = {
        "kit_id": kit_id,
        "staging_bay_code": staging_bay_code,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }
    payload.update(overrides)
    return payload


def create_install_delivery_payload(kit_id, crew_code="CREW-1",
                                    delivery_date="2026-09-12",
                                    estimated_install_hours=4, **overrides):
    payload = {
        "kit_id": kit_id,
        "crew_code": crew_code,
        "delivery_date": delivery_date,
        "estimated_install_hours": estimated_install_hours,
    }
    payload.update(overrides)
    return payload


def create_damage_claim_payload(delivery_id, part_number="PN-600",
                                claim_type="DAMAGED",
                                replacement_component_count=1,
                                replacement_cost_cents=100, **overrides):
    payload = {
        "delivery_id": delivery_id,
        "part_number": part_number,
        "claim_type": claim_type,
        "replacement_component_count": replacement_component_count,
        "replacement_cost_cents": replacement_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_install_signoff_payload(delivery_id, photo_urls=None, notes=None,
                                   **overrides):
    payload = {
        "delivery_id": delivery_id,
        "photo_urls": list(photo_urls) if photo_urls is not None
        else ["https://photos/evidence-1.jpg"],
    }
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload
