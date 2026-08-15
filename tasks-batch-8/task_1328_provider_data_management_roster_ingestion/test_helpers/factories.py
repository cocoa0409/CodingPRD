"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "NPI": "1234567893",
    "TIN": "123456789",
    "LOCATION_KEY": "LOC1",
    "FRESHNESS_SLA_DAYS": 90,
    "WINDOW_DAYS": 5,
    "EFFECTIVE_DATE": "2026-01-01",
}


def create_roster_source_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "source_code": f"SRC_{n}",
        "display_name": f"Source {n}",
        "format": "CSV",
        "precedence_rank": 10_000 + n,  # unique per test run; override for rank-specific tests
        "freshness_sla_days": DEFAULTS["FRESHNESS_SLA_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_roster_file_payload(roster_source_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "roster_source_id": roster_source_id,
        "external_file_ref": f"file-{n}",
        "declared_row_count": 0,
        "checksum": f"checksum-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": DEFAULTS["NPI"],
        "tin": DEFAULTS["TIN"],
        "location_key": DEFAULTS["LOCATION_KEY"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_attribute_payload(**overrides) -> dict:
    defaults = {
        "attribute_group": "CONTACT",
        "attribute_key": "phone",
        "attribute_value": "V1",
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_target_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "target_code": "CLAIMS",
        "endpoint_uri": f"sftp://downstream-{n}",
        "required_quality_floor": 0,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_batch_payload(distribution_target_id: str, **overrides) -> dict:
    defaults = {"distribution_target_id": distribution_target_id}
    defaults.update(overrides)
    return defaults


def create_attestation_campaign_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"name": f"Campaign {n}", "window_days": DEFAULTS["WINDOW_DAYS"]}
    defaults.update(overrides)
    return defaults


def create_attestation_request_payload(provider_id: str, **overrides) -> dict:
    defaults = {"provider_id": provider_id}
    defaults.update(overrides)
    return defaults


def create_provider_merge_payload(
    survivor_provider_id: str,
    merged_provider_id: str,
    expected_provider_version,
    **overrides,
) -> dict:
    defaults = {
        "survivor_provider_id": survivor_provider_id,
        "merged_provider_id": merged_provider_id,
        "rationale": "duplicate record",
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults
