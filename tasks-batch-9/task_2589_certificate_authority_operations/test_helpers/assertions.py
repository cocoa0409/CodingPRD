"""Domain assertions and the arithmetic the PRD pins down.

The helpers here re-derive the PRD's own formulas so a test can state the
expected number independently of how the service computes it.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AUDIT_CLOSED_FACTOR,
    AUDIT_DECAY_FLOOR,
    AUDIT_DECAY_PER_STEP,
    AUDIT_DECAY_STEP_DAYS,
    AUDIT_OPEN_FACTOR,
    CATEGORY_PENALTY_WEIGHT,
    CATEGORY_RISK_WEIGHT,
    DISCOUNT_BAND_TEN_MAX,
    DISCOUNT_BAND_TEN_MIN,
    DISCOUNT_BAND_TWENTY_MIN,
    DISCOUNT_PCT_NONE,
    DISCOUNT_PCT_TEN,
    DISCOUNT_PCT_TWENTY,
    EXPEDITE_PCT,
    REMEDIATION_PENALTY_BASE_CENTS,
    REQUEST_ID_PREFIX,
    REVOCATION_ALLOWANCE_STANDARD_HOURS,
    REVOCATION_ALLOWANCE_URGENT_HOURS,
    REVOCATION_EV_CAP_HOURS,
    REVOCATION_FLOOR_HOURS,
    REVOCATION_INCIDENT_CAP_HOURS,
    REASON_KEY_COMPROMISE,
    REASON_PRIVILEGE_WITHDRAWN,
    RISK_SCORE_CAP,
    TIER_MULTIPLIER,
    VALIDATION_TYPE_EV,
)

# ---------------------------------------------------------------------------
# Instant arithmetic
# ---------------------------------------------------------------------------
_ISO_OUT = "%Y-%m-%dT%H:%M:%SZ"


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, accepting `Z` or an explicit offset."""
    assert value is not None, "expected an instant, found None"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_ISO_OUT)


def shift(value: str, **kwargs) -> str:
    """Return `value` moved by the given timedelta keyword arguments."""
    return format_instant(parse_instant(value) + timedelta(**kwargs))


def plus_days(value: str, days: int) -> str:
    return shift(value, days=days)


def plus_hours(value: str, hours: int) -> str:
    return shift(value, hours=hours)


def plus_minutes(value: str, minutes: int) -> str:
    return shift(value, minutes=minutes)


def plus_seconds(value: str, seconds: int) -> str:
    return shift(value, seconds=seconds)


def seconds_between(start: str, end: str) -> int:
    return int((parse_instant(end) - parse_instant(start)).total_seconds())


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant"):
    """Compare two ISO-8601 instants by value, not by spelling."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} is {actual}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Rounding (PRD 2.9)
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round a monetary intermediate to a whole cent, halves going up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> Decimal:
    """Round a score to two decimal places, halves going up."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Issuance charge (PRD 3.5 / 3.7)
# ---------------------------------------------------------------------------
def discount_percent_for_subtotal(subtotal_cents: int) -> int:
    """The band is chosen from the pre-discount subtotal."""
    if subtotal_cents >= DISCOUNT_BAND_TWENTY_MIN:
        return DISCOUNT_PCT_TWENTY
    if DISCOUNT_BAND_TEN_MIN <= subtotal_cents <= DISCOUNT_BAND_TEN_MAX:
        return DISCOUNT_PCT_TEN
    return DISCOUNT_PCT_NONE


def issuance_charge_breakdown(
    base_fee_cents: int, validation_type: str, domain_count: int, expedited: bool
) -> Dict[str, int]:
    """Re-derive the six pinned charge steps, rounding only at 1, 4 and 5."""
    unit = round_half_up(
        Decimal(str(base_fee_cents)) * Decimal(str(TIER_MULTIPLIER[validation_type]))
    )
    subtotal = unit * domain_count
    percent = discount_percent_for_subtotal(subtotal)
    discount = round_half_up(Decimal(subtotal) * Decimal(percent) / Decimal(100))
    discounted = subtotal - discount
    expedite = (
        round_half_up(Decimal(discounted) * Decimal(EXPEDITE_PCT) / Decimal(100))
        if expedited
        else 0
    )
    return {
        "unit_cents": unit,
        "subtotal_cents": subtotal,
        "discount_percent": percent,
        "discount_cents": discount,
        "discounted_cents": discounted,
        "expedite_cents": expedite,
        "total_cents": discounted + expedite,
    }


def issuance_charge_cents(
    base_fee_cents: int, validation_type: str, domain_count: int, expedited: bool = False
) -> int:
    return issuance_charge_breakdown(
        base_fee_cents, validation_type, domain_count, expedited
    )["total_cents"]


# ---------------------------------------------------------------------------
# Revocation deadline (PRD 3.8)
# ---------------------------------------------------------------------------
def revocation_allowance_hours(
    reason_code: str, linked_to_incident: bool, validation_type: str
) -> int:
    base = (
        REVOCATION_ALLOWANCE_URGENT_HOURS
        if reason_code in (REASON_KEY_COMPROMISE, REASON_PRIVILEGE_WITHDRAWN)
        else REVOCATION_ALLOWANCE_STANDARD_HOURS
    )
    allowance = base
    if linked_to_incident:
        allowance = min(allowance, REVOCATION_INCIDENT_CAP_HOURS)
    if validation_type == VALIDATION_TYPE_EV:
        allowance = min(allowance, REVOCATION_EV_CAP_HOURS)
    return max(allowance, REVOCATION_FLOOR_HOURS)


def revocation_deadline_at(
    requested_at: str,
    reason_code: str,
    linked_to_incident: bool = False,
    validation_type: str = "DV",
) -> str:
    hours = revocation_allowance_hours(reason_code, linked_to_incident, validation_type)
    return plus_hours(requested_at, hours)


# ---------------------------------------------------------------------------
# Remediation penalty (PRD 3.9)
# ---------------------------------------------------------------------------
def residual_fraction(clock: str, not_before: str, not_after: str) -> Decimal:
    total = Decimal(seconds_between(not_before, not_after))
    remaining = Decimal(seconds_between(clock, not_after))
    if remaining <= 0:
        return Decimal(0)
    return remaining / total


def remediation_penalty_for_certificate(
    category: str, clock: str, not_before: str, not_after: str
) -> int:
    """One certificate's penalty, rounded before it joins the batch total."""
    weight = Decimal(str(CATEGORY_PENALTY_WEIGHT[category]))
    fraction = residual_fraction(clock, not_before, not_after)
    return round_half_up(Decimal(REMEDIATION_PENALTY_BASE_CENTS) * weight * fraction)


def remediation_penalty_total(
    category: str, clock: str, windows: Iterable[Dict[str, str]]
) -> int:
    return sum(
        remediation_penalty_for_certificate(
            category, clock, window["not_before"], window["not_after"]
        )
        for window in windows
    )


# ---------------------------------------------------------------------------
# Risk scores (PRD 3.9)
# ---------------------------------------------------------------------------
def operational_risk_score(categories: Iterable[str]) -> int:
    total = sum(CATEGORY_RISK_WEIGHT[category] for category in categories)
    return min(total, RISK_SCORE_CAP)


def audit_decay_factor(discovered_at: str, opinion_clock: str) -> Decimal:
    """Age decay measured in whole days from discovery to the opinion instant."""
    age_days = (parse_instant(opinion_clock) - parse_instant(discovered_at)).days
    steps = age_days // AUDIT_DECAY_STEP_DAYS
    factor = Decimal(1) - Decimal(str(AUDIT_DECAY_PER_STEP)) * Decimal(steps)
    floor = Decimal(str(AUDIT_DECAY_FLOOR))
    return floor if factor < floor else factor


def audit_final_risk_score(incidents: Iterable[Dict[str, Any]], opinion_clock: str):
    """Sum the per-incident terms, then round once to two decimals."""
    total = Decimal(0)
    for incident in incidents:
        weight = Decimal(CATEGORY_RISK_WEIGHT[incident["category"]])
        state_factor = Decimal(
            str(AUDIT_CLOSED_FACTOR if incident.get("closed") else AUDIT_OPEN_FACTOR)
        )
        total += weight * state_factor * audit_decay_factor(
            incident["discovered_at"], opinion_clock
        )
    rounded = round_half_up_2dp(total)
    cap = Decimal(RISK_SCORE_CAP)
    return cap if rounded > cap else rounded


# ---------------------------------------------------------------------------
# Envelope and identity assertions (PRD 2.2 / 2.4)
# ---------------------------------------------------------------------------
def assert_envelope_meta(body: Dict[str, Any], expected_response_type: str):
    meta = body.get("meta")
    assert isinstance(meta, dict), "response envelope is missing its meta object"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith(REQUEST_ID_PREFIX), (
        f"api_request_id {request_id!r} does not start with {REQUEST_ID_PREFIX!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"api_request_timestamp {meta.get('api_request_timestamp')!r} is not ISO-8601"
    )
    # PRD 2.2 places `response_type` at the top level of the envelope, beside
    # `meta` and `data`.
    response_type = body.get("response_type", meta.get("response_type"))
    assert response_type == expected_response_type, (
        f"response_type is {response_type!r}, expected {expected_response_type!r}"
    )


def assert_modifiable_identity(entity: Dict[str, Any], expected_version: int = None):
    assert is_valid_uuid(entity.get("id")), f"id {entity.get('id')!r} is not a UUID"
    assert is_iso8601_timestamp(entity.get("created_at")), "created_at is not ISO-8601"
    assert is_iso8601_timestamp(entity.get("updated_at")), "updated_at is not ISO-8601"
    assert isinstance(entity.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version is {entity['version']}, expected {expected_version}"
        )


def assert_append_only_identity(entity: Dict[str, Any]):
    """Append-only resources carry `id` and `created_at` and nothing else."""
    assert is_valid_uuid(entity.get("id")), f"id {entity.get('id')!r} is not a UUID"
    assert is_iso8601_timestamp(entity.get("created_at")), "created_at is not ISO-8601"
    assert "updated_at" not in entity, (
        "an append-only resource must not expose updated_at"
    )
    assert "version" not in entity, "an append-only resource must not expose version"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_crl_ledger_conserved(profile: Dict[str, Any]):
    """total_crl_entries_published + pending_crl_entry_count == revoked count."""
    published = profile["total_crl_entries_published"]
    pending = profile["pending_crl_entry_count"]
    revoked = profile["revoked_certificate_count"]
    assert published + pending == revoked, (
        f"CRL ledger broken: {published} published + {pending} pending != "
        f"{revoked} revoked"
    )


def assert_balance_matches_unrefunded(
    subscriber: Dict[str, Any], certificates: List[Dict[str, Any]]
):
    """outstanding_balance_cents is the sum over certificates never refunded."""
    expected = sum(
        certificate["charged_amount_cents"]
        for certificate in certificates
        if certificate.get("refunded_at") is None
    )
    assert subscriber["outstanding_balance_cents"] == expected, (
        f"outstanding_balance_cents is {subscriber['outstanding_balance_cents']}, "
        f"expected {expected} from the unrefunded certificates"
    )


def assert_certificate_dimensions(
    certificate: Dict[str, Any], lifecycle_status: str, revocation_status: str
):
    assert certificate["lifecycle_status"] == lifecycle_status, (
        f"lifecycle_status is {certificate['lifecycle_status']!r}, "
        f"expected {lifecycle_status!r}"
    )
    assert certificate["revocation_status"] == revocation_status, (
        f"revocation_status is {certificate['revocation_status']!r}, "
        f"expected {revocation_status!r}"
    )


def assert_counters(entity: Dict[str, Any], **expected):
    for field, value in expected.items():
        assert entity.get(field) == value, (
            f"{field} is {entity.get(field)!r}, expected {value!r}"
        )


def assert_nulls(entity: Dict[str, Any], *fields):
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} is {entity.get(field)!r}, expected null"
        )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
