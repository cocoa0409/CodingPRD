"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LINE_OF_BUSINESS_VALUES = ["COMMERCIAL_AUTO", "GENERAL_LIABILITY", "WORKERS_COMP", "PROPERTY"]
CLAIM_STATUS_VALUES = ["OPEN", "CLOSED", "REOPENED"]
TRANSACTION_TYPE_VALUES = ["PAYMENT", "PAYMENT_REVERSAL", "CASE_RESERVE_SET"]
BASIS_VALUES = ["PAID", "INCURRED"]
METHOD_VALUES = ["CHAIN_LADDER", "BORNHUETTER_FERGUSON"]
PATTERN_STATUS_VALUES = ["DRAFT", "SELECTED", "WITHDRAWN"]
STUDY_STATUS_VALUES = ["DRAFT", "IN_REVIEW", "APPROVED", "LOCKED", "WITHDRAWN"]
OPINION_SCOPE_VALUES = ["REASONABLE", "DEFICIENT", "REDUNDANT", "NO_OPINION"]
OPINION_STATUS_VALUES = ["DRAFT", "SIGNED"]
QUARTERS = "YYYY-Qn"


def _assert_common_fields(data: dict, label: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_quarter_label(value, label: str):
    assert isinstance(value, str) and len(value) == 7, f"{label} must be YYYY-Qn"
    assert value[4] == "-" and value[5] == "Q" and value[6] in "1234", (
        f"{label} must match the YYYY-Qn quarter-label form, got {value!r}"
    )


def assert_segment(data: dict):
    _assert_common_fields(data, "ReservingSegment")
    assert isinstance(data["name"], str) and data["name"]
    assert data["line_of_business"] in LINE_OF_BUSINESS_VALUES
    assert isinstance(data["large_loss_threshold_cents"], int)
    assert data["large_loss_threshold_cents"] > 0
    assert isinstance(data["max_range_width_pct"], (int, float))
    assert data["max_range_width_pct"] > 0
    assert isinstance(data["benchmark_open_severity_cents"], int)
    assert data["benchmark_open_severity_cents"] >= 0
    assert "last_closed_quarter" in data, "segment read must carry last_closed_quarter"
    if data["last_closed_quarter"] is not None:
        _assert_quarter_label(data["last_closed_quarter"], "last_closed_quarter")


def assert_catastrophe_event(data: dict):
    _assert_common_fields(data, "CatastropheEvent")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["accident_date"], str)
    assert isinstance(data["report_date"], str)
    assert data["status"] in CLAIM_STATUS_VALUES
    assert isinstance(data["paid_to_date_cents"], int)
    assert isinstance(data["case_outstanding_cents"], int)
    assert isinstance(data["reported_incurred_cents"], int)
    assert isinstance(data["is_large_loss"], bool)
    assert isinstance(data["is_segregated"], bool)
    assert "catastrophe_event_id" in data
    assert "adequacy_ratio_development" in data
    assert "adequacy_ratio_benchmark" in data
    assert_claim_financial_invariants(data)


def assert_claim_financial_invariants(data: dict):
    """PRD §3.2: reported incurred is always paid-to-date plus case outstanding."""
    assert data["reported_incurred_cents"] == (
        data["paid_to_date_cents"] + data["case_outstanding_cents"]
    ), (
        "reported_incurred_cents must equal "
        f"paid_to_date_cents + case_outstanding_cents, got {data}"
    )
    assert data["is_segregated"] == (
        data["is_large_loss"] or data.get("catastrophe_event_id") is not None
    ), "is_segregated must be is_large_loss OR catastrophe-assigned"


