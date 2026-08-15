"""Payload factories — one per entity, input fields only."""
import uuid


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": f"Facility-{_tag()}",
        "cms_certification_number": f"CCN-{_tag()}",
        "bed_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Payer-{_tag()}",
        "payer_type": "COMMERCIAL",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(facility_id, payer_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "payer_id": payer_id,
        "confidentiality_clause": "DISCLOSE_ALLOWED",
        "annual_volume": 100,
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_item_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "code": f"C{_tag()}".upper(),
        "code_type": "CPT",
        "description": "Test service",
        "service_class": "SHOPPABLE",
        "gross_charge_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_rate_payload(contract_id, service_item_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "service_item_id": service_item_id,
        "rate_type": "PERCENT_OF_GROSS",
        "rate_percent": 40,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "cycle_type": "MONTHLY",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "schema_version": "v2.0.0",
    }
    defaults.update(overrides)
    return defaults


def create_charge_record_payload(facility_id, publication_cycle_id,
                                 service_item_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "publication_cycle_id": publication_cycle_id,
        "service_item_id": service_item_id,
        "discounted_cash_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_machine_file_payload(publication_cycle_id,
                                expected_publication_cycle_version,
                                **overrides) -> dict:
    defaults = {
        "publication_cycle_id": publication_cycle_id,
        "file_format": "JSON",
        "expected_publication_cycle_version":
            expected_publication_cycle_version,
    }
    defaults.update(overrides)
    return defaults


def shoppable_entry(service_item_id, **overrides) -> dict:
    defaults = {
        "service_item_id": service_item_id,
        "display_name": "Service",
        "bundled_ancillary_item_ids": [],
        "include_conditional_ancillaries": False,
        "display_order": 1,
    }
    defaults.update(overrides)
    return defaults


def create_shoppable_list_payload(facility_id, entries, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "title": f"List-{_tag()}",
        "entries": entries,
    }
    defaults.update(overrides)
    return defaults


def create_discrepancy_payload(publication_cycle_id, standard_charge_record_id,
                               **overrides) -> dict:
    defaults = {
        "publication_cycle_id": publication_cycle_id,
        "standard_charge_record_id": standard_charge_record_id,
        "reporter_type": "CONSUMER",
        "description": "Reported discrepancy",
    }
    defaults.update(overrides)
    return defaults
