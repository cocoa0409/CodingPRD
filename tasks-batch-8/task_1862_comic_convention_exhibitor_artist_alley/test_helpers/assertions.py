"""Entity assertions and domain invariant checkers (PRD Sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    BadgeStatus,
    CancellationReason,
    ConventionPhase,
    ExhibitorCategory,
    ExhibitorStanding,
    FreightBookingStatus,
    Hall,
    IssueCategory,
    IssueOutcome,
    IssueSeverity,
    IssueStatus,
    LoadDirection,
    LoadSlotStatus,
    NeighborRequestKind,
    NeighborRequestStatus,
    PermitStatus,
    PlacementStatus,
    SalesReportStatus,
    SpaceKind,
    SpaceUnitStatus,
)


def _assert_common_fields(data: dict):
    """PRD Section 2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_immutable_fields(data: dict):
    """JuryScore and DockDoor carry only id + created_at (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "immutable resource must not expose updated_at"
    assert "version" not in data, "immutable resource must not expose version"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_convention(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["phase"] in _enum_values(ConventionPhase)
    assert isinstance(data["ops_run_count"], int) and data["ops_run_count"] >= 0
    assert isinstance(data["deposit_window_days"], int)
    assert isinstance(data["tax_permit_required"], bool)
    assert isinstance(data["sales_tax_rate_bp"], int)


def assert_category_quota(data: dict):
    _assert_common_fields(data)
    assert data["category"] in _enum_values(ExhibitorCategory)
    assert isinstance(data["max_accepted"], int) and data["max_accepted"] >= 0
    assert isinstance(data["max_waitlisted"], int) and data["max_waitlisted"] >= 0
    assert isinstance(data["accepted_count"], int) and data["accepted_count"] >= 0
    assert isinstance(data["waitlisted_count"], int) and data["waitlisted_count"] >= 0


def assert_space_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["space_code"], str) and data["space_code"]
    assert isinstance(data["block"], str) and data["block"]
    assert isinstance(data["unit_number"], int)
    assert data["hall"] in _enum_values(Hall)
    assert data["kind"] in _enum_values(SpaceKind)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["status"] in _enum_values(SpaceUnitStatus)
    assert "current_application_id" in data, "current_application_id must be present"


def assert_exhibitor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["category"] in _enum_values(ExhibitorCategory)
    assert isinstance(data["prior_years_completed"], int)
    assert isinstance(data["prior_on_time_payments"], int)
    assert isinstance(data["strike_points"], int) and data["strike_points"] >= 0
    assert data["standing"] in _enum_values(ExhibitorStanding)
    assert isinstance(data["renewal_priority_score"], int)
    assert data["renewal_priority_score"] >= 0, "renewal_priority_score is floored at zero"


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("exhibitor_id", ""))
    assert is_valid_uuid(data.get("convention_id", ""))
    assert data["category"] in _enum_values(ExhibitorCategory)
    assert data["channel"] in ("RENEWAL", "OPEN")
    assert isinstance(data["requested_space_kinds"], list)
    assert all(k in _enum_values(SpaceKind) for k in data["requested_space_kinds"])
    assert isinstance(data["requested_space_count"], int)
    assert data["requested_space_count"] >= 1
    assert isinstance(data["estimated_daily_sales_cents"], int)
    assert isinstance(data["conflicted_juror_user_ids"], list)
    assert data["status"] in _enum_values(ApplicationStatus)
    assert data["permit_status"] in _enum_values(PermitStatus)
    # Nullable computed/stamped fields: type-checked only once populated.
    if data.get("jury_composite_score") is not None:
        assert isinstance(data["jury_composite_score"], (int, float))
    for money_field in (
        "provisional_quote_cents",
        "final_invoice_cents",
        "deposit_cents",
        "refund_cents",
        "tax_estimate_cents",
    ):
        if data.get(money_field) is not None:
            assert isinstance(data[money_field], int), (
                f"{money_field} must be integer cents, got {data[money_field]!r}"
            )
    for ts_field in ("submitted_at", "decided_at", "permit_expires_at"):
        if data.get(ts_field) is not None:
            assert is_iso8601_timestamp(data[ts_field])
    if data.get("cancellation_reason") is not None:
        assert data["cancellation_reason"] in _enum_values(CancellationReason)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["badge_fees_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["included_badges"], int)
    assert isinstance(data["purchased_extra_badges"], int)


def assert_jury_score(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["juror_user_id"], str) and data["juror_user_id"]
    for criterion in ("originality", "craft", "category_fit", "professionalism"):
        assert isinstance(data[criterion], int), f"{criterion} must be an integer"
        assert 0 <= data[criterion] <= 100, f"{criterion} must be within 0..100"
    assert isinstance(data["weighted_total"], (int, float))


def assert_placement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("space_unit_id", ""))
    assert data["status"] in _enum_values(PlacementStatus)


def assert_neighbor_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("convention_id", ""))
    assert is_valid_uuid(data.get("requester_exhibitor_id", ""))
    assert is_valid_uuid(data.get("target_exhibitor_id", ""))
    assert data["kind"] in _enum_values(NeighborRequestKind)
    assert data["status"] in _enum_values(NeighborRequestStatus)


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("exhibitor_id", ""))
    assert is_valid_uuid(data.get("convention_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["badge_status"] in _enum_values(BadgeStatus)


def assert_load_slot(data: dict):
    _assert_common_fields(data)
    assert data["direction"] in _enum_values(LoadDirection)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["pallet_capacity"], int) and data["pallet_capacity"] >= 0
    assert isinstance(data["reserved_pallets"], int) and data["reserved_pallets"] >= 0
    assert data["reserved_pallets"] <= data["pallet_capacity"], (
        "reserved_pallets must never exceed pallet_capacity"
    )
    assert data["status"] in _enum_values(LoadSlotStatus)


def assert_dock_door(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data.get("convention_id", ""))
    assert isinstance(data["door_code"], str) and data["door_code"]


def assert_freight_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("exhibitor_id", ""))
    assert is_valid_uuid(data.get("load_slot_id", ""))
    assert is_valid_uuid(data.get("dock_door_id", ""))
    assert is_iso8601_timestamp(data["door_starts_at"])
    assert is_iso8601_timestamp(data["door_ends_at"])
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] >= 1
    assert data["status"] in _enum_values(FreightBookingStatus)


def assert_issue_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("convention_id", ""))
    assert is_valid_uuid(data.get("exhibitor_id", ""))
    assert isinstance(data["reporter_user_id"], str) and data["reporter_user_id"]
    assert data["category"] in _enum_values(IssueCategory)
    assert data["severity"] in _enum_values(IssueSeverity)
    assert isinstance(data["description"], str)
    assert data["status"] in _enum_values(IssueStatus)
    if data.get("outcome") is not None:
        assert data["outcome"] in _enum_values(IssueOutcome)
    assert isinstance(data["strike_points_applied"], int)
    assert data["strike_points_applied"] >= 0


def assert_sales_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("exhibitor_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["gross_cents"], int)
        assert isinstance(line["sale_date"], str) and line["sale_date"]
    assert data["status"] in _enum_values(SalesReportStatus)
    if data.get("tax_settlement_cents") is not None:
        assert isinstance(data["tax_settlement_cents"], int)


def assert_exhibitor_standing_consistent(exhibitor: dict):
    """PRD Section 3.2: standing derives from strike_points, bands inclusive at
    their lower edge (<3 GOOD; >=3 PROBATION; >=5 SUSPENDED; >=7 EVICTED)."""
    points = exhibitor["strike_points"]
    expected = (
        "EVICTED" if points >= 7
        else "SUSPENDED" if points >= 5
        else "PROBATION" if points >= 3
        else "GOOD"
    )
    assert exhibitor["standing"] == expected, (
        f"standing {exhibitor['standing']} inconsistent with {points} strike points "
        f"(expected {expected})"
    )


def assert_renewal_priority_score(exhibitor: dict):
    """PRD Section 3.2: max(0, 10*years + 3*on_time_payments - 8*strike_points)."""
    expected = max(
        0,
        10 * exhibitor["prior_years_completed"]
        + 3 * exhibitor["prior_on_time_payments"]
        - 8 * exhibitor["strike_points"],
    )
    assert exhibitor["renewal_priority_score"] == expected, (
        f"renewal_priority_score {exhibitor['renewal_priority_score']} != {expected}"
    )
