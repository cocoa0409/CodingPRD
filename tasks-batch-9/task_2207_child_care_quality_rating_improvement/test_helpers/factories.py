"""Payload factories — one per creating endpoint, input fields only."""
import itertools

from .constants import SUBSCALE_CODES

_license_seq = itertools.count(9001)
_registry_seq = itertools.count(7001)


def next_license_number() -> str:
    return f"LIC-{next(_license_seq)}"


def next_staff_registry_id() -> str:
    return f"REG-{next(_registry_seq)}"


# --- Standard domains -------------------------------------------------------

#: The five-domain configuration used by the canonical rating spine. Weights sum
#: to exactly 1.00, LEARNING_ENVIRONMENT is the observation-linked domain.
CANONICAL_DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 8,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.15,
        "observation_linked": False,
    },
]

DOMAIN_CODES = [d["domain_code"] for d in CANONICAL_DOMAINS]

#: A second five-domain configuration with unequal point ceilings, used where a
#: test needs the weighted total to land on a specific non-round value.
DOMAINS_UNEQUAL_CEILINGS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 20,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.50,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 15,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 12,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 6,
        "weight": 0.10,
        "observation_linked": False,
    },
]


def credential_specs(total_fte, role_type="ASSISTANT", credential_level=1,
                     registry_status="VERIFIED", expires_on="2027-06-30"):
    """Credential specs whose qualifying fte sums to ``total_fte``.

    Each record's fte share is greater than 0 and no greater than 1, so the list
    is a run of whole 1.00 records plus at most one fractional remainder.
    """
    specs = []
    remaining = round(float(total_fte), 2)
    while remaining > 1e-9:
        share = 1.00 if remaining >= 1.00 else round(remaining, 2)
        specs.append(
            {
                "role_type": role_type,
                "credential_level": credential_level,
                "fte": share,
                "registry_status": registry_status,
                "expires_on": expires_on,
            }
        )
        remaining = round(remaining - share, 2)
    return specs


def create_standard_domain_payload(**overrides) -> dict:
    defaults = {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.20,
        "observation_linked": False,
    }
    defaults.update(overrides)
    return defaults


# --- Providers --------------------------------------------------------------


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Sunrise Center",
        "license_number": next_license_number(),
        "county_code": "DANE",
        "region_code": "URBAN",
        "licensed_capacity": 60,
        "active_staff_fte": 1.00,
    }
    defaults.update(overrides)
    return defaults