def assert_claim_transaction(data: dict):
    """Append-only ledger entry: id + created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "ClaimTransaction.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ClaimTransaction.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only entry must not carry updated_at"
    assert "version" not in data, "append-only entry must not carry version"
    assert data["type"] in TRANSACTION_TYPE_VALUES
    _assert_quarter_label(data.get("effective_quarter"), "effective_quarter")


def assert_cell(cell: dict, label: str = "cell"):
    _assert_quarter_label(cell.get("accident_quarter"), f"{label}.accident_quarter")
    assert isinstance(cell.get("dev_quarter"), int) and cell["dev_quarter"] >= 0
    assert isinstance(cell.get("amount_cents"), int)


def assert_cell_multiset(actual_cells, expected_cells, label: str = "cells"):
    """Order-insensitive comparison of triangle cell arrays."""
    actual = sorted(
        (c["accident_quarter"], c["dev_quarter"], c["amount_cents"])
        for c in actual_cells
    )
    expected = sorted(
        (aq, d, amt) for (aq, d, amt) in expected_cells
    )
    assert actual == expected, f"{label} mismatch: expected {expected}, got {actual}"


def assert_triangle(data: dict):
    _assert_common_fields(data, "LossTriangle")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert data["basis"] in BASIS_VALUES
    _assert_quarter_label(data.get("valuation_quarter"), "valuation_quarter")
    assert isinstance(data["cells"], list)
    for cell in data["cells"]:
        assert_cell(cell, "cells[]")
    assert isinstance(data["large_loss_cells"], list)
    for cell in data["large_loss_cells"]:
        assert_cell(cell, "large_loss_cells[]")
    assert isinstance(data["is_stale"], bool)


def assert_development_pattern(data: dict):
    _assert_common_fields(data, "DevelopmentPattern")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert data["basis"] in BASIS_VALUES
    _assert_quarter_label(data.get("valuation_quarter"), "valuation_quarter")
    _assert_quarter_label(data.get("effective_from_quarter"), "effective_from_quarter")
    _assert_quarter_label(data.get("effective_to_quarter"), "effective_to_quarter")
    assert isinstance(data["selected_factors"], list)
    for factor in data["selected_factors"]:
        assert isinstance(factor, (int, float))
    assert isinstance(data["tail_factor"], (int, float))
    assert data["status"] in PATTERN_STATUS_VALUES


def assert_reserve_run(data: dict):
    _assert_common_fields(data, "ReserveRun")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert is_valid_uuid(data.get("development_pattern_id", "")), (
        "development_pattern_id must be a UUID"
    )
    _assert_quarter_label(data.get("valuation_quarter"), "valuation_quarter")
    assert data["method"] in METHOD_VALUES
    assert data["basis"] in BASIS_VALUES
    assert isinstance(data["ultimate_cents"], int)
    assert isinstance(data["ibnr_cents"], int)
    assert isinstance(data["range_low_cents"], int)
    assert isinstance(data["range_high_cents"], int)
    assert isinstance(data["ultimate_by_accident_quarter"], list)
    for entry in data["ultimate_by_accident_quarter"]:
        _assert_quarter_label(entry.get("accident_quarter"), "accident_quarter")
        assert isinstance(entry.get("age_at_valuation"), int)
        assert isinstance(entry.get("cdf"), (int, float))
        assert isinstance(entry.get("ultimate_cents"), int)
    assert isinstance(data["is_stale"], bool)


def assert_study(data: dict):
    _assert_common_fields(data, "ReservingStudy")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    _assert_quarter_label(data.get("valuation_quarter"), "valuation_quarter")
    assert data["selected_method"] in METHOD_VALUES
    assert data["selected_basis"] in BASIS_VALUES
    assert data["status"] in STUDY_STATUS_VALUES
    assert isinstance(data["stale_data_flag"], bool)
    assert isinstance(data["created_by_user_id"], str)
    assert "reviewed_by_user_id" in data
    assert "opinion_id" in data
    for field in (
        "selected_ultimate_cents",
        "selected_ibnr_cents",
        "selected_range_low_cents",
        "selected_range_high_cents",
    ):
        assert field in data, f"study read must carry {field}"
        if data[field] is not None:
            assert isinstance(data[field], int)
    assert "reconciliation_variance_pct" in data


def assert_opinion(data: dict):
    _assert_common_fields(data, "ActuarialOpinion")
    assert isinstance(data["statement_date"], str)
    assert data["opinion_scope"] in OPINION_SCOPE_VALUES
    assert data["status"] in OPINION_STATUS_VALUES
    assert isinstance(data["created_by_user_id"], str)
    assert "signed_by_user_id" in data
    assert "signed_at" in data
    assert isinstance(data["filing_deadline_date"], str)


def assert_roll_forward(data: dict):
    _assert_common_fields(data, "RollForward")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    _assert_quarter_label(data.get("valuation_quarter"), "valuation_quarter")
    _assert_quarter_label(data.get("prior_valuation_quarter"), "prior_valuation_quarter")
    assert data["basis"] in BASIS_VALUES
    assert isinstance(data["expected_emergence_cents"], int)
    assert isinstance(data["actual_emergence_cents"], int)
    assert isinstance(data["ave_variance_cents"], int)
    assert "ave_variance_ratio" in data
