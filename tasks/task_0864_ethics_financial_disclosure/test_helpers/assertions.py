"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    for f in ("gift_single_limit_cents", "gift_annual_source_limit_cents",
              "penalty_base_fee_cents", "penalty_daily_rate_cents", "penalty_cap_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"


def assert_filer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["filer_category"] in ("ELECTED", "APPOINTED", "SENIOR_STAFF", "CANDIDATE")
    assert data["status"] in ("ACTIVE", "INACTIVE", "SEPARATED")
    assert data["compliance_status"] in ("COMPLIANT", "DELINQUENT")
    assert data["training_status"] in ("NONE", "CURRENT", "LAPSED")
    assert isinstance(data["outstanding_penalty_cents"], int)
    assert isinstance(data["reportable_gift_total_cents"], int)
    assert isinstance(data["open_recusal_count"], int)


def assert_filing_period(data: dict):
    _assert_common(data)
    assert data["statement_type"] in ("ANNUAL", "TRANSACTIONAL")
    assert data["status"] in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert is_iso8601_timestamp(data["due_at"])


def assert_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED",
                              "RETURNED_FOR_CORRECTION", "FLAGGED", "SUPERSEDED")
    assert data["public_status"] in ("NOT_PUBLISHED", "PUBLISHED", "WITHHELD")
    assert data["statement_type"] in ("ANNUAL", "TRANSACTIONAL")
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["days_late"], int)
    assert isinstance(data["correction_round"], int)
    assert data["redaction_level"] in ("FULL", "REDACTED")


def assert_gift_report(data: dict):
    _assert_common(data)
    assert data["gift_kind"] in ("GIFT", "TRAVEL")
    assert data["status"] in ("REPORTED", "DISPOSED")
    assert isinstance(data["reportable_value_cents"], int) and data["reportable_value_cents"] >= 0
    assert isinstance(data["disclosed_gross_cents"], int) and data["disclosed_gross_cents"] >= 0


def assert_recusal(data: dict):
    _assert_common(data)
    assert data["status"] in ("DECLARED", "RESOLVED")
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])


def assert_penalty(data: dict):
    _assert_common(data)
    assert data["penalty_type"] in ("LATE_FILING", "SANCTION")
    assert data["status"] in ("ACCRUING", "ASSESSED", "PAID", "WAIVED")
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["assessed_amount_cents"], int)
    assert isinstance(data["days_late"], int)


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "SCREENED", "DISMISSED", "SUBSTANTIATED")


def assert_investigation(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUSTAINED", "NOT_SUSTAINED", "CLOSED")
    assert isinstance(data["final_sanction_cents"], int)


def assert_training_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "COMPLETED", "EXPIRED")


def assert_outstanding_ledger_conserved(filer: dict, expected_cents: int):
    """PRD 2.9: outstanding_penalty_cents equals sum of ASSESSED penalties, never drifting."""
    assert filer["outstanding_penalty_cents"] == expected_cents, (
        f"outstanding_penalty_cents expected {expected_cents}, "
        f"got {filer['outstanding_penalty_cents']}"
    )
    expected_status = "DELINQUENT" if expected_cents > 10000 else "COMPLIANT"
    assert filer["compliance_status"] == expected_status, (
        f"compliance_status expected {expected_status} at "
        f"outstanding={expected_cents}, got {filer['compliance_status']}"
    )
