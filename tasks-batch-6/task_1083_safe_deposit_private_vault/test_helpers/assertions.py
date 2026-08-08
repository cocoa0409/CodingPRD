"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["code"], str)
    assert isinstance(data["viewing_room_capacity"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_box_type(data: dict):
    _assert_common(data)
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE", "JUMBO")
    assert isinstance(data["annual_rate_cents"], int) and data["annual_rate_cents"] > 0


def assert_box(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "RENTED", "DELINQUENT",
        "DRILL_PENDING", "DRILLED", "OUT_OF_SERVICE",
    )


def assert_renter(data: dict):
    _assert_common(data)
    assert data["kyc_status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert data["standing"] in ("GOOD", "FROZEN")
    assert isinstance(data["is_deceased"], bool)


def assert_rental(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "ACTIVE", "PAST_DUE", "DELINQUENT",
        "SURRENDER_PENDING", "CLOSED", "ABANDONED",
    )
    assert isinstance(data["annual_rate_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "VOID", "WRITTEN_OFF")
    for f in ("base_rent_cents", "insurance_rider_cents", "precious_metal_surcharge_cents",
              "late_fee_cents", "total_cents", "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["total_cents"] == (
        data["base_rent_cents"] + data["insurance_rider_cents"]
        + data["precious_metal_surcharge_cents"] + data["late_fee_cents"]
    ), "total_cents must equal the sum of its components"


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_access_grant(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED", "EXERCISED")
    assert data["grant_type"] in ("CO_RENTER", "DEPUTY", "BENEFICIARY")
    assert isinstance(data["requires_death_certificate"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert is_valid_uuid(data.get("branch_id", "")), "branch_id must be denormalized UUID"


def assert_access_event(data: dict):
    """AccessEvent is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in ("ENTRY", "EXIT")
    assert isinstance(data["witness_count"], int)


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("DECLARED", "APPRAISED", "INSURED", "RELEASED")
    assert data["category"] in ("PRECIOUS_METAL", "JEWELRY", "DOCUMENT", "OTHER")


def assert_drilling_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "SCHEDULED", "DRILLED", "CANCELLED")
    assert data["reason"] in ("ABANDONMENT", "DELINQUENCY", "LOST_KEY", "COURT_ORDER")


def assert_compliance_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ESCALATED", "CLEARED", "CLOSED")
    assert data["case_type"] in ("KYC", "SANCTIONS", "SAR", "CTR")


def assert_waterfall_conserved(order: dict, proceeds_cents: int):
    """The four proceeds buckets must sum to the input proceeds exactly (PRD §3.9)."""
    buckets = (
        order["proceeds_to_arrears_cents"],
        order["proceeds_to_drilling_cents"],
        order["proceeds_to_admin_cents"],
        order["proceeds_to_escrow_cents"],
    )
    assert sum(buckets) == proceeds_cents, (
        f"waterfall buckets {buckets} must sum to proceeds {proceeds_cents}"
    )
