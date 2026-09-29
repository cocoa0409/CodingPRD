"""Payload factories — one per record type, carrying input fields only.

All money is an integer count of cents; never a string and never a float.
"""

# Canonical values reused across scenarios.
DEFAULTS = {
    "AREA_CODE": "BRW-01",
    "AREA_NAME": "Bear River Wilderness",
    "TOTAL_ALLOCATED_SERVICE_DAYS": 1000,
    "RESERVED_ADMIN_SERVICE_DAYS": 100,
    "SEASON_YEAR": 2027,
    "SEASON_OPEN_DATE": "2027-05-15",
    "SEASON_CLOSE_DATE": "2027-09-30",
    "PARTY_SIZE_MAX": 12,
    "MAX_CLIENTS_PER_GUIDE": 8,
    "MIN_LIABILITY_COVERAGE_CENTS": 100_000_000,
    "OUTFITTER_LEGAL_NAME": "Alpine Outfitters LLC",
    "OUTFITTER_EIN": "410000001",
    "OUTFITTER_EMAIL": "ops@alpine.example",
    "GUIDE_NAME": "Rita Long",
    "CARRIER_NAME": "Summit Mutual",
    "SURETY_NAME": "Cascade Surety",
    "TERM_START_DATE": "2027-01-01",
    "TERM_END_DATE": "2029-12-31",
}


def use_area_payload(**overrides) -> dict:
    payload = {
        "area_code": DEFAULTS["AREA_CODE"],
        "name": DEFAULTS["AREA_NAME"],
        "total_allocated_service_days": DEFAULTS["TOTAL_ALLOCATED_SERVICE_DAYS"],
        "reserved_admin_service_days": DEFAULTS["RESERVED_ADMIN_SERVICE_DAYS"],
        "season_year": DEFAULTS["SEASON_YEAR"],
        "season_open_date": DEFAULTS["SEASON_OPEN_DATE"],
        "season_close_date": DEFAULTS["SEASON_CLOSE_DATE"],
        "party_size_max": DEFAULTS["PARTY_SIZE_MAX"],
        "max_clients_per_guide": DEFAULTS["MAX_CLIENTS_PER_GUIDE"],
        "min_liability_coverage_cents": DEFAULTS["MIN_LIABILITY_COVERAGE_CENTS"],
    }
    payload.update(overrides)
    return payload


def needs_assessment_payload(**overrides) -> dict:
    payload = {
        "assessment_year": DEFAULTS["SEASON_YEAR"],
        "public_need_finding": "NEED_EXISTS",
        "determined_capacity_service_days": 900,
        "allocated_service_days": 0,
    }
    payload.update(overrides)
    return payload


def outfitter_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["OUTFITTER_LEGAL_NAME"],
        "ein": DEFAULTS["OUTFITTER_EIN"],
        "contact_email": DEFAULTS["OUTFITTER_EMAIL"],
        "prequalification_insurance_verified": True,
    }
    payload.update(overrides)
    return payload


def guide_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["GUIDE_NAME"],
        "qualification_level": "LEAD",
        "first_aid_cert_type": "WFR",
        "first_aid_expires_on": "2030-06-30",
        "seasons_experience": 7,
    }
    payload.update(overrides)
    return payload


def certification_payload(**overrides) -> dict:
    payload = {
        "first_aid_cert_type": "WFR",
        "first_aid_expires_on": "2030-06-30",
    }
    payload.update(overrides)
    return payload


def permit_application_payload(outfitter_id, use_area_id, **overrides) -> dict:
    payload = {
        "outfitter_id": outfitter_id,
        "use_area_id": use_area_id,
        "application_type": "NEW",
        "season_year": DEFAULTS["SEASON_YEAR"],
        "requested_service_days": 200,
        "proposed_activity_type": "RIVER_FLOAT",
    }
    payload.update(overrides)
    return payload


def prospectus_payload(use_area_id, needs_assessment_id, **overrides) -> dict:
    payload = {
        "use_area_id": use_area_id,
        "needs_assessment_id": needs_assessment_id,
        "offered_service_days": 150,
        "submission_deadline_date": "2027-03-01",
    }
    payload.update(overrides)
    return payload


def prospectus_response_payload(application_id, **overrides) -> dict:
    payload = {"application_id": application_id}
    payload.update(overrides)
    return payload


