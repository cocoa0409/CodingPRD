"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, entity: str):
    """Primary resources carry id/created_at/updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_policyholder(data: dict):
    _assert_common_fields(data, "Policyholder")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["fraud_score"], int) and data["fraud_score"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_state_regulation(data: dict):
    _assert_common_fields(data, "StateRegulation")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["zero_deductible_windshield"], bool)
    assert data.get("max_deductible_cents") is None or isinstance(data["max_deductible_cents"], int)
    assert isinstance(data["glass_sales_tax_rate_bp"], int)


def assert_policy(data: dict):
    _assert_common_fields(data, "Policy")
    assert isinstance(data["policyholder_id"], str)
    assert isinstance(data["policy_number"], str)
    assert data["coverage_type"] in ("COMPREHENSIVE", "LIABILITY")
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["oem_endorsement"], bool)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_glass_shop(data: dict):
    _assert_common_fields(data, "GlassShop")
    assert isinstance(data["shop_name"], str) and data["shop_name"]
    assert isinstance(data["service_zip_prefixes"], list)
    assert data["agreement_tier"] in ("PLATINUM", "PREFERRED", "STANDARD")
    assert isinstance(data["bay_count"], int)
    assert isinstance(data["mobile_unit_count"], int)
    assert data["network_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["warranty_strike_count"], int) and data["warranty_strike_count"] >= 0


def assert_part_catalog_entry(data: dict):
    _assert_common_fields(data, "PartCatalogEntry")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["part_category"] in (
        "WINDSHIELD", "SIDE_GLASS", "REAR_GLASS", "MOLDING_KIT", "CALIBRATION")
    assert data["part_origin"] in ("OEM", "AFTERMARKET")
    assert isinstance(data["nags_list_price_cents"], int)
    assert data["status"] in ("AVAILABLE", "DISCONTINUED")


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert is_valid_uuid(data.get("policyholder_id", "")), "claim.policyholder_id must be a UUID"
    assert is_valid_uuid(data.get("policy_id", "")), "claim.policy_id must be a UUID"
    assert isinstance(data["incident_state_code"], str) and len(data["incident_state_code"]) == 2
    assert isinstance(data["service_zip_code"], str) and len(data["service_zip_code"]) == 5
    assert data["part_category"] in ("WINDSHIELD", "SIDE_GLASS", "REAR_GLASS")
    assert isinstance(data["requires_adas_calibration"], bool)
    assert isinstance(data["estimated_repair_cost_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "FRAUD_HOLD", "COVERAGE_VERIFIED", "WORK_AUTHORIZED",
        "WORK_COMPLETED", "INVOICED", "SETTLED", "DENIED", "CANCELLED")


def assert_choice_disclosure_record(data: dict):
    """Append-only record: id + created_at only — no updated_at, no version
    (PRD §2.5: 'both updated_at and version are absent from it')."""
    assert is_valid_uuid(data.get("id", "")), "ChoiceDisclosureRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ChoiceDisclosureRecord must not carry updated_at"
    assert "version" not in data, "ChoiceDisclosureRecord must not carry version"
    assert data["disclosure_channel"] in ("PHONE", "PORTAL", "IN_PERSON")
    assert isinstance(data["shop_solicited"], bool)
    assert isinstance(data["informed_of_network_options"], bool)


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data.get("claim_id", "")), "work_order.claim_id must be a UUID"
    assert is_valid_uuid(data.get("shop_id", "")), "work_order.shop_id must be a UUID"
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "SCHEDULED", "NO_SHOW",
        "COMPLETED", "DECLINED", "CANCELLED", "SUPERSEDED")


def assert_calibration_event(data: dict):
    _assert_common_fields(data, "CalibrationEvent")
    assert data["calibration_type"] in ("STATIC", "DYNAMIC")
    assert data["status"] in ("SCHEDULED", "VERIFIED", "FAILED", "WAIVED")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("work_order_id", "")), "invoice.work_order_id must be a UUID"
    assert data["status"] in ("DRAFT", "SUBMITTED", "DISPUTED", "APPROVED", "PAID", "REJECTED")
    for field in ("submitted_total_cents", "tax_amount_cents",
                  "approved_total_cents", "adjustment_total_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be int cents"


def assert_invoice_line_item(data: dict):
    _assert_common_fields(data, "InvoiceLineItem")
    assert is_valid_uuid(data.get("invoice_id", "")), "line.invoice_id must be a UUID"
    assert data["line_type"] in ("PART", "CALIBRATION", "MOBILE_FEE", "MATERIALS")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["agreement_unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_fraud_alert(data: dict):
    _assert_common_fields(data, "FraudAlert")
    assert data["alert_type"] in (
        "REPEAT_WINDOW", "SOLICITATION", "RAPID_COMPLETION", "SCORE_THRESHOLD")
    assert isinstance(data["score_contribution"], int)
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("original_work_order_id", ""))
    assert isinstance(data["issue_description"], str)
    assert data["status"] in ("FILED", "APPROVED_REWORK", "DENIED", "REWORK_COMPLETED")


def assert_invoice_conservation(invoice: dict):
    """Money conservation (PRD §2.9): submitted == approved + adjustment."""
    assert invoice["submitted_total_cents"] == (
        invoice["approved_total_cents"] + invoice["adjustment_total_cents"]
    ), (
        f"conservation broken: submitted {invoice['submitted_total_cents']} != "
        f"approved {invoice['approved_total_cents']} + adjustment {invoice['adjustment_total_cents']}"
    )


def assert_capacity_conservation(capacity: dict):
    """Bay minutes conservation (PRD §2.9): available == total - booked."""
    assert capacity["bay_minutes_available"] == (
        capacity["bay_minutes_total"] - capacity["bay_minutes_booked"]
    ), (
        f"capacity broken: available {capacity['bay_minutes_available']} != "
        f"total {capacity['bay_minutes_total']} - booked {capacity['bay_minutes_booked']}"
    )
