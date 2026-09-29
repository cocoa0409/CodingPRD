"""Entity assertions and domain invariant checkers for the SFSP API.

Each ``assert_<entity>`` checks the identity and timestamp contract the PRD states for every row,
plus enum membership for the entity's status fields. Fields the PRD only mentions inside a formula
are type-checked when present rather than demanded, so a faithful implementation is never failed
for a serializer choice the PRD leaves open.
"""

from typing import Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActionOrigin,
    ActionStatus,
    AdvanceStatus,
    AreaDataSource,
    BudgetStatus,
    ClaimStatus,
    CountEntryKind,
    DisallowReason,
    EditCheckStatus,
    EligibilityBasis,
    FindingSeverity,
    FoodSafetyStatus,
    MealType,
    ProductionMode,
    RateClass,
    ServiceDayStatus,
    SiteApprovalStatus,
    SiteOperatingStatus,
    SponsorApplicationStatus,
    SponsorType,
    TemperatureClass,
    VisitStatus,
    VisitType,
)

MEAL_TYPES = [m.value for m in MealType]


def _values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_identity_fields(data: dict) -> None:
    """Every record carries a server-minted UUID id and an ISO 8601 UTC created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )


def assert_versioned_row(data: dict) -> None:
    """Rows that carry the row-versioning fields: updated_at plus a version starting at 1."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_row(data: dict) -> None:
    """Append-only rows carry id and created_at and neither updated_at nor version."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "append-only rows must not carry updated_at"
    assert "version" not in data, "append-only rows must not carry version"


def assert_integer_cents(value, field_name: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


# --- Per-entity assertions ---------------------------------------------------


def assert_sponsor(data: dict) -> None:
    assert_versioned_row(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["sponsor_type"] in _values(SponsorType)
    assert data["experience_status"] in ("NEW", "EXPERIENCED")
    assert isinstance(data["program_year"], int)
    assert data["application_status"] in _values(SponsorApplicationStatus)
    for ledger_field in (
        "advance_paid_cents",
        "advance_recovered_cents",
        "advance_outstanding_cents",
        "reimbursement_paid_cents",
    ):
        assert_integer_cents(data[ledger_field], ledger_field)
        assert data[ledger_field] >= 0, f"{ledger_field} must never go negative"


def assert_area_eligibility_record(data: dict) -> None:
    assert_append_only_row(data)
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert data["data_source"] in _values(AreaDataSource)
    assert isinstance(data["free_reduced_pct"], (int, float))
    assert isinstance(data["determination_date"], str)
    assert isinstance(data["valid_through_date"], str)


def assert_sponsor_budget(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(BudgetStatus)
    assert_integer_cents(data["operating_cost_budget_cents"], "operating_cost_budget_cents")
    assert_integer_cents(data["admin_cost_budget_cents"], "admin_cost_budget_cents")
    assert isinstance(data["projected_total_meals"], int)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_advance_payment(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(AdvanceStatus)
    assert isinstance(data["request_month"], str)
    assert_integer_cents(data["requested_amount_cents"], "requested_amount_cents")
    assert_integer_cents(data["recovered_amount_cents"], "recovered_amount_cents")
    if data.get("approved_amount_cents") is not None:
        assert_integer_cents(data["approved_amount_cents"], "approved_amount_cents")


def assert_site(data: dict) -> None:
    assert_versioned_row(data)
    assert data["approval_status"] in _values(SiteApprovalStatus)
    assert data["operating_status"] in _values(SiteOperatingStatus)
    assert data["eligibility_basis"] in _values(EligibilityBasis)
    assert data["production_mode"] in _values(ProductionMode)
    assert isinstance(data["approved_meal_types"], list) and data["approved_meal_types"]
    for meal_type in data["approved_meal_types"]:
        assert meal_type in MEAL_TYPES, f"{meal_type} is not a PRD meal type"
    assert isinstance(data["approved_max_attendance"], int)
    assert isinstance(data["claim_hold"], bool)
    assert isinstance(data["compliance_flag_count"], int) and data["compliance_flag_count"] >= 0
    assert isinstance(data["voided_day_count"], int) and data["voided_day_count"] >= 0


def assert_meal_service_day(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(ServiceDayStatus)
    assert data["food_safety_status"] in _values(FoodSafetyStatus)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["meal_services"], list)
    for service in data["meal_services"]:
        assert service["meal_type"] in MEAL_TYPES
        assert isinstance(service["planned_meals"], int)
    for counter in (
        "counted_first_meals",
        "counted_second_meals",
        "counted_adult_meals",
        "reimbursable_meals",
        "non_reimbursable_meals",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer meal count"


def assert_meal_count_entry(data: dict) -> None:
    assert_append_only_row(data)
    assert data["meal_type"] in MEAL_TYPES
    assert data["entry_kind"] in _values(CountEntryKind)
    for counter in ("first_meals", "second_meals", "adult_meals"):
        assert isinstance(data[counter], int)
    for counter in ("reimbursable_first_meals", "reimbursable_second_meals",
                    "non_reimbursable_meals"):
        assert isinstance(data[counter], int), f"{counter} must be an integer meal count"


def assert_holding_log_entry(data: dict) -> None:
    assert_append_only_row(data)
    assert data["meal_type"] in MEAL_TYPES
    assert data["temperature_class"] in _values(TemperatureClass)
    assert isinstance(data["temperature_f"], (int, float))
    assert isinstance(data["holding_minutes"], int)
    assert isinstance(data["breach_flag"], bool)
    if data["breach_flag"]:
        assert data["breach_reason"] in ("TEMP_OUT_OF_BAND", "HOLDING_TIME_EXCEEDED")
    else:
        assert data.get("breach_reason") is None


def assert_monitoring_visit(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(VisitStatus)
    assert data["visit_type"] in _values(VisitType)
    # The PRD writes highest_severity only when the report is filed (NONE on the no-deficiency
    # branch, the greatest finding severity otherwise), and says nothing about its value on a
    # visit that has not yet reported, so the enum is checked only once the field carries a value.
    if data.get("highest_severity") is not None:
        assert data["highest_severity"] in _values(FindingSeverity)
    assert isinstance(data["monitor_user_id"], str) and data["monitor_user_id"]
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["is_late"], bool)


def assert_corrective_action(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(ActionStatus)
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["origin"] in _values(ActionOrigin)
    assert isinstance(data["finding_code"], str) and data["finding_code"]
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_meal_claim(data: dict) -> None:
    assert_versioned_row(data)
    assert data["status"] in _values(ClaimStatus)
    assert isinstance(data["claim_month"], str)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    if data.get("meals_rate_value_cents") is not None:
        assert_integer_cents(data["meals_rate_value_cents"], "meals_rate_value_cents")
    for money_field in ("preliminary_reimbursement_cents", "final_reimbursement_cents",
                        "advance_offset_cents", "net_payable_cents"):
        if data.get(money_field) is not None:
            assert_integer_cents(data[money_field], money_field)


def assert_claim_line_item(data: dict) -> None:
    assert_versioned_row(data)
    assert data["rate_class"] in _values(RateClass)
    assert data["edit_check_status"] in _values(EditCheckStatus)
    assert data["disallow_reason"] in _values(DisallowReason)
    assert_integer_cents(data["meals_rate_value_cents"], "meals_rate_value_cents")
    assert isinstance(data["finalized_day_count"], int)
    assert isinstance(data["hold_flag"], bool)


# --- Domain invariant checkers ----------------------------------------------


def assert_advance_ledger_conserved(sponsor: dict, advances: Iterable[dict]) -> None:
    """A sponsor's outstanding advance balance equals the sum of the unrecovered parts of its
    disbursed, partially recovered and recovered advances."""
    outstanding_states = ("DISBURSED", "PARTIALLY_RECOVERED", "RECOVERED", "DEMAND_ISSUED")
    expected = sum(
        (advance["approved_amount_cents"] or 0) - advance["recovered_amount_cents"]
        for advance in advances
        if advance["status"] in outstanding_states
    )
    assert sponsor["advance_outstanding_cents"] == expected, (
        "advance_outstanding_cents must equal the sum of approved minus recovered amounts, "
        f"expected {expected}, got {sponsor['advance_outstanding_cents']}"
    )


def assert_day_totals_match_entries(day: dict, entries: List[dict]) -> None:
    """A service day's counted totals equal the signed sums of its meal count entry rows."""
    expected_first = sum(entry["reimbursable_first_meals"] for entry in entries)
    expected_second = sum(entry["reimbursable_second_meals"] for entry in entries)
    assert day["counted_first_meals"] == expected_first, (
        f"counted_first_meals {day['counted_first_meals']} != signed entry sum {expected_first}"
    )
    assert day["counted_second_meals"] == expected_second, (
        f"counted_second_meals {day['counted_second_meals']} != signed entry sum {expected_second}"
    )


def assert_admin_cap_respected(operating_reimbursement_cents: int,
                               admin_reimbursement_cents: int) -> None:
    """The administrative share of a claim never exceeds twenty percent of the operating share,
    the cap being taken as a floored integer number of cents."""
    cap = int(0.20 * operating_reimbursement_cents)
    assert admin_reimbursement_cents <= cap, (
        f"admin reimbursement {admin_reimbursement_cents} exceeds the floored cap {cap}"
    )


def assert_no_version_field(data: dict) -> None:
    """For append-only rows the PRD says carry neither updated_at nor version."""
    assert "version" not in data, "this row must not expose a version"
    assert "updated_at" not in data, "this row must not expose an updated_at"


def assert_status(data: dict, expected_status: str, field: str = "status") -> None:
    assert data[field] == expected_status, (
        f"expected {field} {expected_status}, got {data[field]}"
    )


def assert_pagination_meta(meta: Dict, expected_total: int, expected_has_more: bool,
                           expected_limit: Optional[int] = None,
                           expected_offset: Optional[int] = None) -> None:
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"expected has_more {expected_has_more}, got {meta['has_more']}"
    )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
