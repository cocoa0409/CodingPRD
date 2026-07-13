"""Entity assertions and domain invariant checkers for the Monument & Headstone API."""
from datetime import datetime
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds / Z)."""
    assert isinstance(s, str) and s, f"expected timestamp string, got {s!r}"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant (format-tolerant)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_cemetery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["allowed_materials"], list)
    for m in data["allowed_materials"]:
        assert m in ("GRANITE", "BRONZE", "MARBLE")
    for f in ("max_height_cm", "max_width_cm", "max_base_width_cm"):
        assert isinstance(data[f], int)
    assert isinstance(data["requires_permit"], bool)
    assert isinstance(data["permit_fee_cents"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"]), "customer_id must be a UUID"
    assert is_valid_uuid(data["cemetery_id"]), "cemetery_id must be a UUID"
    assert data["subject_type"] in ("HUMAN", "PET")
    assert data["material"] in ("GRANITE", "BRONZE", "MARBLE")
    assert data["production_status"] in (
        "DRAFTING", "IN_FABRICATION", "READY_TO_INSTALL", "INSTALLED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED")
    for f in (
        "provisional_merchandise_cents", "merchandise_price_cents", "contract_total_cents",
        "deposit_amount_cents", "balance_amount_cents", "amount_paid_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_order_money_invariant(data: dict):
    """deposit + balance == contract_total (PRD §3.2), amounts non-negative."""
    assert data["deposit_amount_cents"] + data["balance_amount_cents"] == data["contract_total_cents"], (
        "deposit + balance must equal contract_total exactly"
    )
    assert data["contract_total_cents"] >= 0
    assert data["deposit_amount_cents"] >= 0


def assert_design_proof(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"]), "order_id must be a UUID"
    assert isinstance(data["engraving_text"], str)
    assert isinstance(data["line_char_counts"], list)
    assert isinstance(data["revision_round"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED", "VOIDED",
    )


def assert_payment(data: dict):
    # Payment is immutable: id + created_at only (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["order_id"]), "order_id must be a UUID"
    assert data["payment_type"] in ("DEPOSIT", "BALANCE", "REFUND")
    assert isinstance(data["signed_amount_cents"], int)
    assert data["status"] == "CAPTURED"


def assert_workshop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["booked_minutes"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["booked_minutes"], int)


def assert_fabrication_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["workshop_id"])
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["cemetery_id"])
    assert data["status"] in ("PENDING", "ISSUED", "REVOKED")


def assert_installation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["crew_id"])
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_restoration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["service_type"] in ("CLEANING", "REPAIR", "REFINISH")
    assert isinstance(data["quoted_cost_cents"], int)
    assert data["status"] in ("REQUESTED", "ASSESSED", "CANCELLED")
