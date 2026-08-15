"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccrualEntryStatus, BudgetStatus, ClearanceLevel, ConflictCheckStatus,
    CustodianStatus, DeadlineStatus, DeadlineType, EngagementStatus,
    EntryKind, FeeArrangement, HoldStatus, JobFamily, MatterStatus, MatterType,
    PanelStatus, PaymentKind, PaymentRail, PaymentStatus, Posture,
    ReleaseReason, ResolutionType, ServiceType, SettlementKind,
    SettlementStatus, WorkOrderStatus,
)

_ALL_STATUSES = {
    "matter": [s.value for s in MatterStatus],
    "engagement": [s.value for s in EngagementStatus],
    "budget": [s.value for s in BudgetStatus],
    "accrual": [s.value for s in AccrualEntryStatus],
    "hold": [s.value for s in HoldStatus],
    "custodian": [s.value for s in CustodianStatus],
    "work_order": [s.value for s in WorkOrderStatus],
    "deadline": [s.value for s in DeadlineStatus],
    "settlement": [s.value for s in SettlementStatus],
    "payment": [s.value for s in PaymentStatus],
    "rail": [s.value for s in PaymentRail],
    "panel": [s.value for s in PanelStatus],
    "conflict": [s.value for s in ConflictCheckStatus],
}


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), \
        f"{label}.version must be an integer"


def assert_matter(data: dict):
    _assert_common_fields(data, "matter")
    assert isinstance(data["matter_number"], str) and data["matter_number"]
    assert data["status"] in _ALL_STATUSES["matter"]
    assert data["matter_type"] in [t.value for t in MatterType]
    assert isinstance(data["accrued_to_date_cents"], int)
    assert data["posture"] in [p.value for p in Posture]
    assert data["close_checklist_ack"] in (True, False)
    assert isinstance(data["owning_counsel_id"], str) and data["owning_counsel_id"]


def assert_staff_user(data: dict):
    _assert_common_fields(data, "staff_user")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["job_family"] in [j.value for j in JobFamily]
    assert data["is_active"] in (True, False)


def assert_counsel_firm(data: dict):
    _assert_common_fields(data, "firm")
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert data["panel_status"] in _ALL_STATUSES["panel"]
    assert data["conflict_check_status"] in _ALL_STATUSES["conflict"]
    assert isinstance(data["blended_rate_cap_cents"], int)


def assert_engagement(data: dict):
    _assert_common_fields(data, "engagement")
    assert data["status"] in _ALL_STATUSES["engagement"]
    assert data["fee_arrangement"] in [f.value for f in FeeArrangement]
    assert isinstance(data["matter_id"], str) and data["matter_id"]
    assert isinstance(data["firm_id"], str) and data["firm_id"]
    assert data["engagement_letter_executed"] in (True, False)


def assert_budget(data: dict):
    _assert_common_fields(data, "budget")
    assert data["status"] in _ALL_STATUSES["budget"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["lifecycle_budget_cents"], int)
    assert isinstance(data["fy_budget_cents"], int)
    assert data["fy_budget_cents"] <= data["lifecycle_budget_cents"]


def assert_accrual_entry(data: dict):
    """Append-only ledger row: id + created_at only, never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "accrual.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "accrual.created_at must be ISO 8601"
    assert "version" not in data, "ledger rows must not carry version"
    assert "updated_at" not in data, "ledger rows must not carry updated_at"
    assert data["status"] in _ALL_STATUSES["accrual"]
    assert data["entry_kind"] in [k.value for k in EntryKind]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["period"], str) and len(data["period"]) == 7


def assert_hold(data: dict):
    _assert_common_fields(data, "hold")
    assert data["status"] in _ALL_STATUSES["hold"]
    assert isinstance(data["matter_id"], str) and data["matter_id"]
    assert isinstance(data["scope_description"], str)


def assert_custodian(data: dict):
    _assert_common_fields(data, "custodian")
    assert data["status"] in _ALL_STATUSES["custodian"]
    assert isinstance(data["hold_id"], str) and data["hold_id"]
    assert isinstance(data["staff_user_id"], str) and data["staff_user_id"]
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_vendor(data: dict):
    _assert_common_fields(data, "vendor")
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert data["security_clearance_level"] in [c.value for c in ClearanceLevel]
    assert isinstance(data["capacity_gb"], int) and data["capacity_gb"] > 0
    assert isinstance(data["committed_gb"], int) and data["committed_gb"] >= 0


def assert_work_order(data: dict):
    _assert_common_fields(data, "work_order")
    assert data["status"] in _ALL_STATUSES["work_order"]
    assert data["service_type"] in [s.value for s in ServiceType]
    assert isinstance(data["estimated_gb"], int) and data["estimated_gb"] > 0
    assert isinstance(data["rate_per_gb_cents"], int) and data["rate_per_gb_cents"] > 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0


def assert_deadline(data: dict):
    _assert_common_fields(data, "deadline")
    assert data["status"] in _ALL_STATUSES["deadline"]
    assert data["deadline_type"] in [d.value for d in DeadlineType]
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data.get("due_at", "")), "deadline.due_at must be ISO 8601"
    assert data["is_jurisdictional"] in (True, False)
    assert isinstance(data["reminder_days"], int) and data["reminder_days"] >= 0


def assert_policy(data: dict):
    _assert_common_fields(data, "policy")
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
    assert data["is_active"] in (True, False)
    assert isinstance(data["max_single_amount_cents"], int)
    assert isinstance(data["dual_approval_required_over_cents"], int)
    assert data["dual_approval_required_over_cents"] >= data["max_single_amount_cents"]


def assert_settlement_request(data: dict):
    _assert_common_fields(data, "settlement")
    assert data["status"] in _ALL_STATUSES["settlement"]
    assert data["settlement_kind"] in [k.value for k in SettlementKind]
    assert isinstance(data["proposed_amount_cents"], int) and \
        data["proposed_amount_cents"] > 0
    assert isinstance(data["approved_by_user_ids"], list)
    assert is_iso8601_timestamp(data.get("expires_at", "")), \
        "settlement.expires_at must be ISO 8601"


def assert_payment_request(data: dict):
    _assert_common_fields(data, "payment")
    assert data["status"] in _ALL_STATUSES["payment"]
    assert data["payment_status"] in _ALL_STATUSES["rail"]
    assert data["payment_kind"] in [k.value for k in PaymentKind]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["payee_name"], str) and data["payee_name"]


def assert_matter_invariants(data: dict):
    """Cross-field invariants that must hold on any matter read."""
    assert_matter(data)
    assert data["accrued_to_date_cents"] >= 0, "accrued spend must be non-negative"
    assert data["reserve_amount_cents"] is None or data["reserve_amount_cents"] >= 0, \
        "reserve floors at zero"
    if data["status"] == MatterStatus.RESOLVED.value:
        assert data["resolution_type"] in [r.value for r in ResolutionType]
        assert data["resolved_at"] is not None
    if data["status"] in (MatterStatus.INTAKE.value, MatterStatus.ASSESSMENT.value,
                          MatterStatus.SETTLEMENT_PENDING.value,
                          MatterStatus.RESOLVED.value, MatterStatus.CLOSED.value):
        assert data["posture"] in (Posture.RESTRICTED.value, Posture.FROZEN.value), \
            f"matter in {data['status']} must be RESTRICTED or FROZEN"
