"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "OPERATOR_NAME": "Test Operator LLC",
    "COUNTY": "Kern",
    "SOURCE_TYPE": "BOILER",
    "POLLUTANT": "NOX",
    "MAX_HOURLY_RATE_LBS": 50,
    "OPERATING_HOURS_PER_YEAR": 8760,
    "PERMIT_LIMIT_PPM": 100,
    "REPORTING_YEAR": 2025,
    "DUE_AT": "2026-12-31T00:00:00Z",
}


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FACILITY_NAME"],
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "county": DEFAULTS["COUNTY"],
    }
    payload.update(overrides)
    return payload


def create_source_payload(facility_id, expected_facility_version, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "source_type": DEFAULTS["SOURCE_TYPE"],
        "pollutant": DEFAULTS["POLLUTANT"],
        "max_hourly_rate_lbs": DEFAULTS["MAX_HOURLY_RATE_LBS"],
        "operating_hours_per_year": DEFAULTS["OPERATING_HOURS_PER_YEAR"],
        "control_efficiency": 0,
        "permit_limit_ppm": DEFAULTS["PERMIT_LIMIT_PPM"],
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(facility_id, permit_type, **overrides) -> dict:
    payload = {"facility_id": facility_id, "permit_type": permit_type}
    payload.update(overrides)
    return payload


def create_public_notice_payload(permit_id, comment_open_at, comment_close_at, **overrides) -> dict:
    payload = {
        "permit_id": permit_id,
        "comment_open_at": comment_open_at,
        "comment_close_at": comment_close_at,
    }
    payload.update(overrides)
    return payload


def create_inventory_payload(facility_id, reporting_year=None, due_at=None, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "reporting_year": reporting_year if reporting_year is not None else DEFAULTS["REPORTING_YEAR"],
        "due_at": due_at if due_at is not None else DEFAULTS["DUE_AT"],
    }
    payload.update(overrides)
    return payload


def create_line_item_payload(inventory_id, source_id, reported_tons, method="ESTIMATED", **overrides) -> dict:
    payload = {
        "inventory_id": inventory_id,
        "source_id": source_id,
        "method": method,
        "reported_tons": reported_tons,
    }
    payload.update(overrides)
    return payload


def create_stack_test_payload(source_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "source_id": source_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_cem_data_payload(period_start, period_end, avg_concentration_ppm, **overrides) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "avg_concentration_ppm": avg_concentration_ppm,
    }
    payload.update(overrides)
    return payload


def create_exceedance_payload(source_id, detected_at, event_type="EXCEEDANCE", magnitude_pct=0, **overrides) -> dict:
    payload = {
        "source_id": source_id,
        "event_type": event_type,
        "detected_at": detected_at,
        "magnitude_pct": magnitude_pct,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(facility_id, description="Odor complaint", severity="MEDIUM", **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "description": description,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(facility_id, scheduled_start, scheduled_end, complaint_id=None, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    payload.update(overrides)
    return payload


def create_enforcement_action_payload(facility_id, action_type, origin="MANUAL", **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "action_type": action_type,
        "origin": origin,
    }
    payload.update(overrides)
    return payload
