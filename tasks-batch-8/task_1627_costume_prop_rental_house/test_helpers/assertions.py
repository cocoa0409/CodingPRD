"""Entity assertions and small domain helpers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating a trailing 'Z'."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_renter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["renter_type"] in ("THEATRE", "FILM", "EVENT", "INDIVIDUAL")
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_hold"], bool)


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("renter_id", ""))
    assert isinstance(data["insurer_name"], str)
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["coverage_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_rate_card(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["long_run_threshold_weeks"], int)
    assert isinstance(data["deep_run_threshold_weeks"], int)
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")


def assert_item(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["period"] in (
        "ANCIENT", "MEDIEVAL", "RENAISSANCE", "REGENCY", "VICTORIAN", "EDWARDIAN",
        "TWENTIES", "FIFTIES", "EIGHTIES", "CONTEMPORARY", "FANTASY",
    )
    assert data["category"] in ("COSTUME", "PROP", "SET_DRESSING", "WEAPONRY", "ACCESSORY")
    assert data["size_class"] in ("NONE", "XS", "S", "M", "L", "XL", "PLUS")
    assert data["alteration_policy"] in ("PROHIBITED", "REVERSIBLE_ONLY", "TAILORING_ALLOWED")
    assert isinstance(data["replacement_value_cents"], int)
    assert isinstance(data["base_daily_rate_cents"], int)
    assert isinstance(data["base_weekly_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "DEACCESSION_PENDING", "DEACCESSIONED")
    assert isinstance(data["serviceable_unit_count"], int)


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["barcode"], str) and data["barcode"]
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert isinstance(data["acquisition_date"], str)
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["status"] in (
        "AVAILABLE", "OUT", "CLEANING", "REPAIR", "AWAITING_DISPOSAL", "DISPOSED",
    )


def assert_production(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("renter_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["rehearsal_start_date"], str)
    assert isinstance(data["performance_start_date"], str)
    assert isinstance(data["closing_date"], str)
    assert data["status"] in ("DRAFT", "CONFIRMED", "IN_RUN", "WRAP", "SETTLED", "CANCELLED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "EXPIRED", "FULFILLED")
    assert data["rate_variant"] in ("DAILY", "WEEKLY", "LONG_RUN")
    assert isinstance(data["quoted_charge_cents"], int)
    assert isinstance(data["hold_expires_at"], str)


def assert_pull_list(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert data["status"] in ("DRAFT", "PICKING", "DISPATCHED", "CLOSED", "CANCELLED")


def assert_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pull_list_id", ""))
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("item_unit_id", ""))
    assert data["status"] in ("PENDING", "PICKED", "OUT", "RETURNED", "DAMAGED", "LOST")
    assert isinstance(data["rental_charge_cents"], int)
    assert isinstance(data["late_fee_cents"], int)


def assert_fitting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pull_list_line_id", ""))
    assert data["alteration_type"] in ("HEM", "TAKE_IN", "LET_OUT", "DYE", "DISTRESS", "TRIM")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "RESTORED")


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pull_list_line_id", ""))
    assert data["condition_grade_before"] in ("A", "B", "C", "D")
    assert data["condition_grade_after"] in ("A", "B", "C", "D")
    assert data["damage_severity"] in ("NONE", "MINOR", "REPAIRABLE", "DESTROYED")
    assert isinstance(data["restoration_complete"], bool)
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0
    assert isinstance(data["assessed_by_user_id"], str)


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pull_list_line_id", ""))
    assert data["claim_type"] in ("DAMAGE", "LOSS")
    assert data["status"] in ("DRAFT", "POSTED", "DISPUTED", "WAIVED")
    assert isinstance(data["assessed_value_cents"], int)


def assert_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("item_unit_id", ""))
    assert data["status"] in ("QUEUED", "IN_CLEANING", "INSPECTION", "REPAIR", "READY")
    assert isinstance(data["requires_repair"], bool)
    assert isinstance(data["repair_done"], bool)
    assert isinstance(data["queue_depth_at_creation"], int)
    assert isinstance(data["cleaning_fee_cents"], int)
    assert isinstance(data["invoiced"], bool)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert data["status"] in ("OPEN", "ISSUED", "PARTIALLY_PAID", "PAID", "CREDITED", "VOID")
    for field in (
        "rental_charges_cents", "late_fee_cents", "cleaning_charges_cents",
        "damage_charges_cents", "total_cents", "credited_cents",
        "amount_paid_cents", "balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["balance_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        "balance_cents must equal total_cents - amount_paid_cents"
    )
