"""Payload factories — one per entity, input fields only (PRD §3).

Each factory takes the caller-controlled required fields as arguments and applies
sensible defaults for the rest; pass **overrides to tune any field.
"""


def create_customer_payload(name="Test Owner", service_address="1 Main St",
                            roofline_feet=200, **overrides):
    payload = {
        "name": name,
        "service_address": service_address,
        "roofline_feet": roofline_feet,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(customer_id, contract_type="SEASONAL_RENTAL",
                            season_year=2026, base_season_fee_cents=50000,
                            early_bird_cutoff="2027-01-01T00:00:00Z", **overrides):
    payload = {
        "customer_id": customer_id,
        "contract_type": contract_type,
        "season_year": season_year,
        "base_season_fee_cents": base_season_fee_cents,
        "early_bird_cutoff": early_bird_cutoff,
    }
    payload.update(overrides)
    return payload


def renew_contract_payload(season_year=2027, base_season_fee_cents=52000,
                           early_bird_cutoff="2027-08-15T00:00:00Z", **overrides):
    payload = {
        "season_year": season_year,
        "base_season_fee_cents": base_season_fee_cents,
        "early_bird_cutoff": early_bird_cutoff,
    }
    payload.update(overrides)
    return payload


def create_estimate_payload(customer_id, product_line="SEASONAL",
                            estimated_footage=120, roofline_complexity="SIMPLE",
                            **overrides):
    payload = {
        "customer_id": customer_id,
        "product_line": product_line,
        "estimated_footage": estimated_footage,
        "roofline_complexity": roofline_complexity,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(name="Crew", home_zone="N", daily_stop_capacity=5, **overrides):
    payload = {
        "name": name,
        "home_zone": home_zone,
        "daily_stop_capacity": daily_stop_capacity,
    }
    payload.update(overrides)
    return payload


def create_route_day_payload(crew_id, service_date="2026-11-01T00:00:00Z",
                             zone="N", max_stops=5, **overrides):
    payload = {
        "crew_id": crew_id,
        "service_date": service_date,
        "zone": zone,
        "max_stops": max_stops,
    }
    payload.update(overrides)
    return payload


def create_route_assignment_payload(route_day_id, job_id, window_start, window_end,
                                    expected_route_day_version, **overrides):
    payload = {
        "route_day_id": route_day_id,
        "job_id": job_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_route_day_version": expected_route_day_version,
    }
    payload.update(overrides)
    return payload


def create_job_payload(contract_id, job_type="INSTALL",
                       scheduled_date="2026-11-01T09:00:00Z", **overrides):
    payload = {
        "contract_id": contract_id,
        "job_type": job_type,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def create_service_call_payload(contract_id, reported_issue="issue",
                                cause="WEATHER", **overrides):
    payload = {
        "contract_id": contract_id,
        "reported_issue": reported_issue,
        "cause": cause,
    }
    payload.update(overrides)
    return payload


def create_storage_bin_payload(bin_code="B-01", warehouse_zone="A", **overrides):
    payload = {
        "bin_code": bin_code,
        "warehouse_zone": warehouse_zone,
    }
    payload.update(overrides)
    return payload


def create_storage_record_payload(contract_id, storage_bin_id, stored_from,
                                  stored_until, **overrides):
    payload = {
        "contract_id": contract_id,
        "storage_bin_id": storage_bin_id,
        "stored_from": stored_from,
        "stored_until": stored_until,
    }
    payload.update(overrides)
    return payload


def create_financing_plan_payload(contract_id, original_principal_cents=1200000,
                                  apr_bps=1000, term_months=12, **overrides):
    payload = {
        "contract_id": contract_id,
        "original_principal_cents": original_principal_cents,
        "apr_bps": apr_bps,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents=110000, **overrides):
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_invoice_payload(customer_id, source_type="MANUAL", line_items=None,
                           **overrides):
    if line_items is None:
        line_items = [{"description": "L1", "amount_cents": 5000, "taxable": False}]
    payload = {
        "customer_id": customer_id,
        "source_type": source_type,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload
