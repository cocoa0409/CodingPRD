"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_provider_site(data: dict):
    _assert_common(data)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["vfc_pin"], str) and data["vfc_pin"]
    assert data["status"] in ("ACTIVE", "SUSPENDED_ORDERING", "TERMINATED")
    assert isinstance(data["excursion_count_open"], int) and data["excursion_count_open"] >= 0
    assert isinstance(data["accountability_balance_doses"], int)
    assert isinstance(data["private_lending_balance"], int)


def assert_storage_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert data["unit_kind"] in ("REFRIGERATOR", "FREEZER")
    assert isinstance(data["min_temp_c"], (int, float))
    assert isinstance(data["max_temp_c"], (int, float))
    assert data["min_temp_c"] <= data["max_temp_c"]
    assert "active_excursion_id" in data
    assert isinstance(data["is_quarantined"], bool)
    # is_quarantined is true exactly while an excursion is active (PRD §2.6).
    assert data["is_quarantined"] == (data["active_excursion_id"] is not None)


def assert_vaccine_product(data: dict):
    _assert_common(data)
    assert isinstance(data["ndc_code"], str) and data["ndc_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["presentation"] in ("SINGLE_DOSE_VIAL", "MULTI_DOSE_VIAL", "PRE_FILLED_SYRINGE")
    assert isinstance(data["doses_per_container"], int) and data["doses_per_container"] >= 1
    assert isinstance(data["vfc_program_eligible"], bool)
    assert data["storage_requirement"] in (
        "REFRIGERATED_2_8C",
        "FROZEN_MINUS_50_MINUS_15C",
        "ULTRA_COLD_MINUS_90_MINUS_60C",
    )


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert is_valid_uuid(data.get("storage_unit_id", ""))
    assert is_valid_uuid(data.get("vaccine_product_id", ""))
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert data["stock_type"] in ("PUBLIC_VFC", "PRIVATE")
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_borrowed_in"], int) and data["quantity_borrowed_in"] >= 0
    assert isinstance(data["expires_on"], str) and len(data["expires_on"]) == 10
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "DEPLETED", "EXPIRED", "WASTED_CLOSED")
    assert "received_via_order_id" in data


def assert_temperature_reading(data: dict):
    # Append-only event log: only id + created_at of the common fields (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TemperatureReading must not carry updated_at"
    assert "version" not in data, "TemperatureReading must not carry version"
    assert is_valid_uuid(data.get("storage_unit_id", ""))
    assert isinstance(data["recorded_at"], str) and data["recorded_at"]
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["is_out_of_range"], bool)


def assert_temperature_excursion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("storage_unit_id", ""))
    assert isinstance(data["opened_at"], str) and data["opened_at"]
    assert "closed_at" in data
    assert isinstance(data["peak_temperature_c"], (int, float))
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 0
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_VIABLE", "RESOLVED_WASTED")
    assert isinstance(data["doses_written_off"], int) and data["doses_written_off"] >= 0


def assert_patient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert data["insurance_category"] in (
        "MEDICAID", "UNINSURED", "UNDERINSURED", "AMERICAN_INDIAN_ALASKA_NATIVE", "COMMERCIAL",
    )
    assert isinstance(data["is_active"], bool)


def assert_eligibility_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert isinstance(data["screening_date"], str) and len(data["screening_date"]) == 10
    assert isinstance(data.get("screened_by_user_id"), str) and data["screened_by_user_id"]
    assert data["insurance_category_at_visit"] in (
        "MEDICAID", "UNINSURED", "UNDERINSURED", "AMERICAN_INDIAN_ALASKA_NATIVE", "COMMERCIAL",
    )
    assert isinstance(data["vfc_eligible"], bool)
    assert data["outcome"] in ("VFC_ELIGIBLE", "PRIVATE_ONLY")
    # outcome is derived from vfc_eligible (PRD §3.6).
    assert data["outcome"] == ("VFC_ELIGIBLE" if data["vfc_eligible"] else "PRIVATE_ONLY")


