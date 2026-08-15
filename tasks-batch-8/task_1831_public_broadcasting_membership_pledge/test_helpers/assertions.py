"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BreakStatus,
    ChallengeStatus,
    DriveStatus,
    FulfillmentStatus,
    MembershipStatus,
    NffsStatus,
    NffsVariant,
    PaymentStatus,
    PledgeChannel,
    PledgeKind,
    ReservationStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.4: id, created_at, updated_at, version on every entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_int_cents(data: dict, field: str, minimum: int = 0):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )
    assert value >= minimum, f"{field} must be >= {minimum}, got {value}"


def assert_membership_level(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    _assert_int_cents(data, "min_annual_cents")
    _assert_int_cents(data, "min_monthly_sustainer_cents")
    assert isinstance(data["premium_eligible"], bool)
    assert isinstance(data["active"], bool)


def assert_premium(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    _assert_int_cents(data, "fair_market_value_cents")
    assert isinstance(data["membership_level_code"], str)
    assert isinstance(data["active"], bool)


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("premium_id", ""))
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["total_qty"], int) and data["total_qty"] >= 1
    for field in ("available_qty", "reserved_qty", "committed_qty", "written_off_qty"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_lot_quantity_conserved(lot: dict):
    """PRD §3.1: available_qty is total minus reserved minus committed minus
    written_off and never goes negative."""
    total = lot["available_qty"] + lot["reserved_qty"] + lot["committed_qty"] + lot["written_off_qty"]
    assert total == lot["total_qty"], (
        f"lot counters do not reconcile: {lot['available_qty']} available + "
        f"{lot['reserved_qty']} reserved + {lot['committed_qty']} committed + "
        f"{lot['written_off_qty']} written off != total {lot['total_qty']}"
    )


def assert_donor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["postal_code"], str)
    _assert_int_cents(data, "lifetime_given_cents")
    assert isinstance(data["lapse_count"], int) and data["lapse_count"] >= 0


def assert_membership(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert isinstance(data["level_code"], str)
    assert data["status"] in [s.value for s in MembershipStatus]
    assert is_iso8601_timestamp(data.get("current_period_start", ""))
    assert is_iso8601_timestamp(data.get("current_period_end", ""))
    assert isinstance(data["sustainer"], bool)


def assert_drive(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in [s.value for s in DriveStatus]
    _assert_int_cents(data, "goal_cents")
    _assert_int_cents(data, "pledged_cents")
    _assert_int_cents(data, "collected_cents")


def assert_break(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drive_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["program_title"], str)
    assert isinstance(data["pitch_level_code"], str)
    assert data["status"] in [s.value for s in BreakStatus]


def assert_pledge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert is_valid_uuid(data.get("membership_id", ""))
    assert is_valid_uuid(data.get("drive_id", ""))
    assert data["channel"] in [c.value for c in PledgeChannel]
    assert data["kind"] in [k.value for k in PledgeKind]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["payment_status"] in [s.value for s in PaymentStatus]
    assert data["fulfillment_status"] in [s.value for s in FulfillmentStatus]
    assert isinstance(data["premium_waived"], bool)
    _assert_int_cents(data, "collected_cents")
    _assert_int_cents(data, "net_collected_cents")


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pledge_id", ""))
    assert is_valid_uuid(data.get("premium_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in [s.value for s in ReservationStatus]


def assert_challenge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drive_id", ""))
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] >= 1
    assert isinstance(data["match_cents"], int) and data["match_cents"] >= 1
    _assert_int_cents(data, "progress_cents")
    assert data["status"] in [s.value for s in ChallengeStatus]


def assert_underwriting_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drive_id", ""))
    assert isinstance(data["underwriter_name"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["aired"], bool)


def assert_nffs_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert data["variant"] in [v.value for v in NffsVariant]
    assert data["status"] in [s.value for s in NffsStatus]
    _assert_int_cents(data, "membership_revenue_cents")
    _assert_int_cents(data, "underwriting_excluded_cents")
    _assert_int_cents(data, "matching_revenue_cents")
    assert isinstance(data["drafted_by_user_id"], str)
