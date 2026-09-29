"""Entity assertions and domain invariant checkers for the warranty service."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import THRESHOLDS

CONFIG_RECORD_FIELDS_ABSENT = ("updated_at", "version")


# --- Generic shape helpers -------------------------------------------------


def assert_identity_fields(data: dict) -> None:
    """Every persisted record carries a bare-UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"


def assert_versioned_record(data: dict, expected_version: int = None) -> None:
    """Records that carry updated_at and version (PRD §2.4)."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_config_record(data: dict) -> None:
    """Configuration and append-only records carry only id and created_at."""
    assert_identity_fields(data)
    for field in CONFIG_RECORD_FIELDS_ABSENT:
        assert field not in data or data[field] is None, (
            f"{field} must be absent from a configuration or append-only record"
        )


def assert_whole_cents(value, label="amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of whole cents, got {value!r}"
    )


def assert_ratio_four_decimals(value, label="ratio") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 4) == float(value), (
        f"{label} must be carried to four decimal places, got {value!r}"
    )


def normalize_instant(value: str) -> str:
    """Canonicalise an ISO 8601 UTC instant so sub-second width never fails a test."""
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
        text = f"{head}.{frac}"
    else:
        text = f"{text}.000"
    return f"{text}Z"


def assert_instant_equals(actual: str, expected: str, label="instant") -> None:
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_date_equals(actual: str, expected_date: str, label="date") -> None:
    """Compare only the calendar date portion of a timestamp or date string."""
    assert actual is not None, f"{label} must not be null"
    assert str(actual)[:10] == expected_date, (
        f"{label}: expected calendar date {expected_date}, got {actual}"
    )


# --- Entity assertions ----------------------------------------------------


def assert_state_law_profile(data: dict) -> None:
    assert_config_record(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"] == data["state_code"].upper()
    assert 0.0 <= float(data["markup_cap_pct"]) <= 1.0
    assert data["labor_rate_method"] in ("RETAIL_SAMPLE", "TIME_AND_PRICE")
    assert isinstance(data["min_sample_repair_orders"], int)
    assert data["min_sample_repair_orders"] >= 0
    assert data["max_labor_rate_cents"] > 0
    assert data["deemed_approved_days"] > 0
    assert data["appeal_window_days"] > 0


def assert_dealer(data: dict) -> None:
    assert_versioned_record(data)
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data["state_law_profile_id"])
    assert_whole_cents(data["approved_labor_rate_cents"], "approved_labor_rate_cents")
    assert isinstance(data["approved_parts_markup_pct"], (int, float))
    assert isinstance(data["vehicles_in_operation"], int)
    assert data["vehicles_in_operation"] >= 0
    assert data["status"] in ("ACTIVE", "PROBATION", "SUSPENDED")
    assert_whole_cents(data["chargeback_balance_cents"], "chargeback_balance_cents")
    assert isinstance(data["open_parts_return_count"], int)
    assert data["open_parts_return_count"] >= 0
    assert isinstance(data["audit_hold"], bool)
    assert isinstance(data["outlier_flag"], bool)


def assert_vehicle(data: dict) -> None:
    assert_config_record(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert 1980 <= data["model_year"] <= 2100
    assert isinstance(data["warranty_start_date"], str)
    assert data["in_service_odometer"] >= 0
    assert data["basic_months"] > 0 and data["basic_miles"] > 0
    assert data["powertrain_months"] >= data["basic_months"]
    assert data["powertrain_miles"] >= data["basic_miles"]


def assert_labor_operation(data: dict) -> None:
    assert_config_record(data)
    assert isinstance(data["op_code"], str) and data["op_code"]
    assert isinstance(data["description"], str) and data["description"]
    assert float(data["standard_time_hours"]) > 0
    assert float(data["max_time_hours"]) >= float(data["standard_time_hours"])
    assert data["category"] in ("BASIC", "POWERTRAIN")
    assert isinstance(data["requires_causal_part"], bool)
    if data["requires_causal_part"]:
        assert data["causal_failure_group"]
    else:
        assert data.get("causal_failure_group") is None
    assert isinstance(data["overlap_group"], str) and data["overlap_group"]


def assert_part_catalog_item(data: dict) -> None:
    assert_config_record(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str) and data["description"]
    assert data["dealer_net_cents"] > 0
    assert isinstance(data["failure_group"], str) and data["failure_group"]
    assert isinstance(data["return_required"], bool)
    assert isinstance(data["retention_days"], int)
    if not data["return_required"]:
        assert data["retention_days"] == 0
    else:
        assert data["retention_days"] >= 0


def assert_labor_rate_request(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["state_law_profile_id"])
    assert data["requested_labor_rate_cents"] > 0
    assert 0.0 <= float(data["requested_parts_markup_pct"]) <= 1.0
    assert isinstance(data["effective_date"], str)
    assert_whole_cents(data["statutory_ceiling_cents"], "statutory_ceiling_cents")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN",
    )
    assert isinstance(data["deemed_approved"], bool)


def assert_claim(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["labor_operation_id"])
    assert isinstance(data["repair_order_number"], str) and data["repair_order_number"]
    assert isinstance(data["repair_date"], str)
    assert data["odometer_at_repair"] >= 0
    assert float(data["claimed_labor_hours"]) > 0
    assert isinstance(data["claimed_parts_qty"], int)
    assert data["coverage_type"] in ("BASIC", "POWERTRAIN", "NONE", "GOODWILL")
    assert data["status"] in ("SUBMITTED", "SUSPENDED", "APPROVED", "DENIED", "VOID")
    assert data["payment_status"] in ("UNPAID", "PAID", "DEBITED", "CREDIT_REINSTATED")
    for money_field in (
        "provisional_total_cents",
        "provisional_labor_amount_cents",
        "provisional_parts_amount_cents",
        "approved_labor_amount_cents",
        "approved_parts_amount_cents",
        "approved_total_cents",
        "dealer_participation_cents",
        "oem_payable_cents",
        "debited_amount_cents",
        "reinstated_amount_cents",
    ):
        assert_whole_cents(data[money_field], money_field)
    assert isinstance(data["suspend_edit_count"], int)
    assert data["suspend_edit_count"] >= 0
    assert (
        data["provisional_total_cents"]
        == data["provisional_labor_amount_cents"] + data["provisional_parts_amount_cents"]
    ), "provisional_total_cents is the labor amount plus the parts amount"


def assert_claim_edit(data: dict) -> None:
    assert_config_record(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["edit_code"] in (
        "EXCESSIVE_TIME", "HIGH_VALUE", "NO_COVERAGE",
        "NARRATIVE_THIN", "REPEAT_REPAIR", "DEALER_POSTURE_HOLD",
    )
    assert data["severity"] in ("SUSPEND", "WARN")
    if data["edit_code"] == "REPEAT_REPAIR":
        assert data["conflicting_claim_id"] is None or is_valid_uuid(
            data["conflicting_claim_id"]
        )
    else:
        assert data.get("conflicting_claim_id") is None, (
            "conflicting_claim_id is null on every edit code but REPEAT_REPAIR"
        )
    if data["severity"] == "SUSPEND":
        assert data["edit_code"] in (
            "EXCESSIVE_TIME", "HIGH_VALUE", "NO_COVERAGE", "DEALER_POSTURE_HOLD",
        )


def assert_parts_return_request(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["part_id"])
    assert data["due_date"] is not None
    assert data["status"] in (
        "REQUESTED", "RECEIVED", "ANALYZED", "NOT_RETURNED", "WAIVED",
    )
    if data.get("analysis_result") is not None:
        assert data["analysis_result"] in (
            "DEFECT_CONFIRMED", "NO_DEFECT_FOUND", "NOT_AVAILABLE",
        )
    assert_whole_cents(data["debit_amount_cents"], "debit_amount_cents")
    assert_whole_cents(data["reversed_amount_cents"], "reversed_amount_cents")


def assert_dealer_audit(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["period_start"] < data["period_end"]
    assert data["sample_size"] > 0
    assert isinstance(data["lead_auditor_user_id"], str) and data["lead_auditor_user_id"]
    assert data["status"] in (
        "SCHEDULED", "IN_FIELD", "FINDINGS_ISSUED", "APPEALED", "CLOSED",
    )
    for money_field in (
        "sample_paid_snapshot_cents",
        "population_paid_snapshot_cents",
        "sample_chargeback_cents",
        "extrapolated_chargeback_cents",
        "total_chargeback_cents",
    ):
        assert_whole_cents(data[money_field], money_field)
    assert_ratio_four_decimals(data["error_rate"], "error_rate")
    assert float(data["extrapolation_factor"]) in (0.00, 0.50, 1.00), (
        "extrapolation_factor is one of exactly three literal tier values"
    )
    assert (
        data["total_chargeback_cents"]
        == data["sample_chargeback_cents"] + data["extrapolated_chargeback_cents"]
    ), "total_chargeback_cents is the sampled plus the extrapolated chargeback"


def assert_audit_finding(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["audit_id"])
    assert is_valid_uuid(data["claim_id"])
    assert data["finding_code"] in (
        "NO_REPAIR_ORDER", "NO_TECHNICIAN_SIGNATURE", "PART_NOT_ON_HAND",
        "TIME_NOT_DOCUMENTED", "NARRATIVE_UNSUPPORTED",
    )
    assert data["unsupported_amount_cents"] > 0
    assert isinstance(data["evidence_note"], str) and data["evidence_note"]
    assert data["status"] in ("OPEN", "CHARGED_BACK", "OVERTURNED", "UPHELD")


def assert_audit_appeal(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["audit_id"])
    assert is_valid_uuid(data["filed_by_dealer_id"])
    assert isinstance(data["grounds"], str) and data["grounds"]
    assert isinstance(data["contested_finding_ids"], list)
    assert len(data["contested_finding_ids"]) >= 1
    assert isinstance(data["overturned_finding_ids"], list)
    assert data["status"] in ("FILED", "GRANTED", "PARTIALLY_GRANTED", "DENIED")
    assert_whole_cents(data["reinstated_amount_cents"], "reinstated_amount_cents")


def assert_goodwill_authorization(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert data["requested_amount_cents"] > 0
    assert 0.00 <= float(data["policy_adjustment_pct"]) <= 0.50
    assert isinstance(data["justification"], str) and data["justification"]
    assert_whole_cents(data["adjudicator_limit_cents"], "adjudicator_limit_cents")
    assert_whole_cents(data["manager_limit_cents"], "manager_limit_cents")
    assert_ratio_four_decimals(
        data["out_of_warranty_margin_pct"], "out_of_warranty_margin_pct"
    )
    assert data["status"] in (
        "PENDING", "ESCALATED", "APPROVED", "DENIED", "WITHDRAWN",
    )


def assert_ledger_entry(data: dict) -> None:
    assert_config_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["source_type"] in (
        "PARTS_NON_RETURN", "PARTS_NO_DEFECT", "LATE_RETURN_REVERSAL",
        "AUDIT_CHARGEBACK_SAMPLE", "AUDIT_CHARGEBACK_EXTRAPOLATION",
        "APPEAL_REVERSAL_SAMPLE", "APPEAL_REVERSAL_EXTRAPOLATION",
    )
    assert is_valid_uuid(data["source_id"])
    assert_whole_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] != 0, "a ledger amount is signed and never zero"
    assert_whole_cents(data["balance_after_cents"], "balance_after_cents")


# --- Domain invariants ----------------------------------------------------


def expected_dealer_posture(balance_cents: int) -> str:
    if balance_cents >= THRESHOLDS["SUSPENSION_THRESHOLD_CENTS"]:
        return "SUSPENDED"
    if balance_cents >= THRESHOLDS["PROBATION_THRESHOLD_CENTS"]:
        return "PROBATION"
    return "ACTIVE"


def assert_dealer_posture_matches_balance(dealer: dict) -> None:
    """PRD §2.8: posture is recomputed from the balance after every ledger append."""
    assert dealer["status"] == expected_dealer_posture(
        dealer["chargeback_balance_cents"]
    ), (
        f"balance {dealer['chargeback_balance_cents']} implies "
        f"{expected_dealer_posture(dealer['chargeback_balance_cents'])}, "
        f"dealer reports {dealer['status']}"
    )


def assert_ledger_balance_invariant(dealer: dict, entries: list) -> None:
    """PRD §2.8: the balance is the signed sum of the dealer's ledger rows, and each
    row records the balance immediately after it was appended."""
    running = 0
    for entry in entries:
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"balance_after_cents {entry['balance_after_cents']} does not match the "
            f"running balance {running} for row {entry['id']}"
        )
    assert dealer["chargeback_balance_cents"] == running, (
        f"dealer balance {dealer['chargeback_balance_cents']} does not equal the "
        f"signed sum {running} of its ledger rows"
    )
