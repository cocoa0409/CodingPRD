"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ADMIN_SURCHARGE_RATE
from .types import (
    AccessOutcome,
    AppointmentStatus,
    AssociationPosture,
    BillingStatus,
    ChargeStatus,
    ChargeType,
    ContractorStatus,
    CredentialStatus,
    CredentialType,
    GrantStatus,
    GrantType,
    ListingStatus,
    LockboxModel,
    LockboxStatus,
    MembershipStatus,
    PlacementStatus,
    ReviewSeverity,
    ReviewStatus,
    VariantApplied,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Most resources carry id, created_at, updated_at and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer at or above 1, got {data.get('version')}"
    )


def assert_association(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    for field in (
        "temp_code_daily_limit",
        "temp_code_overage_fee_cents",
        "removal_grace_days",
        "late_removal_daily_fee_cents",
        "late_removal_cap_cents",
        "credential_cap_per_member",
        "grant_buffer_minutes",
        "lockbox_total_count",
        "boxes_in_field_count",
        "unplaced_inventory_count",
        "missing_box_count",
        "active_placement_count",
        "delinquent_placement_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["recovery_target_pct"], (int, float))
    assert isinstance(data["recovery_rate_pct"], (int, float))
    assert data["posture"] in _values(AssociationPosture), (
        f"unexpected posture {data['posture']}"
    )


def assert_member(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["association_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["dues_paid_through"], str) and data["dues_paid_through"]
    assert data["membership_status"] in _values(MembershipStatus)
    assert isinstance(data["active_credential_count"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_contractor(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["association_id"])
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["insurance_expires_on"], str)
    assert data["status"] in _values(ContractorStatus)


def assert_lockbox(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["association_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["model"] in _values(LockboxModel)
    assert isinstance(data["replacement_cost_cents"], int)
    assert data["replacement_cost_cents"] > 0
    assert isinstance(data["in_service_since"], str)
    assert data["status"] in _values(LockboxStatus)


def assert_listing(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["association_id"])
    assert is_valid_uuid(data["listing_agent_id"])
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["mls_number"], str) and data["mls_number"]
    assert isinstance(data["concurrent_showing_limit"], int)
    assert data["concurrent_showing_limit"] >= 1
    assert data["status"] in _values(ListingStatus)


def assert_placement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["lockbox_id"])
    assert is_valid_uuid(data["listing_id"])
    assert data["placement_status"] in _values(PlacementStatus)
    assert data["billing_status"] in _values(BillingStatus)
    assert is_iso8601_timestamp(data["placed_at"])


def assert_credential(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["credential_type"] in _values(CredentialType)
    assert isinstance(data["expires_at"], str) and data["expires_at"]
    assert data["status"] in _values(CredentialStatus)
    assert isinstance(data["suspended_by_cascade"], bool)


def assert_grant(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["lockbox_id"])
    assert data["grant_type"] in _values(GrantType)
    assert data["status"] in _values(GrantStatus)
    assert isinstance(data["max_uses"], int) and data["max_uses"] >= 1
    assert isinstance(data["uses_count"], int) and data["uses_count"] >= 0
    assert isinstance(data["window_start"], str) and isinstance(data["window_end"], str)


def assert_showing(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["showing_member_id"])
    assert data["status"] in _values(AppointmentStatus)
    assert isinstance(data["access_event_count"], int)


def assert_access_event(data: dict):
    """An access-log entry is append-only evidence: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "access event id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "access event created_at must be ISO 8601"
    assert "updated_at" not in data, "an access event must not carry updated_at"
    assert "version" not in data, "an access event must not carry version"
    assert data["outcome"] in _values(AccessOutcome)
    assert isinstance(data["after_hours"], bool)
    assert is_valid_uuid(data["lockbox_id"])


def assert_incident_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["association_id"])
    assert data["status"] in _values(ReviewStatus)
    assert data["severity"] in _values(ReviewSeverity)
    assert isinstance(data["event_count"], int)
    assert isinstance(data["risk_score"], (int, float))
    assert 0.00 <= float(data["risk_score"]) <= 100.00, (
        f"risk_score must sit inside 0.00..100.00, got {data['risk_score']}"
    )


def assert_billing_charge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["charge_type"] in _values(ChargeType)
    assert data["status"] in _values(ChargeStatus)
    assert isinstance(data["amount_cents"], int)
    assert data["variant_applied"] in _values(VariantApplied)


# ---- Domain invariant checkers ---------------------------------------------


def expected_line_contribution(amount_cents: int) -> int:
    """One open charge line grossed up by the administration surcharge and rounded
    half up to a whole cent, exactly as the member statement pins it."""
    from decimal import ROUND_HALF_UP, Decimal

    gross = Decimal(str(amount_cents)) * (Decimal("1") + Decimal(str(ADMIN_SURCHARGE_RATE)))
    return int(gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_balance(*amounts_cents: int) -> int:
    """Per-line rounding first, then summation."""
    return sum(expected_line_contribution(amount) for amount in amounts_cents)


def assert_balance_matches_open_charges(member: dict, charges: list):
    """The member's outstanding balance is recomputed from the open charge set."""
    open_amounts = [
        charge["amount_cents"]
        for charge in charges
        if charge["status"] in ("PENDING", "INVOICED")
    ]
    expected = expected_balance(*open_amounts)
    assert member["outstanding_balance_cents"] == expected, (
        f"Expected outstanding_balance_cents {expected} from open lines "
        f"{open_amounts}, got {member['outstanding_balance_cents']}"
    )


def assert_posture_counters(association: dict):
    """Counters an association reports must stay internally consistent."""
    assert association["missing_box_count"] >= 0
    assert association["delinquent_placement_count"] <= association["active_placement_count"]
    assert association["unplaced_inventory_count"] >= 0
    assert association["lockbox_total_count"] >= 0
