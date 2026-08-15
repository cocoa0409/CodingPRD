"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Every resource carries id (UUID), created_at / updated_at (ISO 8601 UTC with
three fractional digits), and version (starts at 1) per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_optional_ts(data: dict, field: str, entity: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity}.{field} must be null or ISO 8601, got {value!r}"
    )


def _assert_optional_int(data: dict, field: str, entity: str):
    value = data.get(field)
    assert value is None or isinstance(value, int), (
        f"{entity}.{field} must be null or an integer, got {value!r}"
    )


def assert_legal_department(data: dict):
    _assert_common(data, "LegalDepartment")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["annual_rate_increase_cap_pct"], (int, float))
    assert isinstance(data["partner_ratio_min_pct"], (int, float))
    assert isinstance(data["partner_ratio_max_pct"], (int, float))
    assert isinstance(data["guideline_notice_days"], int)
    assert isinstance(data["acknowledgment_window_days"], int)


def assert_panel_firm(data: dict):
    _assert_common(data, "PanelFirm")
    assert data["legal_department_id"] and is_valid_uuid(data["legal_department_id"])
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")


def assert_guideline_version(data: dict):
    _assert_common(data, "GuidelineVersion")
    assert data["legal_department_id"] and is_valid_uuid(data["legal_department_id"])
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_guideline_acknowledgment(data: dict):
    _assert_common(data, "GuidelineAcknowledgment")
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert data["guideline_version_id"] and is_valid_uuid(data["guideline_version_id"])
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "OVERDUE")
    _assert_optional_ts(data, "acknowledged_at", "GuidelineAcknowledgment")


def assert_matter(data: dict):
    _assert_common(data, "Matter")
    assert data["legal_department_id"] and is_valid_uuid(data["legal_department_id"])
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["engagement_status"] in ("PENDING", "ENGAGED", "CLOSED")
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["billed_to_date_cents"], int)
    assert isinstance(data["accrual_outstanding_cents"], int)


def assert_matter_spend_invariants(data: dict):
    """Spend counters never go negative (PRD §3.3, §3.5, §3.6, §3.7)."""
    assert data["billed_to_date_cents"] >= 0, (
        f"billed_to_date_cents must be >= 0, got {data['billed_to_date_cents']}"
    )
    assert data["accrual_outstanding_cents"] >= 0, (
        f"accrual_outstanding_cents must be >= 0, got {data['accrual_outstanding_cents']}"
    )


def assert_rate_card(data: dict):
    _assert_common(data, "RateCard")
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert isinstance(data["effective_year"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
    _assert_optional_ts(data, "submitted_at", "RateCard")


def assert_timekeeper(data: dict):
    _assert_common(data, "Timekeeper")
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["tk_class"] in ("PARTNER", "ASSOCIATE", "PARALEGAL")
    assert data["qualification_status"] in ("PENDING", "QUALIFIED", "DISQUALIFIED")


def assert_timekeeper_rate(data: dict):
    _assert_common(data, "TimekeeperRate")
    assert data["rate_card_id"] and is_valid_uuid(data["rate_card_id"])
    assert data["timekeeper_id"] and is_valid_uuid(data["timekeeper_id"])
    assert isinstance(data["hourly_rate_cents"], int)
    _assert_optional_int(data, "approved_rate_cents", "TimekeeperRate")


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert data["matter_id"] and is_valid_uuid(data["matter_id"])
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]
    assert is_iso8601_timestamp(data["billing_period_start"])
    assert is_iso8601_timestamp(data["billing_period_end"])
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED",
        "REJECTED", "PAID", "VOID",
    )
    assert isinstance(data["submitted_total_cents"], int)
    assert isinstance(data["approved_total_cents"], int)
    assert isinstance(data["final_payable_cents"], int)


def assert_invoice_line_item(data: dict):
    _assert_common(data, "InvoiceLineItem")
    assert data["invoice_id"] and is_valid_uuid(data["invoice_id"])
    assert data["timekeeper_id"] and is_valid_uuid(data["timekeeper_id"])
    assert isinstance(data["utbms_task_code"], str) and data["utbms_task_code"]
    assert isinstance(data["narrative"], str)
    assert isinstance(data["hours"], (int, float))
    assert isinstance(data["rate_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["review_status"] in (
        "PENDING", "APPROVED", "ADJUSTED_APPROVED", "REJECTED", "REINSTATED", "UPHELD",
    )
    _assert_optional_int(data, "adjusted_amount_cents", "InvoiceLineItem")
    reason = data.get("rejection_reason_code")
    assert reason is None or reason in (
        "BLOCK_BILLING", "RATE_EXCEEDS_APPROVED", "UNAPPROVED_TIMEKEEPER",
        "STAFFING_RATIO", "OVER_BUDGET",
    ), f"rejection_reason_code out of domain: {reason!r}"


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert data["invoice_line_item_id"] and is_valid_uuid(data["invoice_line_item_id"])
    assert isinstance(data["rationale"], str)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "GRANTED", "DENIED")
    note = data.get("resolution_note")
    assert note is None or isinstance(note, str)


def assert_accrual(data: dict):
    _assert_common(data, "Accrual")
    assert data["matter_id"] and is_valid_uuid(data["matter_id"])
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert isinstance(data["amount_cents"], int)
    matched = data.get("matched_invoice_id")
    assert matched is None or is_valid_uuid(matched)


def assert_matter_forecast(data: dict):
    _assert_common(data, "MatterForecast")
    assert data["matter_id"] and is_valid_uuid(data["matter_id"])
    assert isinstance(data["lifecycle_estimate_cents"], int)
    assert isinstance(data["wip_estimate_cents"], int)
    assert isinstance(data["variance_cents"], int)


def assert_scorecard_snapshot(data: dict):
    _assert_common(data, "ScorecardSnapshot")
    assert data["panel_firm_id"] and is_valid_uuid(data["panel_firm_id"])
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    for field in ("on_time_ack_pct", "rejection_rate_pct", "appeal_uphold_rate_pct",
                  "accrual_timeliness_pct", "overall_pct"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
