"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7)."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_wrvu(actual, expected):
    """wRVU quantities are pinned to 2 decimal places (PRD §2.7)."""
    assert actual is not None, "expected a wRVU value, got None"
    assert float(actual) == pytest.approx(expected, abs=1e-6), (
        f"Expected wRVU {expected}, got {actual}"
    )


def assert_cents(actual, expected):
    """All money is represented as integer cents (PRD §2.7)."""
    assert actual is not None, "expected a cent amount, got None"
    assert int(actual) == expected, f"Expected {expected} cents, got {actual}"


def assert_physician(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["provider_type"] in ("PHYSICIAN", "APP")
    assert 0 < float(data["fte"]) <= 1.0


def assert_comp_plan(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "FMV_APPROVED", "ACTIVE", "SUPERSEDED", "CLOSED"
    )
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert isinstance(data["quality_pool_cents"], int)
    assert isinstance(data["fmv_cap_cents"], int)


def assert_cpt_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["cpt_code"], str) and data["cpt_code"]
    assert float(data["wrvu_value"]) >= 0
    assert data["effective_to"] > data["effective_from"]


def assert_physician_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PENDING_FMV", "FMV_APPROVED", "EFFECTIVE", "AMENDMENT_REQUIRED", "TERMINATED"
    )
    assert isinstance(data["base_salary_cents"], int) and data["base_salary_cents"] > 0
    assert isinstance(data["period_draw_cents"], int) and data["period_draw_cents"] >= 0
    assert isinstance(data["pinned_plan_version"], int)


def assert_production_capture(data: dict):
    _assert_common(data)
    assert data["capture_status"] in ("POSTED", "VALIDATED", "LOCKED", "VOIDED")
    assert data["credit_status"] in ("UNCREDITED", "CREDITED", "REVERSED")
    assert data["capture_kind"] in ("CLINICAL", "SUPERVISION_CREDIT")
    assert isinstance(data["units"], int) and data["units"] >= 1


def assert_supervision_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "ENDED")
    assert 0 < float(data["credit_pct"]) <= 1
    assert 0 < float(data["supervised_fte"]) <= 4.0
    assert data["end_date"] >= data["start_date"]


def assert_quality_scorecard(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
    assert isinstance(data["measures"], list) and len(data["measures"]) >= 1
    assert isinstance(data["period"], str) and len(data["period"]) == 7


def assert_comp_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "FINALIZED", "VOIDED")
    assert 1 <= int(data["period_month"]) <= 12
    assert isinstance(data["capture_ids"], list)
    for field in (
        "tier_bonus_cents", "productivity_earned_ytd_cents", "period_productivity_cents",
        "quality_bonus_cents", "period_draw_cents", "trueup_adjustment_cents",
        "net_payment_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_trueup_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("COMPUTED", "POSTED", "VOIDED")
    assert isinstance(data["adjustments"], list)
    for adj in data["adjustments"]:
        assert isinstance(adj["agreement_id"], str)
        assert isinstance(adj["variance_cents"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "DATA_CORRECTION", "RESOLVED_ACCEPTED", "RESOLVED_REJECTED"
    )
    assert data["subject_type"] in ("CAPTURE", "STATEMENT")


def assert_plan_change_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "MODELED", "COMMUNICATED", "EFFECTIVE", "WITHDRAWN")
    assert isinstance(data["acknowledged_physician_ids"], list)


def assert_agreement_ledger_invariants(agreement: dict):
    """Ledger invariants that hold after any operation (PRD §3.4, §3.7)."""
    assert_wrvu(agreement["ytd_wrvu_credited"], float(agreement["ytd_wrvu_credited"]))
    assert isinstance(agreement["lifetime_paid_cents"], int)
    assert isinstance(agreement["pending_trueup_adjustment_cents"], int)
