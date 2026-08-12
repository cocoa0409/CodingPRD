"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(str(data.get("id", ""))), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert isinstance(data["total_rentable_sf"], int) and data["total_rentable_sf"] >= 1
    assert isinstance(data["fiscal_year_end_month"], int)
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert data["posture"] in ("OPERATING", "SUSPENDED")


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("property_id", "")))
    assert isinstance(data["tenant_legal_name"], str) and data["tenant_legal_name"]
    assert isinstance(data["suite"], str)
    assert isinstance(data["leased_sf"], int) and data["leased_sf"] >= 1
    assert isinstance(data["commencement_date"], str)
    assert isinstance(data["expiration_date"], str)
    assert isinstance(data["base_rent_annual_cents"], int)
    assert data["base_rent_annual_cents"] >= 0
    assert data["escalation_type"] in ("NONE", "FIXED_PCT", "CPI", "STEPPED")
    assert data["recovery_structure"] in ("NNN", "MODIFIED_GROSS", "GROSS")
    assert isinstance(data["pro_rata_share_bps"], int)
    assert 0 <= data["pro_rata_share_bps"] <= 10000
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert data["abstraction_status"] in ("PENDING", "ABSTRACTED", "CERTIFIED")
    assert data["billing_posture"] in ("CURRENT", "FROZEN", "DELINQUENT")
    assert isinstance(data["cached_annual_rent_cents"], int)
    assert isinstance(data["cached_recovery_ytd_cents"], int)
    assert isinstance(data["security_deposit_cents"], int)
    assert data["security_deposit_cents"] >= 0


def assert_rent_schedule_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["base_rent_cents"], int) and data["base_rent_cents"] >= 0
    assert "escalation_step_id" in data
    assert isinstance(data["effective_rent_cents"], int)
    assert data["effective_rent_cents"] >= 0


def assert_escalation_step(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert isinstance(data["step_index"], int) and data["step_index"] >= 1
    assert data["kind"] in ("FIXED_PCT", "CPI_LOOKUP", "STEPPED_AMOUNT")
    assert isinstance(data["effective_on"], str)


def assert_recovery_pool(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("property_id", "")))
    assert data["category"] in ("CAM", "TAX", "INSURANCE", "UTILITIES", "MANAGEMENT_FEE")
    assert isinstance(data["fiscal_year"], int)
    assert 2000 <= data["fiscal_year"] <= 2100
    assert isinstance(data["budgeted_cents"], int) and data["budgeted_cents"] >= 0
    assert data.get("actual_cents") is None or (
        isinstance(data["actual_cents"], int) and data["actual_cents"] >= 0
    )
    assert isinstance(data["gross_up_floor_pct_bps"], int)
    assert 0 <= data["gross_up_floor_pct_bps"] <= 10000


def assert_recovery_billing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert is_valid_uuid(str(data.get("pool_id", "")))
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["estimate_cents"], int) and data["estimate_cents"] >= 0
    assert data.get("final_cents") is None or isinstance(data["final_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "DISPUTED", "VOID")


def assert_reconciliation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert isinstance(data["fiscal_year"], int)
    assert data["status"] in ("OPEN", "POSTED", "APPROVED", "CLOSED", "CHALLENGED")


def assert_critical_date(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert data["kind"] in (
        "OPTION_EXERCISE", "NOTICE_DEADLINE", "EXPIRATION",
        "RENEWAL_WINDOW_OPEN", "RENEWAL_WINDOW_CLOSE", "AUDIT_WINDOW_CLOSE",
    )
    assert isinstance(data["due_date"], str)
    assert isinstance(data["advance_notice_days"], int)
    assert data["advance_notice_days"] >= 0
    assert data["status"] in ("PENDING", "NOTIFIED", "EXERCISED", "LAPSED", "WAIVED")


def assert_compliance_doc(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert data["kind"] in ("INSURANCE_CERT", "ESTOPPEL", "FINANCIAL_STMT", "SNDA")
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED", "EXPIRED",
    )


def assert_amendment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert data["kind"] in (
        "EXTENSION", "CONTRACTION", "EXPANSION",
        "ASSIGNMENT", "RENT_CHANGE", "USE_CHANGE",
    )
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("PROPOSED", "APPROVED", "APPLIED", "REJECTED")


def assert_tenant_challenge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert is_valid_uuid(str(data.get("reconciliation_id", "")))
    assert data["reason_code"] in (
        "GROSS_UP_DISPUTE", "PRO_RATA_DISPUTE", "AUDIT_FINDING",
        "MATH_ERROR", "POOL_MISCLASS",
    )
    assert isinstance(data["claimed_overbilling_cents"], int)
    assert data["claimed_overbilling_cents"] > 0
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "RESOLVED_ACCEPTED",
        "RESOLVED_REJECTED", "ESCALATED", "WITHDRAWN",
    )
    assert isinstance(data["round_index"], int) and data["round_index"] >= 0


def assert_audit_right(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(str(data.get("lease_id", "")))
    assert is_valid_uuid(str(data.get("reconciliation_id", "")))
    assert isinstance(data["invoked_on"], str)
    assert isinstance(data["window_close_date"], str)
    assert data["status"] in (
        "INVOKED", "FIELDWORK", "FINDINGS_ISSUED", "SETTLED", "TIME_BARRED",
    )


def assert_lease_cache_invariants(lease: dict):
    """Domain invariants that must hold on the Lease derived figures (PRD §3.1)."""
    assert lease["cached_annual_rent_cents"] >= 0, (
        "cached_annual_rent_cents must be non-negative"
    )
    assert lease["cached_recovery_ytd_cents"] >= 0, (
        "cached_recovery_ytd_cents must be non-negative"
    )
