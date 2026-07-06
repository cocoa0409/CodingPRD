"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DECEDENT_NAME": "Jane Doe",
    "DATE_OF_DEATH": "2026-04-01T00:00:00Z",
    "COUNTY_CODE": "LA",
    "GROSS_FULL": 6_000_000,          # -> FULL supervision
    "GROSS_INDEPENDENT": 300_000,     # -> INDEPENDENT supervision (no bond)
    "SURETY_NAME": "Acme Surety",
}


def create_estate_payload(**overrides) -> dict:
    defaults = {
        "decedent_name": DEFAULTS["DECEDENT_NAME"],
        "date_of_death": DEFAULTS["DATE_OF_DEATH"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "estate_type": "INTESTATE",
        "gross_estate_value_cents": DEFAULTS["GROSS_FULL"],
    }
    defaults.update(overrides)
    return defaults


def create_petition_payload(estate_id, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "petitioner_name": "P",
        "will_lodged": False,
        "nominated_representative_name": "R",
    }
    defaults.update(overrides)
    return defaults


def create_representative_payload(estate_id, petition_id, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "petition_id": petition_id,
        "full_name": "R",
        "representative_user_id": "pr-user-1",
    }
    defaults.update(overrides)
    return defaults


def create_bond_payload(estate_id, representative_id, penal_amount_cents, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "representative_id": representative_id,
        "surety_name": DEFAULTS["SURETY_NAME"],
        "penal_amount_cents": penal_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(estate_id, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "full_name": "Heir",
        "relationship": "CHILD",
        "share_bps": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(estate_id, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "creditor_name": "C",
        "claim_class": "GENERAL",
        "claimed_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(estate_id, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "description": "Asset",
        "asset_class": "CASH",
        "declared_value_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(estate_id, beneficiary_id, proposed_amount_cents, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "beneficiary_id": beneficiary_id,
        "proposed_amount_cents": proposed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_accounting_payload(estate_id, report_type, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "report_type": report_type,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(estate_id, start_at, end_at, **overrides) -> dict:
    defaults = {
        "estate_id": estate_id,
        "hearing_type": "PETITION",
        "courtroom_code": "C1",
        "judge_user_id": "judge-1",
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults
