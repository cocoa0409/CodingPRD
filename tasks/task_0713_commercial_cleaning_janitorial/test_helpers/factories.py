"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Each factory accepts **overrides so tests
can control the values they care about.
"""

DEFAULTS = {
    "ACCOUNT_NAME": "Test Account",
    "INDUSTRY": "OFFICE",
    "RFP_TITLE": "Test RFP",
    "DUE_AT": "2026-04-01T00:00:00Z",
    "ESTIMATED_TOTAL_SQFT": 4000,
    "SITE_CONTACT_NAME": "Test Contact",
    "AVAIL_START_AT": "2026-03-02T08:00:00Z",
    "AVAIL_END_AT": "2026-03-02T18:00:00Z",
    "SERVICE_AREA_LABEL": "Test Area",
    "SQFT": 4000,
    "SOIL_LEVEL": "LIGHT",
    "FREQUENCY_PER_WEEK": 1,
    "BASE_WAGE_CENTS": 1800,
    "TARGET_MARGIN_PCT": 0.20,
    "LOADING_METHOD": "LOADED",
    "TERM_MONTHS": 12,
    "CREW_NAME": "Test Crew",
    "WEEKLY_CAPACITY_HOURS": 50,
    "ITEM_LABEL": "Test Item",
    "AMOUNT_CENTS": 10000,
    "TOTAL_CENTS": 50000,
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["ACCOUNT_NAME"],
        "industry": DEFAULTS["INDUSTRY"],
    }
    defaults.update(overrides)
    return defaults


def create_rfp_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["RFP_TITLE"],
        "due_at": DEFAULTS["DUE_AT"],
        "estimated_total_sqft": DEFAULTS["ESTIMATED_TOTAL_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_site_contact_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["SITE_CONTACT_NAME"],
        "avail_start_at": DEFAULTS["AVAIL_START_AT"],
        "avail_end_at": DEFAULTS["AVAIL_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_walkthrough_payload(site_contact_id, **overrides) -> dict:
    defaults = {
        "site_contact_id": site_contact_id,
        "start_at": "2026-03-02T09:00:00Z",
        "end_at": "2026-03-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_area_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["SERVICE_AREA_LABEL"],
        "sqft": DEFAULTS["SQFT"],
        "soil_level": DEFAULTS["SOIL_LEVEL"],
        "frequency_per_week": DEFAULTS["FREQUENCY_PER_WEEK"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_estimate_payload(**overrides) -> dict:
    defaults = {
        "base_wage_cents": DEFAULTS["BASE_WAGE_CENTS"],
        "target_margin_pct": DEFAULTS["TARGET_MARGIN_PCT"],
        "loading_method": DEFAULTS["LOADING_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(bid_estimate_id, **overrides) -> dict:
    defaults = {"bid_estimate_id": bid_estimate_id}
    defaults.update(overrides)
    return defaults


def create_contract_payload(proposal_id, **overrides) -> dict:
    defaults = {
        "proposal_id": proposal_id,
        "term_months": DEFAULTS["TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CREW_NAME"],
        "weekly_capacity_hours": DEFAULTS["WEEKLY_CAPACITY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_shift_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "start_at": "2026-03-03T09:00:00Z",
        "end_at": "2026-03-03T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_supply_budget_payload(**overrides) -> dict:
    defaults = {"total_cents": DEFAULTS["TOTAL_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_requisition_payload(**overrides) -> dict:
    defaults = {
        "item_label": DEFAULTS["ITEM_LABEL"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_renewal_cycle_payload(escalation_method="CPI", **overrides) -> dict:
    defaults = {"escalation_method": escalation_method}
    defaults.update(overrides)
    return defaults


def create_upsell_payload(monthly_addon_cents, expected_contract_version,
                          upsell_type="FLOOR", **overrides) -> dict:
    defaults = {
        "upsell_type": upsell_type,
        "monthly_addon_cents": monthly_addon_cents,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults
