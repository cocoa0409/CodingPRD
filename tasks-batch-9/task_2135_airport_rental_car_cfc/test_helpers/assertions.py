"""Entity assertions and domain invariant checkers."""

import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

# PRD §2.4: ISO 8601 UTC form with three fractional digits.
_ISO8601_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BARE_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# ---------------------------------------------------------------------------
# Shared structural helpers
# ---------------------------------------------------------------------------

def assert_bare_uuid(value) -> None:
    assert isinstance(value, str), f"id must be a string, got {value!r}"
    assert _BARE_UUID_RE.match(value), f"id must be a bare UUID with no prefix, got {value!r}"


def assert_iso8601_millis(value) -> None:
    """ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert _ISO8601_MILLIS_RE.match(value), (
        f"timestamp must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_calendar_date(value) -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"expected a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_versioned_common_fields(data: dict) -> None:
    """Every resource except a shuttle cost allocation line carries all four."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_facility(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "cfc_rate_per_transaction_day_cents",
        "ds_reserve_requirement_cents",
        "om_reserve_requirement_cents",
        "capital_fund_cap_cents",
        "overflow_lot_stalls",
        "overflow_daily_surcharge_cents",
        "remittance_grace_days",
        "trust_lifetime_received_cents",
        "trust_debt_service_reserve_cents",
        "trust_debt_service_funded_cents",
        "trust_om_reserve_cents",
        "trust_capital_fund_cents",
        "trust_unallocated_cents",
        "trust_encumbered_cents",
        "trust_disbursed_cents",
        "funded_obligation_count",
        "overflow_stalls_allocated",
        "overflow_stalls_available",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer cents/count value"
    assert data["bond_coverage_status"] in ("SATISFIED", "DEFICIENT")
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be an ISO 8601 instant"


def assert_concessionaire(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["agreement_count"], int)


