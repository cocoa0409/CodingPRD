"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) verifies shape and common-field presence (every entity
carries the full common-field set per PRD §2.4). Domain invariant checkers verify
relationships the PRD pins (e.g. net_sales never negative, rebate pool conserved).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every entity carries id, created_at, updated_at, version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_brand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_period_index"], int)
    for rate in (
        "royalty_tier_1_rate",
        "royalty_tier_2_rate",
        "royalty_tier_3_rate",
        "ad_fund_rate",
        "late_fee_monthly_rate",
    ):
        assert isinstance(data[rate], (int, float)), f"{rate} must be numeric"


def assert_territory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "RETIRED")


def assert_franchisee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["status"] in (
        "APPLICANT",
        "APPROVED",
        "ACTIVE",
        "DEFAULTED",
        "TERMINATED",
    )
    assert isinstance(data["open_compliance_strikes"], int)
    assert data["open_compliance_strikes"] >= 0


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "EXECUTED",
        "RENEWAL_PENDING",
        "RENEWED",
        "TRANSFERRED",
        "TERMINATED",
    )
    assert isinstance(data["term_end_period_index"], int)


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert data["operational_status"] in ("PLANNED", "OPEN", "CLOSED")
    assert data["compliance_status"] in ("GOOD_STANDING", "PROBATION", "SUSPENDED")
    assert isinstance(data["lifetime_net_sales_cents"], int)
    assert data["lifetime_net_sales_cents"] >= 0


def assert_sales_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("POLLED", "ACCEPTED", "AMENDED")
    assert isinstance(data["net_sales_cents"], int)
    assert data["net_sales_cents"] >= 0, "net_sales_cents must never be negative (§3.8)"
    assert data["net_sales_cents"] == max(
        0, data["gross_sales_cents"] - data["discounts_cents"]
    ), "net_sales_cents == max(0, gross - discounts)"


def assert_royalty_statement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "OVERDUE", "WRITTEN_OFF")
    for f in (
        "net_sales_basis_cents",
        "royalty_cents",
        "ad_fund_cents",
        "late_fee_cents",
        "total_due_cents",
        "amount_paid_cents",
        "due_period_index",
    ):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert data["approval_status"] in ("PENDING", "APPROVED", "REVOKED")
    assert data["category"] in ("FOOD", "PACKAGING", "EQUIPMENT", "SERVICES")


def assert_vendor_authorization(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DISABLED")
    assert isinstance(data["qualifying_purchase_cents"], int)


def assert_brand_audit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "FINALIZED",
        "REMEDIATION",
        "CLOSED",
    )
    if data.get("grade") is not None:
        assert data["grade"] in ("PASS", "CONDITIONAL", "FAIL")


def assert_development_schedule(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ON_TRACK", "BEHIND", "SATISFIED", "BREACHED")
    assert isinstance(data["opened_units"], int)
    assert isinstance(data["required_units"], int)


def assert_national_account(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "DISTRIBUTED")
    assert isinstance(data["rebate_pool_cents"], int)


# ─── Domain invariant checkers ───────────────────────────────────────────────
def assert_total_due_consistent(statement: dict):
    """total_due_cents == royalty_cents + ad_fund_cents + late_fee_cents (§3.8)."""
    expected = (
        statement["royalty_cents"]
        + statement["ad_fund_cents"]
        + statement["late_fee_cents"]
    )
    assert statement["total_due_cents"] == expected, (
        f"total_due_cents {statement['total_due_cents']} != royalty+ad_fund+late_fee "
        f"{expected}"
    )
