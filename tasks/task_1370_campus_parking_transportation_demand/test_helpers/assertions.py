"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus,
    AppealOutcome,
    CampusRole,
    CitationStatus,
    ClosureReason,
    ClosureStatus,
    CommuteMode,
    LotPosture,
    LotZone,
    PatronStanding,
    PermitStatus,
    ProrationPolicy,
    Residency,
    ResidencyRule,
    ShuttleRouteStatus,
    ViolationType,
    WaitlistEntryStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')}"
    )


def assert_patron(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["campus_role"] in [r.value for r in CampusRole]
    assert data["residency"] in [r.value for r in Residency]
    assert data["primary_commute_mode"] in [m.value for m in CommuteMode]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data["standing"] in [s.value for s in PatronStanding]


def assert_parking_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["zone"] in [z.value for z in LotZone]
    assert isinstance(data["capacity_total"], int) and data["capacity_total"] >= 1
    assert data["posture"] in [p.value for p in LotPosture]
    assert isinstance(data["reserved_spaces_total"], int)
    assert isinstance(data["available_capacity"], int)


def assert_lot_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a valid UUID"
    assert isinstance(data["permit_code"], str) and data["permit_code"]
    assert isinstance(data["eligible_roles"], list) and len(data["eligible_roles"]) >= 1
    assert all(r in [c.value for c in CampusRole] for r in data["eligible_roles"])
    assert data["residency_rule"] in [r.value for r in ResidencyRule]
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert data["proration_policy"] in [p.value for p in ProrationPolicy]
    assert isinstance(data["term_start"], str)
    assert isinstance(data["term_end"], str)
    assert isinstance(data["quota"], int) and data["quota"] >= 0
    assert isinstance(data["allocated_count"], int) and data["allocated_count"] >= 0
    assert isinstance(data["offers_outstanding"], int) and data["offers_outstanding"] >= 0
    assert data["status"] in [s.value for s in AllocationStatus]


def assert_waitlist_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("allocation_id", ""))
    assert is_valid_uuid(data.get("patron_id", ""))
    assert data["status"] in [s.value for s in WaitlistEntryStatus]
    assert is_iso8601_timestamp(data.get("waiting_since", ""))
    assert data.get("offered_at") is None or is_iso8601_timestamp(data["offered_at"])
    assert data.get("offer_expires_at") is None or is_iso8601_timestamp(data["offer_expires_at"])
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0
    assert isinstance(data["requeue_count"], int) and data["requeue_count"] >= 0


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patron_id", ""))
    assert is_valid_uuid(data.get("allocation_id", ""))
    assert data.get("displaced_from_allocation_id") is None or is_valid_uuid(
        data["displaced_from_allocation_id"]
    )
    assert isinstance(data["plate_number"], str) and data["plate_number"]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in [s.value for s in PermitStatus]
    assert isinstance(data["fee_base_cents"], int)
    assert isinstance(data["surcharge_cents"], int)
    assert isinstance(data["fee_total_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["fee_paid_cents"], int)
    assert data.get("refund_cents") is None or isinstance(data["refund_cents"], int)


def assert_citation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["plate_number"], str) and data["plate_number"]
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("patron_id", ""))
    assert data["violation_type"] in [v.value for v in ViolationType]
    assert isinstance(data["fine_amount_cents"], int)
    assert data["status"] in [s.value for s in CitationStatus]
    assert isinstance(data["issued_by_officer_id"], str)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert data.get("appeal_reason") is None or isinstance(data["appeal_reason"], str)
    assert data["appeal_outcome"] in [o.value for o in AppealOutcome]
    assert data.get("appeal_decided_by") is None or isinstance(data["appeal_decided_by"], str)


def assert_lot_closure(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["reason"] in [r.value for r in ClosureReason]
    assert isinstance(data["reserved_spaces"], int)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in [s.value for s in ClosureStatus]
    assert isinstance(data["displaced_permit_count"], int)


def assert_shuttle_route(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fund_id", ""))
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["fleet_group"], str) and data["fleet_group"]
    assert isinstance(data["service_window_start_minutes"], int)
    assert isinstance(data["service_window_end_minutes"], int)
    assert isinstance(data["headway_minutes"], int) and data["headway_minutes"] >= 1
    assert isinstance(data["vehicle_capacity"], int) and data["vehicle_capacity"] >= 1
    assert isinstance(data["projected_daily_ridership"], int)
    assert isinstance(data["annual_operating_cost_cents"], int)
    assert data["status"] in [s.value for s in ShuttleRouteStatus]
    assert isinstance(data["planned_daily_runs"], int)
    assert isinstance(data["daily_capacity"], int)
    assert isinstance(data["ridership_total"], int)


def assert_incentive_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patron_id", ""))
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["lifetime_points"], int) and data["lifetime_points"] >= 0
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0


def assert_transportation_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fund_code"], str) and data["fund_code"]
    assert isinstance(data["permit_revenue_cents"], int)
    assert isinstance(data["citation_revenue_cents"], int)
    assert isinstance(data["committed_shuttle_funding_cents"], int)
    assert isinstance(data["available_balance_cents"], int)


def assert_permit_fee_consistency(permit: dict):
    """fee_paid_cents == fee_total_cents - credit_applied_cents (PRD §3.3.3)."""
    assert permit["fee_total_cents"] == permit["fee_base_cents"] + permit["surcharge_cents"]
    assert permit["fee_paid_cents"] == permit["fee_total_cents"] - permit["credit_applied_cents"]


def assert_allocation_counts_within_quota(allocation: dict):
    """allocated_count + offers_outstanding never exceeds quota (PRD §3.2)."""
    assert allocation["allocated_count"] + allocation["offers_outstanding"] <= allocation["quota"]


def assert_fund_balance_consistency(fund: dict):
    """available == permit_revenue + citation_revenue - committed (PRD §3.10)."""
    assert fund["available_balance_cents"] == (
        fund["permit_revenue_cents"]
        + fund["citation_revenue_cents"]
        - fund["committed_shuttle_funding_cents"]
    )
