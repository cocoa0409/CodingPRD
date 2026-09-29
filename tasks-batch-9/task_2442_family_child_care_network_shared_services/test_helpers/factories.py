"""Request payload builders with sensible, override-friendly defaults."""

from test_helpers.constants import CLOCK_EPOCH


class _Omit:
    """Sentinel marking a field that must be left out of the request body."""

    def __repr__(self):
        return "OMIT"


OMIT = _Omit()


def _prune(payload):
    """Drop every field whose override asked for omission."""
    return {key: value for key, value in payload.items() if value is not OMIT}


DEFAULTS = {
    "provider_legal_name": "Alvarez Family Child Care",
    "provider_county_tier": "STANDARD",
    "provider_license_number": "FCC-1001",
    "provider_license_expires_on": "2027-06-30T00:00:00Z",
    "provider_capacity_slots": 6,
    "provider_fixed_monthly_cost_cents": 237000,
    "agreement_network_fee_pct": 6.0,
    "agreement_shared_services": ["ENROLLMENT", "BILLING"],
    "agreement_effective_on": CLOCK_EPOCH,
    "enrollment_child_ref": "CH-1",
    "enrollment_family_name": "Alvarez",
    "enrollment_days_per_week": 5,
    "enrollment_start_on": CLOCK_EPOCH,
    "contract_agency_code": "CCDF-01",
    "contract_daily_rate_cents": 4500,
    "contract_contracted_slots": 4,
    "contract_authorized_amount_cents": 5000000,
    "contract_period_start_on": CLOCK_EPOCH,
    "substitute_full_name": "Rosa Nunez",
    "substitute_credential_level": "NONE",
    "substitute_clearance_expires_on": "2026-12-31T00:00:00Z",
    "substitute_hourly_rate_cents": 2000,
    "substitute_service_county_tiers": ["STANDARD"],
    "assignment_reason": "ILLNESS",
    "assignment_min_credential_level": "NONE",
    "visit_focus_area": "ENVIRONMENT",
    "review_severity": "MAJOR",
    "order_category": "SUPPLIES",
}


def clock_payload(instant):
    """Body for the logical clock setter."""
    return {"current_utc": instant}


def create_provider_payload(**overrides):
    """Body for a provider application."""
    payload = {
        "legal_name": DEFAULTS["provider_legal_name"],
        "county_tier": DEFAULTS["provider_county_tier"],
        "license_number": DEFAULTS["provider_license_number"],
        "license_expires_on": DEFAULTS["provider_license_expires_on"],
        "capacity_slots": DEFAULTS["provider_capacity_slots"],
        "fixed_monthly_cost_cents": DEFAULTS["provider_fixed_monthly_cost_cents"],
    }
    payload.update(overrides)
    return _prune(payload)


def create_license_verification_payload(**overrides):
    """Body for the licensing verification result."""
    payload = {
        "license_number": DEFAULTS["provider_license_number"],
        "license_expires_on": DEFAULTS["provider_license_expires_on"],
        "capacity_slots": DEFAULTS["provider_capacity_slots"],
    }
    payload.update(overrides)
    return _prune(payload)


def create_agreement_payload(provider_id, expected_provider_version, **overrides):
    """Body for issuing a membership agreement."""
    payload = {
        "provider_id": provider_id,
        "network_fee_pct": DEFAULTS["agreement_network_fee_pct"],
        "shared_services": list(DEFAULTS["agreement_shared_services"]),
        "effective_on": DEFAULTS["agreement_effective_on"],
        "expected_provider_version": expected_provider_version,
    }
    payload.update(overrides)
    return _prune(payload)


def create_enrollment_payload(provider_id, **overrides):
    """Body for enrolling a child."""
    payload = {
        "provider_id": provider_id,
        "child_ref": DEFAULTS["enrollment_child_ref"],
        "family_name": DEFAULTS["enrollment_family_name"],
        "days_per_week": DEFAULTS["enrollment_days_per_week"],
        "private_monthly_tuition_cents": 0,
        "subsidy_certified": True,
        "start_on": DEFAULTS["enrollment_start_on"],
    }
    payload.update(overrides)
    return _prune(payload)


