"""Entity assertions and domain invariant checkers (PRD §2.4, §3, §2.10)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --- Common-field helpers ------------------------------------------------------

def assert_common_full(data: dict):
    """id + created_at + updated_at + version quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_common_light(data: dict):
    """Lightweight resources carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lightweight resource must not carry version"
    assert "updated_at" not in data, "lightweight resource must not carry updated_at"


# --- Entity assertions ---------------------------------------------------------

def assert_permittee(data: dict):
    assert_common_full(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["permittee_type"] in ["CARRIER", "VALET_OPERATOR", "TNC", "MERCHANT"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["outstanding_fines_cents"], int)


def assert_zone(data: dict):
    assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["designation"] in ["LOADING", "VALET", "TNC", "PASSENGER", "METERED", "NO_STANDING"]
    assert data["capacity_slots"] >= 1
    assert data["status"] in ["ACTIVE", "SUSPENDED", "RETIRED"]
    assert data["sensor_occupancy_state"] in ["VACANT", "OCCUPIED"]
    assert isinstance(data["revenue_accrued_cents"], int)


def assert_permit(data: dict):
    assert_common_full(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACTIVE", "DENIED", "REVOKED"]
    assert isinstance(data["zone_ids"], list)
    assert data["requested_designation"] in ["LOADING", "VALET", "TNC"]


def assert_reservation(data: dict):
    assert_common_full(data)
    assert data["booking_status"] in [
        "PENDING", "CONFIRMED", "FULFILLED", "CANCELLED", "NO_SHOW", "CANCELLED_BY_EVENT",
    ]
    assert data["payment_status"] in ["UNPAID", "CAPTURED", "REFUNDED"]


def assert_occupancy_session(data: dict):
    assert_common_full(data)
    assert data["session_status"] in ["OPEN", "CLOSED"]
    assert is_iso8601_timestamp(data.get("entered_at", "")), "entered_at must be ISO 8601"


def assert_citation(data: dict):
    assert_common_full(data)
    assert data["violation_type"] in ["OVERSTAY", "NO_PERMIT", "UNAUTHORIZED_ZONE", "WRONG_DESIGNATION"]
    assert data["status"] in ["ISSUED", "DISPUTED", "UPHELD", "PAID", "DISMISSED"]
    assert isinstance(data["fine_due_cents"], int)


def assert_event(data: dict):
    assert_common_full(data)
    assert data["status"] in ["PLANNED", "ACTIVE", "CLOSED", "CANCELLED"]
    assert isinstance(data["zone_ids"], list)


def assert_pricing_policy(data: dict):
    assert_common_light(data)
    assert isinstance(data["base_rate_cents_per_15min"], int)


def assert_schedule_window(data: dict):
    assert_common_light(data)
    assert 0 <= data["day_of_week"] <= 6


def assert_ledger_entry(data: dict):
    assert_common_light(data)
    assert data["entry_type"] in ["CHARGE", "REFUND", "ADJUSTMENT", "FINE"]
    assert isinstance(data["amount_cents"], int)


# --- Ledger inspection helpers -------------------------------------------------

def ledger_entries_for_reservation(entries: list, reservation_id: str) -> list:
    return [e for e in entries if e.get("reservation_id") == reservation_id]


def ledger_entries_for_citation(entries: list, citation_id: str) -> list:
    return [e for e in entries if e.get("citation_id") == citation_id]


def ledger_entries_of_type(entries: list, entry_type: str) -> list:
    return [e for e in entries if e.get("entry_type") == entry_type]


def sum_ledger_amount(entries: list) -> int:
    return sum(e.get("amount_cents", 0) for e in entries)
