"""Entity assertions and domain invariant checkers.

assert_{entity}(data) validates the system-managed shape of a returned resource.
Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (all resources except Donation)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_patron(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("INDIVIDUAL", "DUAL", "HOUSEHOLD", "PATRON_CIRCLE")
    assert data["annual_fee_cents"] >= 0
    assert data["household_max"] >= 0
    assert data["guest_passes_granted"] >= 0
    assert data["member_admission_cents"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_PAYMENT", "ACTIVE", "GRACE", "EXPIRED", "CANCELLED"
    )
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["primary_patron_id"], str)
    assert isinstance(data["term_count"], int) and data["term_count"] >= 1


def assert_household_member(data: dict):
    _assert_common(data)
    assert data["relationship"] in ("SPOUSE", "CHILD", "PARTNER", "OTHER")
    assert isinstance(data["active"], bool)


def assert_guest_pass(data: dict):
    _assert_common(data)
    assert data["status"] in ("UNUSED", "RESERVED", "REDEEMED", "EXPIRED")
    assert isinstance(data["membership_id"], str)


def assert_timed_entry_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["capacity_total"] >= 1
    assert data["reserved_count"] >= 0, "reserved_count must be floored at 0"
    assert data["reserved_count"] <= data["capacity_total"], \
        "reserved_count must never exceed capacity_total"


def assert_special_exhibit(data: dict):
    _assert_common(data)
    assert data["surcharge_cents"] >= 0
    assert 0 <= data["member_surcharge_discount_pct"] <= 1
    assert data["buffer_minutes"] >= 0


def assert_exhibit_session(data: dict):
    _assert_common(data)
    assert data["capacity_total"] >= 1
    assert data["reserved_count"] >= 0


def assert_admission_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "CHECKED_IN", "CANCELLED", "REFUNDED"
    )
    assert isinstance(data["party_size"], int) and data["party_size"] >= 0
    assert isinstance(data["patron_id"], str)
    assert isinstance(data["slot_id"], str)


def assert_admission_ticket(data: dict):
    _assert_common(data)
    assert data["ticket_type"] in ("MEMBER", "NON_MEMBER", "GUEST", "RECIPROCAL")
    assert data["state"] in ("ACTIVE", "SCANNED", "VOIDED")
    assert isinstance(data["order_id"], str)


def assert_reciprocal_partner(data: dict):
    _assert_common(data)
    assert data["benefit_type"] in ("FREE", "DISCOUNT")
    assert 0 <= data["discount_pct"] <= 1


def assert_donation(data: dict):
    """Donation is an immutable receipt: only id + created_at + join/amount.
    It carries NO updated_at and NO version (PRD §2.4, §3.8)."""
    assert is_valid_uuid(data.get("id", "")), "donation id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Donation must not carry updated_at"
    assert "version" not in data, "Donation must not carry version"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
