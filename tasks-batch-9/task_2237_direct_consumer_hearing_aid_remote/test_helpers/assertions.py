"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime.

    PRD §2.4 mints timestamps "in ISO 8601 UTC form with three fractional digits",
    so ``2026-08-01T00:00:00.000Z`` and ``2026-08-01T00:00:00Z`` denote the same
    instant. Comparisons must therefore be on instants, not on raw strings.
    """
    assert isinstance(value, str), f"expected an ISO 8601 timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, message: str = "") -> None:
    """Assert two ISO 8601 UTC timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected), (
        message or f"expected the instant {expected!r}, got {actual!r}"
    )


def _assert_common(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_event_common(data: dict, entity: str) -> None:
    """Append-only event rows expose id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity} must not expose a version field"
    assert "updated_at" not in data, f"{entity} must not expose an updated_at field"


def assert_state_policy(data: dict) -> None:
    _assert_common(data, "StatePolicy")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["restocking_fee_mode"] in ("FLAT_PCT", "PRORATED_DAILY", "PROHIBITED")
    assert isinstance(data["trial_period_days"], int)
    assert isinstance(data["is_retired"], bool)


def assert_patient(data: dict) -> None:
    _assert_common(data, "Patient")
    assert data["status"] in (
        "REGISTERED", "SCREENING_IN_PROGRESS", "CANDIDATE_APPROVED", "REFERRAL_REQUIRED",
        "PROVIDER_CLEARED", "MEDICALLY_DISQUALIFIED", "DEACTIVATED",
    ), f"unexpected Patient.status {data['status']!r}"
    assert data["candidacy_risk_band"] in ("LOW", "MODERATE", "HIGH")
    assert data["candidacy_risk_score"] >= 0
    assert data["open_mandatory_flag_count"] >= 0


def assert_screening_session(data: dict) -> None:
    _assert_common(data, "ScreeningSession")
    assert data["status"] in ("DRAFT", "IN_PROGRESS", "SUBMITTED", "SCORED", "INVALIDATED")
    assert data["attempt_ordinal"] >= 1


def assert_red_flag_finding(data: dict) -> None:
    assert_event_common(data, "RedFlagFinding")
    assert data["severity"] in ("MANDATORY_REFERRAL", "ADVISORY")
    assert is_iso8601_timestamp(data["detected_at"]), "RedFlagFinding.detected_at must be ISO 8601"


def assert_provider(data: dict) -> None:
    _assert_common(data, "Provider")
    assert data["provider_type"] in ("TELECARE_FITTER", "LICENSED_AUDIOLOGIST")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert data["daily_capacity_minutes"] >= 0
    assert isinstance(data["licensed_state_codes"], list)


def assert_provider_referral(data: dict) -> None:
    _assert_common(data, "ProviderReferral")
    assert data["status"] in (
        "OPEN", "SCHEDULED", "EVALUATED", "CLEARED", "NOT_CLEARED", "EXPIRED", "WITHDRAWN",
    )
    assert data["reschedule_count"] >= 0


def assert_remote_fitting_session(data: dict) -> None:
    _assert_common(data, "RemoteFittingSession")
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "CANCELLED",
    )
    assert data["session_type"] in ("INITIAL_FIT", "FOLLOW_UP", "REFERRAL_EVALUATION")


def assert_device_order(data: dict) -> None:
    _assert_common(data, "DeviceOrder")
    assert data["payment_status"] in (
        "PENDING_AUTH", "AUTHORIZED", "AUTH_FAILED", "CAPTURED", "VOIDED",
        "PARTIALLY_REFUNDED", "REFUNDED",
    )
    assert data["fulfillment_status"] in (
        "PENDING_FIT_CONFIRM", "READY_TO_SHIP", "MEDICAL_HOLD", "SHIPPED", "DELIVERED",
        "RETURN_IN_TRANSIT", "RETURNED", "CANCELLED",
    )
    for field in ("tax_cents", "total_cents", "captured_cents", "refunded_cents", "retained_cents"):
        assert isinstance(data[field], int), f"DeviceOrder.{field} must be an integer count of cents"
        assert data[field] >= 0, f"DeviceOrder.{field} must not be negative"


def assert_cash_conservation(order: dict) -> None:
    """captured_cents == refunded_cents + retained_cents + open_balance_cents."""
    assert order["captured_cents"] == (
        order["refunded_cents"] + order["retained_cents"] + order["open_balance_cents"]
    ), (
        "cash conservation violated: captured_cents "
        f"{order['captured_cents']} != refunded {order['refunded_cents']} + retained "
        f"{order['retained_cents']} + open balance {order['open_balance_cents']}"
    )


def assert_device(data: dict) -> None:
    _assert_common(data, "Device")
    assert data["status"] in (
        "IN_STOCK", "ASSIGNED", "WITH_PATIENT", "IN_REPAIR", "RETIRED", "REPLACED", "LOST",
    )
    assert data["loss_damage_claims_approved"] >= 0


def assert_inventory_pool(data: dict) -> None:
    _assert_common(data, "InventoryPool")
    for field in ("on_hand_units", "reserved_units", "dispatched_units", "total_units_received"):
        assert data[field] >= 0, f"InventoryPool.{field} must not be negative"


def assert_inventory_conservation(pool: dict) -> None:
    """on_hand_units + reserved_units + dispatched_units == total_units_received."""
    assert (
        pool["on_hand_units"] + pool["reserved_units"] + pool["dispatched_units"]
        == pool["total_units_received"]
    ), (
        "inventory conservation violated: "
        f"{pool['on_hand_units']} + {pool['reserved_units']} + {pool['dispatched_units']} "
        f"!= {pool['total_units_received']}"
    )


def assert_trial_period(data: dict) -> None:
    _assert_common(data, "TrialPeriod")
    assert data["status"] in (
        "ACTIVE", "PAUSED", "RETURN_INITIATED", "RETURN_SETTLED", "EXPIRED_KEPT", "VOIDED",
    )
    assert data["days_used"] >= 0
    assert data["paused_days"] >= 0


def assert_return_authorization(data: dict) -> None:
    _assert_common(data, "ReturnAuthorization")
    assert data["status"] in (
        "ISSUED", "IN_TRANSIT", "RECEIVED", "INSPECTED", "REFUND_SETTLED", "EXPIRED", "VOIDED",
    )
    for field in ("restocking_fee_cents", "non_refundable_shipping_cents", "refund_amount_cents"):
        assert data[field] >= 0, f"ReturnAuthorization.{field} must not be negative"


def assert_fit_exchange(data: dict) -> None:
    _assert_common(data, "FitExchange")
    assert data["status"] in (
        "REQUESTED", "RESERVED", "REJECTED", "SHIPPED", "COMPLETED", "CANCELLED",
    )
    assert data["exchange_fee_cents"] >= 0


def assert_repair_order(data: dict) -> None:
    _assert_common(data, "RepairOrder")
    assert data["status"] in (
        "KIT_REQUESTED", "KIT_SENT", "RECEIVED", "IN_REPAIR", "REPAIRED", "UNREPAIRABLE",
        "RETURNED_TO_PATIENT", "ESCALATED_TO_WARRANTY", "CANCELLED",
    )
    assert data["sla_credit_cents"] >= 0


def assert_warranty_claim(data: dict) -> None:
    _assert_common(data, "WarrantyClaim")
    assert data["status"] in (
        "FILED", "TRIAGED", "APPROVED_REPLACEMENT", "APPROVED_REPAIR", "DENIED",
        "FULFILLED", "WITHDRAWN",
    )
    assert data["claim_kind"] in ("DEFECT", "DAMAGE", "LOSS")
    assert data["deductible_cents"] >= 0
    assert data["deductible_paid_cents"] >= 0


def assert_reimbursement_claim(data: dict) -> None:
    _assert_common(data, "ReimbursementClaim")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED",
        "PAID", "VOIDED",
    )
    assert data["subject_kind"] in ("DEVICE_ORDER", "REPAIR", "CARE_PLAN")
    for field in ("insurance_paid_cents", "fsa_paid_cents", "patient_responsibility_cents"):
        assert data[field] >= 0, f"ReimbursementClaim.{field} must not be negative"


def assert_benefit_conservation(claim: dict) -> None:
    """insurance_paid_cents + fsa_paid_cents + patient_responsibility_cents == eligible_amount_cents."""
    assert (
        claim["insurance_paid_cents"] + claim["fsa_paid_cents"] + claim["patient_responsibility_cents"]
        == claim["eligible_amount_cents"]
    ), (
        "benefit conservation violated: "
        f"{claim['insurance_paid_cents']} + {claim['fsa_paid_cents']} + "
        f"{claim['patient_responsibility_cents']} != {claim['eligible_amount_cents']}"
    )


def assert_care_plan_subscription(data: dict) -> None:
    _assert_common(data, "CarePlanSubscription")
    assert data["status"] in ("TRIALING", "ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")
    assert data["plan_tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert data["credit_balance_cents"] >= 0
    assert data["cycle_ordinal"] >= 0
    assert data["dunning_attempts"] >= 0


def assert_firmware_campaign(data: dict) -> None:
    _assert_common(data, "FirmwareCampaign")
    assert data["status"] in ("DRAFT", "SCHEDULED", "ROLLING", "PAUSED", "COMPLETED", "ABORTED")
    assert data["rollout_count"] >= 0
    assert data["installed_count"] >= 0


def assert_firmware_rollout(data: dict) -> None:
    _assert_common(data, "FirmwareRollout")
    assert data["status"] in (
        "PENDING", "OFFERED", "INSTALLING", "INSTALLED", "FAILED", "ROLLED_BACK",
        "CANCELLED_INELIGIBLE",
    )
    assert data["attempt_count"] >= 0


def assert_compliance_override(data: dict) -> None:
    _assert_common(data, "ComplianceOverride")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_pagination_meta(meta: dict, expected_limit: int, expected_offset: int,
                           expected_total: int, expected_has_more: bool) -> None:
    assert meta["limit"] == expected_limit, f"limit should be {expected_limit}, got {meta['limit']}"
    assert meta["offset"] == expected_offset, f"offset should be {expected_offset}, got {meta['offset']}"
    assert meta["total_count"] == expected_total, (
        f"total_count should be {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"has_more should be {expected_has_more}, got {meta['has_more']}"
    )