def assert_dose_administration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("eligibility_screening_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["administration_date"], str) and len(data["administration_date"]) == 10
    assert isinstance(data.get("administered_by_user_id"), str) and data["administered_by_user_id"]
    assert data["funding_source"] in ("PUBLIC_VFC", "PRIVATE")
    assert data["registry_status"] in ("PENDING_SUBMISSION", "SUBMITTED", "REJECTED_BY_REGISTRY")
    assert "borrowed_context_ticket_id" in data


def assert_vaccine_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert isinstance(data.get("order_number"), str) and data["order_number"]
    assert isinstance(data.get("submitted_by_user_id"), str) and data["submitted_by_user_id"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "PARTIALLY_RECEIVED", "FULLY_RECEIVED", "CANCELLED",
    )
    assert isinstance(data["expected_vfc_doses"], int) and data["expected_vfc_doses"] >= 1
    assert isinstance(data["approved_vfc_doses"], int) and data["approved_vfc_doses"] >= 0
    assert isinstance(data["received_vfc_doses"], int) and data["received_vfc_doses"] >= 0
    assert data["received_vfc_doses"] <= data["approved_vfc_doses"]


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vaccine_order_id", ""))
    assert is_valid_uuid(data.get("vaccine_product_id", ""))
    assert isinstance(data["requested_doses"], int) and data["requested_doses"] >= 1
    assert isinstance(data["approved_doses"], int) and data["approved_doses"] >= 0
    assert isinstance(data["received_doses"], int) and data["received_doses"] >= 0
    # Cumulative receipts must never exceed the allocation (PRD §3.5).
    assert data["received_doses"] <= data["approved_doses"]


def assert_allocation_receipt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vaccine_order_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("storage_unit_id", ""))
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["expires_on"], str) and len(data["expires_on"]) == 10
    assert isinstance(data["quantity_doses"], int) and data["quantity_doses"] >= 1
    assert is_valid_uuid(data.get("lot_id", ""))


def assert_borrow_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert is_valid_uuid(data.get("from_lot_id", ""))
    assert is_valid_uuid(data.get("to_lot_id", ""))
    assert data["direction"] in ("PUBLIC_FROM_PRIVATE", "PRIVATE_FROM_PUBLIC")
    assert isinstance(data["borrowed_quantity"], int) and data["borrowed_quantity"] >= 1
    assert isinstance(data["paid_back_quantity"], int) and data["paid_back_quantity"] >= 0
    assert data["paid_back_quantity"] <= data["borrowed_quantity"]
    assert data["status"] in ("OPEN", "PARTIALLY_REPAID", "REPAID", "VOIDED")
    assert isinstance(data.get("opened_by_user_id"), str) and data["opened_by_user_id"]
    assert data["reason_code"] in ("STOCK_OUT", "SHORT_DATE_AVOIDANCE", "EMERGENCY_CLINIC")


def assert_site_visit_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert isinstance(data["visit_date"], str) and len(data["visit_date"]) == 10
    assert isinstance(data.get("conducted_by_user_id"), str) and data["conducted_by_user_id"]
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "CLOSED_PASS", "CLOSED_FAIL", "CANCELLED",
    )


def assert_site_visit_audit_snapshot(data: dict):
    """Frozen accountability fields populated by issue-findings (PRD §3.9)."""
    for field in (
        "public_doses_received", "public_doses_administered", "public_doses_wasted",
        "public_doses_transferred_out", "accountability_gap", "on_hand_public_total",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer on the frozen snapshot"
    assert data["accountability_gap"] == (
        data["public_doses_received"]
        - data["public_doses_administered"]
        - data["public_doses_wasted"]
        - data["public_doses_transferred_out"]
    ), "accountability_gap must equal received - administered - wasted - transferred_out"


def assert_short_date_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_site_id", ""))
    assert is_valid_uuid(data.get("from_lot_id", ""))
    assert is_valid_uuid(data.get("destination_site_id", ""))
    assert is_valid_uuid(data.get("destination_storage_unit_id", ""))
    assert isinstance(data["quantity_doses"], int) and data["quantity_doses"] >= 1
    assert isinstance(data["reason"], str)
    assert data["status"] in ("INITIATED", "IN_TRANSIT", "RECEIVED", "CANCELLED")
    assert "new_lot_id" in data
