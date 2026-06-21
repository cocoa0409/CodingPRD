"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validates shape (UUID id, ISO timestamps, enum
membership, field types). Invariant checkers enforce cross-field rules the PRD
states hold "at all times" (e.g. the deposit ledger conservation in §2.10).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def _assert_common_lean(data: dict):
    """id + created_at only — append-only / immutable entities (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_student(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["deposit_balance_cents"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["deposit_consumed_cents"], int)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert_deposit_invariants(data)


def assert_deposit_invariants(data: dict):
    """Non-negativity / held-vs-consumed sanity that always holds on a Student."""
    assert data["deposit_held_cents"] >= 0, "deposit_held_cents never negative"
    assert data["deposit_consumed_cents"] >= 0, "deposit_consumed_cents never negative"


def assert_instructor(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["cfi_rate_cents_per_hour"], int)
    assert isinstance(data["authorized_endorsement_codes"], list)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_aircraft(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["tail_number"], str) and len(data["tail_number"]) > 0
    assert isinstance(data["model"], str)
    assert isinstance(data["is_complex"], bool)
    assert isinstance(data["rental_rate_cents_per_hour"], int)
    assert data["billing_basis"] in ("HOBBS", "TACH")
    assert isinstance(data["current_hobbs"], (int, float))
    assert isinstance(data["current_tach"], (int, float))
    assert isinstance(data["open_squawk_count"], int) and data["open_squawk_count"] >= 0
    assert data["status"] in ("AVAILABLE", "GROUNDED", "RETIRED")


def assert_syllabus(data: dict):
    _assert_common_lean(data)
    assert "version" not in data, "Syllabus is immutable and carries no version"
    assert "updated_at" not in data, "Syllabus carries no updated_at"
    assert isinstance(data["name"], str)
    assert isinstance(data["required_dual_hours"], (int, float))
    assert isinstance(data["required_solo_hours"], (int, float))
    assert isinstance(data["stage_count"], int)
    assert isinstance(data["min_deposit_cents"], int)


def assert_enrollment(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["syllabus_id"])
    assert data["medical_status"] in ("PENDING", "CLEARED", "EXPIRED")
    assert data["tsa_status"] in ("PENDING", "CLEARED", "DENIED")
    assert isinstance(data["logged_dual_hours"], (int, float))
    assert isinstance(data["logged_solo_hours"], (int, float))
    assert isinstance(data["current_stage_index"], int)
    assert data["status"] in (
        "PENDING_CLEARANCE", "ACTIVE", "SUSPENDED", "COMPLETED", "WITHDRAWN",
    )


def assert_deposit_transaction(data: dict):
    _assert_common_lean(data)
    assert "version" not in data, "DepositTransaction is append-only and carries no version"
    assert "updated_at" not in data, "DepositTransaction carries no updated_at"
    assert is_valid_uuid(data["student_id"])
    assert data["txn_type"] in ("DEPOSIT", "HOLD", "RELEASE", "CONSUME")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0, \
        "amount_cents is always a positive magnitude"


def assert_squawk(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["aircraft_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["is_grounding"], bool)
    assert data["status"] in ("OPEN", "DEFERRED", "RESOLVED")


def assert_booking(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert data["lesson_type"] in ("DUAL", "SOLO")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["estimated_hours"], (int, float))
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "DISPATCHED", "COMPLETED", "CANCELLED", "NO_SHOW",
    )


def assert_flight_log(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert isinstance(data["hobbs_start"], (int, float))
    assert isinstance(data["hobbs_end"], (int, float))
    assert isinstance(data["tach_start"], (int, float))
    assert isinstance(data["tach_end"], (int, float))
    assert isinstance(data["landings"], int)
    assert data["status"] in ("DRAFT", "POSTED", "VOID")


def assert_stage_check(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["examiner_instructor_id"])
    assert isinstance(data["stage_index"], int)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")


def assert_endorsement(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert data["endorsement_code"] in ("SOLO", "XC", "COMPLEX", "TAILWHEEL")
    assert data["status"] in ("VALID", "REVOKED")


def assert_ledger_conservation(student: dict, transactions: list):
    """PRD §2.10 conservation invariant across the student's full ledger.

    deposit_balance_cents   = sum(DEPOSIT) - sum(HOLD) + sum(RELEASE) - sum(CONSUME)
    deposit_held_cents      = sum(HOLD) - sum(RELEASE)
    deposit_consumed_cents  = sum(CONSUME)
    """
    by = {"DEPOSIT": 0, "HOLD": 0, "RELEASE": 0, "CONSUME": 0}
    for txn in transactions:
        by[txn["txn_type"]] += txn["amount_cents"]
    expected_balance = by["DEPOSIT"] - by["HOLD"] + by["RELEASE"] - by["CONSUME"]
    expected_held = by["HOLD"] - by["RELEASE"]
    expected_consumed = by["CONSUME"]
    assert student["deposit_balance_cents"] == expected_balance, (
        f"balance {student['deposit_balance_cents']} != ledger-derived {expected_balance}"
    )
    assert student["deposit_held_cents"] == expected_held, (
        f"held {student['deposit_held_cents']} != ledger-derived {expected_held}"
    )
    assert student["deposit_consumed_cents"] == expected_consumed, (
        f"consumed {student['deposit_consumed_cents']} != ledger-derived {expected_consumed}"
    )
