"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

RMA_STATUSES = [
    "DRAFT", "AUTHORIZED", "RECEIVED", "TRIAGED", "DIAGNOSED",
    "AWAITING_QUOTE_APPROVAL", "QUOTE_DECLINED", "IN_REPAIR", "AWAITING_PARTS",
    "QA_HOLD", "READY_TO_SHIP", "REPLACEMENT_PENDING", "SHIPPED", "CLOSED",
    "SCRAPPED", "CANCELLED",
]
QUOTE_STATUSES = ["SENT", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED"]
LINE_STATUSES = ["CONSUMED", "REVERSED"]
LOANER_UNIT_STATUSES = ["AVAILABLE", "RESERVED", "SHIPPED_OUT", "INSPECTION", "RETIRED"]
RESERVATION_STATUSES = [
    "RESERVED", "SHIPPED", "CLOSED_RETURNED", "CLOSED_DAMAGED",
    "CLOSED_FORFEITED", "CANCELLED",
]
ESCALATION_STATUSES = [
    "OPEN", "ACKNOWLEDGED", "CONTAINMENT_ACTIVE", "RESOLVED", "MONITORING",
    "CLOSED_FINAL",
]
NOTIFICATION_TYPES = [
    "RMA_AUTHORIZED", "RECEIVED", "QUOTE_SENT", "QUOTE_APPROVED",
    "QUOTE_DECLINED", "QUOTE_EXPIRED", "SHIPPED", "SLA_BREACH", "LOANER_LATE",
    "ESCALATION_OPENED", "CLOSED", "CANCELLED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["loyalty_tier"] in ("STANDARD", "PREFERRED")
    assert isinstance(data["deposit_exposure_cents"], int)
    assert data["deposit_exposure_cents"] >= 0


def assert_product_model(data: dict):
    _assert_common(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    for f in ("standard_warranty_days", "replacement_cost_cents",
              "flat_rate_repair_cents", "labor_rate_cents_per_minute",
              "replace_threshold_pct", "sla_turnaround_business_days"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["containment_flag"], bool)


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert is_valid_uuid(data.get("model_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["channel"] in ("RETAIL", "ENTERPRISE")
    assert data["disposition"] in ("ACTIVE", "SCRAPPED")


def assert_rma(data: dict):
    _assert_common(data)
    assert isinstance(data["rma_number"], str) and data["rma_number"].startswith("RMA-")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["service_option"] in ("STANDARD", "LOANER", "ADVANCE_EXCHANGE")
    assert data["status"] in RMA_STATUSES
    if data.get("coverage_path") is not None:
        assert data["coverage_path"] in (
            "IN_WARRANTY", "OUT_OF_WARRANTY", "GOODWILL_FULL", "GOODWILL_PARTIAL")
    if data.get("decision") is not None:
        assert data["decision"] in ("REPAIR", "REPLACE")
    assert isinstance(data.get("sla_pause_intervals", []), list)
    assert isinstance(data.get("engineering_review_pending", False), bool)
    assert isinstance(data.get("rework_count", 0), int)


def assert_quote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rma_id", ""))
    assert isinstance(data["quote_seq"], int) and data["quote_seq"] >= 1
    assert data["status"] in QUOTE_STATUSES
    assert isinstance(data["lines"], list)
    for f in ("labor_minutes", "labor_cents", "parts_subtotal_cents",
              "discount_pct", "discount_cents", "taxable_cents", "tax_cents",
              "expedite_fee_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["total_cents"] == (
        data["taxable_cents"] + data["tax_cents"] + data["expedite_fee_cents"]
    ), "total_cents must equal taxable + tax + expedite fee"


def assert_repair_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rma_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    assert is_valid_uuid(data.get("failure_code_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in LINE_STATUSES


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["stock_on_hand"], int)
    assert data["stock_on_hand"] >= 0


def assert_failure_code(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def assert_depot_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_loaner_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["condition_grade"] in ("A", "B", "C")
    assert isinstance(data["deposit_value_cents"], int)
    assert data["status"] in LOANER_UNIT_STATUSES
    assert isinstance(data["completed_loan_cycles"], int)
    assert data["completed_loan_cycles"] >= 0


def assert_loaner_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rma_id", ""))
    assert is_valid_uuid(data.get("loaner_unit_id", ""))
    assert data["mode"] in ("LOANER", "ADVANCE_EXCHANGE")
    assert data["status"] in RESERVATION_STATUSES
    for f in ("late_fee_cents", "damage_fee_cents", "forfeit_charge_cents"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_engineering_escalation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rma_id", ""))
    assert is_valid_uuid(data.get("model_id", ""))
    assert is_valid_uuid(data.get("failure_code_id", ""))
    assert data["trigger_source"] in ("AUTO_RECURRING", "MANUAL")
    assert data["status"] in ESCALATION_STATUSES
    assert isinstance(data["recurrence_count"], int)


def assert_notification_event(data: dict):
    # Append-only: id + created_at only; updated_at/version absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "notification events carry no updated_at"
    assert "version" not in data, "notification events carry no version"
    assert is_valid_uuid(data.get("rma_id", ""))
    assert data["event_type"] in NOTIFICATION_TYPES
    assert isinstance(data["recipient"], str) and "@" in data["recipient"]
    assert isinstance(data["message"], str)
