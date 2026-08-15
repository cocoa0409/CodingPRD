"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FUNDRAISER_DISPLAY_NAME": "Officer One",
    "FUNDRAISER_EMAIL": "o1@x.edu",
    "FUNDRAISER_MAX_PROSPECT_COUNT": 10,
    "FUNDRAISER_MAX_OPEN_ASK_CENTS": 100000000,
    "PROSPECT_FULL_NAME": "Donor A",
    "PROSPECT_TYPE": "INDIVIDUAL",
    "PROSPECT_CONTACT_EMAIL": "a@x.com",
    "ASSESSED_CAPACITY_CENTS": 30000000,
    "ENGAGEMENT_SCORE": 80,
    "PHILANTHROPY_SCORE": 70,
    "RECENCY_SCORE": 60,
    "EVIDENCE_TIER": "VERIFIED_DOCUMENT",
    "CAMPAIGN_NAME": "Campaign C",
    "CAMPAIGN_GOAL_CENTS": 50000000,
    "CAMPAIGN_COUNTING_START": "2026-08-01T00:00:00Z",
    "CAMPAIGN_COUNTING_END": "2027-07-31T00:00:00Z",
    "NAMING_NAME": "Waters Hall",
    "NAMING_CATEGORY": "BUILDING",
    "NAMING_PRICE_FLOOR_CENTS": 1500000,
    "RECEIVED_AT": "2026-08-10T00:00:00Z",
    "PAYMENT_METHOD": "WIRE",
}


def create_fundraiser_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["FUNDRAISER_DISPLAY_NAME"],
        "email": DEFAULTS["FUNDRAISER_EMAIL"],
        "max_prospect_count": DEFAULTS["FUNDRAISER_MAX_PROSPECT_COUNT"],
        "max_open_ask_cents": DEFAULTS["FUNDRAISER_MAX_OPEN_ASK_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_prospect_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROSPECT_FULL_NAME"],
        "prospect_type": DEFAULTS["PROSPECT_TYPE"],
        "contact_email": DEFAULTS["PROSPECT_CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "assessed_capacity_cents": DEFAULTS["ASSESSED_CAPACITY_CENTS"],
        "engagement_score": DEFAULTS["ENGAGEMENT_SCORE"],
        "philanthropy_score": DEFAULTS["PHILANTHROPY_SCORE"],
        "recency_score": DEFAULTS["RECENCY_SCORE"],
        "evidence_tier": DEFAULTS["EVIDENCE_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(prospect_id, expected_fundraiser_version) -> dict:
    return {
        "prospect_id": prospect_id,
        "expected_fundraiser_version": expected_fundraiser_version,
    }


def create_proposal_payload(prospect_id, expected_prospect_version, **overrides) -> dict:
    defaults = {
        "prospect_id": prospect_id,
        "proposal_type": "OUTRIGHT",
        "ask_amount_cents": 1000000,
        "designation_purpose": "Programs",
        "expected_prospect_version": expected_prospect_version,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "restriction_type": "UNRESTRICTED",
        "agreement_amount_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "total_amount_cents": 100000,
        "installment_count": 1,
        "frequency": "ANNUAL",
        "first_due_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_write_off_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100,
        "reason": "UNCOLLECTIBLE",
    }
    defaults.update(overrides)
    return defaults


def create_gift_payment_payload(donor_prospect_id, **overrides) -> dict:
    defaults = {
        "donor_prospect_id": donor_prospect_id,
        "amount_cents": 1000,
        "received_at": DEFAULTS["RECEIVED_AT"],
        "payment_method": DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "goal_cents": DEFAULTS["CAMPAIGN_GOAL_CENTS"],
        "counting_start": DEFAULTS["CAMPAIGN_COUNTING_START"],
        "counting_end": DEFAULTS["CAMPAIGN_COUNTING_END"],
    }
    defaults.update(overrides)
    return defaults


def create_naming_opportunity_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["NAMING_NAME"],
        "category": DEFAULTS["NAMING_CATEGORY"],
        "price_floor_cents": DEFAULTS["NAMING_PRICE_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_valuation_payload(**overrides) -> dict:
    defaults = {
        "quarter_end": "2025-09-30T00:00:00Z",
        "value_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100,
        "purpose_note": "probe",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recognition_society_payload(**overrides) -> dict:
    defaults = {
        "name": "Bronze Circle",
        "level": "BRONZE",
        "threshold_cash_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults
