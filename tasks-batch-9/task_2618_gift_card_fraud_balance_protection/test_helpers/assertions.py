"""Domain assertions and reference arithmetic for the PRD's derived fields.

Every helper here re-implements one rule stated in the PRD, so a test can assert
against an independently computed expectation rather than against a number
copied out of the implementation.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ACTIVATION_STATES,
    CARD_CHANNELS,
    DRAIN_RESTRICT_SCORE_THRESHOLD,
    DRAIN_WATCH_SCORE_THRESHOLD,
    RISK_POSTURE_RANK,
    RISK_POSTURES,
    SCREENING_COMPONENT_KEYS,
)


# ----------------------------------------------------------------------
# Rounding: "rounded half up — a value whose fractional part is exactly one
# half always rounds away from zero to the larger magnitude"
# ----------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round to a whole number half up, away from zero on an exact half."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round to exactly two decimal places half up (the drawdown_ratio rule)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents: int, rate_bps: int) -> int:
    """"applying a rate to an amount means multiplying the amount by the basis-point
    figure and dividing by 10000", rounded half up."""
    return round_half_up(Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000))


def clamp_score(raw) -> int:
    """A score is "an integer produced by rounding half up exactly once, at the very
    end of the composition, and then clamped into the closed range 0 through 100"."""
    return max(0, min(100, round_half_up(raw)))


# ----------------------------------------------------------------------
# Envelope and common fields
# ----------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Most resources expose "a server-minted id, which is a UUID with no type prefix",
    a created_at, an updated_at and "version, an integer that starts at 1 on creation"."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_create_only_fields(entity: Dict[str, Any]) -> None:
    """"Ledger events, balance inquiries and law-enforcement referrals carry only id and
    created_at: they have no updated_at and no version at all"."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "immutable audit record must have no updated_at"
    assert "version" not in entity, "immutable audit record must have no version"


def assert_three_fraction_digits(timestamp: str) -> None:
    """Timestamps are "ISO 8601 UTC with three fractional digits"."""
    assert is_iso8601_timestamp(timestamp), timestamp
    assert "." in timestamp, f"timestamp has no fractional digits: {timestamp}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits: {timestamp}"


def assert_unchanged_version(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A read "stores nothing and increments no version"."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    """A version "increases by exactly 1 on every mutation"."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )


