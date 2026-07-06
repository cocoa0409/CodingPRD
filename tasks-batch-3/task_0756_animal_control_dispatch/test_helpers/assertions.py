"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ZONES = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["zone"] in ZONES
    assert data["animal_type"] in ["DOG", "CAT", "WILDLIFE", "LIVESTOCK", "OTHER"]
    assert data["complaint_type"] in ["STRAY", "BITE", "CRUELTY", "DANGEROUS_DOG", "NOISE", "OTHER"]
    assert isinstance(data["involves_vulnerable_victim"], bool)
    assert isinstance(data["severity_score"], (int, float))
    assert data["priority"] in ["P1", "P2", "P3"]
    assert data["status"] in ["NEW", "DISPATCHED", "RESOLVED", "CLOSED"]


def assert_officer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["territory_zone"] in ZONES
    assert isinstance(data["max_daily_dispatches"], int)
    assert isinstance(data["active_dispatch_count"], int)


def assert_kennel(data: dict):
    _assert_common(data)
    assert data["facility_zone"] in ZONES
    assert isinstance(data["occupied_slots"], int)


def assert_dispatch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["complaint_id"])
    assert is_valid_uuid(data["officer_id"])
    assert data["status"] in ["PENDING", "EN_ROUTE", "CLEARED"]


def assert_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["complaint_id"])
    assert is_valid_uuid(data["assigned_officer_id"])
    assert data["case_type"] in ["STRAY", "BITE", "CRUELTY", "DANGEROUS_DOG"]
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["outstanding_fines_total"], (int, float))
    assert isinstance(data["public_health_flag"], bool)
    assert data["status"] in ["OPEN", "UNDER_INVESTIGATION", "SUBSTANTIATED", "UNFOUNDED", "CLOSED"]


def assert_investigation_note(data: dict):
    """InvestigationNote is append-only/immutable: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["note_type"] in ["OBSERVATION", "EVIDENCE", "WITNESS", "FOLLOWUP"]
    assert isinstance(data["body"], str)


def assert_quarantine_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert data["hold_type"] in ["HOME_QUARANTINE", "FACILITY_QUARANTINE"]
    assert isinstance(data["required_days"], int)
    assert is_iso8601_timestamp(data["release_due_at"])
    assert data["status"] in ["ACTIVE", "RELEASED", "ESCALATED", "VOIDED"]


def assert_impound(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["kennel_id"])
    assert isinstance(data["boarding_fee"], (int, float))
    assert data["status"] in ["HELD", "REDEEMED", "ADOPTED", "EUTHANIZED", "RELEASED"]


def assert_citation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert data["violation_code"] in ["UNLICENSED", "LEASH", "DANGEROUS", "BITE", "CRUELTY"]
    assert isinstance(data["base_fine"], (int, float))
    assert isinstance(data["fine_amount"], (int, float))
    assert data["status"] in ["ISSUED", "PAID", "COURT_REFERRED"]


def assert_rabies_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["quarantine_hold_id"])
    assert is_iso8601_timestamp(data["deadline_at"])
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ["SUBMITTED", "CLEARED", "ESCALATED"]
