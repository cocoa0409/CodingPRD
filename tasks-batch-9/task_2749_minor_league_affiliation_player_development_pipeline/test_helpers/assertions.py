"""Entity shape assertions and domain invariant checkers.

Numeric comparison helpers exist because the PRD fixes the *scale* of each
derived number (PRD 2.8) but not its JSON spelling: `84.50` and `84.5` are the
same number.  Tests therefore compare Decimals at the declared scale rather
than raw strings.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DEFICIENCY_MINOR_MIN_SCORE,
    DEFICIENCY_NONE_MIN_SCORE,
    OPTION_YEARS_TOTAL,
)

# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def as_decimal(value: Any) -> Decimal:
    """Coerce a JSON number or numeric string to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def assert_decimal(actual: Any, expected: str, places: int, field: str = "value") -> None:
    """Assert a derived number equals `expected` at the declared scale."""
    exp = Decimal(expected)
    act = as_decimal(actual)
    quantum = Decimal(1).scaleb(-places)
    assert act.quantize(quantum) == exp.quantize(quantum), (
        f"{field}: expected {exp} but got {actual}"
    )


def assert_money(actual: Any, expected: int, field: str = "amount_cents") -> None:
    """Monetary fields are whole-cent JSON integers, never strings (PRD 2.8)."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be a JSON integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents but got {actual}"


def assert_integer(actual: Any, expected: int, field: str = "count") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} but got {actual}"


def normalize_iso(timestamp: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to millisecond precision for compares."""
    if timestamp is None:
        return None
    text = timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_iso_timestamp(value: Any, field: str = "timestamp") -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 UTC timestamp: {value!r}"


def assert_calendar_date(value: Any, field: str = "date") -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be YYYY-MM-DD, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common-field assertions (PRD 2.4)
# ---------------------------------------------------------------------------


def assert_audit_quartet(row: Dict[str, Any], entity: str = "resource") -> None:
    """Assert the id/created_at/updated_at/version quartet (PRD 2.4)."""
    assert is_valid_uuid(row["id"]), f"{entity}.id is not a bare UUID: {row['id']!r}"
    assert_iso_timestamp(row["created_at"], f"{entity}.created_at")
    assert_iso_timestamp(row["updated_at"], f"{entity}.updated_at")
    assert isinstance(row["version"], int) and row["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {row.get('version')!r}"
    )


def assert_append_only_event(row: Dict[str, Any], entity: str = "workload log") -> None:
    """A workload outing carries only `id` and `created_at` (PRD 2.4)."""
    assert is_valid_uuid(row["id"]), f"{entity}.id is not a bare UUID: {row['id']!r}"
    assert_iso_timestamp(row["created_at"], f"{entity}.created_at")
    assert "updated_at" not in row, f"{entity} must not expose updated_at: {row!r}"
    assert "version" not in row, f"{entity} must not expose version: {row!r}"


def assert_has_fields(row: Dict[str, Any], fields: Iterable[str], entity: str) -> None:
    missing = [f for f in fields if f not in row]
    assert not missing, f"{entity} response is missing fields {missing}: {sorted(row)}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

AFFILIATE_FIELDS = (
    "id", "name", "level", "market_city", "meal_stipend_cents_per_day",
    "roster_limit", "reserve_slots", "housing_beds", "travel_standard_tier",
    "active_roster_count", "rehab_assignment_count", "reserve_list_count",
    "facility_score", "open_major_deficiency_count", "facility_status",
    "created_at", "updated_at", "version",
)

AGREEMENT_FIELDS = (
    "id", "affiliate_id", "term_start_date", "term_end_date",
    "facility_standard_tier", "club_reimbursement_cap_cents",
    "minimum_active_players", "required_staff_roles",
    "housing_expense_cents", "meal_expense_cents", "travel_expense_cents",
    "upkeep_expense_cents", "provisional_club_obligation_cents",
    "final_club_obligation_cents", "affiliate_overflow_cents",
    "settlement_status", "status", "posture", "submitted_by_user_id",
    "created_at", "updated_at", "version",
)

FACILITY_REVIEW_FIELDS = (
    "id", "affiliate_id", "category", "review_date", "score",
    "deficiency_level", "status", "remediation_due_date", "reopen_count",
    "is_overdue", "created_at", "updated_at", "version",
)

