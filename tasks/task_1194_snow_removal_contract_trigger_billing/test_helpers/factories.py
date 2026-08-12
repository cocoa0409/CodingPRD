"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "SITE_NAME": "Test Lot",
    "SITE_ADDRESS": "1 Main St",
    "REGION": "NE",
    "PAVEMENT_AREA_SQFT": 10_000,
    "SEASON_START": "2026-11-01T00:00:00Z",
    "SEASON_END": "2027-03-31T23:59:59Z",
    "TRIGGER_DEPTH_INCHES": 2.0,
    "PER_PUSH_RATE_CENTS": 45_000,
    "HOURLY_RATE_CENTS": 12_000,
    "HOURLY_TIER2_RATE_CENTS": 6_000,
    "SEASONAL_FEE_CENTS": 2_000_000,
    "SEASONAL_PUSH_CAP": 2,
    "SEASONAL_OVERAGE_RATE_CENTS": 40_000,
    "PRIORITY_SEQUENCE": 1,
    "COMPLETION_TARGET_MINUTES": 360,
    "WINDOW_START": "2026-12-10T00:00:00Z",
    "WINDOW_END": "2026-12-10T08:00:00Z",
    "REPORTED_ACCUMULATION_INCHES": 2.0,
    "REPORTED_SOURCE_NAME": "NOAA",
    "VISIT_START": "2026-12-10T09:00:00Z",
    "VISIT_END": "2026-12-10T10:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "name": DEFAULTS["SITE_NAME"],
        "address": DEFAULTS["SITE_ADDRESS"],
        "region_code": DEFAULTS["REGION"],
        "pavement_area_sqft": DEFAULTS["PAVEMENT_AREA_SQFT"],
        "requires_loader": False,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(client_id, contract_type="PER_PUSH", **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "contract_type": contract_type,
        "season_start": DEFAULTS["SEASON_START"],
        "season_end": DEFAULTS["SEASON_END"],
        "require_photo_verification": False,
    }
    if contract_type == "PER_PUSH":
        defaults["per_push_rate_cents"] = DEFAULTS["PER_PUSH_RATE_CENTS"]
    elif contract_type == "HOURLY":
        defaults["hourly_rate_cents"] = DEFAULTS["HOURLY_RATE_CENTS"]
        defaults["hourly_tier2_rate_cents"] = DEFAULTS["HOURLY_TIER2_RATE_CENTS"]
    elif contract_type == "SEASONAL":
        defaults["seasonal_fee_cents"] = DEFAULTS["SEASONAL_FEE_CENTS"]
        defaults["seasonal_push_cap"] = DEFAULTS["SEASONAL_PUSH_CAP"]
        defaults["seasonal_overage_rate_cents"] = DEFAULTS["SEASONAL_OVERAGE_RATE_CENTS"]
    defaults.update(overrides)
    return defaults


def create_contract_site_payload(contract_id, site_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "site_id": site_id,
        "priority_sequence": DEFAULTS["PRIORITY_SEQUENCE"],
        "completion_target_minutes": DEFAULTS["COMPLETION_TARGET_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(contract_id, expected_contract_version, effective_from,
                             **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "expected_contract_version": expected_contract_version,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults


def create_storm_event_payload(**overrides) -> dict:
    defaults = {
        "region_code": DEFAULTS["REGION"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "reported_accumulation_inches": DEFAULTS["REPORTED_ACCUMULATION_INCHES"],
        "reported_source_name": DEFAULTS["REPORTED_SOURCE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_observation_payload(storm_event_id, source_name, observed_at,
                               accumulation_inches, **overrides) -> dict:
    defaults = {
        "storm_event_id": storm_event_id,
        "source_name": source_name,
        "observed_at": observed_at,
        "accumulation_inches": accumulation_inches,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(storm_event_id, contract_site_id, **overrides) -> dict:
    defaults = {
        "storm_event_id": storm_event_id,
        "contract_site_id": contract_site_id,
        "scheduled_start": DEFAULTS["VISIT_START"],
        "scheduled_end": DEFAULTS["VISIT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(visit_id, material_type, quantity_lbs) -> dict:
    return {
        "visit_id": visit_id,
        "material_type": material_type,
        "quantity_lbs": quantity_lbs,
    }


def create_photo_payload(visit_id, phase, image_uri) -> dict:
    return {
        "visit_id": visit_id,
        "phase": phase,
        "image_uri": image_uri,
    }


def create_event_invoice_payload(contract_id, storm_event_id) -> dict:
    return {
        "contract_id": contract_id,
        "kind": "EVENT",
        "storm_event_id": storm_event_id,
    }


def create_period_invoice_payload(contract_id, period_start, period_end) -> dict:
    return {
        "contract_id": contract_id,
        "kind": "PERIOD",
        "period_start": period_start,
        "period_end": period_end,
    }


def create_dispute_payload(invoice_id, visit_id, reason) -> dict:
    return {
        "invoice_id": invoice_id,
        "visit_id": visit_id,
        "reason": reason,
    }


def create_claim_payload(site_id, incident_at, severity, description) -> dict:
    return {
        "site_id": site_id,
        "incident_at": incident_at,
        "severity": severity,
        "description": description,
    }


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Plow LLC",
        "contact_email": "dispatch@plow.example",
        "has_loader": False,
        "has_brine_truck": False,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(storm_event_id, contract_id, subcontractor_id,
                            coverage_start, coverage_end) -> dict:
    return {
        "storm_event_id": storm_event_id,
        "contract_id": contract_id,
        "subcontractor_id": subcontractor_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }


def create_true_up_payload(contract_id, expected_contract_version) -> dict:
    return {
        "contract_id": contract_id,
        "expected_contract_version": expected_contract_version,
    }
