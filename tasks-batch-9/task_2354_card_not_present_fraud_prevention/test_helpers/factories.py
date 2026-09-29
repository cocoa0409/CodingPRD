"""Request-payload builders.

Every factory returns only client-supplied input fields — never a server-managed
field such as ``id``, ``version``, a derived counter or a computed score. All of
them accept ``**overrides`` so a test can pin exactly the field it is exercising.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_EPOCH,
    FAST_CHECKOUT_SESSION_SECONDS,
    MODEL_INTERCEPT,
    MODEL_SLOPE,
    NORMAL_CART_ITEM_COUNT,
    PACK_DECLINE_FLOOR,
    PACK_MODEL_WEIGHT,
    PACK_REVIEW_FLOOR,
    PACK_RULE_POINTS,
    PACK_RULE_WEIGHT,
    PROB_REVIEW_MID_BAND,
    STANDARD_ORDER_CENTS,
)
from .types import (
    AuthEventType,
    BlendMode,
    ChargebackReasonCode,
    ExceptionScope,
    RuleCode,
    RULE_CODE_FAMILY,
    Seniority,
    SignalFamily,
)

_counter = itertools.count(1)


def _next() -> int:
    """A process-unique integer for building distinguishable payload values."""
    return next(_counter)


# ---------------------------------------------------------------------------
# Instant arithmetic against the logical clock
# ---------------------------------------------------------------------------

_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


def parse_instant(instant: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    normalised = instant.replace("Z", "+0000")
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(normalised, fmt)
        except ValueError:
            continue
    raise ValueError(f"Not an ISO 8601 UTC instant: {instant!r}")


def format_instant(moment: datetime) -> str:
    """Render an instant in the wire format the API accepts: ``...Z``."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_seconds(instant: str, seconds: int) -> str:
    """The instant ``seconds`` after ``instant``; negative values move backwards."""
    return format_instant(parse_instant(instant) + timedelta(seconds=seconds))


def plus_hours(instant: str, hours: float) -> str:
    return plus_seconds(instant, int(hours * 3600))


def plus_days(instant: str, days: float) -> str:
    return plus_seconds(instant, int(days * 86400))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock_payload(current_utc: str = CLOCK_EPOCH, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


def create_customer_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "email": f"shopper{n}@example.com",
        "home_country": "US",
    }
    payload.update(overrides)
    return payload


def customer_posture_payload(**overrides: Any) -> Dict[str, Any]:
    """Supplies exactly one of ``account_status`` or ``ato_posture``.

    Callers must name which axis they are driving; nothing is supplied by default.
    """
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def lock_account_payload(reason: str = "manual review hold") -> Dict[str, Any]:
    return {"account_status": "LOCKED", "reason": reason}


def unlock_account_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"account_status": "ACTIVE"}
    payload.update(overrides)
    return payload


def close_account_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"account_status": "CLOSED"}
    payload.update(overrides)
    return payload


def clear_ato_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ato_posture": "CLEAR"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------


def create_analyst_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "display_name": f"Analyst {n}",
        "seniority": Seniority.JUNIOR,
        "skill_families": [SignalFamily.BEHAVIORAL],
        "shift_capacity_cases": 2,
    }
    payload.update(overrides)
    return payload


def analyst_shift_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Device profile
# ---------------------------------------------------------------------------


def create_device_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "device_hash": f"device-hash-{n:06d}",
        "tz_offset_minutes": -300,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------


def create_address_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "line1": f"{n} Market Street",
        "postal_code": "94105",
        "country_code": "US",
    }
    payload.update(overrides)
    return payload


