"""Entity assertions and domain invariant checkers for the Chargemaster Governance API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ChargemasterPosture, TransparencyStatus, RoundingMode, DuplicateDetectionMode,
    RevenueCodeStatus, PricingClass, CodeType, ItemLifecycleStatus, ItemPriceStatus,
    PricingMethod, PriceRuleStatus, RequestType, ChangeRequestStatus, CycleStatus,
    CodeSet, EntryAction, EntryStatus, ProductLine, ReimbursementMethod, ContractStatus,
    BatchStatus, MatchStatus, FindingStatus, AnalysisVariant, AnalysisStatus,
    FileFormat, TransparencyFileStatus,
)

_FULL_COMMON = ("id", "created_at", "updated_at", "version")


def _assert_common(data: dict, entity: str):
    for key in _FULL_COMMON:
        assert key in data, f"{entity} must expose '{key}'"
    assert is_valid_uuid(data["id"]), f"{entity}.id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data["created_at"]), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data["updated_at"]), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def _assert_narrow_common(data: dict, entity: str):
    """Reference data and append-only lines carry only id and created_at."""
    assert is_valid_uuid(data["id"]), f"{entity}.id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data["created_at"]), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def _enum(data, field, enum_cls, entity):
    assert data.get(field) in [e.value for e in enum_cls], (
        f"{entity}.{field} must be one of {[e.value for e in enum_cls]}, got {data.get(field)!r}"
    )


def assert_facility(data: dict):
    _assert_common(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cms_certification_number"], str)
    _enum(data, "rounding_mode", RoundingMode, "Facility")
    _enum(data, "duplicate_detection_mode", DuplicateDetectionMode, "Facility")
    _enum(data, "chargemaster_posture", ChargemasterPosture, "Facility")
    _enum(data, "transparency_status", TransparencyStatus, "Facility")
    for f in (
        "aggregate_markup_limit_bp", "volume_growth_bp", "impact_lookback_days",
        "active_item_count", "aggregate_gross_charge_cents", "aggregate_cost_basis_cents",
        "aggregate_markup_ratio_bp", "stale_price_item_count",
    ):
        assert isinstance(data[f], int), f"Facility.{f} must be an integer"
    assert "published_transparency_file_id" in data


def assert_department(data: dict):
    _assert_common(data, "Department")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["cost_center_code"], str)
    assert isinstance(data["manager_user_id"], str)
    assert isinstance(data["capture_hold"], bool)
    for f in ("unresolved_finding_amount_cents", "recovered_charge_cents", "open_request_count"):
        assert isinstance(data[f], int), f"Department.{f} must be an integer"
    assert isinstance(data["allowed_revenue_code_values"], list)


def assert_revenue_code(data: dict):
    _assert_narrow_common(data, "RevenueCode")
    assert isinstance(data["code"], str) and len(data["code"]) == 4
    assert isinstance(data["description"], str)
    assert isinstance(data["requires_hcpcs"], bool)
    assert isinstance(data["allowed_code_types"], list)
    _enum(data, "status", RevenueCodeStatus, "RevenueCode")
    _enum(data, "pricing_class", PricingClass, "RevenueCode")


def assert_charge_item(data: dict):
    _assert_common(data, "ChargeItem")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["department_id"], str)
    assert isinstance(data["revenue_code_id"], str)
    assert isinstance(data["cdm_number"], str)
    assert isinstance(data["description"], str)
    _enum(data, "code_type", CodeType, "ChargeItem")
    _enum(data, "lifecycle_status", ItemLifecycleStatus, "ChargeItem")
    _enum(data, "price_status", ItemPriceStatus, "ChargeItem")
    for f in (
        "cost_basis_cents", "medicare_rate_cents", "market_p75_cents",
        "gross_charge_cents", "prior_gross_charge_cents", "companion_window_hours",
    ):
        assert isinstance(data[f], int), f"ChargeItem.{f} must be an integer"
    assert isinstance(data["price_conflict"], bool)
    assert is_iso8601_timestamp(data["effective_from"]), "ChargeItem.effective_from must be ISO 8601"
    for f in (
        "duplicate_of_item_id", "companion_required_item_id", "applied_price_rule_id",
        "approved_by_user_id", "last_code_cycle_id", "code_value",
    ):
        assert f in data, f"ChargeItem must expose '{f}'"


def assert_price_rule(data: dict):
    _assert_common(data, "PriceRule")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["revenue_code_id"], str)
    _enum(data, "pricing_method", PricingMethod, "PriceRule")
    _enum(data, "status", PriceRuleStatus, "PriceRule")
    assert isinstance(data["min_medicare_multiple_bp"], int)
    assert isinstance(data["market_cap_multiple_bp"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert "effective_to" in data
    assert "superseded_by_rule_id" in data
    assert isinstance(data["applied_item_count"], int)


def assert_change_request(data: dict):
    _assert_common(data, "ChangeRequest")
    assert isinstance(data["department_id"], str)
    assert isinstance(data["charge_item_id"], str)
    _enum(data, "request_type", RequestType, "ChangeRequest")
    _enum(data, "status", ChangeRequestStatus, "ChangeRequest")
    assert isinstance(data["revision_round"], int)
    assert isinstance(data["justification"], str) and len(data["justification"]) >= 10
    assert isinstance(data["submitted_by_user_id"], str)
    for f in (
        "reviewed_by_user_id", "approved_by_user_id", "pinned_charge_item_version",
        "decision_note", "proposed_cost_basis_cents", "proposed_revenue_code_id",
        "proposed_description",
    ):
        assert f in data, f"ChangeRequest must expose '{f}'"
    assert isinstance(data["projected_gross_charge_cents"], int)
    assert isinstance(data["projected_markup_ratio_bp"], int)


def assert_code_update_cycle(data: dict):
    _assert_common(data, "CodeUpdateCycle")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["cycle_year"], int)
    _enum(data, "code_set", CodeSet, "CodeUpdateCycle")
    _enum(data, "status", CycleStatus, "CodeUpdateCycle")
    assert isinstance(data["cost_inflator_bp"], int)
    for f in ("entry_count", "unmapped_entry_count", "applied_entry_count"):
        assert isinstance(data[f], int), f"CodeUpdateCycle.{f} must be an integer"
    for f in (
        "pre_activation_active_item_count", "pre_activation_aggregate_gross_charge_cents",
        "activated_at", "rolled_back_at",
    ):
        assert f in data, f"CodeUpdateCycle must expose '{f}'"


def assert_code_update_entry(data: dict):
    _assert_common(data, "CodeUpdateEntry")
    assert isinstance(data["cycle_id"], str)
    _enum(data, "action", EntryAction, "CodeUpdateEntry")
    _enum(data, "status", EntryStatus, "CodeUpdateEntry")
    for f in (
        "old_code_value", "new_code_value", "target_charge_item_id", "new_revenue_code_id",
        "carried_gross_charge_cents", "prior_code_value", "prior_gross_charge_cents",
        "prior_revenue_code_id", "prior_lifecycle_status", "defer_reason", "mapped_by_user_id",
    ):
        assert f in data, f"CodeUpdateEntry must expose '{f}'"


def assert_payer_contract(data: dict):
    _assert_common(data, "PayerContract")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["payer_code"], str)
    _enum(data, "product_line", ProductLine, "PayerContract")
    _enum(data, "reimbursement_method", ReimbursementMethod, "PayerContract")
    _enum(data, "status", ContractStatus, "PayerContract")
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert isinstance(data["trailing_units"], int)
    assert isinstance(data["renegotiation_notice_days"], int)


def assert_charge_capture_batch(data: dict):
    _assert_common(data, "ChargeCaptureBatch")
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["department_id"], str)
    _enum(data, "status", BatchStatus, "ChargeCaptureBatch")
    for f in (
        "line_count", "matched_line_count", "exception_line_count",
        "total_expected_charge_cents", "total_posted_charge_cents", "open_finding_count",
        "reconcile_pass_count",
    ):
        assert isinstance(data[f], int), f"ChargeCaptureBatch.{f} must be an integer"
    assert "mean_line_variance_bp" in data
    assert is_iso8601_timestamp(data["window_start_date"])
    assert is_iso8601_timestamp(data["window_end_date"])


def assert_captured_charge(data: dict):
    _assert_narrow_common(data, "CapturedCharge")
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["submitted_cdm_number"], str)
    assert isinstance(data["encounter_id"], str)
    assert isinstance(data["payer_code"], str)
    assert is_iso8601_timestamp(data["service_datetime"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["posted_charge_cents"], int)
    _enum(data, "match_status", MatchStatus, "CapturedCharge")
    assert "charge_item_id" in data
    assert "expected_charge_cents" in data
    assert "line_variance_bp" in data


def assert_missing_charge_finding(data: dict):
    _assert_common(data, "MissingChargeFinding")
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["department_id"], str)
    assert isinstance(data["trigger_captured_charge_id"], str)
    assert isinstance(data["expected_charge_item_id"], str)
    assert isinstance(data["estimated_lost_charge_cents"], int)
    _enum(data, "status", FindingStatus, "MissingChargeFinding")
    assert "disposition_note" in data
    assert "recovery_captured_charge_id" in data


def assert_price_change_analysis(data: dict):
    _assert_common(data, "PriceChangeImpactAnalysis")
    assert isinstance(data["change_request_id"], str)
    _enum(data, "variant", AnalysisVariant, "PriceChangeImpactAnalysis")
    _enum(data, "status", AnalysisStatus, "PriceChangeImpactAnalysis")
    assert isinstance(data["analysed_charge_item_version"], int)
    assert isinstance(data["old_gross_charge_cents"], int)
    assert isinstance(data["new_gross_charge_cents"], int)
    assert isinstance(data["payer_lines"], list)
    assert isinstance(data["total_reimbursement_delta_cents"], int)
    assert "signed_off_by_user_id" in data


def assert_transparency_file(data: dict):
    _assert_common(data, "TransparencyFile")
    assert isinstance(data["facility_id"], str)
    _enum(data, "file_format", FileFormat, "TransparencyFile")
    _enum(data, "status", TransparencyFileStatus, "TransparencyFile")
    assert isinstance(data["included_item_count"], int)
    assert isinstance(data["total_gross_charge_cents"], int)
    assert isinstance(data["payer_column_count"], int)
    assert isinstance(data["validation_errors"], list)
    assert "content_hash" in data
    assert "published_at" in data
    assert "superseded_by_file_id" in data


# --------------------------- Domain invariants ---------------------------

def assert_facility_aggregate_invariants(facility: dict):
    """Aggregates are derived from persisted ACTIVE items and are never negative."""
    assert facility["active_item_count"] >= 0
    assert facility["aggregate_gross_charge_cents"] >= 0
    assert facility["aggregate_cost_basis_cents"] >= 0
    assert facility["stale_price_item_count"] >= 0
    if facility["aggregate_cost_basis_cents"] == 0:
        assert facility["aggregate_markup_ratio_bp"] == 0, (
            "aggregate_markup_ratio_bp is defined as 0 when the aggregate cost basis is 0"
        )
    else:
        expected = round_half_up_div(
            facility["aggregate_gross_charge_cents"] * 10000,
            facility["aggregate_cost_basis_cents"],
        )
        assert facility["aggregate_markup_ratio_bp"] == expected, (
            f"aggregate_markup_ratio_bp should be {expected}, "
            f"got {facility['aggregate_markup_ratio_bp']}"
        )


def assert_department_leakage_conserved(department: dict, expected_total: int):
    """unresolved + recovered always equals the sum over CONFIRMED and RESOLVED findings."""
    actual = department["unresolved_finding_amount_cents"] + department["recovered_charge_cents"]
    assert actual == expected_total, (
        f"Department leakage must be conserved: unresolved "
        f"{department['unresolved_finding_amount_cents']} + recovered "
        f"{department['recovered_charge_cents']} = {actual}, expected {expected_total}"
    )


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half away from zero, as the PRD's rounding discipline demands."""
    assert denominator != 0
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    n, d = abs(numerator), abs(denominator)
    return sign * ((2 * n + d) // (2 * d))