def create_contract_payload(provider_id, **overrides):
    """Body for registering a subsidy contract."""
    payload = {
        "provider_id": provider_id,
        "agency_code": DEFAULTS["contract_agency_code"],
        "daily_rate_cents": DEFAULTS["contract_daily_rate_cents"],
        "contracted_slots": DEFAULTS["contract_contracted_slots"],
        "authorized_amount_cents": DEFAULTS["contract_authorized_amount_cents"],
        "period_start_on": DEFAULTS["contract_period_start_on"],
    }
    payload.update(overrides)
    return _prune(payload)


def claim_line(enrollment_id, attended_days, absent_days):
    """One attendance line of a subsidy claim."""
    return {
        "enrollment_id": enrollment_id,
        "attended_days": attended_days,
        "absent_days": absent_days,
    }


def create_claim_payload(contract_id, period_month, lines, expected_contract_version, **overrides):
    """Body for drafting a monthly attendance claim."""
    payload = {
        "contract_id": contract_id,
        "period_month": period_month,
        "lines": lines,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return _prune(payload)


def create_remittance_payload(contract_id, agency_reference, amount_cents, **overrides):
    """Body for posting an agency payment."""
    payload = {
        "contract_id": contract_id,
        "agency_reference": agency_reference,
        "amount_cents": amount_cents,
        "received_on": CLOCK_EPOCH,
    }
    payload.update(overrides)
    return _prune(payload)


def meal_line(child_ref, service_date, breakfasts=0, lunches=0, snacks=0):
    """One meal-count line of a food program claim."""
    return {
        "child_ref": child_ref,
        "service_date": service_date,
        "breakfasts": breakfasts,
        "lunches": lunches,
        "snacks": snacks,
    }


def create_food_claim_payload(provider_id, period_month, meal_lines, **overrides):
    """Body for filing a monthly food program claim."""
    payload = {
        "provider_id": provider_id,
        "period_month": period_month,
        "meal_lines": meal_lines,
    }
    payload.update(overrides)
    return _prune(payload)


def create_substitute_payload(**overrides):
    """Body for adding a substitute to the pool."""
    payload = {
        "full_name": DEFAULTS["substitute_full_name"],
        "credential_level": DEFAULTS["substitute_credential_level"],
        "clearance_expires_on": DEFAULTS["substitute_clearance_expires_on"],
        "hourly_rate_cents": DEFAULTS["substitute_hourly_rate_cents"],
        "service_county_tiers": list(DEFAULTS["substitute_service_county_tiers"]),
    }
    payload.update(overrides)
    return _prune(payload)


def create_assignment_payload(provider_id, start_at, end_at, **overrides):
    """Body for requesting substitute coverage."""
    payload = {
        "provider_id": provider_id,
        "start_at": start_at,
        "end_at": end_at,
        "reason": DEFAULTS["assignment_reason"],
        "min_credential_level": DEFAULTS["assignment_min_credential_level"],
    }
    payload.update(overrides)
    return _prune(payload)


def create_visit_payload(provider_id, scheduled_on, **overrides):
    """Body for scheduling a coaching visit."""
    payload = {
        "provider_id": provider_id,
        "scheduled_on": scheduled_on,
        "focus_area": DEFAULTS["visit_focus_area"],
    }
    payload.update(overrides)
    return _prune(payload)


def conduct_visit_payload(visit_conducted_on, observation_score, findings=None, **overrides):
    """Body for recording a coaching observation."""
    payload = {
        "visit_conducted_on": visit_conducted_on,
        "observation_score": observation_score,
        "findings": list(findings) if findings is not None else [],
        "critical_finding": False,
    }
    payload.update(overrides)
    return _prune(payload)


def create_review_payload(provider_id, standard_codes, cap_due_on, **overrides):
    """Body for opening a compliance review."""
    payload = {
        "provider_id": provider_id,
        "standard_codes": list(standard_codes),
        "severity": DEFAULTS["review_severity"],
        "cap_due_on": cap_due_on,
    }
    payload.update(overrides)
    return _prune(payload)


def order_line(sku, unit_price_cents, quantity):
    """One line of a group purchase order."""
    return {"sku": sku, "unit_price_cents": unit_price_cents, "quantity": quantity}


def create_order_payload(provider_id, lines, **overrides):
    """Body for opening a group purchase order."""
    payload = {
        "provider_id": provider_id,
        "category": DEFAULTS["order_category"],
        "lines": lines,
    }
    payload.update(overrides)
    return _prune(payload)
