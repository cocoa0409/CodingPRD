"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)


def assert_consultation(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "COMPLETED")
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "INELIGIBLE")
    assert data["recommended_protocol"] in ("ANTAGONIST", "LONG_AGONIST", "MINIMAL_STIM", "NONE")
    assert isinstance(data["expected_oocyte_yield"], int)


def assert_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "MONITORING", "SUSPENDED", "TRIGGERED", "COMPLETED", "CANCELLED"
    )
    assert isinstance(data["monitoring_visit_count"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)


def assert_monitoring_appointment(data: dict):
    _assert_common(data)
    assert data["visit_status"] in ("SCHEDULED", "CANCELLED")


def assert_storage_tank(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["used_slots"], int) and data["used_slots"] >= 0
    assert isinstance(data["is_full"], bool)
    assert data["is_full"] == (data["used_slots"] >= data["capacity_slots"]), \
        "is_full must equal used_slots >= capacity_slots"


def assert_cryo_specimen(data: dict):
    _assert_common(data)
    assert data["status"] in ("STORED", "RESERVED", "THAWED", "DISCARDED")
    assert data["specimen_type"] in ("VIAL", "STRAW")


def assert_storage_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "PAST_DUE", "LAPSED", "CANCELLED")
    assert isinstance(data["specimen_count"], int) and data["specimen_count"] >= 0
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0


def assert_benefit_coverage(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED")
    assert data["consumed_cents"] + data["remaining_cents"] == data["annual_cap_cents"], \
        "invariant consumed_cents + remaining_cents == annual_cap_cents must hold"


def assert_directive(data: dict):
    _assert_common(data)
    assert data["directive_type"] in ("CONSENT", "DISPOSITION")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED")


def assert_thaw_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "EXECUTED", "DENIED")
    assert isinstance(data["specimen_ids"], list)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "VOID")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_due_cents"], int)
