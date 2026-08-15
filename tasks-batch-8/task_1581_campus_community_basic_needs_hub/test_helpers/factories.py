"""Payload factories — input fields only (PRD §3)."""

DEFAULTS = {
    "STAFF_NAME": "Test Staff",
    "ALIAS": "test-alias",
    "CONTACT_CHANNEL": "EMAIL",
    "POPULATION_TYPE": "COMMUNITY_RESIDENT",
    "HOUSEHOLD_SIZE": 1,
    "MONTHLY_INCOME_CENTS": 50000,
    "HOUSING_STATUS": "STABLE",
    "FOOD_INSECURITY_SCORE": 1,
    "ITEM_NAME": "Test Item",
    "POINT_COST": 10,
    "QUANTITY_ON_HAND": 10,
    "REORDER_THRESHOLD": 0,
    "PER_VISIT_LIMIT": 5,
    "FUND_NAME": "Test Fund",
    "FISCAL_YEAR": 2026,
    "ALLOCATED_CENTS": 500000,
    "REQUESTED_CENTS": 50000,
    "HARDSHIP_STATEMENT": "test hardship",
    "AGENCY_NAME": "Test Agency",
    "WEEKLY_CAPACITY": 5,
    "BED_SITE": "Haven",
    "BED_LABEL": "B1",
    "EVENT_TITLE": "Test Event",
    "EVENT_DATE": "2026-08-20T10:00:00Z",
    "EVENT_CAPACITY": 3,
    "STIGMA_THEME": "NORMALIZATION",
    "SERVICE_CATEGORY": "SNAP_APPLICATION",
}


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STAFF_NAME"],
        "email": "staff@hub.test",
        "staff_role": "INTAKE_COORDINATOR",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "alias_name": DEFAULTS["ALIAS"],
        "contact_channel": DEFAULTS["CONTACT_CHANNEL"],
        "population_type": DEFAULTS["POPULATION_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "monthly_income_cents": DEFAULTS["MONTHLY_INCOME_CENTS"],
        "housing_status": DEFAULTS["HOUSING_STATUS"],
        "dependents_under_18": 0,
        "receives_snap": False,
        "receives_childcare_subsidy": False,
        "food_insecurity_score": DEFAULTS["FOOD_INSECURITY_SCORE"],
        "consent_confidential": True,
    }
    defaults.update(overrides)
    return defaults


def create_pantry_item_payload(**overrides) -> dict:
    defaults = {
        "item_name": DEFAULTS["ITEM_NAME"],
        "category": "SHELF_STABLE",
        "point_cost": DEFAULTS["POINT_COST"],
        "quantity_on_hand": DEFAULTS["QUANTITY_ON_HAND"],
        "reorder_threshold": DEFAULTS["REORDER_THRESHOLD"],
        "per_visit_limit": DEFAULTS["PER_VISIT_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(item_id, quantity=1, **overrides) -> dict:
    defaults = {"item_id": item_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_screening_payload(program="SNAP", **overrides) -> dict:
    defaults = {"program": program}
    defaults.update(overrides)
    return defaults


def create_grant_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": DEFAULTS["FUND_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "allocated_cents": DEFAULTS["ALLOCATED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_application_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "category": "RENT",
        "requested_cents": DEFAULTS["REQUESTED_CENTS"],
        "hardship_statement": DEFAULTS["HARDSHIP_STATEMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_shelter_bed_payload(**overrides) -> dict:
    defaults = {
        "shelter_site": DEFAULTS["BED_SITE"],
        "bed_label": DEFAULTS["BED_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_shelter_stay_payload(bed_id, **overrides) -> dict:
    defaults = {
        "bed_id": bed_id,
        "check_in_date": "2026-08-10",
        "planned_nights": 2,
    }
    defaults.update(overrides)
    return defaults


def create_partner_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "service_categories": [DEFAULTS["SERVICE_CATEGORY"]],
        "weekly_capacity": DEFAULTS["WEEKLY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "service_category": DEFAULTS["SERVICE_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_outreach_event_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["EVENT_TITLE"],
        "event_date": DEFAULTS["EVENT_DATE"],
        "capacity": DEFAULTS["EVENT_CAPACITY"],
        "stigma_theme": DEFAULTS["STIGMA_THEME"],
    }
    defaults.update(overrides)
    return defaults


def create_event_registration_payload(client_id, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults
