"""Entity assertions for the Estate Sale API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PROJECT_STATES = {
    "LEAD", "ASSESSED", "PROPOSED", "COUNTERED", "CONTRACTED",
    "SALE_SETUP", "SALE_LIVE", "SETTLING", "SETTLED", "CANCELLED",
}
LOT_STATES = {
    "NEW", "RESEARCHED", "PRICED", "STAGED", "TAGGED", "LISTED",
    "BID_CLOSED", "SOLD", "UNSOLD", "WITHDRAWN",
}
SALE_EVENT_STATES = {"SCHEDULED", "OPEN", "CLOSED", "CANCELLED"}
TRANSACTION_STATES = {"RECORDED", "VOIDED"}
BID_STATES = {"PLACED", "WON", "LOST", "VOIDED"}
HAUL_JOB_STATES = {"SCHEDULED", "COMPLETED", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in PROJECT_STATES, f"unexpected project status {data['status']}"
    assert isinstance(data["client_id"], str)
    assert isinstance(data["gross_sales_cents"], int)
    assert isinstance(data["buyout_advances_cents"], int)
    assert isinstance(data["unsold_lot_count"], int)


def assert_lot(data: dict):
    _assert_common(data)
    assert data["status"] in LOT_STATES, f"unexpected lot status {data['status']}"
    assert data["handling_type"] in {"CONSIGNMENT", "BUYOUT"}
    assert isinstance(data["is_bid_lot"], bool)
    assert isinstance(data["title"], str) and len(data["title"]) > 0


def assert_sale_event(data: dict):
    _assert_common(data)
    assert data["status"] in SALE_EVENT_STATES, f"unexpected sale event status {data['status']}"
    assert isinstance(data["window_minutes"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["booked_minutes"], int)


def assert_transaction(data: dict):
    _assert_common(data)
    assert data["status"] in TRANSACTION_STATES, f"unexpected transaction status {data['status']}"
    assert data["payment_method"] in {"CASH", "CARD"}
    assert isinstance(data["final_price_cents"], int)
    assert isinstance(data["card_fee_cents"], int)


def assert_bid(data: dict):
    _assert_common(data)
    assert data["status"] in BID_STATES, f"unexpected bid status {data['status']}"
    assert isinstance(data["amount_cents"], int)


def assert_haul_job(data: dict):
    _assert_common(data)
    assert data["status"] in HAUL_JOB_STATES, f"unexpected haul job status {data['status']}"
    assert data["disposition_type"] in {"DONATION", "HAULAWAY", "BUYBACK"}


def assert_truck(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_settlement_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["gross_consignment_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["card_fees_cents"], int)
    assert isinstance(data["net_to_client_cents"], int)
    assert isinstance(data["unsold_lot_count"], int)
    assert isinstance(data["superseded"], bool)
