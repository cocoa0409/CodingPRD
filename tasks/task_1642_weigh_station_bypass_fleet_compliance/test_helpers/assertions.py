"""Entity assertions and domain invariant checkers.

Only field presence/types that the PRD itself pins are asserted here.
Append-only records (safety-score snapshots, bypass events, inspection
reports) carry only id and created_at from the identity block — both
updated_at and version are absent on them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CarrierStatus,
    ClosedReason,
    CredentialStatus,
    CredentialStatusReason,
    Decision,
    DeviceType,
    DisputeStatus,
    EligibilityStatus,
    InspectionLevel,
    InvoiceStatus,
    OperationalStatus,
    OverrideStatus,
    ParticipationStatus,
    PaymentStanding,
    SafetyRating,
    ServiceStatus,
    SnapshotSource,
    StationType,
    SubscriptionStatus,
    SupportedChannel,
    TierApplied,
)


def _assert_identity_block(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_identity(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_carrier(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["dot_number"], str) and data["dot_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in {s.value for s in CarrierStatus}
    assert data["eligibility_status"] in {s.value for s in EligibilityStatus}
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["credit_ledger"], list)
    assert isinstance(data["closed_billing_periods"], list)
    for entry in data["credit_ledger"]:
        assert isinstance(entry["amount_cents"], int)
        assert entry["reason"] in (
            "DISPUTE_OVERTURN_CREDIT", "INVOICE_CREDIT_APPLICATION")
        assert "reference_id" in entry
        assert is_iso8601_timestamp(entry["recorded_at"])


def assert_credit_ledger_invariant(carrier: dict):
    """credit_balance_cents is, by invariant, exactly the sum of amount_cents
    over all credit_ledger entries (PRD §2.8)."""
    total = sum(e["amount_cents"] for e in carrier["credit_ledger"])
    assert carrier["credit_balance_cents"] == total, (
        f"credit_balance_cents {carrier['credit_balance_cents']} != "
        f"ledger sum {total}")


def assert_config(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["participation_status"] in {s.value for s in ParticipationStatus}
    assert 50 <= data["iss_refusal_threshold"] <= 100
    assert 0 <= data["random_pull_in_rate_bps"] <= 10000
    assert 1 <= data["bypass_rate_cap_bps"] <= 10000
    assert isinstance(data["hazmat_bypass_allowed"], bool)
    assert isinstance(data["requires_weight_clearance"], bool)
    assert isinstance(data["credential_sets_required"], list)
    assert set(data["credential_sets_required"]) <= {"IFTA", "IRP", "UCR", "HOS_LOG"}


def assert_station(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["state_program_config_id"], str)
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert data["station_type"] in {s.value for s in StationType}
    assert data["supported_channel"] in {s.value for s in SupportedChannel}
    assert data["operational_status"] in {s.value for s in OperationalStatus}


def assert_vehicle(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["plate_number"], str)
    assert isinstance(data["plate_state"], str)
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["gvwr_lbs"], int) and data["gvwr_lbs"] > 0
    assert isinstance(data["hazmat_endorsed"], bool)
    assert data["service_status"] in {s.value for s in ServiceStatus}


def assert_credential(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert data["device_type"] in {s.value for s in DeviceType}
    assert isinstance(data["device_serial"], str) and data["device_serial"]
    assert data["status"] in {s.value for s in CredentialStatus}
    assert data["status_reason"] in {s.value for s in CredentialStatusReason}


def assert_subscription(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["service_start_date"], str)
    assert isinstance(data["service_end_date"], str)
    assert data["status"] in {s.value for s in SubscriptionStatus}
    assert data["payment_standing"] in {s.value for s in PaymentStanding}
    assert isinstance(data["paused_days_current_period"], int)
    if data["status"] == "PAUSED":
        assert isinstance(data.get("paused_at"), str) and data["paused_at"]
    if data["status"] == "CLOSED":
        assert data["closed_reason"] in {s.value for s in ClosedReason}


def assert_snapshot(data: dict):
    _assert_append_only_identity(data, "SafetyScoreSnapshot")
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["iss_score"], int) and 0 <= data["iss_score"] <= 100
    assert data["safety_rating"] in {s.value for s in SafetyRating}
    assert data["source"] in {s.value for s in SnapshotSource}
    assert isinstance(data["effective_date"], str)


def assert_event(data: dict):
    _assert_append_only_identity(data, "BypassEvent")
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert is_iso8601_timestamp(data["approach_at"])
    assert data["decision"] in {s.value for s in Decision}
    assert isinstance(data["decision_reasons"], list)
    if data["decision"] == Decision.BYPASS_GRANTED.value:
        assert data["decision_reasons"] == [], \
            "a granted bypass stores an empty decision_reasons"
    assert isinstance(data["weight_verified"], bool)
    assert isinstance(data["credentials_complete"], bool)
    assert isinstance(data["ruleset_version"], int)
    assert isinstance(data["cap_granted_before"], int)
    assert isinstance(data["cap_total_before"], int)


def assert_dispute(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["bypass_event_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["reason"], str)
    assert isinstance(data["claimed_credit_cents"], int)
    assert 1 <= data["claimed_credit_cents"] <= 100000
    assert data["status"] in {s.value for s in DisputeStatus}


def assert_override(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["reason"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in {s.value for s in OverrideStatus}


def assert_invoice(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["vehicle_id"], str)
        assert isinstance(line["subscription_id"], str)
        assert isinstance(line["tier_rate_cents"], int)
        assert isinstance(line["surcharge_cents"], int)
        assert isinstance(line["billable_days"], int)
        assert isinstance(line["line_net_cents"], int)
    assert isinstance(data["billed_line_count"], int)
    assert data["tier_applied"] in {s.value for s in TierApplied}
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] == data["gross_cents"] - data["credit_applied_cents"], \
        "amount_due_cents is gross_cents minus credit_applied_cents"
    assert isinstance(data["due_date"], str)
    assert data["status"] in {s.value for s in InvoiceStatus}
    assert is_iso8601_timestamp(data["issued_at"])


def assert_inspection(data: dict):
    _assert_append_only_identity(data, "InspectionReport")
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["inspection_level"] in {s.value for s in InspectionLevel}
    assert is_iso8601_timestamp(data["inspected_at"])
    assert isinstance(data["violations_found"], int) and data["violations_found"] >= 0
    assert isinstance(data["out_of_service_order"], bool)
