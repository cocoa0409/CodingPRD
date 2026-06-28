"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD: fields with a server-side default
(ServiceType.requires_medical_clearance, ServiceType.active, MembershipPlan.rollover_cap,
MembershipPlan.late_cancel_fee_waived, MembershipPlan.active) are omitted from the base
defaults and supplied only via overrides.
"""

import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="member") -> str:
    """A process-unique email so the unique-email constraint never collides across calls."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_location_payload(**overrides) -> dict:
    defaults = {
        "name": "Austin Lounge",
        "state_code": "TX",
        "timezone": "America/Chicago",
    }
    defaults.update(overrides)
    return defaults


def create_service_type_payload(**overrides) -> dict:
    # code, name, duration_minutes, buffer_minutes, credit_cost are required.
    # requires_medical_clearance and active have server defaults — only set via overrides.
    defaults = {
        "code": "COMPRESSION",
        "name": "Compression",
        "duration_minutes": 30,
        "buffer_minutes": 0,
        "credit_cost": 1,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(service_type_id, **overrides) -> dict:
    defaults = {
        "service_type_id": service_type_id,
        "name": "Room 1",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Tech One",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(location_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_membership_plan_payload(**overrides) -> dict:
    # tier, monthly_fee_cents, monthly_credit_grant required.
    # rollover_cap, late_cancel_fee_waived, active have server defaults.
    defaults = {
        "tier": "BASE",
        "monthly_fee_cents": 9900,
        "monthly_credit_grant": 4,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_location_id, **overrides) -> dict:
    defaults = {
        "home_location_id": home_location_id,
        "email": unique_email(),
        "full_name": "Test Member",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    defaults = {
        "screening_answers": {"heart": False},
        "has_contraindication": False,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_credit_pack_payload(total_credits, is_intro, **overrides) -> dict:
    defaults = {
        "total_credits": total_credits,
        "is_intro": is_intro,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(member_id, location_id, room_id, starts_at,
                           expected_room_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "room_id": room_id,
        "starts_at": starts_at,
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_freeze_payload(freeze_cycles, **overrides) -> dict:
    defaults = {
        "freeze_cycles": freeze_cycles,
    }
    defaults.update(overrides)
    return defaults


def create_upgrade_payload(plan_id, expected_subscription_version, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults
