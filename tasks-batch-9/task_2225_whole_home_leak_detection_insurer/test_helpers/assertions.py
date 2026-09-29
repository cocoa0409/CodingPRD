"""Entity assertions and domain invariant checkers for the leak-detection API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountState,
    AttestationDenialReason,
    AttestationStatus,
    Classification,
    ClaimDenialReason,
    ClaimStatus,
    ContactStatus,
    CreditState,
    EventState,
    FeedbackLabel,
    InvalidatedReason,
    IrrigationWindowStatus,
    LearningState,
    LifecycleState,
    ModelCode,
    MonitorMode,
    NotificationChannel,
    PayoutVariant,
    PropertyState,
    ReadingSource,
    SuppressionReason,
    SuspendedReason,
    TicketExpiryReason,
    TicketStage,
    TransferCancelReason,
    TransferStatus,
    ValveState,
    VerificationState,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Common record shape (PRD §2.4)
# --------------------------------------------------------------------------
def assert_common_record_properties(data: dict) -> None:
    """Every entity but a telemetry reading carries all four common fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_no_version_change(before: dict, after: dict) -> None:
    """A refused write must not advance the row's version."""
    assert after["version"] == before["version"], (
        "a refused write must leave version untouched, "
        f"but it moved from {before['version']} to {after['version']}"
    )


