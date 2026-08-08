"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq():
    return next(_counter)


def create_advisor_payload(**overrides) -> dict:
    """POST /advisors input fields. Ann Reyes / TX-AUS / capacity 3 by default."""
    n = _uniq()
    defaults = {
        "full_name": "Ann Reyes",
        "email": f"advisor{n}@apfm.test",
        "region_code": "TX-AUS",
        "is_va_certified": False,
        "caseload_capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_community_payload(**overrides) -> dict:
    """POST /communities input fields. Cedar Grove / PREFERRED by default."""
    defaults = {
        "name": "Cedar Grove",
        "region_code": "TX-AUS",
        "contract_tier": "PREFERRED",
        "referral_fee_pct": 0.85,
        "tour_slot_capacity": 5,
        "quality_rating": 4.0,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_payload(community_id, **overrides) -> dict:
    """POST /inventories input fields. ASSISTED_LIVING pool of 5 at 500000 by default."""
    defaults = {
        "community_id": community_id,
        "care_level": "ASSISTED_LIVING",
        "total_units": 5,
        "monthly_rate_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    """POST /families input fields. Dana Kim by default."""
    n = _uniq()
    defaults = {
        "primary_contact_name": "Dana Kim",
        "email": f"family{n}@apfm.test",
        "phone": "512-555-0100",
        "relationship_to_senior": "ADULT_CHILD",
        "state_code": "TX",
        "senior_first_name": "Ruth",
        "senior_age": 82,
    }
    defaults.update(overrides)
    return defaults


def create_inquiry_payload(family_id, **overrides) -> dict:
    """POST /inquiries input fields. ASSISTED_LIVING / target 2026-06-20 / budget 520000."""
    defaults = {
        "family_id": family_id,
        "origin": "WEB",
        "region_code": "TX-AUS",
        "requested_care_level": "ASSISTED_LIVING",
        "target_move_in_date": "2026-06-20",
        "declared_budget_monthly_cents": 520000,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(inquiry_id, **overrides) -> dict:
    """POST /assessments input fields. adl6/cog4/mob5, budget 520000, MARRIED, va_eligible."""
    defaults = {
        "inquiry_id": inquiry_id,
        "adl_score": 6,
        "cognitive_score": 4,
        "mobility_score": 5,
        "budget_monthly_cents": 520000,
        "gross_monthly_income_cents": 320000,
        "va_eligible": True,
        "marital_status": "MARRIED",
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(inquiry_id, community_id, **overrides) -> dict:
    """POST /matches input fields."""
    defaults = {
        "inquiry_id": inquiry_id,
        "community_id": community_id,
        "care_level": "ASSISTED_LIVING",
    }
    defaults.update(overrides)
    return defaults


def create_tour_payload(match_id, **overrides) -> dict:
    """POST /tours input fields. A 60-minute IN_PERSON window on 2026-06-05."""
    defaults = {
        "match_id": match_id,
        "scheduled_start": "2026-06-05T15:00:00Z",
        "scheduled_end": "2026-06-05T16:00:00Z",
        "mode": "IN_PERSON",
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(match_id, inventory_id, expected_inventory_version, **overrides) -> dict:
    """POST /placements input fields."""
    defaults = {
        "match_id": match_id,
        "inventory_id": inventory_id,
        "agreed_move_in_date": "2026-06-20",
        "contracted_monthly_rate_cents": 500000,
        "expected_inventory_version": expected_inventory_version,
    }
    defaults.update(overrides)
    return defaults


def create_guidance_payload(inquiry_id, expected_assessment_version, **overrides) -> dict:
    """POST /benefit-guidances input fields."""
    defaults = {
        "inquiry_id": inquiry_id,
        "benefit_type": "VA_AID_ATTENDANCE",
        "expected_assessment_version": expected_assessment_version,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(placement_id, **overrides) -> dict:
    """POST /surveys input fields. nps 9 / care 4 / value 3 -> composite 79.00."""
    defaults = {
        "placement_id": placement_id,
        "nps_score": 9,
        "care_rating": 4,
        "value_rating": 3,
    }
    defaults.update(overrides)
    return defaults
