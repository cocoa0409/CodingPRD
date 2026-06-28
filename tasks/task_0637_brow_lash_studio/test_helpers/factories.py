"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STUDIO_NAME": "Glow",
    "MEMBER_NAME": "Ada",
    "MEMBER_EMAIL": "ada@x.com",
    "TECH_NAME": "Mara",
    "CYCLE_ANCHOR": "2026-01-15T00:00:00Z",
}


def create_studio_payload(**overrides) -> dict:
    """POST /studios — only `name` required; policy knobs default server-side."""
    defaults = {"name": DEFAULTS["STUDIO_NAME"]}
    defaults.update(overrides)
    return defaults


def create_service_type_payload(studio_id, code="FULL_SET", name="Full Set",
                                 duration_minutes=120, base_price_cents=12000,
                                 credit_cost=4, category="PREMIUM", **overrides) -> dict:
    """POST /service-types."""
    defaults = {
        "studio_id": studio_id,
        "code": code,
        "name": name,
        "duration_minutes": duration_minutes,
        "base_price_cents": base_price_cents,
        "credit_cost": credit_cost,
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_membership_plan_payload(studio_id, tier="ESSENTIAL",
                                    monthly_credit_allotment=4, monthly_fee_cents=6900,
                                    **overrides) -> dict:
    """POST /membership-plans."""
    defaults = {
        "studio_id": studio_id,
        "tier": tier,
        "monthly_credit_allotment": monthly_credit_allotment,
        "monthly_fee_cents": monthly_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_lash_tech_payload(studio_id, full_name=DEFAULTS["TECH_NAME"],
                             skill_level=3, station_number=1, **overrides) -> dict:
    """POST /lash-techs."""
    defaults = {
        "studio_id": studio_id,
        "full_name": full_name,
        "skill_level": skill_level,
        "station_number": station_number,
    }
    defaults.update(overrides)
    return defaults


def create_sanitation_log_payload(lash_tech_id, sanitized_at_utc, **overrides) -> dict:
    """POST /sanitation-logs."""
    defaults = {
        "lash_tech_id": lash_tech_id,
        "sanitized_at_utc": sanitized_at_utc,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(studio_id, full_name=DEFAULTS["MEMBER_NAME"],
                          email=DEFAULTS["MEMBER_EMAIL"], **overrides) -> dict:
    """POST /members."""
    defaults = {
        "studio_id": studio_id,
        "full_name": full_name,
        "email": email,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_id, plan_id, cycle_anchor_utc=DEFAULTS["CYCLE_ANCHOR"],
                              **overrides) -> dict:
    """POST /memberships. `initial_credits` optional (defaults to plan allotment)."""
    defaults = {
        "member_id": member_id,
        "plan_id": plan_id,
        "cycle_anchor_utc": cycle_anchor_utc,
    }
    defaults.update(overrides)
    return defaults


def create_patch_test_payload(member_id, administered_utc, consent_signed=True,
                              **overrides) -> dict:
    """POST /patch-tests."""
    defaults = {
        "member_id": member_id,
        "administered_utc": administered_utc,
        "consent_signed": consent_signed,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(member_id, service_type_id, start_utc,
                               pay_with_credits=False, **overrides) -> dict:
    """POST /appointments. Optional: membership_id, expected_membership_version."""
    defaults = {
        "member_id": member_id,
        "service_type_id": service_type_id,
        "start_utc": start_utc,
        "pay_with_credits": pay_with_credits,
    }
    defaults.update(overrides)
    return defaults


def create_retail_order_payload(member_id, appointment_id, lines, **overrides) -> dict:
    """POST /retail-orders. `lines` is a list of {sku, unit_price_cents, quantity}."""
    defaults = {
        "member_id": member_id,
        "appointment_id": appointment_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_recurring_schedule_payload(member_id, service_type_id, cadence_days=14,
                                      first_start_utc="2026-06-15T10:00:00Z", **overrides) -> dict:
    """POST /recurring-schedules."""
    defaults = {
        "member_id": member_id,
        "service_type_id": service_type_id,
        "cadence_days": cadence_days,
        "first_start_utc": first_start_utc,
    }
    defaults.update(overrides)
    return defaults
