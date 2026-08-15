"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PRODUCTION_TITLE": "Prod A",
    "PRODUCTION_COMPANY": "Co A",
    "CAST_SIZE": 40,
    "UMBRELLA_LIMIT_CENTS": 100_000_000,
    "JURISDICTION_CODE": "LA-CITY",
    "JURISDICTION_NAME": "Los Angeles City",
    "LEAD_TIME_BUSINESS_DAYS": 5,
    "NOTIFICATION_LEAD_CALENDAR_DAYS": 3,
    "NOTIFICATION_RADIUS_FT": 500,
    "BASE_FEE_CENTS": 100_000,
    "PER_DAY_FEE_CENTS": 50_000,
    "PER_LANE_FEE_CENTS": 20_000,
    "LARGE_CAST_THRESHOLD": 50,
    "LARGE_CAST_MULTIPLIER_BPS": 12_500,
    "MIN_LIABILITY_LIMIT_CENTS": 100_000_000,
    "POLICE_MONITOR_LANE_THRESHOLD": 2,
    "OWNER_LEGAL_NAME": "Owner One",
    "OWNER_CONTACT_EMAIL": "owner1@x.com",
    "OWNER_DEFAULT_DAY_RATE_CENTS": 150_000,
    "LOCATION_NAME": "Loc A",
    "LOCATION_ADDRESS": "100 Main St",
    "DEPOSIT_FLOOR_CENTS": 200_000,
    "BUFFER_DAYS": 2,
    "MAX_SHOOT_HOURS_PER_DAY": 14,
    "PHOTO_COUNT": 6,
    "COVERAGE_SCORE_PCT": 80,
    "SCOUT_DATE": "2026-08-01",
    "SHOOT_START_DATE": "2026-08-10",
    "SHOOT_END_DATE": "2026-08-12",
    "PROPOSED_DAY_RATE_CENTS": 150_000,
    "CLOSED_LANES": 0,
    "SHOOT_HOURS_PER_DAY": 8,
    "SHOOT_DATE": "2026-08-10",
    "PLANNED_HOURS": 8,
    "STREET_SEGMENT": "MAIN-ST-100-BLOCK",
    "CLOSURE_START": "2026-08-10T06:00:00Z",
    "CLOSURE_END": "2026-08-10T20:00:00Z",
    "HOUSEHOLDS_REACHED": 40,
    "RADIUS_FT_USED": 500,
    "INSURER_NAME": "InsureCo",
    "INDEMNITY_CLAUSE_REF": "IND-1",
    "CERT_EFFECTIVE_DATE": "2026-08-01",
    "CERT_EXPIRY_DATE": "2026-08-31",
    "MONITOR_TYPE": "FILM_OFFICER",
    "OFFICER_BADGE": "FO-1",
    "HOURS_BOOKED": 8,
    "COMPLAINT_CATEGORY": "NOISE",
    "COMPLAINT_SEVERITY": "LOW",
    "BOOKING_START_DATE": "2026-08-10",
    "BOOKING_END_DATE": "2026-08-12",
}


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PRODUCTION_TITLE"],
        "production_company": DEFAULTS["PRODUCTION_COMPANY"],
        "cast_size": DEFAULTS["CAST_SIZE"],
        "umbrella_liability_limit_cents": DEFAULTS["UMBRELLA_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["JURISDICTION_CODE"],
        "name": DEFAULTS["JURISDICTION_NAME"],
        "lead_time_business_days": DEFAULTS["LEAD_TIME_BUSINESS_DAYS"],
        "notification_lead_calendar_days": DEFAULTS["NOTIFICATION_LEAD_CALENDAR_DAYS"],
        "notification_radius_ft": DEFAULTS["NOTIFICATION_RADIUS_FT"],
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
        "per_day_fee_cents": DEFAULTS["PER_DAY_FEE_CENTS"],
        "per_lane_fee_cents": DEFAULTS["PER_LANE_FEE_CENTS"],
        "large_cast_threshold": DEFAULTS["LARGE_CAST_THRESHOLD"],
        "large_cast_multiplier_bps": DEFAULTS["LARGE_CAST_MULTIPLIER_BPS"],
        "min_liability_limit_cents": DEFAULTS["MIN_LIABILITY_LIMIT_CENTS"],
        "police_monitor_lane_threshold": DEFAULTS["POLICE_MONITOR_LANE_THRESHOLD"],
        "holidays": [],
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["OWNER_LEGAL_NAME"],
        "contact_email": DEFAULTS["OWNER_CONTACT_EMAIL"],
        "default_day_rate_cents": DEFAULTS["OWNER_DEFAULT_DAY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(jurisdiction_id, owner_id, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LOCATION_NAME"],
        "address": DEFAULTS["LOCATION_ADDRESS"],
        "jurisdiction_id": jurisdiction_id,
        "owner_id": owner_id,
        "deposit_floor_cents": DEFAULTS["DEPOSIT_FLOOR_CENTS"],
        "buffer_days": DEFAULTS["BUFFER_DAYS"],
        "max_shoot_hours_per_day": DEFAULTS["MAX_SHOOT_HOURS_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_location_booking_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "booking_start_date": DEFAULTS["BOOKING_START_DATE"],
        "booking_end_date": DEFAULTS["BOOKING_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_scout_package_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "photo_count": DEFAULTS["PHOTO_COUNT"],
        "coverage_score_pct": DEFAULTS["COVERAGE_SCORE_PCT"],
        "scout_date": DEFAULTS["SCOUT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_owner_agreement_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "shoot_start_date": DEFAULTS["SHOOT_START_DATE"],
        "shoot_end_date": DEFAULTS["SHOOT_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_application_payload(location_id, expected_production_version, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "shoot_start_date": DEFAULTS["SHOOT_START_DATE"],
        "shoot_end_date": DEFAULTS["SHOOT_END_DATE"],
        "closed_lanes": DEFAULTS["CLOSED_LANES"],
        "shoot_hours_per_day": DEFAULTS["SHOOT_HOURS_PER_DAY"],
        "expected_production_version": expected_production_version,
    }
    defaults.update(overrides)
    return defaults


def create_street_closure_payload(permit_application_id, **overrides) -> dict:
    defaults = {
        "permit_application_id": permit_application_id,
        "street_segment": DEFAULTS["STREET_SEGMENT"],
        "closure_start": DEFAULTS["CLOSURE_START"],
        "closure_end": DEFAULTS["CLOSURE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(permit_application_id, **overrides) -> dict:
    defaults = {
        "permit_application_id": permit_application_id,
        "households_reached": DEFAULTS["HOUSEHOLDS_REACHED"],
        "radius_ft_used": DEFAULTS["RADIUS_FT_USED"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "insurer_name": DEFAULTS["INSURER_NAME"],
        "umbrella_limit_cents": DEFAULTS["UMBRELLA_LIMIT_CENTS"],
        "indemnity_clause_ref": DEFAULTS["INDEMNITY_CLAUSE_REF"],
        "effective_date": DEFAULTS["CERT_EFFECTIVE_DATE"],
        "expiry_date": DEFAULTS["CERT_EXPIRY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_deposit_account_payload(location_id, **overrides) -> dict:
    defaults = {"location_id": location_id}
    defaults.update(overrides)
    return defaults


def create_walkthrough_report_payload(location_id, kind, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "kind": kind,
        "damage_item_count": 0,
        "damage_claim_cents": 0,
        "signed_by_owner": True,
        "signed_by_manager": True,
    }
    defaults.update(overrides)
    return defaults


def create_monitor_assignment_payload(shoot_day_id, **overrides) -> dict:
    defaults = {
        "shoot_day_id": shoot_day_id,
        "monitor_type": DEFAULTS["MONITOR_TYPE"],
        "officer_badge": DEFAULTS["OFFICER_BADGE"],
        "hours_booked": DEFAULTS["HOURS_BOOKED"],
    }
    defaults.update(overrides)
    return defaults


def create_shoot_day_payload(permit_application_id, location_id, **overrides) -> dict:
    defaults = {
        "permit_application_id": permit_application_id,
        "location_id": location_id,
        "shoot_date": DEFAULTS["SHOOT_DATE"],
        "planned_hours": DEFAULTS["PLANNED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(shoot_day_id, **overrides) -> dict:
    defaults = {
        "shoot_day_id": shoot_day_id,
        "category": DEFAULTS["COMPLAINT_CATEGORY"],
        "severity": DEFAULTS["COMPLAINT_SEVERITY"],
    }
    defaults.update(overrides)
    return defaults
