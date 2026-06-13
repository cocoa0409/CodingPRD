"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_REGISTRATION_STATES = {
    "PENDING_PAYMENT", "CONFIRMED", "BIB_ASSIGNED", "WAITLISTED",
    "CANCELLED", "DEFERRED", "TRANSFERRED", "FINISHED",
}
_EVENT_STATES = {"DRAFT", "OPEN", "CLOSED", "RESULTS_POSTED", "CANCELLED"}
_WAITLIST_STATES = {"QUEUED", "OFFERED", "CLAIMED", "EXPIRED", "DECLINED", "WITHDRAWN"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["gender"] in ("M", "F", "X")


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in _EVENT_STATES, f"unexpected event status {data['status']}"


def assert_distance(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_total"], int) and data["capacity_total"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert isinstance(data["charity_confirmed_count"], int)
    assert isinstance(data["waitlist_open"], bool)


def assert_wave(data: dict):
    _assert_common(data)
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in _REGISTRATION_STATES, f"unexpected status {data['status']}"
    assert data["entry_type"] in ("STANDARD", "CHARITY")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in _WAITLIST_STATES


def assert_pledge(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLEDGED", "SETTLED", "VOIDED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ACCEPTED", "REJECTED", "CANCELLED")


def assert_bib_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["bib_number"], int)
    assert isinstance(data["corral"], str) and len(data["corral"]) == 1


def assert_packet_pickup(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "VOIDED")


def assert_result_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROVISIONAL", "OFFICIAL", "DQ")


def assert_pricing_tier(data: dict):
    """A PricingTier is immutable: it carries only id and created_at — no
    updated_at and no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PricingTier must NOT carry a version field"
    assert "updated_at" not in data, "PricingTier must NOT carry an updated_at field"
