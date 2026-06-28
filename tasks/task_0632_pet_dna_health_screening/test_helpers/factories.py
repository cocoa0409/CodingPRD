"""Payload factories — one per entity, input fields only.

Each factory returns the body for a create/transition call. Only fields the
PRD declares as client-supplied input appear here.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="user") -> str:
    """Generate a unique login email (email must be unique across accounts)."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("acct"),
        "full_name": "Test Account",
    }
    defaults.update(overrides)
    return defaults


def create_pet_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "name": "Test Pet",
        "species": "DOG",
        "birth_year": 2020,
    }
    defaults.update(overrides)
    return defaults


def create_kit_payload(account_id, product_tier="BREED", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "product_tier": product_tier,
    }
    defaults.update(overrides)
    return defaults


def activate_kit_payload(pet_id, **overrides) -> dict:
    defaults = {"pet_id": pet_id}
    defaults.update(overrides)
    return defaults


def create_sample_payload(kit_id, **overrides) -> dict:
    defaults = {"kit_id": kit_id}
    defaults.update(overrides)
    return defaults


def create_genotyping_run_payload(call_rate=0.99, het_rate=0.35,
                                  contamination=0.01, **overrides) -> dict:
    defaults = {
        "call_rate": call_rate,
        "het_rate": het_rate,
        "contamination": contamination,
    }
    defaults.update(overrides)
    return defaults


def pass_run_payload(breed_segments=None, **overrides) -> dict:
    """A run payload that yields outcome PASS (0.99/0.35/0.01 -> qc 99.10)."""
    if breed_segments is None:
        breed_segments = [{"breed": "LABRADOR", "match_cm": 1000}]
    return create_genotyping_run_payload(breed_segments=breed_segments, **overrides)


def create_marker_payload(marker_code="MDR1", genotype="AT_RISK", **overrides) -> dict:
    defaults = {
        "marker_code": marker_code,
        "genotype": genotype,
    }
    defaults.update(overrides)
    return defaults


def finalize_report_payload(expected_report_version, **overrides) -> dict:
    defaults = {"expected_report_version": expected_report_version}
    defaults.update(overrides)
    return defaults


def create_share_link_payload(report_id, vet_email="vet@example.com", **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "vet_email": vet_email,
    }
    defaults.update(overrides)
    return defaults


def create_relative_match_payload(pet_id, relative_pet_id, shared_cm=600, **overrides) -> dict:
    defaults = {
        "pet_id": pet_id,
        "relative_pet_id": relative_pet_id,
        "shared_cm": shared_cm,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(account_id, tier="BASIC", annual_fee_cents=9900,
                                **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "tier": tier,
        "annual_fee_cents": annual_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def upgrade_subscription_payload(expected_subscription_version, **overrides) -> dict:
    defaults = {"expected_subscription_version": expected_subscription_version}
    defaults.update(overrides)
    return defaults


def create_data_request_payload(account_id, kind="DOWNLOAD", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def create_marker_catalog_payload(marker_code="MDR1", category="HEALTH",
                                  species="DOG", **overrides) -> dict:
    defaults = {
        "marker_code": marker_code,
        "category": category,
        "species": species,
    }
    defaults.update(overrides)
    return defaults
