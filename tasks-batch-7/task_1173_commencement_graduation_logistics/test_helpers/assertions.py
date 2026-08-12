"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ReadinessPosture, WeatherMode, GraduateStatus, HonorTier, HonorBasis,
    AuditResult, AppealStatus, TicketAllocationStatus, RegaliaOrderStatus,
    SeatAssignmentStatus, ReaderCardStatus, PrintBatchStatus, DiplomaStatus,
    RehearsalSessionStatus, RehearsalAttendanceStatus,
    AccommodationRequestStatus, VendorContractStatus,
)


def _assert_common(data: dict):
    """System-managed properties shared by all resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_ceremony(data: dict):
    _assert_common(data)
    assert data["readiness_posture"] in [p.value for p in ReadinessPosture]
    assert data["weather_mode"] in [w.value for w in WeatherMode]
    assert isinstance(data["effective_capacity"], int)
    assert isinstance(data["ticket_pool_total"], int)
    assert isinstance(data["ticket_pool_remaining"], int)
    assert isinstance(data["open_seat_count"], int)
    assert data["ticket_pool_remaining"] <= data["ticket_pool_total"]
    assert 0 <= data["open_seat_count"] <= data["effective_capacity"]


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["total_capacity"], int) and data["total_capacity"] >= 1
    assert isinstance(data["accessible_capacity"], int)
    assert 0 <= data["accessible_capacity"] <= data["total_capacity"]
    assert isinstance(data["indoor"], bool)


def assert_graduate(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in GraduateStatus]
    assert data["honor_tier"] in [t.value for t in HonorTier]
    assert data["honor_basis"] in [b.value for b in HonorBasis]
    assert isinstance(data["conduct_strike_count"], int) and data["conduct_strike_count"] >= 0
    assert isinstance(data["walk_privilege_revoked"], bool)


def assert_eligibility_audit(data: dict):
    _assert_common(data)
    assert data["result"] in [r.value for r in AuditResult]
    assert isinstance(data["fail_reasons"], list)
    assert data["appeal_status"] in [s.value for s in AppealStatus]
    assert data["provisional_honor_tier"] in [t.value for t in HonorTier]


def assert_ticket_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in TicketAllocationStatus]
    assert isinstance(data["requested_count"], int) and data["requested_count"] >= 0
    assert isinstance(data["granted_count"], int) and data["granted_count"] >= 0
    assert isinstance(data["provisional_granted_count"], int)
    assert data.get("waitlist_position") is None or isinstance(data["waitlist_position"], int)


def assert_regalia_order(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in RegaliaOrderStatus]
    for field in ("subtotal_cents", "discount_cents", "late_fee_cents", "total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be non-negative cents"
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"] + data["late_fee_cents"], \
        "total_cents must equal subtotal - discount + late fee"


def assert_seat_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in SeatAssignmentStatus]
    assert isinstance(data["seat_number"], int) and data["seat_number"] >= 1
    assert isinstance(data["accessible"], bool)


def assert_reader_card(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in ReaderCardStatus]


def assert_print_batch(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in PrintBatchStatus]
    assert isinstance(data["diploma_count"], int) and data["diploma_count"] >= 0


def assert_diploma(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in DiplomaStatus]
    assert data["pinned_honor_tier"] in [t.value for t in HonorTier]
    assert isinstance(data["correction_count"], int) and data["correction_count"] >= 0


def assert_rehearsal_session(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in RehearsalSessionStatus]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0


def assert_rehearsal_attendance(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in RehearsalAttendanceStatus]


def assert_accommodation_request(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in AccommodationRequestStatus]


def assert_vendor_contract(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in VendorContractStatus]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_ceremony_pool_invariants(ceremony: dict, assigned_seat_count: int, non_terminal_granted_sum: int):
    """PRD §2.9 pool accounting invariants that must hold after any operation."""
    assert ceremony["open_seat_count"] == ceremony["effective_capacity"] - assigned_seat_count, (
        f"open_seat_count {ceremony['open_seat_count']} != effective_capacity "
        f"{ceremony['effective_capacity']} - assigned {assigned_seat_count}"
    )
    assert ceremony["ticket_pool_remaining"] == ceremony["ticket_pool_total"] - non_terminal_granted_sum, (
        f"ticket_pool_remaining {ceremony['ticket_pool_remaining']} != ticket_pool_total "
        f"{ceremony['ticket_pool_total']} - granted {non_terminal_granted_sum}"
    )
