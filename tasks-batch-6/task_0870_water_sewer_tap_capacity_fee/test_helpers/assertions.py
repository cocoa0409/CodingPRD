"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
        "DENIED", "READY_FOR_ACTIVATION", "ACTIVATED", "WITHDRAWN",
    ], f"unexpected application status {data.get('status')!r}"
    assert isinstance(data["parcel_id"], str)
    assert data["service_type"] in ["WATER", "SEWER", "BOTH"]
    assert data["use_type"] in ["RESIDENTIAL", "COMMERCIAL", "IRRIGATION"]
    assert isinstance(data["fees_paid_cents"], int)


def assert_availability_determination(data: dict):
    _assert_common(data)
    assert isinstance(data["water_main_available"], bool)
    assert isinstance(data["sewer_main_available"], bool)
    assert isinstance(data["extension_required"], bool)


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PROPOSED", "APPROVED_TO_CONSTRUCT", "UNDER_CONSTRUCTION", "INSPECTED",
        "ACCEPTED", "CANCELLED",
    ]


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "PENDING_ESCROW", "EXECUTED", "COMPLETION_PENDING", "CLOSED", "TERMINATED",
    ]


def assert_escrow_transaction(data: dict):
    """Append-only ledger entry: id + created_at only, no updated_at/version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["txn_type"] in ["DEPOSIT", "DRAWDOWN", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_latecomer(data: dict):
    _assert_common(data)
    assert data["status"] in ["ASSESSED", "COLLECTED", "WAIVED"]
    assert data["method"] in ["FRONT_FOOTAGE", "AREA"]


def assert_escrow_conservation(agreement: dict):
    """Conservation invariant (§3.3): deposited == held + drawn + refunded."""
    assert agreement["escrow_deposited_cents"] == (
        agreement["escrow_held_cents"]
        + agreement["escrow_drawn_cents"]
        + agreement["escrow_refunded_cents"]
    ), f"escrow conservation violated: {agreement}"


def assert_pool_conservation(project: dict):
    """Conservation invariant (§3.8): principal == collected + outstanding."""
    assert project["reimbursable_principal_cents"] == (
        project["reimbursed_collected_cents"] + project["outstanding_recoverable_cents"]
    ), f"reimbursement-pool conservation violated: {project}"
