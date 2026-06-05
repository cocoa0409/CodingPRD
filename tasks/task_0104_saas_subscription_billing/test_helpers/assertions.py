"""Entity assertions and domain invariant checkers.

Assertions validate only the fields the PRD guarantees on each resource
(PRD §2.4 enumerates which entities carry id/created_at/updated_at/version,
and UsageRecord is the lone append-only exception with id + created_at only).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ─────────────────────────────
def assert_common_fields(data: dict):
    """Full common-field set: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Append-only set: id + created_at only (PRD §2.4, UsageRecord)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ─── Entity assertions ────────────────────────────────
def assert_plan(data: dict):
    assert_common_fields(data)
    assert data["tier"] in ("BASIC", "PRO", "ENTERPRISE"), f"unexpected tier {data['tier']!r}"
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_usage_units"], int) and data["included_usage_units"] >= 0
    assert isinstance(data["overage_tiers"], list)
    assert isinstance(data["trial_days"], int) and data["trial_days"] >= 0
    assert data["status"] in ("ACTIVE", "ARCHIVED"), f"unexpected status {data['status']!r}"


def assert_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["company_name"], str)
    assert isinstance(data["mrr_cents"], int)
    assert data["status"] in ("ACTIVE", "CLOSED"), f"unexpected status {data['status']!r}"


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert data["lifecycle_status"] in ("TRIALING", "ACTIVE", "CANCELED"), (
        f"unexpected lifecycle_status {data['lifecycle_status']!r}"
    )
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "UNPAID"), (
        f"unexpected billing_status {data['billing_status']!r}"
    )
    assert isinstance(data["dunning_attempt"], int) and data["dunning_attempt"] >= 0
    assert isinstance(data["mrr_contribution_cents"], int)


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "OPEN", "PAID", "PAST_DUE", "VOID"), (
        f"unexpected status {data['status']!r}"
    )
    for field in (
        "subtotal_cents",
        "discount_cents",
        "tax_cents",
        "total_cents",
        "amount_paid_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_invoice_line(data: dict):
    assert_common_fields(data)
    assert data["kind"] in (
        "SUBSCRIPTION",
        "ADDON",
        "OVERAGE",
        "PRORATION_CREDIT",
        "PRORATION_CHARGE",
    ), f"unexpected kind {data['kind']!r}"
    assert isinstance(data["amount_cents"], int), "amount_cents must be an integer"


def assert_payment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in ("PENDING", "CLEARED", "FAILED"), (
        f"unexpected status {data['status']!r}"
    )


def assert_revenue_schedule_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["total_recognizable_cents"], int)
    assert isinstance(data["recognized_to_date_cents"], int)


def assert_usage_record(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["billed"], bool)


def assert_coupon(data: dict):
    assert_common_fields(data)
    assert data["discount_type"] in ("PERCENT", "FIXED")
    assert data["duration"] in ("ONCE", "RECURRING")
    assert isinstance(data["max_redemptions"], int) and data["max_redemptions"] >= 1
    assert isinstance(data["redemption_count"], int) and data["redemption_count"] >= 0
    assert data["status"] in ("ACTIVE", "EXHAUSTED")


def assert_subscription_addon(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_pause_window(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "CANCELED")


# ─── Domain invariant checkers ────────────────────────
def assert_invoice_total_consistent(data: dict):
    """PRD §3.6 total identity: total_cents == (subtotal - discount) + tax."""
    expected = (data["subtotal_cents"] - data["discount_cents"]) + data["tax_cents"]
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != (subtotal {data['subtotal_cents']} - "
        f"discount {data['discount_cents']}) + tax {data['tax_cents']} = {expected}"
    )


def find_line_by_kind(lines: list, kind: str) -> dict:
    """Return the single InvoiceLine of the given kind, or None if absent."""
    matches = [ln for ln in lines if ln.get("kind") == kind]
    assert len(matches) <= 1, f"expected at most one {kind} line, got {len(matches)}"
    return matches[0] if matches else None