STAFF_MEMBER_FIELDS = (
    "id", "full_name", "discipline", "curriculum_version_certified",
    "certification_expires_on", "total_committed_fte_pct", "status",
    "created_at", "updated_at", "version",
)

STAFF_ALLOCATION_FIELDS = (
    "id", "staff_member_id", "affiliate_id", "staff_role", "fte_pct",
    "effective_start", "effective_end", "curriculum_version", "status",
    "created_at", "updated_at", "version",
)

PLAYER_FIELDS = (
    "id", "full_name", "origin", "signed_date", "service_days_accrued",
    "roster_status", "medical_status", "current_affiliate_id",
    "is_on_domestic_reserve_list", "option_years_used",
    "option_years_remaining", "workload_index", "workload_index_projected",
    "promotion_readiness", "created_at", "updated_at", "version",
)

CLEARANCE_FIELDS = (
    "id", "player_id", "clearance_type", "status", "requested_by_user_id",
    "issued_by_user_id", "cleared_workload_ceiling_index", "expires_on",
    "restriction_note", "is_expired", "created_at", "updated_at", "version",
)

ASSIGNMENT_FIELDS = (
    "id", "player_id", "affiliate_id", "assignment_type", "movement_reason",
    "effective_date", "end_date", "level_at_assignment",
    "workload_ceiling_index", "superseded_assignment_id",
    "projected_optional_days", "option_year_charged", "initiated_by_user_id",
    "status", "created_at", "updated_at", "version",
)

PLAN_FIELDS = (
    "id", "assignment_id", "target_level", "curriculum_version",
    "curriculum_modules", "workload_limit_weekly_index",
    "completed_module_count", "completion_pct", "review_cycle_count",
    "revision_note", "status", "created_at", "updated_at", "version",
)

WORKLOAD_LOG_FIELDS = (
    "id", "assignment_id", "log_date", "pitches_thrown", "innings_pitched",
    "high_intensity_minutes", "is_rehab_outing", "created_at",
)

OPTION_YEAR_FIELDS = (
    "id", "triggering_assignment_id", "season_year", "optional_days",
    "charged_at", "status", "created_at", "updated_at", "version",
)

REPORT_FIELDS = (
    "id", "assignment_id", "transaction_type", "status", "filing_deadline",
    "filed_at", "certified_by_user_id", "initiated_by_user_id", "league_note",
    "refile_count", "is_late", "late_fee_cents", "created_at", "updated_at",
    "version",
)

POOL_FIELDS = (
    "id", "season_year", "base_pool_cents", "trade_adjustment_cents",
    "forfeited_cents", "allocated_cents", "overage_tax_accrued_cents",
    "effective_pool_cents", "remaining_cents", "status", "created_at",
    "updated_at", "version",
)

SIGNING_FIELDS = (
    "id", "pool_id", "player_id", "academy_affiliate_id", "bonus_cents",
    "pool_charge_cents", "overage_tax_cents", "tier3_breach",
    "rejection_reason", "approved_by_user_id", "status", "created_at",
    "updated_at", "version",
)


def assert_affiliate(row: Dict[str, Any]) -> None:
    assert_has_fields(row, AFFILIATE_FIELDS, "Affiliate")
    assert_audit_quartet(row, "Affiliate")


def assert_agreement(row: Dict[str, Any]) -> None:
    assert_has_fields(row, AGREEMENT_FIELDS, "AffiliationAgreement")
    assert_audit_quartet(row, "AffiliationAgreement")


def assert_facility_review(row: Dict[str, Any]) -> None:
    assert_has_fields(row, FACILITY_REVIEW_FIELDS, "FacilityStandardReview")
    assert_audit_quartet(row, "FacilityStandardReview")


def assert_staff_member(row: Dict[str, Any]) -> None:
    assert_has_fields(row, STAFF_MEMBER_FIELDS, "StaffMember")
    assert_audit_quartet(row, "StaffMember")


def assert_staff_allocation(row: Dict[str, Any]) -> None:
    assert_has_fields(row, STAFF_ALLOCATION_FIELDS, "StaffAllocation")
    assert_audit_quartet(row, "StaffAllocation")


def assert_player(row: Dict[str, Any]) -> None:
    assert_has_fields(row, PLAYER_FIELDS, "Player")
    assert_audit_quartet(row, "Player")


def assert_medical_clearance(row: Dict[str, Any]) -> None:
    assert_has_fields(row, CLEARANCE_FIELDS, "MedicalClearance")
    assert_audit_quartet(row, "MedicalClearance")


