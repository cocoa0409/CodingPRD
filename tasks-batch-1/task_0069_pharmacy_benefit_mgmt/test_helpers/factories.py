"""Payload factories — one per entity, input fields only (PRD §3)."""

STANDARD_TIER_COPAY = {"TIER_1": 1000, "TIER_2": 3500, "TIER_3": 7000, "SPECIALTY": 25000}


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Plan",
        "plan_year": 2026,
        "deductible_cents": 50000,
        "oop_max_cents": 200000,
        "tier_copay_cents": dict(STANDARD_TIER_COPAY),
    }
    defaults.update(overrides)
    return defaults


def create_formulary_drug_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "ndc": "NDC-001",
        "drug_name": "Test Drug",
        "tier": "TIER_2",
        "ingredient_cost_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_step_therapy_protocol_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "name": "Test Protocol",
        "first_line_ndcs": ["FL1"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(plan_id, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "full_name": "Test Member"}
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(member_id, formulary_drug_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "formulary_drug_id": formulary_drug_id,
        "authorized_fills": 1,
        "valid_through_date": "2026-12-31T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(member_id, formulary_drug_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "formulary_drug_id": formulary_drug_id,
        "days_supply": 30,
        "pharmacy_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_copay_card_payload(member_id, formulary_drug_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "formulary_drug_id": formulary_drug_id,
        "max_benefit_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_rebate_agreement_payload(plan_id, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "manufacturer_name": "Acme"}
    defaults.update(overrides)
    return defaults
