"""Entity assertions and domain invariant checkers for the housing API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AttendeeType,
    CommissionBasis,
    ContactChannel,
    DetectionSource,
    HotelBlockStatus,
    HotelStanding,
    HousingPosture,
    IncidentStatus,
    InventoryStatus,
    InvoiceStatus,
    PickupSource,
    ReductionStatus,
    ReservationStatus,
    SubBlockApprovalStatus,
    SubBlockSegment,
    TransmissionStatus,
    TransmissionType,
    VendorStatus,
    WarningSeverity,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_identity_fields(data: dict):
    """PRD §2.4 — server-minted UUID id plus an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_record(data: dict):
    """PRD §2.4 — mutable resources additionally carry updated_at and version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_append_only_record(data: dict):
    """PRD §2.4 — append-only records carry only id and created_at."""
    assert_identity_fields(data)
    assert "version" not in data, "append-only records carry no version"
    assert "updated_at" not in data, "append-only records carry no updated_at"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_event(data: dict):
    assert_mutable_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["housing_posture"] in _values(HousingPosture)
    assert isinstance(data["night_count"], int) and data["night_count"] >= 1
    for field in (
        "total_contracted_room_nights",
        "total_confirmed_room_nights",
        "commission_collected_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"


def assert_hotel(data: dict):
    assert_mutable_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["distance_to_venue_miles"] >= 0
    assert 0 <= data["room_tax_pct"] < 1
    assert data["total_rooms"] >= 1
    assert data["standing"] in _values(HotelStanding)


def assert_hotel_block(data: dict):
    assert_mutable_record(data)
    assert data["status"] in _values(HotelBlockStatus)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["negotiated_nightly_rate_cents"] >= 1
    assert 0 < data["commission_pct"] <= 0.25
    assert data["rebate_per_room_night_cents"] >= 0
    assert 0 <= data["reduction_rights_pct"] <= 0.50
    assert data["contracted_rooms_per_night"] >= 0
    assert data["unassigned_rooms_per_night"] >= 0
    assert data["released_rooms_per_night"] >= 0
    assert data["contracted_room_nights"] >= 0
    assert data["attrition_liability_cents"] >= 0


def assert_sub_block(data: dict):
    assert_mutable_record(data)
    assert data["segment"] in _values(SubBlockSegment)
    assert data["approval_status"] in _values(SubBlockApprovalStatus)
    assert data["inventory_status"] in _values(InventoryStatus)
    assert data["allotted_rooms"] >= 0
    assert data["committed_rooms"] >= 0
    assert data["released_rooms"] >= 0
    assert isinstance(data["carve_seq"], int) and data["carve_seq"] >= 1
    # PRD §3.3 — available_rooms is allotted_rooms minus committed_rooms and
    # inventory_status is FULL exactly when available_rooms is zero.
    assert data["available_rooms"] == data["allotted_rooms"] - data["committed_rooms"]
    expected_status = (
        InventoryStatus.FULL.value
        if data["available_rooms"] == 0
        else InventoryStatus.OPEN.value
    )
    assert data["inventory_status"] == expected_status


def assert_attendee(data: dict):
    assert_mutable_record(data)
    assert data["attendee_type"] in _values(AttendeeType)
    assert isinstance(data["eligibility_codes"], list)
    assert isinstance(data["warning_count"], int) and data["warning_count"] >= 0
    assert isinstance(data["housing_risk_flag"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_reservation(data: dict):
    assert_mutable_record(data)
    assert data["reservation_status"] in _values(ReservationStatus)
    assert data["transmission_status"] in _values(TransmissionStatus)
    assert 1 <= data["occupants"] <= 4
    assert isinstance(data["intake_seq"], int) and data["intake_seq"] >= 1
    assert data["room_nights"] >= 1
    assert data["quoted_nightly_rate_cents"] >= 1
    assert data["total_room_charge_cents"] >= 0
    assert isinstance(data["eligibility_review_required"], bool)
    assert data["no_show_billed_cents"] >= 0


def assert_rooming_list_transmission(data: dict):
    assert_append_only_record(data)
    assert data["transmission_type"] in _values(TransmissionType)
    assert isinstance(data["batch_seq"], int) and data["batch_seq"] >= 1
    assert isinstance(data["included_reservation_ids"], list)
    assert data["reservation_count"] == len(data["included_reservation_ids"])
    assert is_iso8601_timestamp(data["transmitted_at"])


def assert_pickup_report(data: dict):
    assert_append_only_record(data)
    assert data["source"] in _values(PickupSource)
    assert data["reported_rooms_picked_up"] >= 0
    assert data["reported_room_nights"] >= 0
    assert data["reported_gross_revenue_cents"] >= 0


def assert_attrition_reduction(data: dict):
    assert_mutable_record(data)
    assert data["status"] in _values(ReductionStatus)
    assert data["requested_reduction_rooms"] >= 1
    assert data["rooms_absorbed_from_unassigned"] >= 0
    assert data["rooms_absorbed_from_sub_blocks"] >= 0


def assert_rogue_vendor(data: dict):
    assert_mutable_record(data)
    assert data["status"] in _values(VendorStatus)
    assert data["detection_source"] in _values(DetectionSource)
    # PRD §3.8 — the score is clamped to the range 0 through 100 inclusive.
    assert 0 <= data["risk_score"] <= 100
    assert data["verified_incident_count"] >= 0
    assert data["warning_issued_count"] >= 0


def assert_poaching_incident(data: dict):
    assert_mutable_record(data)
    assert data["contact_channel"] in _values(ContactChannel)
    assert data["status"] in _values(IncidentStatus)
    assert isinstance(data["verified"], bool)
    if data.get("warning_severity") is not None:
        assert data["warning_severity"] in _values(WarningSeverity)


def assert_commission_invoice(data: dict):
    assert_mutable_record(data)
    assert data["basis"] in _values(CommissionBasis)
    assert data["status"] in _values(InvoiceStatus)
    assert data["paid_cents"] >= 0
    assert data["written_off_cents"] >= 0
    # PRD §3.9 — outstanding_cents is commission_due_cents minus paid_cents
    # minus written_off_cents.
    assert (
        data["outstanding_cents"]
        == data["commission_due_cents"] - data["paid_cents"] - data["written_off_cents"]
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_block_inventory_invariant(block: dict, sub_blocks: list):
    """PRD §2.7 — contracted_rooms_per_night equals unassigned plus released
    plus the allotments of every sub-block that is not REJECTED."""
    counted = sum(
        sub["allotted_rooms"]
        for sub in sub_blocks
        if sub["approval_status"]
        in (
            SubBlockApprovalStatus.PENDING_APPROVAL.value,
            SubBlockApprovalStatus.APPROVED.value,
            SubBlockApprovalStatus.RELEASED.value,
        )
    )
    total = (
        block["unassigned_rooms_per_night"] + block["released_rooms_per_night"] + counted
    )
    assert block["contracted_rooms_per_night"] == total, (
        f"block inventory invariant broken: contracted "
        f"{block['contracted_rooms_per_night']} != unassigned "
        f"{block['unassigned_rooms_per_night']} + released "
        f"{block['released_rooms_per_night']} + allotted {counted}"
    )


def assert_no_version_field(data: dict):
    """PRD §2.4 — neither updated_at nor version exists on append-only records."""
    assert "version" not in data, "record must not carry a version"
    assert "updated_at" not in data, "record must not carry an updated_at"
