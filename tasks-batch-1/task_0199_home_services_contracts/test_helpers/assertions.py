"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the common-property contract (PRD §2.4) plus the
entity's own fields. First-class entities carry id/created_at/updated_at/version;
the two append-only ledgers (RefrigerantLog, PartUsage) carry only id/created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

MEMBERSHIP_STATES = {"PENDING_ACTIVATION", "ACTIVE", "RENEWAL_PENDING", "SUSPENDED", "LAPSED", "CANCELLED"}
VISIT_STATES = {"SCHEDULED", "DISPATCHED", "EN_ROUTE", "ON_SITE", "COMPLETED", "CANCELLED", "NO_SHOW"}
CLAIM_STATES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "SETTLED"}
EQUIPMENT_OPERATIONAL = {"OPERATIONAL", "NEEDS_SERVICE", "DECOMMISSIONED"}
EQUIPMENT_WARRANTY = {"IN_WARRANTY", "EXPIRED", "VOIDED"}
OFFER_STATES = {"PENDING", "ACCEPTED", "AUTO_ACCEPTED", "DECLINED", "EXPIRED"}


def _assert_first_class_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_ledger_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Append-only ledgers must NOT carry updated_at / version (PRD §2.4).


def assert_service_plan(data: dict):
    _assert_first_class_common(data)
    assert data["tier"] in {"BASIC", "PLUS", "PREMIUM"}
    assert data["trade"] in {"HVAC", "PEST"}
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0
    assert isinstance(data["included_visits_per_year"], int) and data["included_visits_per_year"] >= 0
    assert isinstance(data["extra_visit_fee_cents"], int) and data["extra_visit_fee_cents"] >= 0
    assert isinstance(data["sla_response_hours"], int) and data["sla_response_hours"] >= 1
    assert 0 <= data["parts_discount_pct"] <= 1
    assert isinstance(data["active"], bool)


def assert_customer(data: dict):
    _assert_first_class_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["billing_balance_cents"], int)


def assert_site(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["address"], str)
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0


def assert_membership(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in MEMBERSHIP_STATES, f"unexpected membership status {data['status']!r}"
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["visits_consumed"], int) and data["visits_consumed"] >= 0
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1


def assert_equipment(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["model"], str)
    assert data["refrigerant_type"] in {"R410A", "R32", "R454B", "NONE"}
    assert isinstance(data["nameplate_charge_grams"], int) and data["nameplate_charge_grams"] >= 0
    assert isinstance(data["current_charge_grams"], int)
    assert data["operational_status"] in EQUIPMENT_OPERATIONAL
    assert data["warranty_status"] in EQUIPMENT_WARRANTY


def assert_technician(data: dict):
    _assert_first_class_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["region_code"], str)
    assert data["trade"] in {"HVAC", "PEST"}
    assert isinstance(data["epa_certified"], bool)
    assert isinstance(data["daily_visit_capacity"], int) and data["daily_visit_capacity"] >= 1


def assert_service_visit(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["visit_kind"] in {"SEASONAL", "PRIORITY", "WARRANTY"}
    assert data["status"] in VISIT_STATES, f"unexpected visit status {data['status']!r}"
    assert isinstance(data["billable_charge_cents"], int)


def assert_warranty_claim(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["equipment_id"])
    assert is_valid_uuid(data["origin_visit_id"])
    assert data["status"] in CLAIM_STATES, f"unexpected claim status {data['status']!r}"
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert isinstance(data["approved_amount_cents"], int)


def assert_renewal_offer(data: dict):
    _assert_first_class_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["offered_plan_id"])
    assert data["status"] in OFFER_STATES, f"unexpected offer status {data['status']!r}"
    assert isinstance(data["offered_annual_fee_cents"], int)


def assert_refrigerant_log(data: dict):
    _assert_ledger_common(data)
    assert is_valid_uuid(data["equipment_id"])
    assert data["action"] in {"ADD", "RECOVER"}
    assert isinstance(data["grams"], int) and data["grams"] > 0


def assert_part_usage(data: dict):
    _assert_ledger_common(data)
    assert isinstance(data["part_name"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0


__all__ = [
    "assert_service_plan",
    "assert_customer",
    "assert_site",
    "assert_membership",
    "assert_equipment",
    "assert_technician",
    "assert_service_visit",
    "assert_warranty_claim",
    "assert_renewal_offer",
    "assert_refrigerant_log",
    "assert_part_usage",
]
