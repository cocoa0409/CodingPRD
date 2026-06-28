"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if with_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _append_only_common(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_council(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["charter_fee_cents"], int) and data["charter_fee_cents"] >= 0
    assert isinstance(data["youth_dues_cents"], int) and data["youth_dues_cents"] >= 0
    assert isinstance(data["adult_dues_cents"], int) and data["adult_dues_cents"] >= 0
    assert isinstance(data["fund_cash_cents"], int)
    assert isinstance(data["fund_liability_cents"], int)
    assert isinstance(data["program_year"], int) and data["program_year"] >= 2000


def assert_troop(data: dict):
    _common(data)
    assert isinstance(data["unit_number"], str) and len(data["unit_number"]) > 0
    assert data["program_type"] in ("CUB", "SCOUTS", "VENTURING")
    assert data["charter_status"] in ("PROVISIONAL", "CHARTERED", "LAPSED", "DROPPED")
    assert data["recharter_posture"] in ("READY", "BLOCKED", "EXPIRED")
    assert isinstance(data["registered_youth_count"], int) and data["registered_youth_count"] >= 0
    assert isinstance(data["cleared_leader_count"], int) and data["cleared_leader_count"] >= 0
    assert isinstance(data["dues_account_cents"], int)


def assert_member(data: dict):
    _common(data)
    assert data["member_type"] in ("YOUTH", "ADULT")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["rank"] in ("SCOUT", "TENDERFOOT", "SECOND_CLASS", "FIRST_CLASS")
    assert data["registration_status"] in ("PENDING", "REGISTERED", "SUSPENDED", "DROPPED")


def assert_dues_invoice(data: dict):
    _common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("OPEN", "PAID", "VOID")


def assert_payment(data: dict):
    """Payment is append-only: id + created_at only, no version / updated_at."""
    _append_only_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] == "POSTED"


def assert_leader_credential(data: dict):
    _common(data)
    assert data["bgcheck_status"] in ("NOT_STARTED", "PENDING", "CLEARED", "FLAGGED")
    assert data["training_status"] in ("UNTRAINED", "TRAINED")


def assert_advancement(data: dict):
    _common(data)
    assert data["kind"] in ("RANK", "BADGE")
    assert isinstance(data["requirements_total"], int) and data["requirements_total"] >= 1
    assert isinstance(data["requirements_signed"], int) and data["requirements_signed"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED")


def assert_event(data: dict):
    _common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["status"] in ("OPEN", "LOCKED", "CANCELLED")


def assert_event_registration(data: dict):
    _common(data)
    assert data["permission_status"] in ("UNSIGNED", "SIGNED")
    assert data["health_status"] in ("MISSING", "ON_FILE")
    assert data["status"] in ("HOLD", "CONFIRMED", "CANCELLED")


def assert_fundraiser(data: dict):
    _common(data)
    assert data["product"] in ("COOKIES", "POPCORN")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["total_inventory_units"], int) and data["total_inventory_units"] >= 0
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["available_units"], int)
    assert data["status"] in ("DRAFT", "LIVE", "CLOSED")


def assert_fundraiser_order(data: dict):
    _common(data)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["troop_commission_cents"], int)
    assert data["status"] in ("PLACED", "FILLED", "CANCELLED")


def assert_booth_reservation(data: dict):
    _common(data)
    assert isinstance(data["location_code"], str) and len(data["location_code"]) > 0
    assert data["status"] in ("BOOKED", "RELEASED")


def assert_fund_ledger_entry(data: dict):
    """FundLedgerEntry is append-only: id + created_at only."""
    _append_only_common(data)
    assert data["account"] in ("COUNCIL_CASH", "PRODUCT_LIABILITY", "TROOP_DUES")
    assert isinstance(data["amount_cents"], int)
    assert data["source_kind"] in ("PAYMENT", "FUNDRAISER_ORDER", "RECHARTER", "REVERSAL")
