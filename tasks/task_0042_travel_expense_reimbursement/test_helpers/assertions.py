"""Entity assertions and domain invariant checkers (PRD Section 3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for mutable resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_traveler(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_office_state"], str)
    assert is_valid_uuid(data.get("manager_id", "")), "manager_id must be a valid UUID"
    assert data["status"] == "ACTIVE", "Travelers are created ACTIVE (PRD §3.1)"


def assert_approver(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["approval_limit_cents"], int)
    assert data["status"] == "ACTIVE", "Approvers are created ACTIVE (PRD §3.1)"


def assert_travel_policy(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["max_economy_fare_cents"], int)
    assert isinstance(data["business_class_min_hours"], int)
    assert isinstance(data["advance_purchase_days"], int)
    assert isinstance(data["cdw_daily_cap_cents"], int)
    assert isinstance(data["mileage_rate_milli_cents"], int)
    assert isinstance(data["receipt_required_threshold_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_per_diem_rate(data: dict):
    """PerDiemRate is immutable: id + created_at only, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PerDiemRate must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "PerDiemRate must not carry version (PRD §2.4)"
    assert isinstance(data["state_code"], str)
    assert isinstance(data["lodging_cap_cents"], int)
    assert isinstance(data["mie_cents"], int)


def assert_trip_request(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("traveler_id", "")), "traveler_id must be a valid UUID"
    assert isinstance(data["destination_state"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["budget_total_cents"], int)
    assert data["status"] in (
        "PENDING", "PENDING_OOP_APPROVAL", "AUTO_APPROVED",
        "APPROVED", "DENIED", "CANCELLED",
    )


def assert_virtual_card(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("trip_request_id", "")), "trip_request_id must be a valid UUID"
    assert isinstance(data["load_limit_cents"], int)
    assert isinstance(data["authorized_holds_cents"], int)
    assert isinstance(data["captured_total_cents"], int)
    assert isinstance(data["available_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "FROZEN", "CLOSED")


def assert_expense_report(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("trip_request_id", "")), "trip_request_id must be a valid UUID"
    assert isinstance(data["title"], str)
    assert data["per_diem_method"] in ("PER_DIEM", "ITEMIZED")
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "REJECTED")


def assert_expense_line(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("report_id", "")), "report_id must be a valid UUID"
    assert data["line_type"] in ("FLIGHT", "LODGING", "MEAL", "RENTAL_CDW", "MILEAGE")
    assert isinstance(data["reimbursable_amount_cents"], int)
    assert isinstance(data["in_policy"], bool)
    assert data["settlement_status"] in ("NONE", "PENDING", "SETTLED", "VOID")
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "REJECTED")


def assert_receipt(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("expense_line_id", "")), "expense_line_id must be a valid UUID"
    assert isinstance(data["image_ref"], str)
    assert data["status"] in ("UPLOADED", "OCR_PROCESSED", "VERIFIED", "DISPUTED")


def assert_approval_step(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("report_id", "")), "report_id must be a valid UUID"
    assert is_valid_uuid(data.get("approver_id", "")), "approver_id must be a valid UUID"
    assert isinstance(data["step_order"], int)
    assert data["decision"] in ("PENDING", "APPROVED", "REJECTED")


# --------------------------------------------------------------------------
# Domain invariant checkers (PRD §2.8, §3.3, §3.8)
# --------------------------------------------------------------------------
def assert_card_balance_invariant(card: dict):
    """available_balance == load_limit - authorized_holds - captured_total (PRD §3.3)."""
    assert (
        card["available_balance_cents"]
        == card["load_limit_cents"]
        - card["authorized_holds_cents"]
        - card["captured_total_cents"]
    ), (
        "Card balance invariant violated: "
        f"available={card['available_balance_cents']}, load={card['load_limit_cents']}, "
        f"holds={card['authorized_holds_cents']}, captured={card['captured_total_cents']}"
    )


def assert_trip_budget_invariant(trip: dict):
    """remaining_budget == budget_total - committed (PRD §3.8)."""
    assert (
        trip["remaining_budget_cents"]
        == trip["budget_total_cents"] - trip["committed_amount_cents"]
    ), (
        "Trip budget invariant violated: "
        f"remaining={trip['remaining_budget_cents']}, budget={trip['budget_total_cents']}, "
        f"committed={trip['committed_amount_cents']}"
    )