# --------------------------------------------------------------------------
# Accounts and property
# --------------------------------------------------------------------------
def assert_homeowner(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone_e164"], str) and data["phone_e164"]
    assert data["notification_channel"] in _members(NotificationChannel)
    assert data["account_state"] in _members(AccountState)
    assert isinstance(data["owned_property_count"], int)
    assert data["owned_property_count"] >= 0
    if data["account_state"] == AccountState.ACTIVE.value:
        assert data.get("deactivated_at") is None, "an ACTIVE account has no deactivated_at"


def assert_emergency_contact(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["homeowner_id"])
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert data["verification_state"] in _members(VerificationState)
    assert data["status"] in _members(ContactStatus)


def assert_property(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["homeowner_id"])
    assert isinstance(data["irrigation_present"], bool)
    assert data["property_state"] in _members(PropertyState)
    assert isinstance(data["year_built"], int)
    if data["property_state"] != PropertyState.ARCHIVED.value:
        assert data.get("archived_at") is None, "only an ARCHIVED property has archived_at"


def assert_irrigation_window(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["property_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["start_at"] < data["end_at"], "a window's start must precede its end"
    assert data["status"] in _members(IrrigationWindowStatus)
    assert isinstance(data["expected_max_flow_gpm"], (int, float))
    if data["status"] != IrrigationWindowStatus.SUSPENDED_BY_SHUTOFF.value:
        assert data.get("suspended_at") is None, (
            "suspended_at belongs to a SUSPENDED_BY_SHUTOFF window only, "
            f"but status is {data['status']} with suspended_at {data.get('suspended_at')}"
        )


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
def assert_device(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["model_code"] in _members(ModelCode)
    assert isinstance(data["firmware_version"], str) and data["firmware_version"]
    assert data["lifecycle_state"] in _members(LifecycleState)
    assert data["valve_state"] in _members(ValveState)
    assert data["monitor_mode"] in _members(MonitorMode)
    assert isinstance(data["close_count"], int) and data["close_count"] >= 0
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["baseline_ready"], bool)
    assert is_iso8601_timestamp(data["monitor_mode_updated_at"])
    if data["lifecycle_state"] == LifecycleState.REGISTERED.value:
        assert data.get("install_verified_by_user_id") is None
        assert data.get("install_verified_at") is None
        assert data.get("installed_static_pressure_psi") is None


def assert_baseline_profile(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["device_id"])
    assert data["learning_state"] in _members(LearningState)
    assert isinstance(data["learning_cycle_no"], int) and data["learning_cycle_no"] >= 1
    assert isinstance(data["sample_count"], int) and data["sample_count"] >= 0
    assert isinstance(data["baseline_version"], int) and data["baseline_version"] >= 0
    assert isinstance(data["false_positive_count"], int)
    assert is_iso8601_timestamp(data["learning_started_at"])
    if data["learning_state"] != LearningState.COMPLETE.value:
        assert data.get("completed_at") is None, (
            "completed_at is set only while the profile is COMPLETE, but "
            f"learning_state is {data['learning_state']}"
        )
    if data["invalidated_reason"] is not None:
        assert data["invalidated_reason"] in _members(InvalidatedReason)


def assert_telemetry_reading(data: dict) -> None:
    """A telemetry reading is immutable: `id` and `created_at`, nothing more."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "an immutable reading carries no version field"
    assert "updated_at" not in data, "an immutable reading carries no updated_at field"
    assert is_valid_uuid(data["device_id"])
    assert is_iso8601_timestamp(data["reading_at"])
    assert data["reading_source"] in _members(ReadingSource)
    assert data["classification_at_ingest"] in _members(Classification)
    assert isinstance(data["suppressed_by_irrigation"], bool)
    assert isinstance(data["baseline_eligible"], bool)
    assert isinstance(data["anomaly_event_created"], bool)
    assert isinstance(data["coverage_minutes"], (int, float))


# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------
def assert_anomaly_event(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["device_id"])
    assert is_valid_uuid(data["telemetry_reading_id"])
    assert data["classification"] in ["DRIP", "RUNNING_FIXTURE", "CATASTROPHIC_BURST"]
    assert data["event_state"] in _members(EventState)
    assert is_iso8601_timestamp(data["detected_at"])
    assert isinstance(data["severity_score"], (int, float))
    assert 0.0 <= data["severity_score"] <= 1.0, (
        "every severity component is clamped at 1.0 before weighting and the "
        f"weights sum to 1.0, so the score cannot leave [0, 1]: {data['severity_score']}"
    )
    assert isinstance(data["auto_shutoff_executed"], bool)
    assert isinstance(data["mitigation_credited"], bool)
    assert isinstance(data["baseline_version_used"], int)
    if data["event_state"] == EventState.SUPPRESSED.value:
        assert data["suppression_reason"] in _members(SuppressionReason)
    else:
        assert data.get("suppression_reason") is None, (
            "suppression_reason belongs to a SUPPRESSED event only, but "
            f"event_state is {data['event_state']}"
        )
    if data["feedback_label"] is not None:
        assert data["feedback_label"] in _members(FeedbackLabel)


def assert_escalation_ticket(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["anomaly_event_id"])
    assert data["stage"] in _members(TicketStage)
    assert is_iso8601_timestamp(data["homeowner_deadline_at"])
    assert isinstance(data["notification_attempt_count"], int)
    assert data["notification_attempt_count"] >= 1
    if data["stage"] == TicketStage.EXPIRED.value:
        assert data["expiry_reason"] in _members(TicketExpiryReason)
    else:
        assert data.get("expiry_reason") is None, (
            "expiry_reason belongs to an EXPIRED ticket only, but stage is "
            f"{data['stage']}"
        )
    if data["stage"] == TicketStage.PENDING_HOMEOWNER.value:
        assert data.get("notified_contact_id") is None, (
            "no emergency contact has been notified while the ticket is still "
            "PENDING_HOMEOWNER"
        )
        assert data.get("contact_deadline_at") is None


# --------------------------------------------------------------------------
# Insurer credit program
# --------------------------------------------------------------------------
def assert_insurance_policy(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["credit_state"] in _members(CreditState)
    assert_integer_cents(data["annual_premium_cents"], "annual_premium_cents")
    assert_integer_cents(data["deductible_cents"], "deductible_cents")
    assert_integer_cents(data["credited_cents_total"], "credited_cents_total")
    assert_integer_cents(data["clawback_cents_total"], "clawback_cents_total")
    assert_integer_cents(data["paid_payout_cents_total"], "paid_payout_cents_total")
    assert isinstance(data["true_up_cents"], int), "true_up_cents is a signed integer"
    assert isinstance(data["finalized_period_count"], int)
    assert data["finalized_period_count"] >= 0
    if data["credit_state"] == CreditState.CREDIT_SUSPENDED.value:
        assert data["suspended_reason"] in _members(SuspendedReason)
    else:
        assert data.get("suspended_reason") is None, (
            "suspended_reason belongs to a CREDIT_SUSPENDED policy only, but "
            f"credit_state is {data['credit_state']}"
        )


def assert_credit_attestation(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["status"] in _members(AttestationStatus)
    assert is_iso8601_timestamp(data["period_start_at"])
    assert is_iso8601_timestamp(data["period_end_at"])
    assert data["period_start_at"] < data["period_end_at"]
    assert isinstance(data["period_minutes"], (int, float))
    assert isinstance(data["is_policy_year_close"], bool)
    assert_integer_cents(data["credit_cents_awarded"], "credit_cents_awarded")
    assert isinstance(data["true_up_cents"], int)
    if data["status"] == AttestationStatus.OPEN.value:
        assert data.get("uptime_pct") is None, "an OPEN period has not been scored yet"
        assert data.get("tier_pct") is None
        assert data.get("finalized_at") is None
        assert data.get("device_snapshot_lifecycle_state") is None
    else:
        assert is_iso8601_timestamp(data["finalized_at"])
        assert isinstance(data["uptime_pct"], (int, float))
        assert isinstance(data["covered_minutes"], (int, float))
        assert isinstance(data["offline_gap_count"], int)
    if data["status"] == AttestationStatus.FINALIZED_DENIED.value:
        assert data["denial_reason"] in _members(AttestationDenialReason)
    else:
        assert data.get("denial_reason") is None, (
            "denial_reason belongs to a FINALIZED_DENIED period only, but status "
            f"is {data['status']}"
        )


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def assert_reimbursement_claim(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["claim_type"] in ["WARRANTY_DEVICE", "WATER_DAMAGE"]
    assert data["status"] in _members(ClaimStatus)
    assert_integer_cents(data["documented_loss_cents"], "documented_loss_cents")
    assert isinstance(data["info_request_count"], int)
    assert data["info_request_count"] >= 0
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    if data["payout_variant"] is not None:
        assert data["payout_variant"] in _members(PayoutVariant)
    if data["status"] in (ClaimStatus.SUBMITTED.value, ClaimStatus.UNDER_REVIEW.value):
        assert data.get("payout_variant") is None, (
            "the payout algebra is selected at APPROVE, so a claim in "
            f"{data['status']} carries no payout_variant"
        )
        assert data.get("decided_by_user_id") is None
        assert data.get("decided_at") is None
    if data["status"] == ClaimStatus.DENIED.value and data["denial_reason"] is not None:
        assert data["denial_reason"] in _members(ClaimDenialReason)


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def assert_device_transfer(data: dict) -> None:
    assert_common_record_properties(data)
    assert is_valid_uuid(data["device_id"])
    assert is_valid_uuid(data["from_homeowner_id"])
    assert is_valid_uuid(data["to_homeowner_id"])
    assert data["from_homeowner_id"] != data["to_homeowner_id"], (
        "a transfer to the account that already owns the device is refused, so a "
        "persisted transfer always names two different accounts"
    )
    assert data["status"] in _members(TransferStatus)
    assert is_iso8601_timestamp(data["initiated_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["initiated_at"] < data["expires_at"]
    if data["status"] == TransferStatus.CANCELLED.value:
        assert data["cancel_reason"] in _members(TransferCancelReason)
    else:
        assert data.get("cancel_reason") is None, (
            "cancel_reason belongs to a CANCELLED transfer only, but status is "
            f"{data['status']}"
        )
    if data["status"] != TransferStatus.ACCEPTED.value:
        assert data.get("accepted_at") is None
        assert data.get("accepted_by_user_id") is None


# --------------------------------------------------------------------------
# Precision and rounding (PRD §2.7)
# --------------------------------------------------------------------------
def assert_integer_cents(value, field_name: str = "value") -> None:
    """Money is a whole number of cents, never a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer count of cents, got {value!r} "
        f"of type {type(value).__name__}"
    )
    assert value >= 0, f"{field_name} must not be negative, got {value}"


def assert_decimal_places(value, places: int, field_name: str = "value") -> None:
    """A quantity rounded to `places` decimals must not carry more than that."""
    assert isinstance(value, (int, float)), f"{field_name} must be numeric, got {value!r}"
    scaled = round(float(value) * (10**places))
    assert abs(float(value) * (10**places) - scaled) < 1e-6, (
        f"{field_name} must be rounded to {places} decimal places, got {value}"
    )


def assert_severity_precision(value) -> None:
    """A severity score is rounded once to three decimal places."""
    assert_decimal_places(value, 3, "severity_score")
    assert 0.0 <= value <= 1.0, f"severity_score must fall in [0, 1], got {value}"


def assert_uptime_precision(value) -> None:
    """An uptime percentage is rounded to two decimal places."""
    assert_decimal_places(value, 2, "uptime_pct")
    assert 0.0 <= value <= 100.0, f"uptime_pct must fall in [0, 100], got {value}"


def assert_threshold_precision(value, field_name: str = "drip_threshold_gpm") -> None:
    """A flow threshold is rounded to two decimal places."""
    assert_decimal_places(value, 2, field_name)


# --------------------------------------------------------------------------
# Ledger invariants
# --------------------------------------------------------------------------
def assert_credit_ledger_identity(policy: dict, awarded_total: int) -> None:
    """The policy's running credit equals awards less clawbacks.

    Every awarded period adds to the running credit and every reversal subtracts
    the same figure, so the two columns reconcile against the periods actually
    finalized rather than drifting apart.
    """
    expected = awarded_total - policy["clawback_cents_total"]
    assert policy["credited_cents_total"] == expected, (
        f"credited_cents_total {policy['credited_cents_total']} must equal "
        f"awards {awarded_total} less clawbacks {policy['clawback_cents_total']} "
        f"== {expected}"
    )


def assert_valve_ledger_monotonic(before: dict, after: dict) -> None:
    """Neither valve counter ever decreases."""
    assert after["close_count"] >= before["close_count"], (
        f"close_count went backwards: {before['close_count']} -> {after['close_count']}"
    )
    assert after["reopen_count"] >= before["reopen_count"], (
        f"reopen_count went backwards: {before['reopen_count']} -> "
        f"{after['reopen_count']}"
    )
