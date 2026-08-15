"""Entity assertions and domain invariant checkers (PRD §2.4 common properties)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert 0 < data["budget_warning_pct"] <= 1.0
    assert 0 < data["budget_critical_pct"] <= 1.0
    assert data["budget_critical_pct"] > data["budget_warning_pct"]
    assert 0 <= data["deflection_target_pct"] <= 1.0
    assert "active_fiscal_period_id" in data


def assert_fiscal_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("OPEN", "SOFT_CLOSED", "HARD_CLOSED", "REOPENED")
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["total_actual_spend_cents"], int)
    assert isinstance(data["total_accrual_cents"], int)


def assert_practice_area(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert data["code"].isalnum() and data["code"] == data["code"].upper()
    assert isinstance(data["display_name"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_matter_type(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["practice_area_id"], str)
    assert isinstance(data["code"], str)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["default_budget_cents"], int) and data["default_budget_cents"] >= 0


def assert_firm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["blended_hourly_rate_cents"], int)
    assert data["blended_hourly_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ARCHIVED")


def assert_counsel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["annual_capacity_hours"], int)
    assert data["annual_capacity_hours"] > 0
    assert isinstance(data["loaded_hourly_cost_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_matter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["matter_number"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["practice_area_id"], str)
    assert isinstance(data["matter_type_id"], str)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["lead_counsel_id"], str)
    assert data["status"] in ("INTAKE", "ACTIVE", "ON_HOLD", "CLOSED", "REOPENED", "ARCHIVED")
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert isinstance(data["actual_spend_cents"], int) and data["actual_spend_cents"] >= 0
    assert isinstance(data["accrual_outstanding_cents"], int)
    assert data["accrual_outstanding_cents"] >= 0
    assert "cycle_days" in data


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["matter_id"], str)
    assert isinstance(data["counsel_id"], str)
    assert isinstance(data["allocated_hours"], int) and data["allocated_hours"] >= 0
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_budget(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["practice_area_id"], str)
    assert "matter_type_id" in data
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["consumed_cents"], int) and data["consumed_cents"] >= 0
    assert data["posture"] in ("OK", "WARNING", "CRITICAL", "EXCEEDED")


def assert_accrual(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["matter_id"], str)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["firm_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("OUTSTANDING", "MATCHED", "RELEASED", "EXPIRED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["matter_id"], str)
    assert isinstance(data["firm_id"], str)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["invoice_number"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_status"] in ("SUBMITTED", "APPROVED", "PAID", "REJECTED")
    assert data["accrual_match_status"] in (
        "UNMATCHED", "PARTIALLY_MATCHED", "FULLY_MATCHED", "OVER_BILLED",
    )
    assert "matched_accrual_id" in data


def assert_spend_line(data: dict):
    """Append-only ledger row: carries ONLY id + created_at (PRD §2.4 exception)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "spend lines must not carry updated_at"
    assert "version" not in data, "spend lines must not carry version"
    assert isinstance(data["matter_id"], str)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["firm_id"], str)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["posting_date"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source_status"] in ("POSTED", "REVERSED")


def assert_dashboard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_period_id"], str)
    assert isinstance(data["snapshot_label"], str)
    assert isinstance(data["total_matters_opened"], int) and data["total_matters_opened"] >= 0
    assert isinstance(data["total_matters_closed"], int) and data["total_matters_closed"] >= 0
    assert "mean_cycle_days" in data
    assert isinstance(data["total_actual_spend_cents"], int)
    assert isinstance(data["total_accrual_outstanding_cents"], int)
    assert "budget_accuracy_pct" in data
    assert "deflection_rate_pct" in data
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_utilization(data: dict):
    """Shape of the counsel utilization computed read (PRD §3.8)."""
    assert isinstance(data["counsel_id"], str)
    assert isinstance(data["total_allocated_hours"], int) and data["total_allocated_hours"] >= 0
    assert isinstance(data["annual_capacity_hours"], int) and data["annual_capacity_hours"] > 0
    assert isinstance(data["utilization_pct"], (int, float))
    assert isinstance(data["over_capacity"], bool)


def assert_cost_model(data: dict):
    """Shape of the insource-vs-outsource cost model read (PRD §3.8)."""
    assert isinstance(data["matter_id"], str)
    assert isinstance(data["insource_cost_cents"], int)
    assert "outsource_cost_cents" in data
    assert "modeled_outsource_cost_cents" in data
    assert "savings_cents" in data
    assert "decision" in data
    if data["decision"] is not None:
        assert data["decision"] in ("INSOURCE_CHEAPER", "OUTSOURCE_CHEAPER", "BREAK_EVEN")
