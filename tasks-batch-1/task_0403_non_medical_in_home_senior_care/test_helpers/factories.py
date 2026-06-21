"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "AGENCY_NAME": "Test Agency",
    "BASE_HOURLY_RATE": 30.00,
    "LIVE_IN_DAY_RATE": 250.00,
    "CAREGIVER_NAME": "CG",
    "CLIENT_NAME": "CL",
    "STATE_CODE": "CA",
    "PLAN_TITLE": "Plan",
}


def create_agency_payload(**overrides) -> dict:
    """Input fields for POST /agencies. base_hourly_rate and live_in_day_rate
    are required; the remaining config fields take documented defaults if omitted."""
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "base_hourly_rate": DEFAULTS["BASE_HOURLY_RATE"],
        "live_in_day_rate": DEFAULTS["LIVE_IN_DAY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": DEFAULTS["CAREGIVER_NAME"],
        "hire_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": DEFAULTS["CLIENT_NAME"],
        "residence_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(**overrides) -> dict:
    defaults = {"title": DEFAULTS["PLAN_TITLE"]}
    defaults.update(overrides)
    return defaults


def create_care_task_payload(category, name, **overrides) -> dict:
    defaults = {"category": category, "name": name}
    defaults.update(overrides)
    return defaults


def create_match_payload(caregiver_id, client_id, **overrides) -> dict:
    defaults = {"caregiver_id": caregiver_id, "client_id": client_id}
    defaults.update(overrides)
    return defaults


def create_visit_payload(caregiver_id, client_id, care_plan_id,
                         billing_mode, scheduled_start, scheduled_end,
                         **overrides) -> dict:
    defaults = {
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "care_plan_id": care_plan_id,
        "billing_mode": billing_mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_mileage_payload(miles, purpose="Errand", **overrides) -> dict:
    defaults = {"miles": miles, "purpose": purpose}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(agency_id, caregiver_id, client_id,
                           period_start, period_end, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(client_id, invoice_id, expected_invoice_version,
                         insurer_name="Ins", policy_number="P1",
                         covered_pct=0.50, daily_benefit_max=500,
                         covered_days=5, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "invoice_id": invoice_id,
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "covered_pct": covered_pct,
        "daily_benefit_max": daily_benefit_max,
        "covered_days": covered_days,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


def clock_event_payload(event_at, **overrides) -> dict:
    defaults = {"event_at": event_at}
    defaults.update(overrides)
    return defaults