def assert_assignment(row: Dict[str, Any]) -> None:
    assert_has_fields(row, ASSIGNMENT_FIELDS, "PlayerAssignment")
    assert_audit_quartet(row, "PlayerAssignment")


def assert_development_plan(row: Dict[str, Any]) -> None:
    assert_has_fields(row, PLAN_FIELDS, "DevelopmentPlan")
    assert_audit_quartet(row, "DevelopmentPlan")


def assert_workload_log(row: Dict[str, Any]) -> None:
    assert_has_fields(row, WORKLOAD_LOG_FIELDS, "WorkloadLog")
    assert_append_only_event(row, "WorkloadLog")


def assert_option_year_record(row: Dict[str, Any]) -> None:
    assert_has_fields(row, OPTION_YEAR_FIELDS, "OptionYearRecord")
    assert_audit_quartet(row, "OptionYearRecord")


def assert_transaction_report(row: Dict[str, Any]) -> None:
    assert_has_fields(row, REPORT_FIELDS, "TransactionReport")
    assert_audit_quartet(row, "TransactionReport")


def assert_signing_pool(row: Dict[str, Any]) -> None:
    assert_has_fields(row, POOL_FIELDS, "SigningPool")
    assert_audit_quartet(row, "SigningPool")


def assert_international_signing(row: Dict[str, Any]) -> None:
    assert_has_fields(row, SIGNING_FIELDS, "InternationalSigning")
    assert_audit_quartet(row, "InternationalSigning")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_option_year_conservation(player: Dict[str, Any]) -> None:
    """`option_years_used` and `option_years_remaining` always sum to three."""
    used = player["option_years_used"]
    remaining = player["option_years_remaining"]
    assert used + remaining == OPTION_YEARS_TOTAL, (
        f"option_years_used {used} + option_years_remaining {remaining} "
        f"must equal {OPTION_YEARS_TOTAL}"
    )


def assert_pool_ledger_identity(pool: Dict[str, Any]) -> None:
    """`remaining_cents` is the effective pool minus the allocated amount."""
    assert pool["remaining_cents"] == pool["effective_pool_cents"] - pool["allocated_cents"], (
        "remaining_cents must equal effective_pool_cents - allocated_cents, got "
        f"{pool['remaining_cents']} vs {pool['effective_pool_cents']} - {pool['allocated_cents']}"
    )
    expected_effective = (
        pool["base_pool_cents"] + pool["trade_adjustment_cents"] - pool["forfeited_cents"]
    )
    assert pool["effective_pool_cents"] == expected_effective, (
        "effective_pool_cents must equal base + trade adjustment - forfeited, got "
        f"{pool['effective_pool_cents']} vs {expected_effective}"
    )


def assert_deficiency_banding(review: Dict[str, Any]) -> None:
    """A score of 85+ is NONE, 70-84 is MINOR, 69 or below is MAJOR (PRD 2.9)."""
    score = review["score"]
    if score >= DEFICIENCY_NONE_MIN_SCORE:
        expected = "NONE"
    elif score >= DEFICIENCY_MINOR_MIN_SCORE:
        expected = "MINOR"
    else:
        expected = "MAJOR"
    assert review["deficiency_level"] == expected, (
        f"score {score} must band to {expected}, got {review['deficiency_level']}"
    )


def assert_domestic_reserve_flag(player: Dict[str, Any]) -> None:
    """`is_on_domestic_reserve_list` is derived from roster_status and origin."""
    expected = player["origin"] in ("DOMESTIC_DRAFT", "FOREIGN_PRO") and player[
        "roster_status"
    ] in ("RESERVE_LIST", "ACTIVE", "RESTRICTED")
    assert player["is_on_domestic_reserve_list"] is expected, (
        f"is_on_domestic_reserve_list should be {expected} for origin "
        f"{player['origin']} and roster_status {player['roster_status']}"
    )


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """Error bodies carry response_type 'error' and a machine-readable id."""
    assert body.get("response_type") == "error", (
        f"error responses must carry response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data") or {}
    assert data.get("error_id"), f"error response must carry a non-empty error_id: {body!r}"
    assert data.get("message"), f"error response must carry a message: {body!r}"


def assert_status(row: Dict[str, Any], expected: str, entity: str = "resource") -> None:
    assert row["status"] == expected, (
        f"{entity}.status: expected {expected} but got {row['status']}"
    )