def create_variant_address_payload(parent_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = create_address_payload(canonical_parent_address_id=parent_id)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rule pack and fraud rule
# ---------------------------------------------------------------------------


def create_rule_pack_payload(**overrides: Any) -> Dict[str, Any]:
    """A WEIGHTED pack with normalised weights and correctly ordered bands."""
    n = _next()
    payload: Dict[str, Any] = {
        "version_label": f"pack-{n}",
        "blend_mode": BlendMode.WEIGHTED,
        "rule_weight": PACK_RULE_WEIGHT,
        "model_weight": PACK_MODEL_WEIGHT,
        "review_floor_score": PACK_REVIEW_FLOOR,
        "decline_floor_score": PACK_DECLINE_FLOOR,
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_until": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_rule_dominant_pack_payload(**overrides: Any) -> Dict[str, Any]:
    """A RULE_DOMINANT pack; its weights are ignored but must still sum to 1.00."""
    payload = create_rule_pack_payload(blend_mode=BlendMode.RULE_DOMINANT)
    payload.update(overrides)
    return payload


def create_rule_payload(
    code: str = RuleCode.BEH_FAST_CHECKOUT,
    points: int = PACK_RULE_POINTS,
    evaluation_order: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """A rule whose ``signal_family`` is the family its ``code`` belongs to."""
    payload: Dict[str, Any] = {
        "code": code,
        "signal_family": RULE_CODE_FAMILY[code],
        "points": points,
        "evaluation_order": evaluation_order,
    }
    payload.update(overrides)
    return payload


def fast_checkout_rule_payload(
    points: int = PACK_RULE_POINTS, evaluation_order: int = 10, **overrides: Any
) -> Dict[str, Any]:
    return create_rule_payload(
        RuleCode.BEH_FAST_CHECKOUT, points, evaluation_order, **overrides
    )


def emulator_hard_decline_rule_payload(
    points: int = 45, evaluation_order: int = 10, **overrides: Any
) -> Dict[str, Any]:
    payload = create_rule_payload(
        RuleCode.DEV_EMULATOR, points, evaluation_order, hard_decline=True
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------


def create_risk_model_payload(**overrides: Any) -> Dict[str, Any]:
    """A cold-start model: ``trained_on_chargeback_cutoff_at`` is left unset."""
    n = _next()
    payload: Dict[str, Any] = {
        "model_version_label": f"model-{n}",
        "calibration_intercept": MODEL_INTERCEPT,
        "calibration_slope": MODEL_SLOPE,
    }
    payload.update(overrides)
    return payload


def create_retrained_model_payload(cutoff_at: str, **overrides: Any) -> Dict[str, Any]:
    """A retrained model, which must pass through the training gate."""
    payload = create_risk_model_payload(trained_on_chargeback_cutoff_at=cutoff_at)
    payload.update(overrides)
    return payload


def model_lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Checkout assessment
# ---------------------------------------------------------------------------


def create_assessment_payload(
    customer_id: str,
    device_profile_id: str,
    shipping_address_id: str,
    billing_address_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An order that fires only ``BEH_FAST_CHECKOUT`` under the reference pack.

    ``session_seconds`` 30 is under the 45-second fast-checkout threshold, and
    ``cart_item_count`` 3 is under the 10-item bulk-cart threshold.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "device_profile_id": device_profile_id,
        "shipping_address_id": shipping_address_id,
        "billing_address_id": billing_address_id or shipping_address_id,
        "amount_cents": STANDARD_ORDER_CENTS,
        "card_bin": "411111",
        "ip_country": "US",
        "session_seconds": FAST_CHECKOUT_SESSION_SECONDS,
        "cart_item_count": NORMAL_CART_ITEM_COUNT,
        "model_raw_probability": PROB_REVIEW_MID_BAND,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Review case staffing and resolution
# ---------------------------------------------------------------------------


def assign_case_payload(
    analyst_id: str, expected_analyst_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "analyst_id": analyst_id,
        "expected_analyst_version": expected_analyst_version,
    }
    payload.update(overrides)
    return payload


def resolve_case_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Authentication event and challenge
# ---------------------------------------------------------------------------


def create_auth_event_payload(
    customer_id: str,
    device_profile_id: str,
    event_type: str = AuthEventType.LOGIN,
    ip_country: str = "US",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "device_profile_id": device_profile_id,
        "event_type": event_type,
        "ip_country": ip_country,
    }
    payload.update(overrides)
    return payload


def challenge_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Chargeback
# ---------------------------------------------------------------------------


def create_chargeback_payload(
    assessment_id: str,
    amount_cents: int,
    received_at: str,
    reason_code: str = ChargebackReasonCode.FRAUD_CNP,
    liability_shift: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assessment_id": assessment_id,
        "reason_code": reason_code,
        "amount_cents": amount_cents,
        "liability_shift": liability_shift,
        "received_at": received_at,
    }
    payload.update(overrides)
    return payload


def chargeback_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Policy exception
# ---------------------------------------------------------------------------


def create_policy_exception_payload(
    customer_id: str,
    scope: str = ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
    max_amount_cents: int = 100000,
    effective_from: str = CLOCK_EPOCH,
    expires_at: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "scope": scope,
        "max_amount_cents": max_amount_cents,
        "effective_from": effective_from,
        "expires_at": expires_at,
        "justification": "Long-standing account with a clean dispute history",
    }
    payload.update(overrides)
    return payload


def address_whitelist_exception_payload(
    customer_id: str, whitelisted_address_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = create_policy_exception_payload(
        customer_id,
        scope=ExceptionScope.ADDRESS_WHITELIST,
        whitelisted_address_id=whitelisted_address_id,
    )
    payload.update(overrides)
    return payload


def exception_decision_payload(
    action: str, expected_customer_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "expected_customer_version": expected_customer_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Convenience collections
# ---------------------------------------------------------------------------


def all_rule_families_skill_set() -> List[str]:
    """A skill set that covers every family a case can carry."""
    return list(SignalFamily.ALL)


__all__ = [
    "parse_instant",
    "format_instant",
    "plus_seconds",
    "plus_hours",
    "plus_days",
    "set_clock_payload",
    "create_customer_payload",
    "customer_posture_payload",
    "lock_account_payload",
    "unlock_account_payload",
    "close_account_payload",
    "clear_ato_payload",
    "create_analyst_payload",
    "analyst_shift_payload",
    "create_device_payload",
    "create_address_payload",
    "create_variant_address_payload",
    "create_rule_pack_payload",
    "create_rule_dominant_pack_payload",
    "create_rule_payload",
    "fast_checkout_rule_payload",
    "emulator_hard_decline_rule_payload",
    "create_risk_model_payload",
    "create_retrained_model_payload",
    "model_lifecycle_payload",
    "create_assessment_payload",
    "assign_case_payload",
    "resolve_case_payload",
    "create_auth_event_payload",
    "challenge_payload",
    "create_chargeback_payload",
    "chargeback_transition_payload",
    "create_policy_exception_payload",
    "address_whitelist_exception_payload",
    "exception_decision_payload",
    "all_rule_families_skill_set",
]
