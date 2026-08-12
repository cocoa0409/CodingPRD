"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}: version must be an integer"


def assert_organizer(data: dict):
    _assert_common_fields(data, "Organizer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["standing"] in ("GOOD", "FLAGGED", "SUSPENDED")
    assert isinstance(data["forfeiture_count"], int) and data["forfeiture_count"] >= 0


def assert_street_segment(data: dict):
    _assert_common_fields(data, "StreetSegment")
    assert data["jurisdiction"] in ("CITY", "COUNTY", "STATE_ROUTE")
    assert data["segment_kind"] in ("RESIDENTIAL", "MIXED_USE")
    assert isinstance(data["household_count"], int) and data["household_count"] >= 0
    assert isinstance(data["business_count"], int) and data["business_count"] >= 0
    assert isinstance(data["intersects_arterial"], bool)
    assert isinstance(data["length_m"], int) and data["length_m"] > 0


def assert_petition(data: dict):
    _assert_common_fields(data, "Petition")
    assert data["status"] in ("COLLECTING", "SUBMITTED", "VERIFIED", "DEFICIENT", "LOCKED")
    assert data["support_mode"] in ("SIGNATURE_COUNT", "DISTINCT_HOUSEHOLD")
    assert isinstance(data["required_signatures"], int) and data["required_signatures"] >= 1
    assert isinstance(data["valid_signature_count"], int) and data["valid_signature_count"] >= 0
    assert isinstance(data["distinct_household_count"], int) and data["distinct_household_count"] >= 0
    assert isinstance(data["cure_round"], int) and data["cure_round"] >= 0


def assert_petition_signature(data: dict):
    _assert_common_fields(data, "PetitionSignature")
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert isinstance(data["household_address"], str) and data["household_address"]
    assert isinstance(data["signer_email"], str) and data["signer_email"]


def assert_permit_application(data: dict):
    _assert_common_fields(data, "PermitApplication")
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "SUSPENDED", "APPROVED", "DENIED",
        "ISSUED", "COMPLETED", "CANCELLED", "REVOKED", "EXPIRED",
    )
    assert isinstance(data["expected_attendance"], int) and data["expected_attendance"] > 0
    assert isinstance(data["amplified_sound"], bool)
    assert isinstance(data["alcohol_served"], bool)
    assert isinstance(data["food_vendors"], bool)
    assert isinstance(data["petition_id"], str) and data["petition_id"]
    assert isinstance(data["segment_id"], str) and data["segment_id"]


def assert_traffic_control_plan(data: dict):
    _assert_common_fields(data, "TrafficControlPlan")
    assert data["status"] in ("DRAFT", "SUBMITTED", "TCP_APPROVED", "CHANGES_REQUESTED", "LOCKED")
    assert isinstance(data["barricade_count"], int) and data["barricade_count"] >= 0
    assert isinstance(data["cone_count"], int) and data["cone_count"] >= 0
    assert isinstance(data["sign_count"], int) and data["sign_count"] >= 0
    assert data["emergency_lane_width_m"] >= 0


def assert_sound_plan(data: dict):
    _assert_common_fields(data, "SoundPlan")
    assert data["status"] in ("DRAFT", "SUBMITTED", "SOUND_APPROVED", "CHANGES_REQUESTED", "LOCKED")
    assert isinstance(data["speaker_count"], int) and data["speaker_count"] > 0
    assert isinstance(data["max_db_at_property_line"], int) and data["max_db_at_property_line"] > 0


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data, "InsuranceCertificate")
    assert data["kind"] in ("CERTIFICATE", "WAIVER_REQUEST")
    assert data["status"] in (
        "SUBMITTED", "VERIFIED", "REJECTED", "WAIVER_GRANTED", "WAIVER_DENIED", "SUPERSEDED",
    )


def assert_equipment_stock(data: dict):
    _assert_common_fields(data, "EquipmentStock")
    assert data["equipment_kind"] in ("BARRICADE", "CONE", "SIGN")
    assert isinstance(data["total_units"], int) and data["total_units"] > 0
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["out_units"], int)
    assert isinstance(data["available_units"], int)


def assert_equipment_reservation(data: dict):
    _assert_common_fields(data, "EquipmentReservation")
    assert data["equipment_kind"] in ("BARRICADE", "CONE", "SIGN")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert data["reservation_status"] in (
        "HELD", "CONFIRMED", "DISPATCHED", "RETURNED", "CLOSED", "CANCELLED", "RECALLED",
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID", "WAIVED")


def assert_cost_share_pool(data: dict):
    _assert_common_fields(data, "CostSharePool")
    assert data["status"] in ("OPEN", "FUNDED", "CLOSED", "REFUNDING", "REFUNDED")
    assert isinstance(data["target_cents"], int) and data["target_cents"] > 0
    assert isinstance(data["collected_cents"], int) and data["collected_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_contribution(data: dict):
    _assert_common_fields(data, "Contribution")
    assert data["status"] in ("PAID", "REFUNDED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 100


def assert_deposit(data: dict):
    _assert_common_fields(data, "Deposit")
    assert data["status"] in ("HELD", "SETTLED", "FORFEITED")
    assert isinstance(data["required_cents"], int) and data["required_cents"] > 0
    assert isinstance(data["held_cents"], int) and data["held_cents"] > 0
    assert isinstance(data["charges_cents"], int) and data["charges_cents"] >= 0


def assert_charge_entry(data: dict):
    """ChargeEntry is append-only: id + created_at only from the common set (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ChargeEntry: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ChargeEntry: created_at must be ISO 8601"
    assert "updated_at" not in data, "ChargeEntry must not expose updated_at"
    assert "version" not in data, "ChargeEntry must not expose version"
    assert data["kind"] in ("LATE_EQUIPMENT", "SHORTAGE", "CLEANING")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_post_event_report(data: dict):
    _assert_common_fields(data, "PostEventReport")
    assert data["inspection_result"] in ("PENDING", "PASSED", "FAILED")
    assert isinstance(data["cleanup_completed"], bool)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))


def assert_stock_conservation(stock: dict):
    """PRD §2.9 conservation invariant: total == available + reserved + out."""
    total = stock["total_units"]
    reserved = stock["reserved_units"]
    out = stock["out_units"]
    available = stock["available_units"]
    assert total == available + reserved + out, (
        f"Stock conservation violated: total {total} != available {available} "
        f"+ reserved {reserved} + out {out}"
    )
    assert available >= 0 and reserved >= 0 and out >= 0