def create_staff_credential_payload(**overrides) -> dict:
    defaults = {
        "staff_registry_id": next_staff_registry_id(),
        "role_type": "DIRECTOR",
        "credential_level": 4,
        "fte": 1.00,
        "employment_status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def registry_link_payload(**overrides) -> dict:
    defaults = {
        "registry_status": "VERIFIED",
        "verified_on": "2026-07-01",
        "expires_on": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


# --- Rating spine -----------------------------------------------------------


def create_rating_cycle_payload(expected_provider_version, cycle_type="INITIAL", **overrides):
    defaults = {
        "cycle_type": cycle_type,
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults


def documentation_for(domain_codes=None) -> list:
    """One evidence record per domain code, so every domain is documented."""
    codes = list(domain_codes) if domain_codes is not None else list(DOMAIN_CODES)
    evidence_types = ["LESSON_PLAN", "ROSTER", "FAMILY_SURVEY", "POLICY", "TRAINING_LOG"]
    docs = []
    for idx, code in enumerate(codes):
        docs.append(
            {
                "domain_code": code,
                "evidence_type": evidence_types[idx % len(evidence_types)],
                "reference_label": f"{code[:2]}-{idx + 1:02d}",
                "page_count": 4 + idx,
            }
        )
    return docs


def points_map(learning=12, staff=8, family=0, administration=0, child=0) -> dict:
    return {
        "LEARNING_ENVIRONMENT": learning,
        "STAFF_QUALIFICATIONS": staff,
        "FAMILY_PARTNERSHIP": family,
        "ADMINISTRATION": administration,
        "CHILD_ASSESSMENT": child,
    }


def create_self_assessment_payload(claimed=None, documentation=None, **overrides) -> dict:
    defaults = {
        "claimed_points": claimed if claimed is not None else points_map(),
        "documentation": documentation if documentation is not None else documentation_for(),
    }
    defaults.update(overrides)
    return defaults


def verification_approve_payload(verified=None, note="all five domains documented") -> dict:
    return {
        "decision": "APPROVE",
        "verified_points": verified if verified is not None else points_map(),
        "note": note,
    }


def verification_return_payload(note="please resubmit") -> dict:
    return {"decision": "RETURN", "note": note}


# --- Observation ------------------------------------------------------------


def create_observer_payload(**overrides) -> dict:
    defaults = {"full_name": "Lead Observer One", "tool_code": "ERS_EARLY_CHILDHOOD"}
    defaults.update(overrides)
    return defaults


def certify_observer_payload(anchor_agreement_pct=92.00, certified_until="2027-06-30") -> dict:
    return {
        "decision": "CERTIFY",
        "anchor_agreement_pct": anchor_agreement_pct,
        "certified_until": certified_until,
    }


def create_observation_visit_payload(
    lead_observer_id,
    window_start="2026-08-05T09:00:00Z",
    window_end="2026-08-05T13:00:00Z",
    secondary_observer_id=None,
    **overrides,
) -> dict:
    defaults = {
        "lead_observer_id": lead_observer_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    if secondary_observer_id is not None:
        defaults["secondary_observer_id"] = secondary_observer_id
    defaults.update(overrides)
    return defaults


def score_payload(subscale_code, raw_score) -> dict:
    return {"subscale_code": subscale_code, "raw_score": raw_score}


def all_six_scores(raw_score=4.0) -> list:
    return [score_payload(code, raw_score) for code in SUBSCALE_CODES]


# --- Remedies ---------------------------------------------------------------


def create_appeal_payload(grounds="SCORING_ERROR", narrative="The composite is wrong.") -> dict:
    return {"grounds": grounds, "narrative": narrative}


def create_data_dispute_payload(disputed_field="LICENSED_CAPACITY", claimed_value="72") -> dict:
    return {"disputed_field": disputed_field, "claimed_value": claimed_value}


# --- Funding ----------------------------------------------------------------


def create_improvement_grant_payload(
    rating_cycle_id, awarded_amount_cents=1_000_000, spend_deadline="2027-06-30", **overrides
) -> dict:
    defaults = {
        "rating_cycle_id": rating_cycle_id,
        "awarded_amount_cents": awarded_amount_cents,
        "spend_deadline": spend_deadline,
    }
    defaults.update(overrides)
    return defaults


def create_expenditure_payload(
    expected_grant_version,
    category="PROF_DEV",
    amount_cents=100_000,
    invoice_date="2026-09-15",
    **overrides,
) -> dict:
    defaults = {
        "category": category,
        "amount_cents": amount_cents,
        "invoice_date": invoice_date,
        "expected_grant_version": expected_grant_version,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_allocation_payload(
    coach_user_id,
    funding_source="STATE_BASE",
    funding_grant_id=None,
    period_start="2026-09-01",
    period_end="2026-12-31",
    allocated_hours=10.0,
    hourly_rate_cents=10_000,
    **overrides,
) -> dict:
    defaults = {
        "coach_user_id": coach_user_id,
        "funding_source": funding_source,
        "funding_grant_id": funding_grant_id,
        "period_start": period_start,
        "period_end": period_end,
        "allocated_hours": allocated_hours,
        "hourly_rate_cents": hourly_rate_cents,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_session_payload(scheduled_start, scheduled_end) -> dict:
    return {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}


def create_subsidy_claim_payload(
    service_month="2026-09", infant=0, toddler=0, preschool=0, **overrides
) -> dict:
    defaults = {
        "service_month": service_month,
        "child_days": {"INFANT": infant, "TODDLER": toddler, "PRESCHOOL": preschool},
    }
    defaults.update(overrides)
    return defaults