# ----------------------------------------------------------------------
# Gift-card projection
# ----------------------------------------------------------------------
def assert_card_projection(
    card: Dict[str, Any],
    current_balance_cents: Optional[int] = None,
    total_loaded_cents: Optional[int] = None,
    total_redeemed_cents: Optional[int] = None,
    held_amount_cents: Optional[int] = None,
    available_balance_cents: Optional[int] = None,
    drawdown_ratio=None,
    distinct_merchant_count: Optional[int] = None,
    recent_redemption_count: Optional[int] = None,
) -> None:
    """Assert the card's balance projection: every figure named here is derived by the
    server, never written by a client."""
    checks = {
        "current_balance_cents": current_balance_cents,
        "total_loaded_cents": total_loaded_cents,
        "total_redeemed_cents": total_redeemed_cents,
        "held_amount_cents": held_amount_cents,
        "available_balance_cents": available_balance_cents,
        "distinct_merchant_count": distinct_merchant_count,
        "recent_redemption_count": recent_redemption_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert card[field] == expected, f"{field}: expected {expected}, got {card[field]}"
    if drawdown_ratio is not None:
        assert float(card["drawdown_ratio"]) == float(drawdown_ratio), (
            f"drawdown_ratio: expected {drawdown_ratio}, got {card['drawdown_ratio']}"
        )


def expected_drawdown_ratio(total_redeemed_cents: int, total_loaded_cents: int) -> float:
    """"0.00 when total_loaded_cents is zero, and otherwise total_redeemed_cents divided
    by total_loaded_cents, rounded half up to two decimal places and clamped into the
    closed range 0.00 through 1.00"."""
    if total_loaded_cents == 0:
        return 0.00
    ratio = round_half_up_2dp(Decimal(total_redeemed_cents) / Decimal(total_loaded_cents))
    return max(0.00, min(1.00, ratio))


def assert_available_balance(card: Dict[str, Any]) -> None:
    """"available_balance_cents is the current balance minus the held amount, floored at
    zero"."""
    expected = max(0, card["current_balance_cents"] - card["held_amount_cents"])
    assert card["available_balance_cents"] == expected, (
        f"available_balance_cents: expected {expected}, got {card['available_balance_cents']}"
    )


def assert_signed_amount(event: Dict[str, Any]) -> None:
    """The credit kinds carry "signed_amount_cents is the positive amount"; the debit
    kinds carry "the negated amount"."""
    credits = ("ACTIVATION_LOAD", "REDEMPTION_REVERSAL", "REISSUE_CREDIT", "REISSUE_DEBIT_REVERSAL")
    expected = event["amount_cents"] if event["type"] in credits else -event["amount_cents"]
    assert event["signed_amount_cents"] == expected, (
        f"signed_amount_cents: expected {expected}, got {event['signed_amount_cents']}"
    )


# ----------------------------------------------------------------------
# Drain scores
# ----------------------------------------------------------------------
def expected_inquiry_drain_score(
    velocity_count: int, drawdown_ratio, distinct_merchant_count: int
) -> int:
    """"12 points per inquiry in the current velocity count, plus 30 multiplied by the
    card's drawdown_ratio, plus 5 points per entry in distinct_merchant_count"."""
    raw = (
        Decimal(12) * Decimal(velocity_count)
        + Decimal(30) * Decimal(str(drawdown_ratio))
        + Decimal(5) * Decimal(distinct_merchant_count)
    )
    return clamp_score(raw)


def expected_redemption_drain_score(
    drawdown_ratio, distinct_merchant_count: int, recent_redemption_count: int
) -> int:
    """"45 multiplied by the card's drawdown_ratio, plus 14 points per entry in
    distinct_merchant_count, plus 6 points per event in recent_redemption_count"."""
    raw = (
        Decimal(45) * Decimal(str(drawdown_ratio))
        + Decimal(14) * Decimal(distinct_merchant_count)
        + Decimal(6) * Decimal(recent_redemption_count)
    )
    return clamp_score(raw)


def expected_posture_target(score: int, breach: bool = False) -> str:
    """"If an inquiry velocity breach just occurred, the target is RESTRICTED ...
    Otherwise, if the score is at or above drain_restrict_score_threshold, the target is
    RESTRICTED. Otherwise, if the score is at or above drain_watch_score_threshold, the
    target is WATCH. Otherwise the target is CLEAR."""
    if breach:
        return "RESTRICTED"
    if score >= DRAIN_RESTRICT_SCORE_THRESHOLD:
        return "RESTRICTED"
    if score >= DRAIN_WATCH_SCORE_THRESHOLD:
        return "WATCH"
    return "CLEAR"


def escalate_posture(current: str, target: str) -> str:
    """The posture is set to the target "only when the target sits strictly higher on the
    ladder than the card's current rung"."""
    return target if RISK_POSTURE_RANK[target] > RISK_POSTURE_RANK[current] else current


# ----------------------------------------------------------------------
# Digital issuance screening
# ----------------------------------------------------------------------
def expected_device_component(device_reputation_score: int) -> int:
    """"one hundred minus device_reputation_score, and never below 0"."""
    return max(0, 100 - device_reputation_score)


def expected_email_component(email_age_days: int) -> int:
    """"An email_age_days of at least 365 contributes 0. From 90 through 364 days
    inclusive it contributes 20. From 7 through 89 days inclusive it contributes 45.
    Below 7 days it contributes 70."""
    if email_age_days >= 365:
        return 0
    if email_age_days >= 90:
        return 20
    if email_age_days >= 7:
        return 45
    return 70


def expected_payment_component(payment_risk_band: str) -> int:
    """"LOW contributes 0, MEDIUM contributes 25, and HIGH contributes 60"."""
    return {"LOW": 0, "MEDIUM": 25, "HIGH": 60}[payment_risk_band]


def expected_amount_component(face_value_cents: int) -> int:
    """"take the face value divided by 5000 and discarded down to a whole number of
    steps, award 5 points per step, and cap the result at 30"."""
    return min(30, (face_value_cents // 5000) * 5)


def expected_screening_components(
    device_reputation_score: int,
    email_age_days: int,
    payment_risk_band: str,
    face_value_cents: int,
    bulk_surcharge: int = 0,
) -> Dict[str, int]:
    """screening_components records "the four transformed components alongside the
    pre-surcharge base and the surcharge actually applied under the keys device, email,
    payment, amount, base and bulk_surcharge"."""
    device = expected_device_component(device_reputation_score)
    email = expected_email_component(email_age_days)
    payment = expected_payment_component(payment_risk_band)
    amount = expected_amount_component(face_value_cents)
    base = round_half_up(
        Decimal("0.35") * Decimal(device)
        + Decimal("0.25") * Decimal(email)
        + Decimal("0.25") * Decimal(payment)
        + Decimal("0.15") * Decimal(amount)
    )
    return {
        "device": device,
        "email": email,
        "payment": payment,
        "amount": amount,
        "base": base,
        "bulk_surcharge": bulk_surcharge,
    }


def expected_screening_score(components: Dict[str, int]) -> int:
    """"15 points are added to the base and the result is capped at 100. Otherwise the
    score is the base unchanged."""
    return min(100, components["base"] + components["bulk_surcharge"])


def assert_screening_components(request: Dict[str, Any], expected: Dict[str, int]) -> None:
    """Assert the audit breakdown key by key, and that no extra keys appear."""
    actual = request["screening_components"]
    assert set(actual.keys()) == set(SCREENING_COMPONENT_KEYS), (
        f"screening_components keys: expected {sorted(SCREENING_COMPONENT_KEYS)}, "
        f"got {sorted(actual.keys())}"
    )
    for key in SCREENING_COMPONENT_KEYS:
        assert actual[key] == expected[key], (
            f"screening_components[{key}]: expected {expected[key]}, got {actual[key]}"
        )


# ----------------------------------------------------------------------
# Bulk order pricing
# ----------------------------------------------------------------------
def expected_fee_rate_bps(subtotal_cents: int) -> int:
    """"a subtotal below 25000 cents attracts no fee at all; from 25000 up to but not
    including 100000 cents the rate is 150 basis points; from 100000 up to but not
    including 500000 cents it is 225 basis points; and at 500000 cents or above it is
    300 basis points"."""
    if subtotal_cents < 25000:
        return 0
    if subtotal_cents < 100000:
        return 150
    if subtotal_cents < 500000:
        return 225
    return 300


def expected_bulk_pricing(card_quantity: int, face_value_cents_each: int) -> Dict[str, int]:
    """Pricing runs subtotal, then rate band off that subtotal, then the fee "rounded
    half up exactly once over the whole order", then the total."""
    subtotal = card_quantity * face_value_cents_each
    rate = expected_fee_rate_bps(subtotal)
    fee = apply_bps(subtotal, rate)
    return {
        "face_value_subtotal_cents": subtotal,
        "fee_rate_bps": rate,
        "activation_fee_cents": fee,
        "total_cents": subtotal + fee,
    }


def assert_bulk_pricing(order: Dict[str, Any], expected: Dict[str, int]) -> None:
    """Assert the four pinned pricing fields on a bulk order."""
    for field, value in expected.items():
        assert order[field] == value, f"{field}: expected {value}, got {order[field]}"


# ----------------------------------------------------------------------
# Rack and floor derivation
# ----------------------------------------------------------------------
def expected_missing_card_count(expected_card_count: int, observed_card_count: int) -> int:
    """"Shrink is then derived as the expected count minus the observed count, floored at
    zero"."""
    return max(0, expected_card_count - observed_card_count)


def expected_tamper_state(
    missing_card_count: int,
    seal_breaks_observed: int,
    shrink_threshold: int = 3,
    seal_break_threshold: int = 3,
) -> str:
    """"If missing_card_count is at least rack_shrink_threshold, or seal_breaks_observed
    is at least rack_seal_break_threshold, the rack is TAMPERED. Otherwise, if
    missing_card_count is at least 1 or seal_breaks_observed is at least 1, the rack is
    SUSPECT. Otherwise it is INTACT."""
    if missing_card_count >= shrink_threshold or seal_breaks_observed >= seal_break_threshold:
        return "TAMPERED"
    if missing_card_count >= 1 or seal_breaks_observed >= 1:
        return "SUSPECT"
    return "INTACT"


def expected_floor_posture(
    tampered_rack_count: int,
    suspect_rack_count: int,
    open_alert_count: int,
    heightened_alert_threshold: int = 2,
) -> str:
    """"if tampered_rack_count is at least 1 the floor is SUSPENDED; otherwise, if
    suspect_rack_count is at least 1 or open_alert_count is at least
    floor_heightened_alert_threshold, the floor is HEIGHTENED; otherwise it is OPEN"."""
    if tampered_rack_count >= 1:
        return "SUSPENDED"
    if suspect_rack_count >= 1 or open_alert_count >= heightened_alert_threshold:
        return "HEIGHTENED"
    return "OPEN"


def assert_store_counters(
    store: Dict[str, Any],
    floor_posture: Optional[str] = None,
    tampered_rack_count: Optional[int] = None,
    suspect_rack_count: Optional[int] = None,
    open_alert_count: Optional[int] = None,
    declined_issuance_count: Optional[int] = None,
) -> None:
    """Assert the store's derived counters and its floor posture."""
    checks = {
        "floor_posture": floor_posture,
        "tampered_rack_count": tampered_rack_count,
        "suspect_rack_count": suspect_rack_count,
        "open_alert_count": open_alert_count,
        "declined_issuance_count": declined_issuance_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert store[field] == expected, f"{field}: expected {expected}, got {store[field]}"


# ----------------------------------------------------------------------
# Claim recovery arithmetic
# ----------------------------------------------------------------------
def expected_gross_reissue(line_amounts: Iterable[int], recovery_factor_bps: int = 8500) -> int:
    """"recovery_factor_bps is applied to each line individually, and each line's result
    is rounded to whole cents half-up before the addition"."""
    return sum(apply_bps(amount, recovery_factor_bps) for amount in line_amounts)


def expected_reissue_amount(gross_reissue_cents: int, disputed_amount_cents: int) -> int:
    """"reissue_amount_cents is the smaller of gross_reissue_cents and
    disputed_amount_cents"."""
    return min(gross_reissue_cents, disputed_amount_cents)


# ----------------------------------------------------------------------
# Period reserves and the exposure summary
# ----------------------------------------------------------------------
def expected_reserve(gross_exposure_cents: int, rate_bps: int) -> int:
    """A reserve is the rate "applied to gross_exposure_cents, rounded half-up once over
    the aggregate rather than per alert"."""
    return apply_bps(gross_exposure_cents, rate_bps)


def expected_net_funded_liability(
    funded_card_balances: Iterable[int], unauthorized_writeoff_cents: int
) -> int:
    """"the sum of current_balance_cents over cards whose activation_state is ACTIVE or
    DEPLETED, minus that period's unauthorized_writeoff_cents"."""
    return sum(funded_card_balances) - unauthorized_writeoff_cents


def assert_exposure_summary(
    summary: Dict[str, Any],
    net_funded_liability_cents: Optional[int] = None,
    funded_card_count: Optional[int] = None,
    in_period_alert_count: Optional[int] = None,
    confirmed_alert_count: Optional[int] = None,
    unauthorized_writeoff_cents: Optional[int] = None,
    outstanding_liability_cents: Optional[int] = None,
    gross_exposure_cents: Optional[int] = None,
    provisional_reserve_cents: Optional[int] = None,
    final_reserve_cents=None,
) -> None:
    """Assert the computed read's four live figures alongside the five echoed ones."""
    checks = {
        "net_funded_liability_cents": net_funded_liability_cents,
        "funded_card_count": funded_card_count,
        "in_period_alert_count": in_period_alert_count,
        "confirmed_alert_count": confirmed_alert_count,
        "unauthorized_writeoff_cents": unauthorized_writeoff_cents,
        "outstanding_liability_cents": outstanding_liability_cents,
        "gross_exposure_cents": gross_exposure_cents,
        "provisional_reserve_cents": provisional_reserve_cents,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert summary[field] == expected, (
                f"{field}: expected {expected}, got {summary[field]}"
            )
    if final_reserve_cents is not None:
        assert summary["final_reserve_cents"] == final_reserve_cents, (
            f"final_reserve_cents: expected {final_reserve_cents}, "
            f"got {summary['final_reserve_cents']}"
        )


# ----------------------------------------------------------------------
# Ordering and enum guards
# ----------------------------------------------------------------------
def assert_ordered_by(rows: List[Dict[str, Any]], primary: str, tie_break: str = "created_at") -> None:
    """List results are ordered by a declared primary key with created_at ascending as
    tie-break."""
    keys = [(row[primary], row[tie_break]) for row in rows]
    assert keys == sorted(keys), f"rows are not ordered by {primary} then {tie_break}: {keys}"


def assert_id_sequence(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert an exact ordered id sequence for a cascade or a listing order."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected order {expected_ids}, got {actual}"


def assert_enum_value(value: str, allowed: List[str], field: str) -> None:
    """"every enum-typed field carries one of its declared values"."""
    assert value in allowed, f"{field}: {value!r} is not one of {allowed}"


def assert_card_dimensions(card: Dict[str, Any]) -> None:
    """A card carries "two independent lifecycle dimensions" — activation_state and
    risk_posture — plus its channel."""
    assert_enum_value(card["activation_state"], ACTIVATION_STATES, "activation_state")
    assert_enum_value(card["risk_posture"], RISK_POSTURES, "risk_posture")
    assert_enum_value(card["channel"], CARD_CHANNELS, "channel")


def assert_empty(value: Any, field: str) -> None:
    """A field the PRD describes as "empty" holds no value."""
    assert value in (None, "", [], {}), f"{field}: expected empty, got {value!r}"
