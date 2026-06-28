"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """SuretyProgram input fields (PRD §3.1)."""
    defaults = {
        "name": "Test Program",
        "single_limit_cents": TEST_DEFAULTS["SINGLE_LIMIT"],
        "aggregate_limit_cents": TEST_DEFAULTS["AGGREGATE_LIMIT"],
        "referral_threshold_cents": TEST_DEFAULTS["REFERRAL_THRESHOLD"],
        "loss_alert_threshold_cents": TEST_DEFAULTS["LOSS_ALERT_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_principal_payload(**overrides) -> dict:
    """Principal input fields (PRD §3.2)."""
    defaults = {
        "legal_name": "Test Principal",
        "credit_score": 700,
        "working_capital_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_indemnity_agreement_payload(principal_id, **overrides) -> dict:
    """IndemnityAgreement input fields (PRD §3.2)."""
    defaults = {
        "principal_id": principal_id,
        "indemnitor_count": 1,
        "required_signature_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(principal_id, program_id, **overrides) -> dict:
    """BondApplication input fields (PRD §3.3)."""
    defaults = {
        "principal_id": principal_id,
        "program_id": program_id,
        "bond_type": "PERFORMANCE",
        "requested_penal_sum_cents": 5_000_000,
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_bond_payload(application_id, **overrides) -> dict:
    """Bond bind input fields (PRD §3.4)."""
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_claim_payload(bond_id, **overrides) -> dict:
    """Claim input fields (PRD §3.6)."""
    defaults = {
        "bond_id": bond_id,
        "claimant_name": "Test Obligee",
        "demand_cents": 100_000,
        "reserve_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_rider_payload(bond_id, **overrides) -> dict:
    """Rider input fields (PRD §3.5)."""
    defaults = {
        "bond_id": bond_id,
        "rider_type": "NAME_CHANGE",
        "penal_sum_delta_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_treaty_payload(**overrides) -> dict:
    """ReinsuranceTreaty input fields (PRD §3.1)."""
    defaults = {
        "name": "Test Treaty",
        "cession_pct_bps": 3000,
        "treaty_capacity_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_cession_payload(bond_id, treaty_id, **overrides) -> dict:
    """Cession input fields (PRD §3.5)."""
    defaults = {"bond_id": bond_id, "treaty_id": treaty_id}
    defaults.update(overrides)
    return defaults
