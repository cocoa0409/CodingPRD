"""Payload factories — one per entity/operation, input fields only."""

# A canonical valid 17-character VIN used as the default; tests override as needed.
DEFAULT_VIN = "1HGCM82633A004352"


def create_catalog_part_payload(**overrides) -> dict:
    """POST /catalog-parts — sku, name, wholesale_cost_cents."""
    defaults = {
        "sku": "CP-TEST",
        "name": "Test Part",
        "wholesale_cost_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(**overrides) -> dict:
    """POST /fleet-accounts — company_name, credit_limit_cents, labor_discount_pct."""
    defaults = {
        "company_name": "Test Fleet",
        "credit_limit_cents": 1_000_000,
        "labor_discount_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """POST /customers — email, full_name, home_zone_code, optional fleet_account_id."""
    defaults = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
        "home_zone_code": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_mechanic_payload(**overrides) -> dict:
    """POST /mechanics — full_name, zone_code, skill_tier, labor_rate_cents_per_hour."""
    defaults = {
        "full_name": "Test Mechanic",
        "zone_code": "Z1",
        "skill_tier": "TIER2",
        "labor_rate_cents_per_hour": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(customer_id, **overrides) -> dict:
    """POST /service-requests — customer_id, vehicle_vin, symptom_text, optional severity."""
    defaults = {
        "customer_id": customer_id,
        "vehicle_vin": DEFAULT_VIN,
        "symptom_text": "Test symptom",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    """POST /service-requests/{id}/quotes — diagnosis_text, estimated_labor_hours,
    estimated_parts_cents, labor_rate_cents_per_hour, optional tow_fee_cents."""
    defaults = {
        "diagnosis_text": "Test diagnosis",
        "estimated_labor_hours": 1.0,
        "estimated_parts_cents": 0,
        "labor_rate_cents_per_hour": 9000,
        "tow_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(mechanic_id, expected_service_request_version,
                            routing_mode="ON_SITE",
                            scheduled_start_utc="2026-04-02T09:00:00Z",
                            scheduled_end_utc="2026-04-02T10:00:00Z",
                            **overrides) -> dict:
    """POST /service-requests/{id}/dispatch."""
    defaults = {
        "mechanic_id": mechanic_id,
        "routing_mode": routing_mode,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "expected_service_request_version": expected_service_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(catalog_part_id, quantity=1, **overrides) -> dict:
    """POST /service-requests/{id}/part-lines — catalog_part_id, quantity."""
    defaults = {
        "catalog_part_id": catalog_part_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_finding_payload(job_visit_id, **overrides) -> dict:
    """POST /service-requests/{id}/inspection-findings — job_visit_id, description,
    optional recommended_part_id, recommended_quantity, add_on_labor_hours."""
    defaults = {
        "job_visit_id": job_visit_id,
        "description": "Test finding",
    }
    defaults.update(overrides)
    return defaults


def create_resolve_addons_payload(decisions, **overrides) -> dict:
    """POST /service-requests/{id}/resolve-addons — decisions list."""
    defaults = {"decisions": decisions}
    defaults.update(overrides)
    return defaults


def create_approve_quote_payload(expected_service_request_version, **overrides) -> dict:
    """POST /quotes/{id}/approve — expected_service_request_version."""
    defaults = {"expected_service_request_version": expected_service_request_version}
    defaults.update(overrides)
    return defaults


def create_finish_payload(logged_labor_hours, payment_method="CARD", **overrides) -> dict:
    """POST /job-visits/{id}/finish — logged_labor_hours, payment_method."""
    defaults = {
        "logged_labor_hours": logged_labor_hours,
        "payment_method": payment_method,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(reason_text="Fault recurred", **overrides) -> dict:
    """POST /service-requests/{id}/warranty-claims — reason_text."""
    defaults = {"reason_text": reason_text}
    defaults.update(overrides)
    return defaults


def create_approve_warranty_payload(mechanic_id,
                                    scheduled_start_utc="2026-04-05T09:00:00Z",
                                    scheduled_end_utc="2026-04-05T10:00:00Z",
                                    **overrides) -> dict:
    """POST /warranty-claims/{id}/approve."""
    defaults = {
        "mechanic_id": mechanic_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
    }
    defaults.update(overrides)
    return defaults
