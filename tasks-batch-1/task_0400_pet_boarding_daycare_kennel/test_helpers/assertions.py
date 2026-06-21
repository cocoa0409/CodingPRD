"""Entity assertions and domain invariant checkers.

Each ``assert_{entity}`` validates the response shape of one entity against the
PRD contract. Append-only entities (VaccinationRecord, PackageRedemption) carry
only ``id`` and ``created_at`` — they have no ``updated_at`` or ``version``.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# --------------------------------------------------------------------------- Facility
def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["deposit_policy"] in ("STANDARD", "STRICT", "NONE")
    assert isinstance(data["overbook_grace"], int) and data["overbook_grace"] >= 0
    assert isinstance(data["current_date"], str)


# --------------------------------------------------------------------------- Owner
def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0


# --------------------------------------------------------------------------- Pet
def assert_pet(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ("DOG", "CAT")
    assert data["temperament"] in ("CALM", "PLAYFUL", "REACTIVE")
    assert data["size_class"] in ("TOY", "SMALL", "MEDIUM", "LARGE")
    assert data["vaccination_status"] in ("VALID", "EXPIRED", "MISSING")
    assert data["temperament_clearance"] in ("UNREVIEWED", "CLEARED", "FLAGGED")


# --------------------------------------------------------------------------- Run
def assert_run(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["kind"] in ("OVERNIGHT_SUITE", "DAYCARE_PEN")
    assert data["size_class"] in ("TOY", "SMALL", "MEDIUM", "LARGE")
    assert isinstance(data["daycare_capacity"], int)
    assert data["status"] in ("AVAILABLE", "RETIRED")


# --------------------------------------------------------------------------- Reservation
def assert_reservation(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("DAYCARE", "OVERNIGHT")
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT",
        "CLOSED", "CANCELLED", "NO_SHOW",
    )
    for field in ("deposit_cents", "deposit_paid_cents", "total_cents", "refund_cents"):
        assert isinstance(data[field], int), f"{field} must be an int (cents)"
    assert isinstance(data["redeemed_credit"], bool)
    assert isinstance(data["nights"], int)


# --------------------------------------------------------------------------- RunAssignment
def assert_run_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "OCCUPIED", "RELEASED")
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)


# --------------------------------------------------------------------------- AddOn
def assert_addon(data: dict):
    _assert_common(data)
    assert data["kind"] in ("BATH", "PLAYTIME")
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ("BOOKED", "DELIVERED", "CANCELLED")


# --------------------------------------------------------------------------- Package
def assert_package(data: dict):
    _assert_common(data)
    assert data["tier"] in ("DAYCARE_10", "DAYCARE_20")
    assert isinstance(data["credits_total"], int)
    assert isinstance(data["credits_remaining"], int)
    assert data["credits_remaining"] >= 0
    assert data["status"] in ("ACTIVE", "EXPIRED")


# --------------------------------------------------------------------------- VaccinationRecord
def assert_vaccination_record(data: dict):
    _assert_append_only(data)
    assert data["vaccine"] in ("RABIES", "DHPP", "BORDETELLA", "FVRCP")
    assert isinstance(data["superseded"], bool)
    assert "updated_at" not in data, "VaccinationRecord is append-only; no updated_at"
    assert "version" not in data, "VaccinationRecord is append-only; no version"


# --------------------------------------------------------------------------- PackageRedemption
def assert_package_redemption(data: dict):
    _assert_append_only(data)
    assert isinstance(data["credits_used"], int)
    assert isinstance(data["reversed"], bool)
    assert "updated_at" not in data, "PackageRedemption is append-only; no updated_at"
    assert "version" not in data, "PackageRedemption is append-only; no version"
