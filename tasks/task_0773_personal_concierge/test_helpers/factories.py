"""Payload factories — one per entity, input fields only."""
import uuid


def unique_email(prefix: str = "member") -> str:
    """A globally unique email so multi-member setups never collide within a test."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


DEFAULTS = {
    "STD_PLAN": {
        "name": "Standard Plan",
        "monthly_retainer_cents": 100000,
        "included_hours": 5,
        "overage_rate_cents_per_hour": 6000,
        "default_markup_pct": 0.10,
        "max_pass_through_cents": 40000,
    },
    "GOLD_PLAN": {
        "name": "Gold Plan",
        "monthly_retainer_cents": 300000,
        "included_hours": 10,
        "overage_rate_cents_per_hour": 8000,
        "default_markup_pct": 0.15,
        "max_pass_through_cents": 50000,
    },
}


def create_member_payload(full_name: str = "Test Member", email: str = None, **overrides) -> dict:
    payload = {"full_name": full_name, "email": email or unique_email()}
    payload.update(overrides)
    return payload


def create_retainer_plan_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["STD_PLAN"])
    payload.update(overrides)
    return payload


def create_membership_payload(plan_id: str, expected_member_version: int,
                              vip_tier: str = "STANDARD", **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "vip_tier": vip_tier,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(name: str = "Test Vendor", category: str = "BOOKING", **overrides) -> dict:
    payload = {"name": name, "category": category}
    payload.update(overrides)
    return payload


def create_service_request_payload(membership_id: str, category: str = "ERRAND",
                                   title: str = "Test request", **overrides) -> dict:
    payload = {"membership_id": membership_id, "category": category, "title": title}
    payload.update(overrides)
    return payload


def accept_payload(scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    payload = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    payload.update(overrides)
    return payload


def create_engagement_payload(vendor_id: str, billing_mode: str, estimated_cost_lines: list,
                              service_start: str, service_end: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "billing_mode": billing_mode,
        "estimated_cost_lines": estimated_cost_lines,
        "service_start": service_start,
        "service_end": service_end,
    }
    payload.update(overrides)
    return payload


def create_time_entry_payload(minutes: int, **overrides) -> dict:
    payload = {"minutes": minutes}
    payload.update(overrides)
    return payload


def create_rating_payload(score: int, **overrides) -> dict:
    payload = {"score": score}
    payload.update(overrides)
    return payload
