"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {data.get('version')!r}"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["base_hourly_rate"] > 0
    assert data["live_in_day_rate"] > 0


def assert_caregiver(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["background_tier"] in (
        "PENDING", "TIER_1", "TIER_2", "TIER_3", "REVOKED"
    )
    assert data["employment_status"] in (
        "APPLICANT", "ACTIVE", "SUSPENDED", "TERMINATED"
    )


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("INTAKE", "ACTIVE", "ON_HOLD", "DISCHARGED")
    assert 0 <= data["continuity_score"] <= 1, \
        f"continuity_score must be in [0,1], got {data['continuity_score']}"


def assert_care_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["task_count"], int) and data["task_count"] >= 0


def assert_care_task(data: dict):
    _assert_common(data)
    assert data["category"] in ("ADL", "IADL")
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_match(data: dict):
    _assert_common(data)
    assert data["match_status"] in ("PROPOSED", "ACTIVE", "ENDED")
    assert data["continuity_status"] in ("STANDARD", "PREFERRED", "BROKEN")


def assert_visit(data: dict):
    _assert_common(data)
    assert data["billing_mode"] in ("HOURLY", "LIVE_IN")
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "IN_PROGRESS", "COMPLETED", "CANCELLED", "MISSED"
    )
    assert isinstance(data["billable_minutes"], int)
    assert_cost_precision(data["visit_charge"])


def assert_mileage(data: dict):
    _assert_common(data)
    assert data["miles"] > 0
    assert data["status"] in ("RECORDED", "VOIDED")
    assert_cost_precision(data["line_charge"])


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOID")
    assert_cost_precision(data["labor_total"])
    assert_cost_precision(data["mileage_total"])
    assert_cost_precision(data["invoice_total"])
    assert_cost_precision(data["client_responsible_amount"])


def assert_invoice_totals_consistent(data: dict):
    """invoice_total is labor_total + mileage_total (PRD section 3.9)."""
    expected = round(data["labor_total"] + data["mileage_total"], 2)
    assert abs(data["invoice_total"] - expected) < 0.005, \
        f"invoice_total {data['invoice_total']} != labor+mileage {expected}"


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "APPEALED", "PAID"
    )
    assert_cost_precision(data["covered_amount"])
