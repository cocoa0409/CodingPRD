"""Payload factories — one per entity, input fields only.

Each factory returns a ready-to-post body with sensible defaults; pass
**overrides to control the values a given test cares about.
"""

DEFAULTS = {
    "PRODUCT_NAME": "MicroMesh",
    "PRODUCT_BASE_RATE": 3000,
    "AVAILABLE_COLORS": ["WHITE", "BRONZE", "BLACK", "COPPER"],
    "PREMIUM_COLORS": ["COPPER"],
    "COLOR_SURCHARGE": 500,
    "REP_NAME": "Rep A",
    "REGION": "NE",
    "CREW_NAME": "Crew C",
    "APPT_START": "2026-06-01T10:00:00Z",
    "APPT_END": "2026-06-01T11:00:00Z",
}


def create_product_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": "LEAF_GUARD",
        "base_rate_cents_per_foot": DEFAULTS["PRODUCT_BASE_RATE"],
        "available_colors": list(DEFAULTS["AVAILABLE_COLORS"]),
        "premium_colors": list(DEFAULTS["PREMIUM_COLORS"]),
        "color_surcharge_cents_per_foot": DEFAULTS["COLOR_SURCHARGE"],
    }
    payload.update(overrides)
    return payload


def create_sales_rep_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["REP_NAME"],
        "region": DEFAULTS["REGION"],
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CREW_NAME"],
        "region": DEFAULTS["REGION"],
        "is_certified_leaf_guard": True,
    }
    payload.update(overrides)
    return payload


def create_lead_payload(sales_rep_id, **overrides) -> dict:
    payload = {
        "full_name": "Homeowner",
        "address": "1 Maple St",
        "phone": "555-0100",
        "region": DEFAULTS["REGION"],
        "sales_rep_id": sales_rep_id,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(lead_id, sales_rep_id, **overrides) -> dict:
    payload = {
        "lead_id": lead_id,
        "sales_rep_id": sales_rep_id,
        "scheduled_start": DEFAULTS["APPT_START"],
        "scheduled_end": DEFAULTS["APPT_END"],
    }
    payload.update(overrides)
    return payload


def create_quote_payload(
    lead_id, appointment_id, sales_rep_id, product_id, color,
    estimated_linear_feet, expected_lead_version, **overrides
) -> dict:
    payload = {
        "lead_id": lead_id,
        "appointment_id": appointment_id,
        "sales_rep_id": sales_rep_id,
        "product_id": product_id,
        "color": color,
        "estimated_linear_feet": estimated_linear_feet,
        "expected_lead_version": expected_lead_version,
    }
    payload.update(overrides)
    return payload


def create_financing_plan_payload(quote_id, plan_type, apr_bps, term_months, **overrides) -> dict:
    payload = {
        "quote_id": quote_id,
        "plan_type": plan_type,
        "apr_bps": apr_bps,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(job_id, issue_type, **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "issue_type": issue_type,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_lead_id, referee_lead_id, **overrides) -> dict:
    payload = {
        "referrer_lead_id": referrer_lead_id,
        "referee_lead_id": referee_lead_id,
    }
    payload.update(overrides)
    return payload
