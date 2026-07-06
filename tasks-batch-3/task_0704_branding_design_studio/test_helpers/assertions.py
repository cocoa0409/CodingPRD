"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every persisted resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_rate"], (int, float))
    assert isinstance(data["license_markup_pct"], (int, float))


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["service_type"] in ("LOGO", "IDENTITY", "WEB")
    assert data["status"] in (
        "DRAFT", "DISCOVERY", "CONCEPT", "DELIVERY", "HANDOFF", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["base_scope_cents"], int)
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["deposit_collected_cents"], int)


def assert_moodboard(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_concept(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["revision_limit"], int)
    assert isinstance(data["rounds_used"], int)
    assert data["status"] in ("DRAFT", "PRESENTED", "IN_REVISION", "APPROVED", "REJECTED")


def assert_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["sequence_index"], int)
    assert data["status"] in ("PENDING", "INVOICED", "PAID", "WAIVED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["deposit_credit_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    assert data["status"] in ("ISSUED", "OVERDUE", "PAID", "VOID")


def assert_deliverable(data: dict):
    _assert_common(data)
    assert data["asset_type"] in (
        "LOGO_PRIMARY", "LOGO_MARK", "COLOR_TOKENS", "TYPOGRAPHY", "BRAND_GUIDE", "WEB_KIT",
    )
    assert isinstance(data["is_required_for_handoff"], bool)
    assert data["status"] in ("PENDING", "DELIVERED", "ACCEPTED", "REVISION_REQUESTED")


def assert_license(data: dict):
    _assert_common(data)
    assert data["kind"] in ("STOCK", "FONT")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["billable_cents"], int)
    assert data["status"] in ("RESERVED", "CLEARED", "BILLED", "VOIDED")


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["reason"] in ("SCOPE_ADD", "EXTRA_REVISION", "RUSH")
    assert isinstance(data["delta_cents"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")


def assert_retainer(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_hours"], int)
    assert isinstance(data["tier1_rate_cents"], int)
    assert isinstance(data["tier2_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_care_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["hours_used"], int)
    assert isinstance(data["overage_cents"], int)
    assert isinstance(data["billed_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED", "BILLED")
