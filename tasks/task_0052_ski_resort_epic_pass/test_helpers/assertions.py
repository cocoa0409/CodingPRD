"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version present and well-formed (full common set)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_resort(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["home_network"] in ("EPIC", "IKON")
    assert data["status"] in ("OPEN", "SUSPENDED")
    assert isinstance(data["gate_count"], int) and data["gate_count"] >= 1


def assert_pass_product(data: dict):
    _assert_common(data)
    assert data["tier"] in ("LOCAL", "EPIC_DAY", "FULL_EPIC")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["blackout_dates"], list)
    assert isinstance(data["buddy_ticket_allotment"], int) and data["buddy_ticket_allotment"] >= 0
    assert isinstance(data["buddy_ticket_price_cents"], int) and data["buddy_ticket_price_cents"] >= 0
    assert isinstance(data["ikon_interchange_enabled"], bool)


def assert_pass(data: dict):
    _assert_common(data)
    assert isinstance(data["pass_product_id"], str)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert isinstance(data["magnetic_token"], str) and len(data["magnetic_token"]) > 0
    assert data["status"] in ("ISSUED", "ACTIVE", "SUSPENDED", "REFUNDED", "EXPIRED")
    assert isinstance(data["scan_count"], int) and data["scan_count"] >= 0
    assert isinstance(data["buddy_tickets_remaining"], int) and data["buddy_tickets_remaining"] >= 0
    assert isinstance(data["refund_basis_cents"], int) and data["refund_basis_cents"] >= 0


def assert_buddy_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["pass_id"], str)
    assert isinstance(data["resort_id"], str)
    assert isinstance(data["guest_name"], str) and len(data["guest_name"]) > 0
    assert isinstance(data["valid_date"], str) and len(data["valid_date"]) == 10
    assert isinstance(data["price_charged_cents"], int) and data["price_charged_cents"] >= 0
    assert data["status"] in ("RESERVED", "REDEEMED", "CANCELLED")


def assert_refund_request(data: dict):
    _assert_common(data)
    assert isinstance(data["pass_id"], str)
    assert data["reason"] in ("INJURY", "RELOCATION", "DISSATISFIED")
    assert isinstance(data["scan_count_at_request"], int) and data["scan_count_at_request"] >= 0
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_interchange_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["resort_id"], str)
    assert isinstance(data["max_interchange_days"], int) and data["max_interchange_days"] >= 1
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_lift_scan(data: dict):
    """LiftScan is an immutable audit row: id + created_at only (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["pass_id"], str)
    assert isinstance(data["resort_id"], str)
    assert data["result"] in ("GRANTED", "DENIED")
    if data["result"] == "GRANTED":
        assert data.get("denial_reason") is None, "GRANTED scan must have null denial_reason"
    else:
        assert data["denial_reason"] in (
            "BLACKOUT", "TOKEN_MISMATCH", "NOT_ACTIVE",
            "NO_INTERCHANGE", "RESORT_SUSPENDED", "ANTI_PASSBACK",
        )
