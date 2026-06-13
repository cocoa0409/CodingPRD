"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# --------------------------------------------------------------------------
# Common system fields (PRD §2.4): every entity carries id/created_at/
# updated_at/version.
# --------------------------------------------------------------------------
def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_funeral_home(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["sales_tax_pct"], (int, float))
    assert isinstance(data["state_trust_pct"], (int, float))
    assert isinstance(data["trust_admin_retention_cents"], int)
    assert isinstance(data["chapel_buffer_minutes"], int)
    assert isinstance(data["trust_balance_cents"], int)


def assert_gpl_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("funeral_home_id", ""))
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["category"] in ("SERVICE", "MERCHANDISE")
    assert isinstance(data["taxable"], bool)
    assert isinstance(data["non_declinable"], bool)
    assert isinstance(data["preneed_trustable"], bool)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("funeral_home_id", ""))
    assert isinstance(data["decedent_name"], str) and len(data["decedent_name"]) > 0
    assert data["case_mode"] in ("AT_NEED", "PRENEED")
    assert data["arrangement_status"] in (
        "INTAKE", "DISCLOSED", "ARRANGED", "COMPLETED", "CANCELLED")
    assert data["interment_status"] in ("NOT_READY", "READY", "INTERRED")
    assert isinstance(data["disclosure_acknowledged"], bool)
    assert isinstance(data["statement_total_provisional_cents"], int)
    assert isinstance(data["statement_total_final_cents"], int)
    assert isinstance(data["gfs_issued"], bool)


def assert_statement_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("gpl_item_id", ""))
    assert data["category"] in ("SERVICE", "MERCHANDISE")
    assert isinstance(data["taxable"], bool)
    assert isinstance(data["non_declinable"], bool)
    assert isinstance(data["preneed_trustable"], bool)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_status"] in ("PROPOSED", "SELECTED", "REMOVED")


def assert_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["funding_type"] in (
        "PRENEED_TRUST", "AT_NEED_DIRECT", "INSURANCE_ASSIGNMENT")
    assert data["status"] in ("DRAFT", "PENDING_FUNDING", "FUNDED", "SETTLED", "VOID")
    assert isinstance(data["contract_amount_cents"], int)
    assert isinstance(data["trust_required_cents"], int)
    assert isinstance(data["trust_principal_cents"], int)
    assert isinstance(data["credited_earnings_cents"], int)
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["projected_earnings_cents"], int)


def assert_trust_deposit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["kind"] in ("PRINCIPAL", "EARNINGS", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ("POSTED", "REFUNDED")


def assert_insurance_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["carrier"], str)
    assert isinstance(data["assigned_value_cents"], int) and data["assigned_value_cents"] >= 1
    assert data["status"] in ("PENDING", "VERIFIED", "RELEASED", "DECLINED")


def assert_plot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("funeral_home_id", ""))
    assert isinstance(data["section"], str)
    assert isinstance(data["plot_code"], str)
    assert isinstance(data["current_price_cents"], int) and data["current_price_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "RESERVED", "INTERRED")


def assert_venue(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("funeral_home_id", ""))
    assert isinstance(data["name"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["resource_kind"] in ("CHAPEL", "GRAVESIDE")
    assert is_valid_uuid(data.get("resource_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_permit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["permit_type"] in ("DEATH_CERTIFICATE", "BURIAL_TRANSIT")
    assert data["status"] in ("APPLIED", "ISSUED", "REJECTED")
