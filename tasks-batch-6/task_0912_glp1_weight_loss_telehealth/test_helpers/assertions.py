"""Entity assertions, instant comparison helpers and conservation checkers."""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Instant helpers — compare moments in time, not their textual rendering
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant such as 2026-06-01T00:00:00.000Z."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {label} to be {expected}, got {actual}"
    )


def plus_days(instant: str, days: int) -> str:
    """Return the instant `days` whole days later, rendered with a Z suffix."""
    moved = parse_instant(instant) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_minutes(instant: str, minutes: int) -> str:
    moved = parse_instant(instant) + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer counter beginning at 1"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["current_bmi"], (int, float))
    assert data["eligibility_status"] in (
        "NOT_SCREENED",
        "ELIGIBLE",
        "INELIGIBLE",
        "DEFERRED",
    )
    assert isinstance(data["lifetime_charged_cents"], int)
    assert isinstance(data["lifetime_credited_cents"], int)
    assert data["payment_mode"] in ("INSURANCE", "CASH")


def assert_provider(data: dict) -> None:
    assert_common_fields(data, "Provider")
    assert data["provider_type"] in ("CLINICIAN", "COACH")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_pharmacy(data: dict) -> None:
    assert_common_fields(data, "Pharmacy")
    assert data["dispense_type"] in ("COMPOUNDED", "BRANDED")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_supply_lot(data: dict) -> None:
    assert_common_fields(data, "SupplyLot")
    assert data["status"] in ("RELEASED", "QUARANTINED")
    for field in ("total_units", "available_units", "reserved_units", "dispensed_units"):
        assert isinstance(data[field], int), f"SupplyLot.{field} must be an integer"
    assert_supply_lot_conservation(data)


def assert_screening(data: dict) -> None:
    assert_common_fields(data, "EligibilityScreening")
    assert data["status"] in ("DRAFT", "ELIGIBLE", "INELIGIBLE", "DEFERRED")
    assert data["eligibility_band"] in (None, "OBESITY", "COMORBID", "NONE")
    assert data["decision_reason"] in (
        None,
        "BMI_QUALIFIED",
        "COMORBID_QUALIFIED",
        "BMI_BELOW_BAND",
        "RENAL_EXCLUSION",
        "STALE_LABS",
    )
    assert isinstance(data["submit_count"], int)


def assert_consult(data: dict) -> None:
    assert_common_fields(data, "Consult")
    assert data["status"] in (
        "SCHEDULED",
        "COMPLETED_PRESCRIBED",
        "COMPLETED_DECLINED",
        "NO_SHOW",
    )
    assert isinstance(data["reschedule_count"], int)


def assert_prescription(data: dict) -> None:
    assert_common_fields(data, "Prescription")
    assert data["clinical_status"] in ("ACTIVE", "HELD", "DISCONTINUED")
    assert data["fulfillment_status"] in ("UNROUTED", "ROUTED", "DISPENSED", "REFILL_DUE")
    assert data["active_route_mode"] in ("INSURANCE", "CASH")
    assert data["drug_family"] in ("SEMAGLUTIDE", "TIRZEPATIDE")
    assert 1 <= data["dose_level"] <= 5, "dose_level sits on a five-rung ladder"
    assert isinstance(data["severity_index_rolling"], int)
    assert isinstance(data["severity_index_since_dose_change"], int)


def assert_titration_step(data: dict) -> None:
    assert_common_fields(data, "TitrationStep")
    assert data["status"] in ("DUE", "ADMINISTERED", "HELD", "REDUCED")
    assert data["hold_reason"] in (None, "SIDE_EFFECT", "PROVIDER_HOLD")
    assert isinstance(data["step_number"], int) and data["step_number"] >= 1


def assert_prior_authorization(data: dict) -> None:
    assert_common_fields(data, "PriorAuthorization")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "APPEALED")
    assert isinstance(data["appeal_count"], int)


def assert_pharmacy_order(data: dict) -> None:
    assert_common_fields(data, "PharmacyOrder")
    assert data["status"] in ("CREATED", "RESERVED", "SHIPPED", "CANCELLED")
    assert data["dispense_type_at_route"] in ("COMPOUNDED", "BRANDED")
    assert data["cancel_reason"] in (None, "OPERATOR", "PA_DENIED", "CLINICAL_HOLD")
    assert isinstance(data["units_requested"], int)


def assert_subscription(data: dict) -> None:
    assert_common_fields(data, "Subscription")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["cycle_count"], int)
    assert isinstance(data["pause_days_used"], int)
    assert_coaching_credit_conservation(data)


def assert_billing_cycle(data: dict) -> None:
    assert_common_fields(data, "BillingCycle")
    assert data["status"] in ("OPEN", "INVOICED", "SETTLED", "VOIDED")
    assert data["charge_basis"] in (None, "CASH_PAY", "INSURANCE_ADJUDICATED")
    assert data["void_reason"] in (
        None,
        "ADMIN_REVERSAL",
        "SUBSCRIPTION_PAUSED",
        "SUBSCRIPTION_CANCELLED",
    )
    for field in (
        "medication_charge_cents",
        "coaching_addon_fee_cents",
        "dispensing_fee_cents",
        "adherence_credit_cents",
        "total_due_cents",
        "settled_amount_cents",
        "proration_credit_cents",
        "coaching_unused_credit_cents",
    ):
        assert isinstance(data[field], int), (
            f"BillingCycle.{field} must be a whole number of cents"
        )


def assert_check_in(data: dict) -> None:
    assert_common_fields(data, "CheckIn")
    assert data["status"] in ("SUBMITTED", "CLEARED", "ESCALATED", "RESOLVED")
    assert isinstance(data["severity_score"], int)
    assert 0 <= data["severity_score"] <= 13


def assert_coaching_session(data: dict) -> None:
    assert_common_fields(data, "CoachingSession")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "FORFEITED")


# ---------------------------------------------------------------------------
# Conservation identities
# ---------------------------------------------------------------------------


def assert_supply_lot_conservation(lot: dict) -> None:
    """total_units always equals available + reserved + dispensed."""
    total = lot["total_units"]
    parts = lot["available_units"] + lot["reserved_units"] + lot["dispensed_units"]
    assert total == parts, (
        f"Supply-lot unit conservation broken: total_units {total} != "
        f"available {lot['available_units']} + reserved {lot['reserved_units']} + "
        f"dispensed {lot['dispensed_units']}"
    )


def assert_lot_split(lot: dict, available: int, reserved: int, dispensed: int) -> None:
    assert lot["available_units"] == available, (
        f"Expected available_units {available}, got {lot['available_units']}"
    )
    assert lot["reserved_units"] == reserved, (
        f"Expected reserved_units {reserved}, got {lot['reserved_units']}"
    )
    assert lot["dispensed_units"] == dispensed, (
        f"Expected dispensed_units {dispensed}, got {lot['dispensed_units']}"
    )
    assert_supply_lot_conservation(lot)


def assert_coaching_credit_conservation(subscription: dict) -> None:
    """granted always equals available + reserved + consumed + forfeited."""
    granted = subscription["coaching_credits_granted"]
    parts = (
        subscription["coaching_credits_available"]
        + subscription["coaching_credits_reserved"]
        + subscription["coaching_credits_consumed"]
        + subscription["coaching_credits_forfeited"]
    )
    assert granted == parts, (
        f"Coaching credit conservation broken: granted {granted} != available "
        f"{subscription['coaching_credits_available']} + reserved "
        f"{subscription['coaching_credits_reserved']} + consumed "
        f"{subscription['coaching_credits_consumed']} + forfeited "
        f"{subscription['coaching_credits_forfeited']}"
    )


def assert_credit_split(
    subscription: dict,
    granted: int,
    available: int,
    reserved: int,
    consumed: int,
    forfeited: int,
) -> None:
    assert subscription["coaching_credits_granted"] == granted
    assert subscription["coaching_credits_available"] == available, (
        f"Expected coaching_credits_available {available}, "
        f"got {subscription['coaching_credits_available']}"
    )
    assert subscription["coaching_credits_reserved"] == reserved, (
        f"Expected coaching_credits_reserved {reserved}, "
        f"got {subscription['coaching_credits_reserved']}"
    )
    assert subscription["coaching_credits_consumed"] == consumed, (
        f"Expected coaching_credits_consumed {consumed}, "
        f"got {subscription['coaching_credits_consumed']}"
    )
    assert subscription["coaching_credits_forfeited"] == forfeited, (
        f"Expected coaching_credits_forfeited {forfeited}, "
        f"got {subscription['coaching_credits_forfeited']}"
    )
    assert_coaching_credit_conservation(subscription)


def assert_patient_billing_conservation(patient: dict, settled_cycles: list) -> None:
    """charged minus credited always equals the sum over SETTLED cycles."""
    net = patient["lifetime_charged_cents"] - patient["lifetime_credited_cents"]
    expected = sum(cycle["settled_amount_cents"] for cycle in settled_cycles)
    assert net == expected, (
        f"Member billing conservation broken: lifetime_charged_cents "
        f"{patient['lifetime_charged_cents']} minus lifetime_credited_cents "
        f"{patient['lifetime_credited_cents']} == {net}, but the settled cycles sum "
        f"to {expected}"
    )
