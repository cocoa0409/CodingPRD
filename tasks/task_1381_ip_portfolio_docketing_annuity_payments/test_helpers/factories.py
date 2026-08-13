"""Payload factories — one per entity, input fields only (PRD §2.5, §3)."""

# Canonical "world W" US rule parameters used across tests (PRD §2.5 fields).
US_RULE_PAYLOAD = {
    "jurisdiction": "US",
    "oa_response_months": 3,
    "max_extensions": 2,
    "extension_months": 1,
    "extension_fee_cents": 20000,
    "annuity_start_year": 3,
    "term_years": 5,
    "surcharge_window_months": 6,
    "surcharge_bps_month_1": 2500,
    "surcharge_bps_late": 5000,
    "small_entity_multiplier_bps": 5000,
    "fee_tier_bounds": "1-3|4-7|8-12|13-20",
    "fee_tier_1_cents": 10000,
    "fee_tier_2_cents": 20000,
    "fee_tier_3_cents": 30000,
    "fee_tier_4_cents": 40000,
    "paris_window_months": 12,
    "pct_window_months": 30,
    "fx_to_usd_cents_bps": 10000,
}

# EP rule used by the dual-variant / per-line-rounding scenarios:
# fx 10255 bps and tier fees 10000/1000/3000 for years 1/2/3.
EP_RULE_PAYLOAD = {
    "jurisdiction": "EP",
    "oa_response_months": 3,
    "max_extensions": 2,
    "extension_months": 1,
    "extension_fee_cents": 20000,
    "annuity_start_year": 1,
    "term_years": 3,
    "surcharge_window_months": 6,
    "surcharge_bps_month_1": 2500,
    "surcharge_bps_late": 5000,
    "small_entity_multiplier_bps": 5000,
    "fee_tier_bounds": "1|2|3|4-20",
    "fee_tier_1_cents": 10000,
    "fee_tier_2_cents": 1000,
    "fee_tier_3_cents": 3000,
    "fee_tier_4_cents": 9999,
    "paris_window_months": 12,
    "pct_window_months": 30,
    "fx_to_usd_cents_bps": 10255,
}

# JP rule for the tiered/small-entity/surcharge combinatorial scenario.
JP_RULE_PAYLOAD = {
    "jurisdiction": "JP",
    "oa_response_months": 3,
    "max_extensions": 2,
    "extension_months": 1,
    "extension_fee_cents": 20000,
    "annuity_start_year": 3,
    "term_years": 4,
    "surcharge_window_months": 6,
    "surcharge_bps_month_1": 2500,
    "surcharge_bps_late": 5000,
    "small_entity_multiplier_bps": 5000,
    "fee_tier_bounds": "1-3|4-7|8-12|13-20",
    "fee_tier_1_cents": 10001,
    "fee_tier_2_cents": 20000,
    "fee_tier_3_cents": 30000,
    "fee_tier_4_cents": 40000,
    "paris_window_months": 12,
    "pct_window_months": 30,
    "fx_to_usd_cents_bps": 10000,
}


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = dict(US_RULE_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {"display_name": "Test Client"}
    defaults.update(overrides)
    return defaults


def create_contact_payload(**overrides) -> dict:
    defaults = {"full_name": "C Approver", "email": "ca@x.com"}
    defaults.update(overrides)
    return defaults


def create_counsel_firm_payload(**overrides) -> dict:
    defaults = {"display_name": "Firm US", "accredited_jurisdictions": ["US"]}
    defaults.update(overrides)
    return defaults


def create_inventor_payload(**overrides) -> dict:
    defaults = {"full_name": "Inv One", "email": "i1@x.com"}
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Family",
        "first_priority_date": "2026-01-15",
        "budget_cap_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction": "US",
        "application_type": "ORIGINAL",
        "filing_date": "2026-02-01",
        "application_number": "US-1",
        "entity_size": "LARGE",
    }
    defaults.update(overrides)
    return defaults


def create_docket_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "STATUTORY",
        "title": "Entry",
        "base_due_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_office_action_payload(**overrides) -> dict:
    defaults = {"action_type": "NON_FINAL_REJECTION", "mail_date": "2026-05-20"}
    defaults.update(overrides)
    return defaults


def create_authorization_payload(amount_cents=10000, expected_version=1, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_annuity_obligation_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def create_instruction_payload(**overrides) -> dict:
    defaults = {
        "instruction_type": "FILING",
        "due_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_abandonment_review_payload(expected_application_version=1, **overrides) -> dict:
    defaults = {
        "rationale": "prune low value",
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "assignee_name": "Assignee Inc",
        "inventor_ids": [],
        "execution_date": "2026-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-08-01",
        "window_end": "2026-09-01",
        "register_entries": [],
    }
    defaults.update(overrides)
    return defaults
