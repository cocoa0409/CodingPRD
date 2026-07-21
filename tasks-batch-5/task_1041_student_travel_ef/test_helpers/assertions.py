"""Entity assertions and domain invariant checkers for the Student Travel EF API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_tour(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["destination"], str)
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0


def assert_group_leader(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["school_name"], str)
    assert isinstance(data["free_spot_credit_cents"], int) and data["free_spot_credit_cents"] >= 0


def assert_departure(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"DRAFT", "OPEN", "GUARANTEED", "DEPARTED", "CANCELLED"}
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    for f in ("active_enrollment_count", "paid_in_full_count", "free_spots_earned", "available_seats"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_departure_seat_identity(data: dict):
    """PRD §3.8: capacity == active_enrollment_count + free_spots_earned + available_seats."""
    lhs = data["capacity"]
    rhs = data["active_enrollment_count"] + data["free_spots_earned"] + data["available_seats"]
    assert lhs == rhs, (
        f"seat identity broken: capacity {lhs} != active {data['active_enrollment_count']} "
        f"+ free {data['free_spots_earned']} + available {data['available_seats']}"
    )


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert data["lifecycle_status"] in {"PENDING", "CONFIRMED", "TRAVELING", "COMPLETED", "CANCELLED"}
    assert data["payment_status"] in {"UNPAID", "PARTIAL", "PAID_IN_FULL", "REFUNDED"}
    assert data["traveler_gender"] in {"MALE", "FEMALE", "NONBINARY"}
    assert isinstance(data["price_locked_cents"], int) and data["price_locked_cents"] >= 0
    assert isinstance(data["doc_complete"], bool)


def assert_payment_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ACTIVE", "PAID", "REFUND_DUE", "REFUNDED", "SUPERSEDED"}
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_refunded_cents"], int) and data["amount_refunded_cents"] >= 0
    assert isinstance(data["installment_amounts"], list)


def assert_payment(data: dict):
    """Payment is an append-only ledger row: id + created_at only (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["kind"] in {"DEPOSIT", "INSTALLMENT", "REFUND", "PENALTY_RETAINED"}


def assert_permission_form(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"}


def assert_chaperone(data: dict):
    assert_common_fields(data)
    assert data["status"] == "CONFIRMED"
    assert data["role_type"] in {"TEACHER", "ADULT"}


def assert_rooming_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"DRAFT", "FINALIZED"}
    assert data["room_type"] in {"DOUBLE", "TRIPLE", "QUAD"}
    assert data["room_gender"] in {"MALE", "FEMALE", "NONBINARY"}
    assert isinstance(data["member_enrollment_ids"], list)


def assert_supplier_booking(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"HELD", "CONFIRMED", "CANCELLED"}


def find_payment_by_kind(payments: list, kind: str) -> list:
    """Return all ledger rows of a given kind from a payments list."""
    return [p for p in payments if p.get("kind") == kind]
