"""Payload factories.  Only request fields the PRD declares as input."""


def account_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Account",
        "billing_jurisdiction_code": "JUR_ALPHA",
        "contact_email": "ap@test.example",
    }
    payload.update(overrides)
    return payload


def property_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "address_line": "1 Test Way",
        "jurisdiction_code": "JUR_ALPHA",
        "distance_miles": 10.0,
        "household_size": 3,
    }
    payload.update(overrides)
    return payload


def well_profile_payload(property_id: str, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "jurisdiction_code": "JUR_ALPHA",
        "well_type": "DRILLED",
        "depth_feet": 200.0,
    }
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Technician",
        "tier": "JOURNEYMAN",
        "home_jurisdiction_code": "JUR_ALPHA",
        "status": "AVAILABLE",
    }
    payload.update(overrides)
    return payload


def part_catalog_item_payload(**overrides) -> dict:
    payload = {
        "part_number": "CTL-TEST",
        "category": "CONTROL",
        "unit_cost_cents": 5000,
        "media_kind": "NONE",
        "on_hand_qty": 10,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def inspection_payload(well_profile_id: str, technician_id: str, **overrides) -> dict:
    payload = {
        "well_profile_id": well_profile_id,
        "technician_id": technician_id,
        "scheduled_for": "2026-06-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def inspection_completion_payload(**overrides) -> dict:
    payload = {
        "measured_yield_gpm": 20.0,
        "static_level_feet": 50.0,
        "observed_drawdown_gallons": 6.0,
    }
    payload.update(overrides)
    return payload


def water_test_payload(well_profile_id: str, technician_id: str, **overrides) -> dict:
    payload = {
        "well_profile_id": well_profile_id,
        "collected_by_technician_id": technician_id,
        "panel_type": "BACTERIOLOGICAL",
        "sample_datetime": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def quote_payload(
    property_id: str, well_profile_id: str, inspection_id: str, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "well_profile_id": well_profile_id,
        "inspection_id": inspection_id,
        "scope": "REPAIR",
        "estimated_labor_minutes": 60,
        "estimated_start_at": "2026-06-03T09:00:00Z",
        "quoted_technician_tier": "JOURNEYMAN",
    }
    payload.update(overrides)
    return payload


def quote_line_payload(part_catalog_item_id: str, quantity: int, version: int) -> dict:
    return {
        "part_catalog_item_id": part_catalog_item_id,
        "quantity": quantity,
        "expected_quote_version": version,
    }


def emergency_ticket_payload(
    property_id: str, well_profile_id: str, account_id: str, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "well_profile_id": well_profile_id,
        "account_id": account_id,
        "reported_outage_hours": 2.0,
    }
    payload.update(overrides)
    return payload


def work_order_payload(
    property_id: str, well_profile_id: str, assigned_technician_id: str, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "well_profile_id": well_profile_id,
        "assigned_technician_id": assigned_technician_id,
        "scope": "REPAIR",
    }
    payload.update(overrides)
    return payload


def permit_payload(well_profile_id: str, **overrides) -> dict:
    payload = {
        "well_profile_id": well_profile_id,
        "jurisdiction_code": "JUR_ALPHA",
        "scope": "PUMP_REPLACEMENT",
        "expedited": False,
        "post_hoc": False,
    }
    payload.update(overrides)
    return payload


def maintenance_plan_payload(well_profile_id: str, account_id: str) -> dict:
    return {"well_profile_id": well_profile_id, "account_id": account_id}


def salt_delivery_payload(delivered_lbs: float, version: int) -> dict:
    return {
        "delivered_lbs": delivered_lbs,
        "expected_maintenance_plan_version": version,
    }


def payment_payload(amount_cents: int, version: int) -> dict:
    return {"amount_cents": amount_cents, "expected_invoice_version": version}


def callback_claim_payload(
    warranty_coverage_id: str, complaint_class: str, description: str
) -> dict:
    return {
        "warranty_coverage_id": warranty_coverage_id,
        "complaint_class": complaint_class,
        "description": description,
    }
