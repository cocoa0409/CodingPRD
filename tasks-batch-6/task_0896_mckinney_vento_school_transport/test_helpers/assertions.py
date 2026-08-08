"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_district(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nces_code"], str)
    for f in ("transport_budget_cents", "committed_cost_cents",
              "transport_balance_cents", "categorical_eligible_count"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_liaison(data: dict):
    _common_versioned(data)
    assert isinstance(data["max_caseload"], int)
    assert isinstance(data["current_caseload"], int)


def assert_student(data: dict):
    _common_versioned(data)
    assert data["status"] in ("INTAKE", "ENROLLED", "WITHDRAWN")
    assert data["eligibility_status"] in ("UNDETERMINED", "ELIGIBLE", "INELIGIBLE")
    assert data["priority_basis"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["priority_score"], int)


def assert_determination(data: dict):
    _common_versioned(data)
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_plan(data: dict):
    _common_versioned(data)
    assert data["status"] in ("DRAFT", "PROPOSED", "APPROVED", "DENIED",
                              "ACTIVE", "SUSPENDED", "TERMINATED")
    for f in ("estimated_daily_cost_cents", "estimated_monthly_cost_cents", "actual_cost_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_vehicle(data: dict):
    _common_versioned(data)
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "RETIRED")


def assert_trip(data: dict):
    _common_versioned(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELED", "VOIDED")


def assert_agreement(data: dict):
    _common_versioned(data)
    for f in ("total_monthly_cents", "serving_share_cents", "origin_share_cents", "actual_cost_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert isinstance(data["serving_pct"], (int, float))


def assert_ledger_entry(data: dict):
    """Append-only: id + created_at only, plus event fields; NO updated_at / version."""
    _common(data)
    assert "updated_at" not in data, "CostLedgerEntry must not carry updated_at"
    assert "version" not in data, "CostLedgerEntry must not carry version"
    assert data["entry_type"] in ("TRIP_CHARGE", "REVERSAL")
    assert isinstance(data["amount_cents"], int)


def assert_benefit_link(data: dict):
    _common_versioned(data)
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert data["source"] == "AUTO_ELIGIBILITY"


def assert_dispute(data: dict):
    _common_versioned(data)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "INFO_REQUESTED",
                              "RESOLVED_UPHELD", "RESOLVED_DENIED")


def assert_referral(data: dict):
    _common_versioned(data)
    assert data["status"] in ("OPEN", "CLOSED", "CANCELED")
