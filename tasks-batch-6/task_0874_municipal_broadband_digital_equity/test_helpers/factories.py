"""Payload factories — one per entity, input fields only."""


def grant_payload(**overrides) -> dict:
    payload = {
        "funding_source": "BEAD",
        "program_name": "Metro BEAD",
        "award_amount_cents": 100_000_000,
        "match_required_pct": 25,
        "take_rate_milestone_pct": 40,
    }
    payload.update(overrides)
    return payload


def service_area_payload(grant_id, **overrides) -> dict:
    payload = {
        "grant_id": grant_id,
        "name": "Area 1",
        "census_block_group": "010010001001",
        "homes_passed": 100,
    }
    payload.update(overrides)
    return payload


def service_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "STANDARD",
        "name": "Standard 100",
        "download_mbps": 100,
        "upload_mbps": 20,
        "monthly_price_cents": 6000,
        "sla_uptime_pct": 99.5,
    }
    payload.update(overrides)
    return payload


def subsidy_program_payload(**overrides) -> dict:
    payload = {
        "name": "Digital Equity Credit",
        "monthly_discount_cents": 3000,
        "device_benefit_cents": 12000,
        "eligibility_fpl_pct": 200,
    }
    payload.update(overrides)
    return payload


def subscriber_payload(service_area_id, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "full_name": "Jane Doe",
        "email": "jane@x.com",
        "service_address": "1 Main St",
        "household_size": 2,
    }
    payload.update(overrides)
    return payload


def subscription_payload(subscriber_id, plan_id, service_area_id, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "service_area_id": service_area_id,
    }
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> dict:
    payload = {
        "name": "Tec North",
        "region": "North",
    }
    payload.update(overrides)
    return payload


def install_order_payload(subscription_id, technician_id, scheduled_start_at, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "technician_id": technician_id,
        "scheduled_start_at": scheduled_start_at,
    }
    payload.update(overrides)
    return payload


def device_payload(**overrides) -> dict:
    payload = {
        "device_class": "CPE_MODEM",
        "model": "M1",
        "serial_number": "SN-1",
        "value_cents": 5000,
    }
    payload.update(overrides)
    return payload


def enrollment_payload(subscriber_id, subsidy_program_id, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "subsidy_program_id": subsidy_program_id,
        "household_size": 2,
        "annual_income_cents": 3_000_000,
    }
    payload.update(overrides)
    return payload


def outage_payload(service_area_id, started_at, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "started_at": started_at,
        "severity": "FULL",
    }
    payload.update(overrides)
    return payload


def invoice_period_payload(period_start, period_end) -> dict:
    return {"period_start": period_start, "period_end": period_end}


def payment_payload(amount_cents, expected_invoice_version) -> dict:
    return {"amount_cents": amount_cents, "expected_invoice_version": expected_invoice_version}


def grant_claim_payload(claim_period_start, claim_period_end, service_area_ids, expected_grant_version) -> dict:
    return {
        "claim_period_start": claim_period_start,
        "claim_period_end": claim_period_end,
        "service_area_ids": service_area_ids,
        "expected_grant_version": expected_grant_version,
    }