def issue_permit_payload(**overrides) -> dict:
    payload = {
        "term_start_date": DEFAULTS["TERM_START_DATE"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
        "fee_schedule_code": "GRADUATED",
        "indemnification_acknowledged": True,
    }
    payload.update(overrides)
    return payload


# --- Operating plan sections -------------------------------------------------

def sanitation_section(**overrides) -> dict:
    body = {
        "human_waste_method": "PORTABLE_TOILET",
        "greywater_method": "STRAINED_AND_SCATTERED",
        "packout_commitment": "ALL_SOLID_WASTE",
    }
    body.update(overrides)
    return body


def campsite_section(**overrides) -> dict:
    body = {
        "designated_sites_only": True,
        "max_nights_per_site": 3,
        "fire_policy": "STOVE_ONLY",
    }
    body.update(overrides)
    return body


def stock_section(**overrides) -> dict:
    body = {
        "stock_type": "HORSE",
        "max_head": 12,
        "feed_source": "CERTIFIED_WEED_FREE_HAY",
        "tie_method": "HIGHLINE",
    }
    body.update(overrides)
    return body


def resource_protection_section(**overrides) -> dict:
    body = {
        "weed_free_certification": True,
        "sensitive_site_avoidance": "MAPPED_BUFFERS",
        "monitoring_commitment": "SEASONAL_PHOTO_POINTS",
    }
    body.update(overrides)
    return body


def operating_plan_payload(plan_year=2027, **overrides) -> dict:
    """A complete four-section plan — every required key present and non-null."""
    payload = {
        "plan_year": plan_year,
        "sanitation_section": sanitation_section(),
        "campsite_section": campsite_section(),
        "stock_section": stock_section(),
        "resource_protection_section": resource_protection_section(),
    }
    payload.update(overrides)
    return payload


def plan_section_payload(section_name, section_body, **overrides) -> dict:
    payload = {"section_name": section_name, "section_body": section_body}
    payload.update(overrides)
    return payload


# --- Evidence of insurance and bonding ---------------------------------------

def insurance_certificate_payload(**overrides) -> dict:
    payload = {
        "coverage_type": "GENERAL_LIABILITY",
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "coverage_amount_cents": DEFAULTS["MIN_LIABILITY_COVERAGE_CENTS"],
        "effective_date": DEFAULTS["TERM_START_DATE"],
        "expiration_date": DEFAULTS["TERM_END_DATE"],
        "additional_insured_endorsed": True,
    }
    payload.update(overrides)
    return payload


def bond_payload(**overrides) -> dict:
    payload = {
        "bond_amount_cents": 1_000_000,
        "surety_name": DEFAULTS["SURETY_NAME"],
        "effective_date": DEFAULTS["TERM_START_DATE"],
        "expiration_date": DEFAULTS["TERM_END_DATE"],
    }
    payload.update(overrides)
    return payload


def guide_authorization_payload(guide_id, **overrides) -> dict:
    payload = {"guide_id": guide_id}
    payload.update(overrides)
    return payload


# --- Actual use and fees -----------------------------------------------------

def trip_use_report_payload(**overrides) -> dict:
    payload = {
        "period_start_date": "2027-06-01",
        "period_end_date": "2027-06-16",
        "service_days_used": 10,
        "client_count": 8,
        "gross_revenue_cents": 2_000_000,
        "allowable_deductions_cents": 0,
    }
    payload.update(overrides)
    return payload


def amend_report_payload(expected_permit_version, **overrides) -> dict:
    payload = {
        "expected_permit_version": expected_permit_version,
        "service_days_used": 10,
        "client_count": 8,
        "gross_revenue_cents": 2_000_000,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# --- Performance and enforcement ---------------------------------------------

def performance_evaluation_payload(evaluation_year=2027, **overrides) -> dict:
    payload = {
        "evaluation_year": evaluation_year,
        "resource_protection_score": 80,
        "client_safety_score": 80,
        "reporting_timeliness_score": 80,
        "fee_compliance_score": 80,
    }
    payload.update(overrides)
    return payload


def noncompliance_action_payload(**overrides) -> dict:
    payload = {
        "severity": "MINOR",
        "action_type": "WARNING",
        "cited_provision": "36 CFR 251.56",
        "cure_deadline_date": "2027-07-31",
    }
    payload.update(overrides)
    return payload
