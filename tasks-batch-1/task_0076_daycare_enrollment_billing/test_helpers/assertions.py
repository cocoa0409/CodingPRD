"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_center(data: dict):
    _assert_common(data)
    assert data["cacfp_tier"] in ("TIER_I", "TIER_II")
    assert data["late_pickup_grace_minutes"] >= 0
    assert data["late_pickup_fee_per_block_cents"] >= 0
    assert data["late_pickup_block_minutes"] >= 1


def assert_classroom(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "FULL")
    assert data["age_band"] in ("INFANT", "TODDLER", "PRESCHOOL")
    assert data["active_enrollment_count"] >= 0
    # Derived status invariant (PRD §2.9)
    if data["active_enrollment_count"] < data["licensed_capacity"]:
        assert data["status"] == "OPEN", "classroom below capacity must be OPEN"
    else:
        assert data["status"] == "FULL", "classroom at capacity must be FULL"


def assert_family(data: dict):
    _assert_common(data)
    assert data["sliding_scale_tier"] in ("TIER_A", "TIER_B", "TIER_C", "FULL_PAY")
    assert isinstance(data["account_balance_cents"], int)


def assert_child(data: dict):
    _assert_common(data)
    assert isinstance(data["enrolls_in_cacfp"], bool)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "OFFERED", "CONVERTED", "EXPIRED", "WITHDRAWN")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "ACTIVE", "DECLINED", "WITHDRAWN", "GRADUATED")
    assert 0 <= data["sibling_discount_pct"] <= 100
    assert data["monthly_net_tuition_cents"] >= 0


def assert_attendance(data: dict):
    _assert_common(data)
    assert data["status"] in ("CHECKED_IN", "CHECKED_OUT")
    assert data["late_fine_cents"] >= 0
    assert data["cacfp_reimbursement_cents"] >= 0
    assert data["late_pickup_minutes"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert data["total_cents"] >= 0
    assert data["amount_paid_cents"] >= 0


def assert_payment(data: dict):
    _assert_immutable(data)
    assert data["amount_cents"] >= 1
    assert data["method"] in ("CARD", "ACH", "CASH")


def assert_tax_statement(data: dict):
    _assert_immutable(data)
    assert data["total_paid_cents"] >= 0
    assert data["child_count"] >= 0
