"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_issuer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ticker"], str)
    assert isinstance(data["cik"], str)
    assert isinstance(data["shares_outstanding"], int) and data["shares_outstanding"] > 0
    assert isinstance(data["fiscal_year_end_month"], int)
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert isinstance(data["edgar_ccc"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_reporting_person(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("PROPOSED", "ACTIVE", "EXITED")
    assert isinstance(data["late_filing_count"], int) and data["late_filing_count"] >= 0
    assert isinstance(data["delinquent_flag"], bool)
    assert isinstance(data["open_obligation_count"], int) and data["open_obligation_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("reporting_person_id", "")), "reporting_person_id must be a valid UUID"
    assert data["transaction_code"] in ("P", "S", "A", "M", "F", "G", "V")
    assert data["security_type"] in ("COMMON_STOCK", "OPTION", "RSU", "DERIVATIVE_OTHER")
    assert isinstance(data["shares"], int) and data["shares"] > 0
    assert data["status"] in ("INGESTED", "CONFIRMED", "REPORTED", "VOID")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_filing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert is_valid_uuid(data.get("reporting_person_id", "")), "reporting_person_id must be a valid UUID"
    assert data["form_type"] in ("FORM_3", "FORM_4", "FORM_5")
    assert data["status"] in (
        "DRAFT", "READY", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED", "DISCARDED",
    )
    assert isinstance(data["is_late"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_trading_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("reporting_person_id", "")), "reporting_person_id must be a valid UUID"
    assert isinstance(data["plan_name"], str)
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "ADOPTED", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_blackout_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["start_date"] <= data["end_date"], "blackout start_date must not be later than end_date"


def assert_beneficial_holder(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert isinstance(data["holder_name"], str)
    assert data["status"] in ("MONITORING", "FILING_REQUIRED", "FILED", "AMENDMENT_REQUIRED")
    assert isinstance(data["shares_beneficially_owned"], int)
    assert isinstance(data["exercisable_derivative_shares"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_position_change(data: dict):
    """Immutable event: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "position change must not carry a version field"
    assert "updated_at" not in data, "position change must not carry updated_at"
    assert isinstance(data["shares_delta"], int) and data["shares_delta"] != 0
    assert isinstance(data["effective_date"], str)


def assert_annual_sweep(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert isinstance(data["fiscal_year"], int)
    assert data["status"] in ("OPEN", "COMPLETED")
    assert isinstance(data["fy_start_date"], str)
    assert isinstance(data["fy_end_date"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_filing_agent_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert isinstance(data["agent_user_id"], str)
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_short_swing_analysis(data: dict, person_id: str):
    """Shape of the computed Section 16(b) analysis response (PRD §3.9)."""
    assert data["reporting_person_id"] == person_id
    assert isinstance(data["as_of_date"], str)
    assert isinstance(data["matchable_pair_count"], int) and data["matchable_pair_count"] >= 0
    assert isinstance(data["short_swing_profit"], (int, float))
    assert isinstance(data["short_swing_profit_fifo"], (int, float))
    assert isinstance(data["pairs"], list)
