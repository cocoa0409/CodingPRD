"""Payload factories — one per create endpoint, input fields only.

Only fields the client supplies (source: input) appear here; system- and
computed-source fields are excluded.
"""

DEFAULTS = {
    "PLAN_NAME": "Test Plan",
    "CLINIC_NAME": "Test Clinic",
    "REGION_CODE": "CA",
    "PET_NAME": "Rex",
}


def create_plan_payload(**overrides) -> dict:
    """Plan create body. Required: tier, name, monthly_fee_cents, annual_value_cents.
    Optional with defaults: alacarte_discount_pct (0.0), enrollment_fee_cents (0)."""
    defaults = {
        "tier": "PLUS",
        "name": DEFAULTS["PLAN_NAME"],
        "monthly_fee_cents": 4500,
        "annual_value_cents": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_plan_service_payload(plan_id: str, **overrides) -> dict:
    """PlanService create body. Required: plan_id, service_code, included_quantity, unit_value_cents."""
    defaults = {
        "plan_id": plan_id,
        "service_code": "EXAM",
        "included_quantity": 2,
        "unit_value_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_clinic_payload(**overrides) -> dict:
    """Clinic create body. Required: name, region_code."""
    defaults = {
        "name": DEFAULTS["CLINIC_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_member_account_payload(home_clinic_id: str, email: str, **overrides) -> dict:
    """MemberAccount create body. Required: email, full_name, home_clinic_id."""
    defaults = {
        "email": email,
        "full_name": "Test Member",
        "home_clinic_id": home_clinic_id,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_account_id: str, plan_id: str, **overrides) -> dict:
    """Membership create body. Required: member_account_id, plan_id, billing_anchor_day.
    Optional: auto_renew (defaults true server-side)."""
    defaults = {
        "member_account_id": member_account_id,
        "plan_id": plan_id,
        "billing_anchor_day": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pet_payload(**overrides) -> dict:
    """EnrolledPet create body. Required: name, species, weight_kg."""
    defaults = {
        "name": DEFAULTS["PET_NAME"],
        "species": "DOG",
        "weight_kg": 12,
    }
    defaults.update(overrides)
    return defaults


def plan_change_payload(to_plan_id: str, expected_membership_version: int, **overrides) -> dict:
    """plan-change body. Required: to_plan_id, expected_membership_version."""
    defaults = {
        "to_plan_id": to_plan_id,
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def record_visit_payload(enrolled_pet_id: str, clinic_id: str, service_code: str, **overrides) -> dict:
    """Visit record body. Required: enrolled_pet_id, clinic_id, service_code."""
    defaults = {
        "enrolled_pet_id": enrolled_pet_id,
        "clinic_id": clinic_id,
        "service_code": service_code,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """Clock set body. Required: to_iso8601."""
    return {"to_iso8601": to_iso8601}
