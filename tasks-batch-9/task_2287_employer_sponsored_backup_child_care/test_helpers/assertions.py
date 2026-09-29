"""Entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    OVERAGE_TIER_1_CENTS,
    OVERAGE_TIER_1_MULTIPLIER,
    OVERAGE_TIER_2_CENTS,
    OVERAGE_TIER_2_MULTIPLIER,
    OVERAGE_TIER_3_MULTIPLIER,
    W_CAPACITY,
    W_CONTINUITY,
    W_MODE,
    W_QUALITY,
)

# --------------------------------------------------------------------------
# Shared identity / bookkeeping fields
# --------------------------------------------------------------------------
_VERSIONED_REQUIRED = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_REQUIRED = ("id", "created_at")


def assert_identity_fields(row: Dict[str, Any]) -> None:
    """Server-minted id plus creation timestamp, present on every resource."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert not any(
        row["id"].startswith(p) for p in ("emp_", "pln_", "res_", "prv_", "inv_", "inc_")
    ), f"id carries a type prefix: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"])


def assert_versioned_row(row: Dict[str, Any]) -> None:
    """A resource that carries updated_at and an optimistic version counter."""
    for field in _VERSIONED_REQUIRED:
        assert field in row, f"missing bookkeeping field {field}"
    assert_identity_fields(row)
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """An append-only record: id and created_at only, no updated_at, no version."""
    for field in _APPEND_ONLY_REQUIRED:
        assert field in row, f"missing bookkeeping field {field}"
    assert_identity_fields(row)
    assert "updated_at" not in row, "append-only record must not expose updated_at"
    assert "version" not in row, "append-only record must not expose version"


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def assert_envelope(body: Dict[str, Any], expected_response_type: str) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] == expected_response_type


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == expected_error_id
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    meta = body["meta"]
    assert meta["api_request_id"] is not None
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------
def assert_employer(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "name",
        "industry_code",
        "contract_status",
        "fiscal_year_start_month",
        "invoicing_cycle",
        "admin_fee_pct",
        "overage_billing_enabled",
        "adult_elder_extension_enabled",
        "accrued_overage_cents_current_period",
        "ytd_billed_cents",
    ):
        assert field in row, f"Employer missing {field}"
    assert row["contract_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert row["invoicing_cycle"] in ("MONTHLY", "QUARTERLY")
    assert 1 <= row["fiscal_year_start_month"] <= 12


def assert_benefit_plan(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "employer_id",
        "plan_code",
        "status",
        "annual_use_limit_days",
        "copay_center_cents_per_day",
        "copay_in_home_cents_per_hour",
        "in_home_min_billable_hours",
        "eligible_dependent_types",
        "max_dependents_per_reservation",
        "overage_rate_center_cents_per_day",
        "overage_rate_in_home_cents_per_hour",
        "cancellation_window_hours",
        "no_show_charge_cents",
        "effective_from",
        "superseded_by_plan_id",
        "enrolled_employee_count",
    ):
        assert field in row, f"BenefitPlan missing {field}"
    assert row["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert row["eligible_dependent_types"], "eligible_dependent_types must be non-empty"
    assert len(set(row["eligible_dependent_types"])) == len(row["eligible_dependent_types"])


def assert_employee(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "employer_id",
        "benefit_plan_id",
        "employee_external_id",
        "user_id",
        "email",
        "full_name",
        "employment_status",
        "eligibility_status",
        "entitlement_days_used",
        "entitlement_days_reserved",
        "no_show_strike_count",
    ):
        assert field in row, f"Employee missing {field}"
    assert row["employment_status"] in ("ACTIVE", "LEAVE", "TERMINATED")
    assert row["eligibility_status"] in ("ELIGIBLE", "RESTRICTED", "INELIGIBLE")
    assert "@" in row["email"]


def assert_dependent(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "employee_id",
        "full_name",
        "dependent_type",
        "date_of_birth",
        "relationship",
        "care_notes",
        "status",
    ):
        assert field in row, f"Dependent missing {field}"
    assert row["dependent_type"] in ("CHILD", "ADULT_ELDER")
    assert row["status"] in ("ACTIVE", "INACTIVE")


def assert_provider(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "provider_name",
        "owner_user_id",
        "care_mode",
        "market_code",
        "postal_code",
        "daily_capacity_slots",
        "max_concurrent_assignments",
        "same_day_available",
        "network_status",
        "quality_score",
        "lifetime_quality_score",
        "substantiated_incident_count",
        "completed_reservation_count",
        "last_status_reason_code",
    ):
        assert field in row, f"Provider missing {field}"
    assert row["care_mode"] in ("CENTER_BASED", "IN_HOME")
    assert row["network_status"] in (
        "PENDING",
        "CREDENTIALED",
        "PROBATION",
        "SUSPENDED",
        "DEPROVISIONED",
    )
    assert 0 <= row["quality_score"] <= 100
    assert 0 <= row["lifetime_quality_score"] <= 100


def assert_credential(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in ("provider_id", "credential_type", "issued_on", "expires_on", "verified_by", "status"):
        assert field in row, f"Credential missing {field}"
    assert row["credential_type"] in ("LICENSE", "BACKGROUND_CHECK", "CPR", "INSURANCE")
    assert row["status"] in ("VALID", "EXPIRED", "REVOKED")


def assert_capacity_block(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "provider_id",
        "start_time_utc",
        "end_time_utc",
        "service_date",
        "total_slots",
        "reserved_slots",
        "committed_slots",
        "block_status",
    ):
        assert field in row, f"CapacityBlock missing {field}"
    assert row["block_status"] in ("OPEN", "FULL", "CLOSED")
    assert row["start_time_utc"] < row["end_time_utc"]


def assert_reservation(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "employee_id",
        "benefit_plan_id",
        "plan_version_pinned",
        "requested_care_mode",
        "market_code",
        "care_start_utc",
        "care_end_utc",
        "care_date",
        "dependent_count",
        "dependent_type_mix",
        "required_seats",
        "cancellation_deadline_utc",
        "fulfillment_status",
        "billing_status",
        "matched_provider_id",
        "matched_capacity_block_id",
        "confirmation_code",
        "excluded_provider_ids",
        "billable_hours_provisional",
        "days_charged_provisional",
        "covered_days",
        "overage_days",
        "overage_tier_multiplier",
        "copay_cents",
        "overage_cents",
        "penalty_cents",
    ):
        assert field in row, f"Reservation missing {field}"
    assert row["fulfillment_status"] in (
        "INTAKE",
        "MATCHING",
        "OFFERED",
        "CONFIRMED",
        "IN_SERVICE",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
        "UNFULFILLED",
    )
    assert row["billing_status"] in ("NOT_BILLABLE", "ACCRUED", "INVOICED", "PAID")
    assert row["dependent_type_mix"] in ("CHILD_ONLY", "ADULT_ELDER_ONLY", "MIXED")


def assert_match_offer(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "reservation_id",
        "provider_id",
        "rank_score",
        "rank_position",
        "quality_component",
        "capacity_component",
        "mode_component",
        "continuity_component",
        "probation_penalty_applied",
        "offer_status",
        "offer_expires_at",
    ):
        assert field in row, f"MatchOffer missing {field}"
    assert row["offer_status"] in ("PROPOSED", "SELECTED", "REJECTED", "EXPIRED")
    assert row["rank_position"] >= 1


def assert_employer_invoice(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "employer_id",
        "period_start",
        "period_end",
        "invoice_status",
        "copay_cents",
        "overage_cents",
        "penalty_cents",
        "subtotal_cents",
        "admin_fee_cents",
        "total_cents",
        "line_count",
        "reservation_count",
        "issued_at",
        "paid_amount_cents",
        "void_reason_code",
    ):
        assert field in row, f"EmployerInvoice missing {field}"
    assert row["invoice_status"] in ("DRAFT", "ISSUED", "PAID", "VOID")


def assert_invoice_line(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in (
        "employer_invoice_id",
        "reservation_id",
        "employee_id",
        "line_type",
        "quantity",
        "unit_cents",
        "amount_cents",
    ):
        assert field in row, f"InvoiceLine missing {field}"
    assert row["line_type"] in (
        "CARE_COPAY",
        "CARE_OVERAGE",
        "NO_SHOW_CHARGE",
        "LATE_CANCEL_CHARGE",
    )
    assert row["amount_cents"] != 0, "a line whose amount would be zero is not written at all"


def assert_usage_ledger_entry(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in (
        "employee_id",
        "reservation_id",
        "entry_type",
        "days_delta",
        "cents_delta",
        "benefit_year_start",
        "effective_at",
        "memo",
    ):
        assert field in row, f"UsageLedgerEntry missing {field}"
    assert row["entry_type"] in (
        "RESERVE",
        "COMMIT",
        "RELEASE",
        "OVERAGE_ACCRUE",
        "OVERAGE_REVERSE",
        "NO_SHOW_CHARGE",
        "LATE_CANCEL_CHARGE",
    )


def assert_incident_report(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "provider_id",
        "severity",
        "category",
        "narrative",
        "incident_status",
        "qa_action",
        "reported_at",
        "reported_by_user_id",
        "reviewed_by",
        "resolution_reason_code",
    ):
        assert field in row, f"IncidentReport missing {field}"
    assert row["incident_status"] in ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
    assert row["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert row["qa_action"] in ("NONE", "PROBATION", "SUSPENSION", "DEPROVISION")


def assert_entitlement_projection(row: Dict[str, Any]) -> None:
    for field in (
        "employee_id",
        "benefit_year_start",
        "benefit_year_end",
        "days_limit",
        "days_used",
        "days_reserved",
        "days_remaining",
        "overage_days_projected",
        "no_show_strike_count",
        "eligibility_status",
    ):
        assert field in row, f"entitlement projection missing {field}"
    assert row["days_remaining"] >= 0, "days_remaining never goes below zero"
    assert row["overage_days_projected"] >= 0, "overage_days_projected never goes below zero"


def assert_utilization_report(row: Dict[str, Any]) -> None:
    for field in (
        "employer_id",
        "period_start",
        "period_end",
        "reservations_confirmed",
        "reservations_completed",
        "no_show_count",
        "days_used",
        "days_overage",
        "unique_employees_served",
        "center_share_pct",
        "in_home_share_pct",
        "no_show_rate_pct",
        "min_provider_lifetime_score",
        "renewal_risk_band",
    ):
        assert field in row, f"utilization report missing {field}"
    assert row["renewal_risk_band"] in ("LOW", "MEDIUM", "HIGH")


def assert_maintenance_counters(row: Dict[str, Any]) -> None:
    """The sweep returns exactly the seven declared counters."""
    expected = {
        "credentials_expired",
        "providers_suspended",
        "reservations_unfulfilled",
        "offers_expired",
        "blocks_closed",
        "reservations_no_showed",
        "reservations_withdrawn",
    }
    assert set(row.keys()) == expected, f"unexpected counter set: {sorted(row.keys())}"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_ledger_sequence(entries: List[Dict[str, Any]], expected_types: List[str]) -> None:
    """Ledger rows appear in the given order and no others exist."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == expected_types, f"ledger order {actual} != expected {expected_types}"


def assert_ledger_memos(entries: List[Dict[str, Any]], expected_memos: List[str]) -> None:
    actual = [entry["memo"] for entry in entries]
    assert actual == expected_memos, f"ledger memos {actual} != expected {expected_memos}"


def assert_employee_days_reconcile(
    employee: Dict[str, Any], entries: List[Dict[str, Any]]
) -> None:
    """Employee counters equal the ledger they are derived from."""
    used = sum(e["days_delta"] for e in entries if e["entry_type"] == "COMMIT")
    reserved = sum(
        e["days_delta"] for e in entries if e["entry_type"] in ("RESERVE", "RELEASE")
    )
    assert employee["entitlement_days_used"] == pytest.approx(used, abs=0.01)
    assert employee["entitlement_days_reserved"] == pytest.approx(reserved, abs=0.01)


def assert_block_seats_reconcile(
    block: Dict[str, Any], reserved_seats: int, committed_seats: int
) -> None:
    assert block["reserved_slots"] == reserved_seats
    assert block["committed_slots"] == committed_seats


def assert_invoice_totals(invoice: Dict[str, Any], admin_fee_pct: float) -> None:
    """subtotal + admin fee == total, with the fee derived from the integer subtotal."""
    expected_fee = round_half_up(invoice["subtotal_cents"] * admin_fee_pct)
    assert invoice["admin_fee_cents"] == expected_fee
    assert invoice["total_cents"] == invoice["subtotal_cents"] + invoice["admin_fee_cents"]


def assert_lines_sum_to_subtotal(
    lines: List[Dict[str, Any]], subtotal_cents: int
) -> None:
    """Each line is rounded first, then summed."""
    assert sum(line["amount_cents"] for line in lines) == subtotal_cents


def round_half_up(value: float) -> int:
    """Round to the nearest integer with ties going away from zero."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_to_quarter_hour(hours: float) -> float:
    """Raise a raw duration to the next quarter hour; an exact multiple stays put."""
    import math

    return math.ceil(round(hours * 4, 6)) / 4


def expected_overage_multiplier(accrued_cents_before: int) -> float:
    """The tier snapshot read before this reservation's own accrual."""
    if accrued_cents_before < OVERAGE_TIER_1_CENTS:
        return OVERAGE_TIER_1_MULTIPLIER
    if accrued_cents_before < OVERAGE_TIER_2_CENTS:
        return OVERAGE_TIER_2_MULTIPLIER
    return OVERAGE_TIER_3_MULTIPLIER


def expected_rank_score(
    quality_component: float,
    capacity_component: float,
    mode_component: float,
    continuity_component: float,
    probation: bool = False,
) -> float:
    """The weighted blend, halved on probation, at four decimal places."""
    raw = (
        W_QUALITY * quality_component
        + W_CAPACITY * capacity_component
        + W_MODE * mode_component
        + W_CONTINUITY * continuity_component
    )
    if probation:
        raw *= 0.5
    return round(raw, 4)


def assert_rank_components(
    offer: Dict[str, Any],
    quality: float,
    capacity: float,
    mode: float,
    continuity: float,
    probation: bool = False,
) -> None:
    assert offer["quality_component"] == pytest.approx(quality, abs=0.0001)
    assert offer["capacity_component"] == pytest.approx(capacity, abs=0.0001)
    assert offer["mode_component"] == pytest.approx(mode, abs=0.0001)
    assert offer["continuity_component"] == pytest.approx(continuity, abs=0.0001)
    assert offer["probation_penalty_applied"] is probation
    assert offer["rank_score"] == pytest.approx(
        expected_rank_score(quality, capacity, mode, continuity, probation), abs=0.0001
    )


def assert_offer_ordering(offers: List[Dict[str, Any]]) -> None:
    """Offers descend by rank_score and carry contiguous 1-based positions."""
    positions = [offer["rank_position"] for offer in offers]
    assert positions == list(range(1, len(offers) + 1)), f"positions not contiguous: {positions}"
    scores = [offer["rank_score"] for offer in offers]
    assert scores == sorted(scores, reverse=True), f"rank scores not descending: {scores}"


def assert_cents_conservation(
    entries: List[Dict[str, Any]], expected_total: int
) -> None:
    """The money side of the ledger is untouched by invoicing."""
    assert sum(e["cents_delta"] for e in entries) == expected_total


def assert_ordered_by(
    rows: List[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows not ordered by {field}: {values}"


def find_offer_for_provider(
    offers: List[Dict[str, Any]], provider_id: str
) -> Optional[Dict[str, Any]]:
    for offer in offers:
        if offer["provider_id"] == provider_id:
            return offer
    return None
