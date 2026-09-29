"""Entity assertions and domain invariant checkers for the Alcohol Price Posting API."""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Shared record shape helpers
# --------------------------------------------------------------------------

def assert_versioned_record(data: Dict[str, Any]) -> None:
    """A record carrying id, created_at, updated_at and version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 with three fractional digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 with three fractional digits, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_immutable_record(data: Dict[str, Any]) -> None:
    """A record carrying only id and created_at — no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 with three fractional digits, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "an immutable record must not carry updated_at"
    assert "version" not in data, "an immutable record must not carry version"


def assert_cents(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------

def assert_state_program(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["program_name"], str) and len(data["program_name"]) > 0
    assert 1 <= data["posting_deadline_day"] <= 28
    assert data["hold_window_days"] >= 1
    assert data["correction_window_days"] >= 1
    assert data["combo_cooldown_days"] >= 0
    assert isinstance(data["quantity_discount_allowed"], bool)
    assert isinstance(data["combination_sale_allowed"], bool)
    assert 0 <= data["max_quantity_discount_pct"] <= 1
    assert 0 <= data["max_promotional_allowance_pct"] <= 1
    assert data["depletion_allowance_per_case_cents"] >= 0
    assert data["late_filing_penalty_cents"] >= 0
    assert data["repeat_correction_penalty_cents"] >= 0
    assert data["frivolous_amendment_penalty_cents"] >= 0
    assert 0 <= data["off_posted_penalty_rate_pct"] <= 1
    assert data["max_corrections_per_schedule"] >= 1


def assert_wholesaler(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert is_valid_uuid(data["state_program_id"])
    assert data["license_status"] in ("ACTIVE", "SUSPENDED")
    for field in (
        "late_filing_penalty_accrued_cents",
        "correction_penalty_accrued_cents",
        "amendment_penalty_accrued_cents",
        "assessed_penalty_cents",
        "penalty_exposure_cents",
    ):
        assert_cents(data, field)
    for field in (
        "late_filing_count",
        "frivolous_amendment_count",
        "off_posted_violation_count",
        "open_audit_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_penalty_exposure_identity(data)


def assert_penalty_exposure_identity(data: Dict[str, Any]) -> None:
    """`penalty_exposure_cents` is always the plain sum of the four buckets (PRD §2.9)."""
    expected = (
        data["late_filing_penalty_accrued_cents"]
        + data["correction_penalty_accrued_cents"]
        + data["amendment_penalty_accrued_cents"]
        + data["assessed_penalty_cents"]
    )
    assert data["penalty_exposure_cents"] == expected, (
        f"penalty_exposure_cents must equal the sum of the four buckets "
        f"({expected}), got {data['penalty_exposure_cents']}"
    )


def assert_licensee_user(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["user_role"] in ("FILING_AGENT", "CERTIFYING_OFFICER", "DUAL_ROLE")
    assert isinstance(data["is_active"], bool)


def assert_brand(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert isinstance(data["brand_name"], str) and len(data["brand_name"]) > 0
    assert isinstance(data["supplier_name"], str) and len(data["supplier_name"]) > 0
    assert data["beverage_class"] in ("SPIRITS", "WINE", "MALT")
    assert data["registration_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert is_iso8601_timestamp(data["registration_effective_from"])
    assert is_iso8601_timestamp(data["registration_expires_on"])
    assert data["registration_expires_on"] > data["registration_effective_from"]


def assert_price_schedule(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert is_valid_uuid(data["state_program_id"])
    assert isinstance(data["posting_month"], str) and len(data["posting_month"]) == 7
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "POSTED", "EFFECTIVE", "SUPERSEDED", "WITHDRAWN",
    )
    assert isinstance(data["is_late"], bool)
    for field in ("return_count", "correction_count", "item_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_price_schedule_item(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["schedule_id"])
    assert is_valid_uuid(data["brand_id"])
    assert data["size_ml"] >= 1
    assert data["bottles_per_case"] >= 1
    assert data["case_price_cents"] >= 1
    assert data["unit_price_cents"] >= 1
    assert data["status"] in ("DRAFT", "POSTED", "EFFECTIVE", "SUPERSEDED", "WITHDRAWN")
    for field in ("amendment_count", "correction_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["unit_price_cents"] * data["bottles_per_case"] >= data["case_price_cents"], (
        "unit_price_cents multiplied by bottles_per_case must be at least case_price_cents"
    )


def assert_quantity_discount_tier(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["item_id"])
    assert data["min_cases"] >= 2
    assert 0 < data["discount_pct"] <= 1
    assert_cents(data, "discounted_case_price_cents")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_combination_sale(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["schedule_id"])
    assert isinstance(data["member_item_ids"], list) and len(data["member_item_ids"]) >= 2
    assert is_iso8601_timestamp(data["promo_starts_at"])
    assert is_iso8601_timestamp(data["promo_ends_at"])
    assert data["promo_ends_at"] > data["promo_starts_at"]
    for field in ("combined_case_price_cents", "floor_price_cents", "min_allowed_price_cents"):
        assert_cents(data, field)
    assert data["status"] in ("ACTIVE", "VOID")


def assert_hold_amendment(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["amending_item_id"])
    assert is_valid_uuid(data["reference_item_id"])
    assert data["new_case_price_cents"] >= 1
    assert data["new_unit_price_cents"] >= 1
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED", "REVOKED")


def assert_error_correction(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["item_id"])
    assert data["corrected_case_price_cents"] >= 1
    assert data["corrected_unit_price_cents"] >= 1
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_retailer_invoice(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert isinstance(data["retailer_license_number"], str)
    assert is_iso8601_timestamp(data["invoice_date"])
    assert data["validation_status"] in ("DRAFT", "VALIDATED", "FLAGGED")
    assert data["audit_status"] in ("NOT_AUDITED", "UNDER_AUDIT", "ASSESSED")
    for field in (
        "subtotal_cents", "surcharge_cents", "total_cents",
        "total_allowance_cents", "total_variance_cents",
    ):
        assert_cents(data, field)
    for field in ("line_count", "off_posted_line_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["total_cents"] == data["subtotal_cents"] + data["surcharge_cents"], (
        "total_cents must be subtotal_cents plus surcharge_cents"
    )


def assert_invoice_line(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["item_id"])
    assert data["cases_quantity"] >= 0
    assert data["bottles_quantity"] >= 0
    assert data["case_price_charged_cents"] >= 0
    assert data["unit_price_charged_cents"] >= 0
    assert data["promotional_allowance_cents"] >= 0
    assert data["depletion_allowance_cents"] >= 0
    for field in (
        "gross_cents", "quantity_discount_cents", "allowed_promotional_cents",
        "excess_promotional_cents", "allowed_depletion_cents", "excess_depletion_cents",
        "net_price_cents", "posted_gross_cents", "variance_cents", "finding_variance_cents",
    ):
        assert_cents(data, field)
    assert isinstance(data["is_off_posted"], bool)


def assert_compliance_audit(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert is_valid_uuid(data["state_program_id"])
    assert isinstance(data["audit_period_month"], str) and len(data["audit_period_month"]) == 7
    assert data["status"] in ("OPEN", "COLLECTED", "ASSESSED", "CLOSED", "VOID")
    assert isinstance(data["finding_count"], int) and data["finding_count"] >= 0
    for field in ("total_variance_cents", "base_penalty_cents", "penalty_assessed_cents"):
        assert_cents(data, field)
    assert isinstance(data["prior_violation_count"], int) and data["prior_violation_count"] >= 0
    assert data["tier_multiplier"] in (1.0, 1.00, 1.5, 1.50, 2.0, 2.00)


def assert_audit_finding(data: Dict[str, Any]) -> None:
    """An audit finding is immutable: no updated_at, no version (PRD §2.5)."""
    assert_immutable_record(data)
    assert is_valid_uuid(data["audit_id"])
    assert is_valid_uuid(data["invoice_line_id"])
    assert data["finding_type"] in (
        "OFF_POSTED_UNDERCHARGE", "OFF_POSTED_OVERCHARGE",
        "EXCESS_PROMOTIONAL_ALLOWANCE", "EXCESS_DEPLETION_ALLOWANCE", "UNPOSTED_BRAND",
    )
    assert_cents(data, "variance_cents")
    assert_cents(data, "penalty_component_cents")


# --------------------------------------------------------------------------
# Computed read payload assertions
# --------------------------------------------------------------------------

def assert_posted_price_payload(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data["item_id"])
    assert data["variant"] in ("as_amended", "as_certified")
    assert is_iso8601_timestamp(data["as_of"])
    if data["resolved_item_id"] is None:
        assert data["posted_case_price_cents"] is None
        assert data["posted_unit_price_cents"] is None
    else:
        assert is_valid_uuid(data["resolved_item_id"])
        assert isinstance(data["posted_case_price_cents"], int)
        assert isinstance(data["posted_unit_price_cents"], int)


def assert_penalty_exposure_payload(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data["wholesaler_id"])
    assert data["variant"] in ("assessed_exposure", "provisional_exposure")
    for field in ("accrued_cents", "provisional_cents", "exposure_cents"):
        assert_cents(data, field)
    assert data["exposure_cents"] == data["accrued_cents"] + data["provisional_cents"], (
        "exposure_cents must be accrued_cents plus provisional_cents"
    )


def assert_posting_run_payload(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data["state_program_id"])
    assert is_iso8601_timestamp(data["run_at"])
    assert isinstance(data["processed_schedule_count"], int)
    assert isinstance(data["effective_schedule_ids"], list)
    assert isinstance(data["superseded_schedule_ids"], list)
    assert data["processed_schedule_count"] == len(data["effective_schedule_ids"]), (
        "processed_schedule_count must count exactly the schedules listed in "
        "effective_schedule_ids"
    )