def assert_agreement(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["contract_status"] in (
        "DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED",
    )
    assert data["compliance_status"] in ("COMPLIANT", "DELINQUENT", "COVENANT_BREACH")
    assert data["rent_tier"] in ("MAG_FLOOR", "PERCENTAGE")
    assert data["rent_settlement_basis"] in ("CUMULATIVE_YTD", "MONTHLY_STANDALONE")
    assert_calendar_date(data["term_start_date"])
    assert_calendar_date(data["term_end_date"])
    for field in (
        "contract_year_index",
        "mag_annual_cents",
        "percentage_rent_rate_bps",
        "gross_revenue_ytd_cents",
        "transaction_days_ytd",
        "accepted_report_count",
        "percentage_rent_accrued_cents",
        "rent_billed_to_date_cents",
        "last_installment_cents",
        "mag_shortfall_cents",
        "counter_units_assigned",
        "fleet_stalls_allocated",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_counter_space(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["space_class"] in ("COUNTER", "READY_RETURN")
    assert isinstance(data["terminal_code"], str)
    assert isinstance(data["space_label"], str)
    assert isinstance(data["assignment_count"], int)


def assert_counter_assignment(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("ALLOCATED", "ACTIVE", "RELEASED")
    assert_calendar_date(data["effective_start_date"])
    assert_calendar_date(data["effective_end_date"])


def assert_fleet_zone(data: dict) -> None:
    assert_versioned_common_fields(data)
    for field in ("stall_capacity", "stalls_allocated", "stalls_available"):
        assert isinstance(data[field], int)
    assert data["stalls_allocated"] + data["stalls_available"] == data["stall_capacity"], (
        "stalls_allocated + stalls_available must equal stall_capacity"
    )


def assert_fleet_allocation(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("ALLOCATED", "RELEASED")
    assert_calendar_date(data["start_date"])
    assert_calendar_date(data["end_date"])
    for field in (
        "stalls_requested",
        "zone_stalls_granted",
        "overflow_stalls_granted",
        "inclusive_days",
        "overflow_surcharge_cents",
    ):
        assert isinstance(data[field], int)


def assert_report(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_AUDIT", "REJECTED", "ACCEPTED", "SUPERSEDED",
    )
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int)
    assert isinstance(data["reported_gross_revenue_cents"], int)
    assert isinstance(data["reported_on_airport_transaction_days"], int)
    assert isinstance(data["variance_assessment_cents"], int)
    assert isinstance(data["period_rent_installment_cents"], int)
    assert isinstance(data["submission_count"], int)


def assert_remittance(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("PENDING", "DELINQUENT", "RECEIVED", "RECONCILED")
    assert data["remittance_basis"] in ("PROVISIONAL", "FINAL")
    assert_calendar_date(data["due_date"])
    for field in (
        "expected_amount_cents",
        "amount_received_cents",
        "shortfall_cents",
        "allocated_to_debt_service_cents",
        "allocated_to_om_cents",
        "allocated_to_capital_cents",
        "allocated_to_unallocated_cents",
    ):
        assert isinstance(data[field], int)


def assert_obligation(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("SCHEDULED", "FUNDED", "PAID", "DEFERRED")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["coverage_requirement_bps"], int)
    assert isinstance(data["funded_from_reserve_cents"], int)
    assert isinstance(data["auto_funded"], bool)


def assert_shuttle_period(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("OPEN", "ALLOCATED")
    assert data["allocation_basis"] in ("TRANSACTION_DAYS", "GROSS_REVENUE")
    for field in ("total_cost_cents", "total_basis_value", "allocated_total_cents", "line_count"):
        assert isinstance(data[field], int)


def assert_shuttle_allocation_line(data: dict) -> None:
    """PRD §2.4: the line carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "shuttle cost allocation id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a shuttle cost allocation line must not expose updated_at"
    assert "version" not in data, "a shuttle cost allocation line must not expose version"
    for field in ("basis_value", "share_bps", "floor_cents", "remainder_rank", "amount_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_project(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "FUNDED", "CLOSED", "CANCELLED")
    assert isinstance(data["funding_hold"], bool)
    for field in (
        "budget_cents",
        "disbursed_cents",
        "encumbered_cents",
        "draw_request_count",
        "rejected_draw_count",
    ):
        assert isinstance(data[field], int)


def assert_disbursement(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "PAID", "REJECTED", "VOIDED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["requested_by_user_id"], str)


def assert_settlement(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "SETTLED", "SUPERSEDED")
    for field in (
        "contract_year_index",
        "final_percentage_rent_cents",
        "mag_cents",
        "rent_billed_cents",
        "audit_assessment_cents",
        "base_true_up_cents",
        "credit_bps",
        "shuttle_credit_cents",
        "net_true_up_cents",
        "amount_paid_cents",
    ):
        assert isinstance(data[field], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_trust_conservation(facility: dict) -> None:
    """PRD §2.8 conservation identity across the CFC trust ledger.

    Every cent ever received still sits in one of the live buckets, in the
    encumbrance bucket, or has left through `trust_disbursed_cents`.
    """
    live = (
        facility["trust_debt_service_reserve_cents"]
        + facility["trust_debt_service_funded_cents"]
        + facility["trust_om_reserve_cents"]
        + facility["trust_capital_fund_cents"]
        + facility["trust_unallocated_cents"]
        + facility["trust_encumbered_cents"]
        + facility["trust_disbursed_cents"]
    )
    assert live == facility["trust_lifetime_received_cents"], (
        "CFC trust conservation identity broken: buckets sum to "
        f"{live} but trust_lifetime_received_cents is "
        f"{facility['trust_lifetime_received_cents']}"
    )


def assert_bond_coverage_posture(facility: dict) -> None:
    """PRD §2.8: SATISFIED exactly when reserve + funded >= the requirement."""
    coverage = (
        facility["trust_debt_service_reserve_cents"]
        + facility["trust_debt_service_funded_cents"]
    )
    expected = (
        "SATISFIED"
        if coverage >= facility["ds_reserve_requirement_cents"]
        else "DEFICIENT"
    )
    assert facility["bond_coverage_status"] == expected, (
        f"bond_coverage_status should be {expected} with coverage cash {coverage} "
        f"against a requirement of {facility['ds_reserve_requirement_cents']}, "
        f"got {facility['bond_coverage_status']}"
    )


def assert_overflow_stall_identity(facility: dict) -> None:
    """PRD §3.1: overflow_stalls_available is overflow_lot_stalls minus allocated."""
    assert (
        facility["overflow_stalls_available"]
        == facility["overflow_lot_stalls"] - facility["overflow_stalls_allocated"]
    ), "overflow_stalls_available must equal overflow_lot_stalls - overflow_stalls_allocated"


def assert_zone_stall_identity(zone: dict) -> None:
    """PRD §3.1: stalls_available is always stall_capacity minus stalls_allocated."""
    assert zone["stalls_available"] == zone["stall_capacity"] - zone["stalls_allocated"], (
        "stalls_available must equal stall_capacity - stalls_allocated"
    )


def assert_remittance_split_sums_to_receipt(remittance: dict) -> None:
    """PRD §3.6: the four waterfall amounts always sum to the cash received."""
    total = (
        remittance["allocated_to_debt_service_cents"]
        + remittance["allocated_to_om_cents"]
        + remittance["allocated_to_capital_cents"]
        + remittance["allocated_to_unallocated_cents"]
    )
    assert total == remittance["amount_received_cents"], (
        f"waterfall split sums to {total} but amount_received_cents is "
        f"{remittance['amount_received_cents']}"
    )
