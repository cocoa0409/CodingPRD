"""Payload factories — one per writable resource, input fields only.

Field names match the PRD verbatim. Each factory provides sensible defaults
and accepts **overrides for the values a test needs to control.
"""


def create_plan_payload(**overrides) -> dict:
    """Default UNLIMITED plan. Override tier_type/credits for SINGLE_WASH."""
    defaults = {
        "name": "Test Plan",
        "tier_type": "UNLIMITED",
        "monthly_fee_cents": 3000,
        "included_credits": 0,
        "per_credit_price_cents": 0,
        "wash_cooldown_hours": 0,
        "max_addons": 3,
    }
    defaults.update(overrides)
    return defaults


def create_single_wash_plan_payload(**overrides) -> dict:
    """SINGLE_WASH plan default: fee 0, positive credits, cooldown 0."""
    defaults = {
        "name": "Test PayGo Plan",
        "tier_type": "SINGLE_WASH",
        "monthly_fee_cents": 0,
        "included_credits": 2,
        "per_credit_price_cents": 1200,
        "wash_cooldown_hours": 0,
        "max_addons": 0,
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "state_code": "CA",
        "daily_wash_capacity": 50,
        "in_network": True,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "name": "TIRE_SHINE",
        "recurring_fee_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    """INDIVIDUAL account default. For FLEET, override account_type + company_name."""
    defaults = {
        "account_type": "INDIVIDUAL",
        "contact_email": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "FLEET",
        "contact_email": "fleet@example.com",
        "company_name": "Test Fleet Co",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(license_plate="TST001", state_code="CA", **overrides) -> dict:
    defaults = {
        "license_plate": license_plate,
        "state_code": state_code,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(account_id, vehicle_id, plan_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "vehicle_id": vehicle_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def attach_addon_payload(addon_id, expected_membership_version, **overrides) -> dict:
    defaults = {
        "addon_id": addon_id,
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def topup_payload(credit_quantity, expected_membership_version, **overrides) -> dict:
    defaults = {
        "credit_quantity": credit_quantity,
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def change_plan_payload(new_plan_id, add_addon_ids=None, **overrides) -> dict:
    defaults = {"new_plan_id": new_plan_id}
    if add_addon_ids is not None:
        defaults["add_addon_ids"] = add_addon_ids
    defaults.update(overrides)
    return defaults


def freeze_scheduled_payload(start_utc, end_utc, **overrides) -> dict:
    defaults = {
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def adjustment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def wash_event_payload(location_id, license_plate, state_code, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "license_plate": license_plate,
        "state_code": state_code,
    }
    defaults.update(overrides)
    return defaults
