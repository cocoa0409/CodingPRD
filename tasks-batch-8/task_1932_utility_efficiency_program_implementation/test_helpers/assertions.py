"""Entity assertions and domain invariant checkers (PRD sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common_fields(data)
    for f in ("code", "name", "sector"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert data["sector"] in ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")
    for f in ("budget_cents", "committed_cents", "paid_cents",
              "avoided_kwh_target", "avoided_kwh_actual"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert isinstance(data.get("trc_threshold"), (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_contractor(data: dict):
    _assert_common_fields(data)
    for f in ("legal_name", "license_number", "sector"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert data["sector"] in ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")
    assert isinstance(data.get("service_zip_codes"), list)
    for f in ("qa_score_bps", "qa_window_size", "active_certification_count",
              "on_time_installs", "late_installs", "complaint_count_90d"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert 0 <= data["qa_score_bps"] <= 10000, "qa_score_bps is a basis-point score in [0, 10000]"
    assert data["status"] in ("APPLIED", "APPROVED", "SUSPENDED", "TERMINATED")


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data["measure_type"] in ("HVAC", "INSULATION", "LIGHTING", "WATER_HEATING", "SOLAR")
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    for f in ("full_name", "email", "service_zip", "utility_account_id"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert data["sector"] in ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")


def assert_lead(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["measure_type"] in ("HVAC", "INSULATION", "LIGHTING", "WATER_HEATING", "SOLAR")
    assert data["source_channel"] in ("WEB", "CALL_CENTER", "FIELD_AUDIT", "REFERRAL", "UTILITY_REFERRAL")
    assert isinstance(data.get("estimated_annual_kwh_savings"), int)
    assert data["status"] in ("NEW", "OFFERED", "ACCEPTED", "EXPIRED", "WITHDRAWN")


def assert_project(data: dict):
    _assert_common_fields(data)
    for f in ("lead_id", "customer_id", "contractor_id", "program_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a UUID"
    assert data["measure_type"] in ("HVAC", "INSULATION", "LIGHTING", "WATER_HEATING", "SOLAR")
    assert isinstance(data.get("measure_cost_cents"), int)
    assert isinstance(data.get("estimated_annual_kwh_savings"), int)
    assert data["incentive_recipient"] in ("CONTRACTOR", "CUSTOMER")
    assert data["status"] in (
        "PROPOSED", "APPROVED", "SCHEDULED", "INSTALLED",
        "INSPECTING", "REMEDIATION", "COMPLETED", "CANCELLED",
    )


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data.get("duration_hours"), int)
    assert data["status"] in ("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_inspector(data: dict):
    _assert_common_fields(data)
    for f in ("full_name", "license_number"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert isinstance(data.get("excluded_contractor_ids"), list)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    for f in ("work_order_id", "project_id", "inspector_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a UUID"
    assert data["outcome"] in ("PENDING", "PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "RECORDED", "VOID")


def assert_incentive_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["payee_role"] in ("CONTRACTOR", "CUSTOMER")
    assert isinstance(data.get("payee_id"), str) and data["payee_id"]
    assert data["status"] in ("DRAFT", "AUTHORIZED", "PAID", "RECONCILED", "VOID")


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data["category"] in ("WORKMANSHIP", "SCHEDULING", "BILLING", "CONDUCT", "OTHER")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "IN_REVIEW", "RESOLVED", "ESCALATED")


def assert_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    for f in ("total_incentive_paid_cents", "total_admin_cost_cents", "total_avoided_kwh"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert isinstance(data.get("trc_ratio"), (int, float))
    assert data["trc_flag"] in ("PASS", "MARGINAL", "FAIL")
    assert data["status"] in ("DRAFT", "FINAL")
