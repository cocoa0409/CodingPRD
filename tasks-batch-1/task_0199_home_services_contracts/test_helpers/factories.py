"""Payload factories — one per entity, input fields only.

Each factory returns a dict ready to POST; pass **overrides to control any field.
Only fields the client supplies (PRD input fields) appear here.
"""
from .constants import TEST_DEFAULTS, BASE_CLOCK


def create_service_plan_payload(**overrides) -> dict:
    """A plan template. auto_renew_default is optional (PRD §3.1: defaults true)."""
    defaults = {
        "tier": TEST_DEFAULTS["PLAN_TIER"],
        "trade": TEST_DEFAULTS["PLAN_TRADE"],
        "annual_fee_cents": TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
        "included_visits_per_year": TEST_DEFAULTS["INCLUDED_VISITS_PER_YEAR"],
        "extra_visit_fee_cents": TEST_DEFAULTS["EXTRA_VISIT_FEE_CENTS"],
        "sla_response_hours": TEST_DEFAULTS["SLA_RESPONSE_HOURS"],
        "parts_discount_pct": TEST_DEFAULTS["PARTS_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Customer", "email": "test-customer@example.com"}
    defaults.update(overrides)
    return defaults


def create_site_payload(customer_id: str, **overrides) -> dict:
    """access_notes is optional (PRD §3.2: defaults to empty string)."""
    defaults = {
        "customer_id": customer_id,
        "address": "1 Test St",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(site_id: str, **overrides) -> dict:
    """refrigerant_type is optional (PRD §3.7: defaults NONE)."""
    defaults = {
        "site_id": site_id,
        "model": "AC-9",
        "refrigerant_type": "R410A",
        "nameplate_charge_grams": TEST_DEFAULTS["NAMEPLATE_CHARGE_GRAMS"],
        "warranty_expires_at": "2030-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    """epa_certified is optional (PRD §3.9: defaults false)."""
    defaults = {
        "full_name": "Test Tech",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "trade": TEST_DEFAULTS["PLAN_TRADE"],
        "epa_certified": True,
        "daily_visit_capacity": TEST_DEFAULTS["DAILY_VISIT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id: str, site_id: str, plan_id: str, **overrides) -> dict:
    """auto_renew is optional (PRD §3.2: defaults from plan.auto_renew_default)."""
    defaults = {
        "customer_id": customer_id,
        "site_id": site_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(membership_id: str, expected_membership_version: int, **overrides) -> dict:
    """technician_id is optional (PRD §3.5: may be named up front). expected_membership_version
    is mandatory (PRD §2.8)."""
    defaults = {
        "membership_id": membership_id,
        "visit_kind": "SEASONAL",
        "requested_at": "2026-07-01T08:00:00Z",
        "window_start": "2026-07-02T09:00:00Z",
        "window_end": "2026-07-02T11:00:00Z",
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def reschedule_payload(window_start: str, window_end: str) -> dict:
    return {"window_start": window_start, "window_end": window_end}


def dispatch_payload(technician_id: str) -> dict:
    return {"technician_id": technician_id}


def create_renewal_offer_payload(offered_plan_id: str, expected_membership_version: int, **overrides) -> dict:
    defaults = {
        "offered_plan_id": offered_plan_id,
        "expires_at": "2027-06-30T00:00:00Z",
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def create_refrigerant_log_payload(equipment_id: str, action: str, grams: int) -> dict:
    return {"equipment_id": equipment_id, "action": action, "grams": grams}


def create_part_usage_payload(part_name: str, quantity: int, list_price_cents: int) -> dict:
    return {"part_name": part_name, "quantity": quantity, "list_price_cents": list_price_cents}


def create_warranty_claim_payload(equipment_id: str, origin_visit_id: str, claimed_amount_cents: int) -> dict:
    return {
        "equipment_id": equipment_id,
        "origin_visit_id": origin_visit_id,
        "claimed_amount_cents": claimed_amount_cents,
    }


def approve_claim_payload(approved_amount_cents: int) -> dict:
    return {"approved_amount_cents": approved_amount_cents}


def deny_claim_payload(denial_reason: str = "out of coverage") -> dict:
    return {"denial_reason": denial_reason}


__all__ = [
    "create_service_plan_payload",
    "create_customer_payload",
    "create_site_payload",
    "create_equipment_payload",
    "create_technician_payload",
    "create_membership_payload",
    "create_service_visit_payload",
    "reschedule_payload",
    "dispatch_payload",
    "create_renewal_offer_payload",
    "create_refrigerant_log_payload",
    "create_part_usage_payload",
    "create_warranty_claim_payload",
    "approve_claim_payload",
    "deny_claim_payload",
    "BASE_CLOCK",
]
