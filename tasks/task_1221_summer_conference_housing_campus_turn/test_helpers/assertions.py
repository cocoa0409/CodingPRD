"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_equal(actual: str, expected: str):
    """Clock-stamped instants compare by value, not by string format.

    The PRD pins three fractional digits only for api_request_timestamp,
    created_at, and updated_at (§2.2, §2.4); domain fields stamped from the
    logical clock (actual_checkin_at, window_start, returned_at, ...) carry no
    declared string format, so equality is evaluated on the parsed instant.
    """
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse(actual) == _parse(expected), f"{actual!r} != {expected!r} as instants"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_building(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["key_pool_size"], int) and data["key_pool_size"] >= 0
    assert data["status"] in [
        "ACADEMIC_USE", "RELEASE_REVIEW", "RELEASED",
        "TURN_ACTIVE", "FALL_PREP", "READY_FOR_FALL",
    ]
    for counter in ("released_bed_count", "reserved_bed_count", "available_bed_count",
                    "scheduled_turn_count", "out_of_service_room_count", "available_key_count"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_number"], str) and data["room_number"]
    assert isinstance(data["bed_count"], int) and data["bed_count"] >= 1
    assert data["status"] in [
        "ACADEMIC_OCCUPIED", "RELEASED", "RESERVED", "OCCUPIED",
        "NEEDS_TURN", "IN_TURN", "READY", "OUT_OF_SERVICE",
    ]
    assert "active_turn_task_id" in data
    assert "out_of_service_window_id" in data


def assert_conference_group(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert isinstance(data["contracted_bed_count"], int) and data["contracted_bed_count"] >= 1
    assert isinstance(data["deposit_paid_cents"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "RETURNED", "CONFIRMED",
        "IN_HOUSE", "DEPARTED", "CLOSED", "CANCELLED",
    ]
    assert data["linen_tier"] in ["STANDARD", "DELUXE"]
    assert "provisional_invoice_id" in data
    assert "cancellation_fee_cents" in data


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_in_group"] in ["ATTENDEE", "CHAPERONE", "STAFF"]
    assert isinstance(data["is_minor"], bool)


def assert_rooming_list_revision(data: dict):
    # Immutable entity: only id and created_at of the common fields (PRD).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "revisions carry no version field"
    assert "updated_at" not in data, "revisions carry no updated_at field"
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["assignment_ids"], list)


def assert_stay_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["status"] in [
        "RESERVED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW", "CANCELLED",
    ]
    assert "actual_checkin_at" in data
    assert "actual_checkout_at" in data


def assert_background_screening(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "IN_REVIEW", "CLEARED", "FLAGGED", "APPEALED", "DENIED",
    ]
    assert "decided_at" in data
    assert "cleared_on" in data


def assert_turn_task(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert data["status"] in [
        "SCHEDULED", "IN_PROGRESS", "READY_FOR_INSPECTION",
        "PASSED", "FAILED", "CANCELLED",
    ]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["linen_tier"] in ["STANDARD", "DELUXE"]


def assert_linen_issue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["packs_issued"], int) and data["packs_issued"] >= 1
    assert isinstance(data["packs_returned"], int) and data["packs_returned"] >= 0
    assert isinstance(data["packs_damaged"], int) and data["packs_damaged"] >= 0
    assert data["status"] in ["ISSUED", "PARTIALLY_RETURNED", "RECONCILED"]
    assert isinstance(data["loss_charge_cents"], int)


def assert_key_credential(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["credential_code"], str) and data["credential_code"]
    assert data["status"] in ["ISSUED", "ACTIVATED", "RETURNED", "LOST"]
    assert "returned_at" in data
    assert "late_fee_cents" in data
    assert "lost_fee_cents" in data


def assert_damage_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_items"], list)
    assert isinstance(data["estimate_total_cents"], int)
    assert data["status"] in ["REPORTED", "ASSESSED", "BILLED", "DISPUTED", "WAIVED"]
    assert "assessed_total_cents" in data
    assert "assessed_at" in data


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "PAID", "VOID"]
    assert "provisional_bed_night_subtotal_cents" in data
    assert "provisional_total_cents" in data
    assert "final_bed_night_subtotal_cents" in data
    assert "total_cents" in data
    assert "balance_due_cents" in data


def assert_maintenance_window(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PLANNED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["buffer_days"], int) and data["buffer_days"] >= 0
    assert "blocked_start_date" in data
    assert "blocked_end_date" in data


def assert_allocation_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "LOCKED"]
    for bucket in ("gross_cents", "overhead_cents", "reserve_cents", "ops_cents"):
        assert isinstance(data[bucket], int), f"{bucket} must be an integer"


def assert_bed_ledger_invariant(building: dict):
    """available + reserved must always equal the frozen released bed count."""
    assert building["available_bed_count"] + building["reserved_bed_count"] \
        == building["released_bed_count"], (
        f"bed ledger drift: available {building['available_bed_count']} + reserved "
        f"{building['reserved_bed_count']} != released {building['released_bed_count']}"
    )


def assert_allocation_buckets_sum_to_gross(run: dict):
    """The three waterfall buckets always sum to gross exactly (PRD)."""
    assert run["overhead_cents"] + run["reserve_cents"] + run["ops_cents"] \
        == run["gross_cents"], (
        f"waterfall drift: {run['overhead_cents']} + {run['reserve_cents']} + "
        f"{run['ops_cents']} != gross {run['gross_cents']}"
    )
