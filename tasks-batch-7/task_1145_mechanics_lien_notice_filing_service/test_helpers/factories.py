"""Payload factories — one per creatable entity, input fields only (PRD §3)."""

DEFAULTS = {
    "COMPANY_NAME": "Test Claimant Co",
    "CONTACT_EMAIL": "billing@example.com",
    "COUNTY": "Kern",
    "PROPERTY_DESCRIPTION": "Lot 1, Tract 1234",
    "CONTRACT_VALUE_CENTS": 500000,
    "SPAN_START": "2026-05-02",
    "SPAN_END": "2026-06-10",
    "PROOF_URL": "https://proof.example.com/doc",
    "COUNSEL_NAME": "Counsel LLP",
}


def create_company_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    """Defaults: CA / COMMERCIAL_PRIVATE, prelim required 20 CALENDAR days,
    90-day filing window, 90-day foreclosure, UNCAPPED, retainage excluded."""
    defaults = {
        "state_code": "CA",
        "project_type": "COMMERCIAL_PRIVATE",
        "prelim_notice_required": True,
        "prelim_days": 20,
        "prelim_day_basis": "CALENDAR",
        "refused_counts_as_served": False,
        "allowed_delivery_methods": ["CERTIFIED_MAIL", "PERSONAL_SERVICE"],
        "filing_window_days": 90,
        "foreclosure_deadline_days": 90,
        "stop_notice_days": 30,
        "bond_claim_days": 45,
        "counts_punch_list": False,
        "retainage_claimable": False,
        "cap_mode": "UNCAPPED",
        "interest_annual_rate": 0.10,
        "bond_pct": 1.25,
        "effective_from": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "state_code": "CA",
        "county": DEFAULTS["COUNTY"],
        "project_type": "COMMERCIAL_PRIVATE",
        "property_legal_description": DEFAULTS["PROPERTY_DESCRIPTION"],
        "contract_value_cents": DEFAULTS["CONTRACT_VALUE_CENTS"],
        "approved_extras_cents": 0,
        "retainage_held_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_party_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "party_role": "OWNER",
        "legal_name": "Owner LLC",
        "address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_furnishing_span_payload(project_id, expected_project_version, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "span_kind": "BASE_CONTRACT",
        "start_date": DEFAULTS["SPAN_START"],
        "end_date": DEFAULTS["SPAN_END"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(project_id, recipient_party_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "recipient_party_id": recipient_party_id,
        "delivery_method": "CERTIFIED_MAIL",
    }
    defaults.update(overrides)
    return defaults


def create_lien_claim_payload(project_id, **overrides) -> dict:
    defaults = {"project_id": project_id}
    defaults.update(overrides)
    return defaults


def create_waiver_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "waiver_type": "UNCONDITIONAL_PROGRESS",
        "amount_cents": 10000,
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "amount_cents": 10000,
        "received_at": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_bonding_request_payload(lien_claim_id, surety_party_id, **overrides) -> dict:
    defaults = {
        "lien_claim_id": lien_claim_id,
        "surety_party_id": surety_party_id,
    }
    defaults.update(overrides)
    return defaults


def create_foreclosure_referral_payload(lien_claim_id, **overrides) -> dict:
    defaults = {
        "lien_claim_id": lien_claim_id,
        "counsel_name": DEFAULTS["COUNSEL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_notice_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "amount_cents": 50000,
        "coverage_start": "2026-06-01",
        "coverage_end": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_bond_claim_payload(project_id, surety_party_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "surety_party_id": surety_party_id,
        "amount_cents": 70000,
    }
    defaults.update(overrides)
    return defaults
