"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

LISTING_STATUSES = ["DRAFT", "ACTIVE", "UNDER_CONTRACT", "PENDING", "CLOSED", "WITHDRAWN"]
OFFER_STATUSES = ["OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED", "ACCEPTED",
                  "REJECTED", "WITHDRAWN", "EXPIRED"]
SHOWING_STATUSES = ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]
CONTINGENCY_STATUSES = ["PENDING", "WAIVED", "SATISFIED", "FAILED"]
CONTINGENCY_KINDS = ["INSPECTION", "APPRAISAL", "FINANCING"]


def _assert_common_quartet(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_brokerage(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["default_total_commission_pct"], (int, float))
    assert isinstance(data["default_coop_split_pct"], (int, float))


def assert_agent(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["brokerage_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_no"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_buyer(data: dict):
    """Buyer is append-only: id + created_at only, no updated_at / version."""
    _assert_append_only(data)
    assert "updated_at" not in data, "Buyer is append-only and must omit updated_at"
    assert "version" not in data, "Buyer is append-only and must omit version"
    assert is_valid_uuid(data["buyer_agent_id"])
    assert isinstance(data["max_budget_cents"], int)
    assert isinstance(data["prequalified_amount_cents"], int)
    assert isinstance(data["monthly_income_cents"], int)
    assert isinstance(data["monthly_debt_cents"], int)


def assert_listing(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["listing_agent_id"])
    assert isinstance(data["address"], str)
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in LISTING_STATUSES
    assert data["offer_posture"] in ["NONE", "SINGLE", "MULTIPLE"]


def assert_lockbox(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["listing_id"])
    assert isinstance(data["serial_no"], str)
    assert data["access_mode"] in ["APPOINTMENT_ONLY", "OPEN_ACCESS"]
    assert isinstance(data["turnaround_minutes"], int)
    assert data["status"] in ["INSTALLED", "DISABLED"]


def assert_showing(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["lockbox_id"])
    assert is_valid_uuid(data["buyer_agent_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in SHOWING_STATUSES


def assert_offer(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert is_valid_uuid(data["buyer_agent_id"])
    assert isinstance(data["initial_price_cents"], int)
    assert isinstance(data["current_price_cents"], int)
    assert data["current_party"] in ["SELLER", "BUYER"]
    assert isinstance(data["round_count"], int)
    assert data["status"] in OFFER_STATUSES


def assert_counter_round(data: dict):
    """CounterRound is append-only: id + created_at only."""
    _assert_append_only(data)
    assert "updated_at" not in data, "CounterRound is append-only and must omit updated_at"
    assert "version" not in data, "CounterRound is append-only and must omit version"
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["by_party"] in ["SELLER", "BUYER"]
    assert isinstance(data["counter_price_cents"], int)


def assert_contingency(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["offer_id"])
    assert data["kind"] in CONTINGENCY_KINDS
    assert data["status"] in CONTINGENCY_STATUSES


def assert_commission_ledger(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["listing_id"])
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["total_commission_cents"], int)
    assert isinstance(data["coop_commission_cents"], int)
    assert isinstance(data["listing_side_commission_cents"], int)


def assert_commission_conserved(data: dict):
    """Co-op + listing-side shares must sum exactly to the total (PRD Section 2.7)."""
    assert (data["coop_commission_cents"] + data["listing_side_commission_cents"]
            == data["total_commission_cents"]), (
        f"shares {data['coop_commission_cents']} + "
        f"{data['listing_side_commission_cents']} must equal total "
        f"{data['total_commission_cents']}")
