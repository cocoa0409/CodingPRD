"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides for the values
a test needs to control. Only fields the PRD lists as client-supplied input are
included; system/computed fields are never sent.
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


# ---------------------------------------------------------------------------
# MembershipTier (PRD §3.1) — only billing_mode is required besides code/name.
# All commercial parameters are optional with neutral defaults.
# ---------------------------------------------------------------------------
def create_tier_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("TIER"),
        "name": "Test Tier",
        "billing_mode": "MONTHLY",
        "monthly_fee_cents": 0,
        "daypass_fee_cents": 0,
        "discount_bps": 1000,
        "prepaid_machine_minutes": 0,
        "locker_free_liters": 50,
        "unsupervised_allowed": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Member (PRD §3.2) — email, full_name, tier_id all required.
# ---------------------------------------------------------------------------
def create_member_payload(tier_id, **overrides) -> dict:
    defaults = {
        "email": _uniq("m") + "@x.com",
        "full_name": "Test Member",
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Machine (PRD §3.1) — name, machine_class, hourly_rate_cents required.
# ---------------------------------------------------------------------------
def create_machine_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Machine",
        "machine_class": "LASER",
        "hourly_rate_cents": 4800,
        "setup_fee_cents": 500,
        "min_billing_minutes": 30,
        "cooldown_minutes": 15,
        "requires_certification": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Certification (PRD §3.4) — member_id, machine_class required.
# ---------------------------------------------------------------------------
def create_certification_payload(member_id, machine_class="LASER", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "machine_class": machine_class,
        "orientation_complete": True,
        "supervised_minutes": 240,
        "required_supervised_minutes": 240,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Reservation (PRD §3.5) — member_id, machine_id, start_at, end_at,
# supervision_mode required; certification_id optional.
# ---------------------------------------------------------------------------
def create_reservation_payload(
    member_id, machine_id, start_at, end_at, supervision_mode="SUPERVISED", **overrides
) -> dict:
    defaults = {
        "member_id": member_id,
        "machine_id": machine_id,
        "start_at": start_at,
        "end_at": end_at,
        "supervision_mode": supervision_mode,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Locker (PRD §3.7) — member_id, label, capacity_liters, expected_member_version
# required; used_liters optional (default 0).
# ---------------------------------------------------------------------------
def create_locker_payload(
    member_id, expected_member_version, capacity_liters=100, **overrides
) -> dict:
    defaults = {
        "member_id": member_id,
        "label": _uniq("L"),
        "capacity_liters": capacity_liters,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# MaterialItem (PRD §3.1) — sku, name, unit_price_cents required.
# ---------------------------------------------------------------------------
def create_material_item_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Material",
        "unit_price_cents": 100,
        "stock_qty": 100,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# MaterialPurchase (PRD §3.8) — member_id, lines required.
# ---------------------------------------------------------------------------
def create_material_purchase_payload(member_id, lines, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "lines": lines,
        "waste_surcharge_bps": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Workshop (PRD §3.9) — title, instructor_id, starts_at, capacity required;
# machine_class optional.
# ---------------------------------------------------------------------------
def create_workshop_payload(instructor_id, starts_at, capacity=5, **overrides) -> dict:
    defaults = {
        "title": "Test Workshop",
        "instructor_id": instructor_id,
        "starts_at": starts_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# WorkshopEnrollment (PRD §3.9) — workshop_id, member_id required.
# ---------------------------------------------------------------------------
def create_enrollment_payload(workshop_id, member_id, **overrides) -> dict:
    defaults = {"workshop_id": workshop_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults
