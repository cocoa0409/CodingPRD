"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.8)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BillingMode,
    CertificateStatus,
    EnvironmentalEventKind,
    EnvironmentalEventStatus,
    HoldKind,
    HoldSource,
    HoldStatus,
    HullType,
    LedgerEntryCategory,
    LedgerEntryKind,
    LedgerEntryStatus,
    LiftSlotKind,
    LiftSlotStatus,
    PartCategory,
    PartStatus,
    RefitJobStatus,
    StandAssignmentStatus,
    WorkerType,
    WorkOrderStatus,
    WorkOrderType,
)


def _assert_common_fields(data: dict):
    """Fields carried by every versioned resource (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """LaborEntry / LedgerEntry carry only id + created_at (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, \
        "append-only records must not carry updated_at"
    assert "version" not in data, \
        "append-only records must not carry version"


def assert_vessel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert data["loa_ft"] > 0, "loa_ft must be greater than zero"
    assert data["beam_ft"] > 0, "beam_ft must be greater than zero"
    assert data["displacement_tons"] > 0
    assert data["hull_type"] in HullType._value2member_map_


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vessel_id", ""))
    assert isinstance(data["provider"], str) and data["provider"]
    assert isinstance(data["policy_no"], str) and data["policy_no"]
    assert isinstance(data["liability_coverage_cents"], int)
    assert data["liability_coverage_cents"] > 0
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in CertificateStatus._value2member_map_


def assert_refit_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vessel_id", ""))
    assert data["status"] in RefitJobStatus._value2member_map_
    assert data["billing_mode"] in BillingMode._value2member_map_
    assert isinstance(data["lay_days"], int) and data["lay_days"] >= 0
    assert isinstance(data["open_hold_count"], int) \
        and data["open_hold_count"] >= 0


def assert_lift_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["kind"] in LiftSlotKind._value2member_map_
    assert data["status"] in LiftSlotStatus._value2member_map_
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["vessel_displacement_tons"] > 0


def assert_yard_row(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["total_stands"], int) and data["total_stands"] > 0
    assert isinstance(data["stands_in_use"], int) \
        and data["stands_in_use"] >= 0


def assert_stand_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("row_id", ""))
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["stands_used"], int) and data["stands_used"] > 0
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in StandAssignmentStatus._value2member_map_


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["type"] in WorkOrderType._value2member_map_
    assert isinstance(data["description"], str)
    assert data["quoted_hours"] >= 0
    assert isinstance(data["quoted_rate_cents"], int) \
        and data["quoted_rate_cents"] >= 0
    assert isinstance(data["quoted_parts_cents"], int) \
        and data["quoted_parts_cents"] >= 0
    assert isinstance(data["quoted_total_cents"], int) \
        and data["quoted_total_cents"] >= 0
    assert isinstance(data["actual_cost_cents"], int) \
        and data["actual_cost_cents"] >= 0
    assert isinstance(data["revision"], int) and data["revision"] >= 0
    assert data["status"] in WorkOrderStatus._value2member_map_


def assert_labor_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["worker_type"] in WorkerType._value2member_map_
    assert data["hours"] > 0
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] > 0
    assert isinstance(data["line_cost_cents"], int) \
        and data["line_cost_cents"] > 0


def assert_part(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["description"], str)
    assert data["category"] in PartCategory._value2member_map_
    assert isinstance(data["owner_supplied"], bool)
    assert isinstance(data["declared_value_cents"], int) \
        and data["declared_value_cents"] >= 0
    assert data["status"] in PartStatus._value2member_map_


def assert_environmental_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["kind"] in EnvironmentalEventKind._value2member_map_
    assert isinstance(data["containment_used"], bool)
    assert data["runoff_tss_ppm"] >= 0
    assert data["status"] in EnvironmentalEventStatus._value2member_map_


def assert_compliance_hold(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["kind"] in HoldKind._value2member_map_
    assert data["source"] in HoldSource._value2member_map_
    assert data["status"] in HoldStatus._value2member_map_


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["kind"] in LedgerEntryKind._value2member_map_
    assert data["category"] in LedgerEntryCategory._value2member_map_
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in LedgerEntryStatus._value2member_map_


def assert_statement(data: dict):
    """Computed billing statement shape (PRD section 3.11)."""
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["billing_mode"] in BillingMode._value2member_map_
    assert data["status"] in RefitJobStatus._value2member_map_
    for field in (
        "lay_days",
        "storage_charges_cents",
        "labor_charges_cents",
        "parts_handling_charges_cents",
        "total_charges_cents",
        "payments_cents",
        "credits_cents",
        "deposits_cents",
        "balance_cents",
        "required_deposit_cents",
    ):
        assert isinstance(data.get(field), int), \
            f"statement field {field} must be an integer"
    assert isinstance(data.get("deposit_satisfied"), bool)


def assert_ledger_balance_invariants(statement: dict):
    """Balance identity from PRD section 2.8:
    balance == POSTED charges - POSTED payments/credits/deposits."""
    expected = (
        statement["total_charges_cents"]
        - statement["payments_cents"]
        - statement["credits_cents"]
        - statement["deposits_cents"]
    )
    assert statement["balance_cents"] == expected, (
        f"balance_cents {statement['balance_cents']} != charges minus "
        f"payments/credits/deposits ({expected})"
    )
